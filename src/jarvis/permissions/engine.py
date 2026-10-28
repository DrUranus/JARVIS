"""The permission engine: the single place that decides whether an action may happen.

    request -> validate -> effective level -> invariants (RED, lockdown) -> resource checks (paths/hosts)
            -> policy rules (deny > confirm > allow) -> level default / session grant -> [confirmation] -> decision

Everything fails closed: malformed input, policy problems, provider errors, audit failures and unexpected
exceptions all end in a denial, never a grant. The engine knows no concrete tools; tools describe their calls.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Iterator

from jarvis.errors import InvalidRequestError, PermissionDeniedError, PolicyError, SecurityError
from jarvis.permissions.audit import AuditEvent, AuditEventType, AuditLogger, AuditSink
from jarvis.permissions.confirmation import ConfirmationChoice, ConfirmationProvider, ConfirmationRequest
from jarvis.permissions.decision import DecisionStatus, GrantScope, PermissionDecision
from jarvis.permissions.budget import SessionBudget
from jarvis.permissions.emergency import EmergencyStop, ResetResult
from jarvis.permissions.grants import ExecutionGrant, SessionGrants, SessionKey, _SEAL, _enter_scope
from jarvis.permissions.levels import PermissionLevel, max_level
from jarvis.permissions.paths import PathGuard
from jarvis.permissions.policy import Effect, Policy
from jarvis.permissions.request import PermissionRequest
from jarvis.permissions.resources import ResourceType, normalize_host
from jarvis.redaction import REDACTED, SecretDetector

Level = PermissionLevel

# Actions that change something or reach outside can never be GREEN, whatever a tool claims.
CONSEQUENTIAL_VERBS = frozenset({
    "write", "modify", "edit", "update", "create", "delete", "remove", "rm", "move", "rename", "copy", "overwrite",
    "append", "truncate", "chmod", "chown", "mkdir", "rmdir", "execute", "exec", "shell", "spawn", "kill",
    "install", "uninstall", "send", "post", "publish", "upload", "pay", "spend", "purchase", "buy", "order",
    "book", "transfer", "sign", "submit", "push", "deploy", "format", "wipe", "drop",
    # input / UI automation (Phase 4): anything that acts on a screen, window or application is never GREEN
    "click", "type", "press", "hotkey", "scroll", "drag", "focus", "minimize", "maximize", "restore", "close",
    "launch", "save",
    # browser (Phase 5): typing into a page and fetching files are never GREEN
    "fill", "download",
})
_SPLIT = re.compile(r"[._:\-/]+")
APPROVAL_TTL_SECONDS = 60.0


def action_floor(action: str) -> PermissionLevel:
    """Minimum level implied by the action name itself."""
    tokens = _SPLIT.split(action.casefold())
    return Level.YELLOW if any(t in CONSEQUENTIAL_VERBS for t in tokens) else Level.GREEN


class PermissionMode(str, Enum):
    STANDARD = "standard"   # GREEN automatic, YELLOW asks (or a configured allow rule)
    LOCKDOWN = "lockdown"   # only GREEN; everything else denied, no questions asked


@dataclass(frozen=True)
class _Eval:
    decision: PermissionDecision
    level: PermissionLevel | None = None
    resource: str | None = None                # normalised resource
    session_key: SessionKey | None = None
    via_confirm_rule: bool = False


class PermissionEngine:
    def __init__(self, *, policy: Policy | None = None, path_guard: PathGuard | None = None,
                 confirmation: ConfirmationProvider | None = None, audit: AuditLogger | AuditSink | None = None,
                 redactor: SecretDetector | None = None, mode: PermissionMode = PermissionMode.STANDARD,
                 allow_session_grants: bool = True, session_ttl: float = 3600.0,
                 trust_caller_confirmation: bool = False, undeclared_level: PermissionLevel = Level.YELLOW,
                 require_protected_tools: bool = True, audit_strict: bool = True, audit_green: bool = False,
                 clock: Callable[[], float] = time.monotonic, budget: SessionBudget | None = None) -> None:
        self._redactor = redactor or SecretDetector()
        self._guard = path_guard or PathGuard()
        self._policy = policy or Policy()
        self._policy.validate_paths(self._guard)
        self._confirmation = confirmation
        self.audit = audit if isinstance(audit, AuditLogger) else AuditLogger([audit] if audit else [], self._redactor)
        # Security switches are fixed at construction and exposed read-only: code holding a reference to the
        # engine cannot weaken it by assignment (it must build a new engine, which is visible in bootstrap).
        self._mode = PermissionMode(mode)
        self._allow_session_grants = allow_session_grants
        self._trust_caller_confirmation = trust_caller_confirmation
        self._undeclared_level = undeclared_level
        self._require_protected_tools = require_protected_tools
        self._audit_strict, self._audit_green = audit_strict, audit_green
        self._clock = clock
        self._budget = budget                 # total tool-call / run-time cap for this process (None = off); fixed at construction
        self._session = SessionGrants(session_ttl, clock)
        self._approved: dict[str, tuple[float, str | None, str | None, str, PermissionDecision]] = {}
        self._lock = threading.RLock()
        self._confirm_lock = threading.Lock()  # one prompt at a time; re-checks state after waiting
        # Emergency stop: ONE latch for the whole application. While it is engaged every request is denied (GREEN included) and no execution scope opens.
        # `emergency.engage/trigger` are not tools; only `reset_emergency_stop` (explicit human confirmation) clears it.
        self.emergency = EmergencyStop(on_event=self._emergency_event)

    @classmethod
    def legacy(cls, **overrides: Any) -> "PermissionEngine":
        """Engine for a bare `ToolRegistry()` (Phase-1 behaviour): undeclared tools are GREEN, a caller may pass
        `confirmed=True`, no filesystem roots, no audit. The application never uses this; bootstrap builds a strict one."""
        opts: dict[str, Any] = dict(trust_caller_confirmation=True, undeclared_level=Level.GREEN,
                                    require_protected_tools=False, audit_strict=False)
        opts.update(overrides)
        return cls(**opts)

    # -- read-only configuration ------------------------------------------------------------------------
    mode = property(lambda self: self._mode)
    guard = property(lambda self: self._guard)
    confirmation = property(lambda self: self._confirmation)
    allow_session_grants = property(lambda self: self._allow_session_grants)
    trust_caller_confirmation = property(lambda self: self._trust_caller_confirmation)
    undeclared_level = property(lambda self: self._undeclared_level)
    require_protected_tools = property(lambda self: self._require_protected_tools)
    audit_strict = property(lambda self: self._audit_strict)
    audit_green = property(lambda self: self._audit_green)
    budget = property(lambda self: self._budget)

    def set_confirmation_provider(self, provider: ConfirmationProvider | None, source: str = "api") -> None:
        """Install the provider that asks the user (e.g. a voice or GUI one). Audited; None = nobody can be asked."""
        self._confirmation = provider
        self._emit(AuditEventType.POLICY_CHANGED, None,
                   detail=f"confirmation provider set to {type(provider).__name__ if provider else 'none'} via {source}")

    # -- emergency stop ---------------------------------------------------------------------------------------
    def _emergency_event(self, kind: str, detail: str) -> None:
        self._emit(AuditEventType.EMERGENCY_STOP, None, detail=self.redact(f"{kind}: {detail}")[:300])

    def reset_emergency_stop(self, source: str = "user") -> ResetResult:
        """Clear the emergency stop after an explicit human decision, asked through this engine's ConfirmationProvider (ALLOW_ONCE only; a missing, denying or
        failing provider keeps the stop engaged). Never call this from a tool or from model output."""
        def authorize() -> bool:
            provider = self._confirmation
            if provider is None:
                return False
            if not self._confirm_lock.acquire(timeout=10.0):          # a prompt is stuck: do not wait forever
                return False
            try:
                request = ConfirmationRequest(
                    request_id="emergency-reset", tool="jarvis", action="emergency_reset", level=PermissionLevel.YELLOW, resource="emergency stop",
                    reason="Der Notaus wird aufgehoben: Aktionen, Ziele und Tool-Aufrufe sind danach wieder möglich.", context={}, session_allowed=False)
                return provider.confirm(request) is ConfirmationChoice.ALLOW_ONCE
            finally:
                self._confirm_lock.release()
        return self.emergency.reset(authorize, source)

    # -- helpers ------------------------------------------------------------------------------------
    def redact(self, text: Any) -> str:
        return self._redactor.redact(text)

    @property
    def policy(self) -> Policy:
        return self._policy

    def _emit(self, type_: AuditEventType, request: Any = None, *, decision: PermissionDecision | None = None,
              detail: str = "", extra: dict[str, str] | None = None, level: PermissionLevel | None = None) -> bool:
        def s(name: str) -> str | None:
            v = getattr(request, name, None)
            return v if isinstance(v, str) else None

        lv = level if isinstance(level, PermissionLevel) else (decision.level if decision else None)
        if lv is None and isinstance(getattr(request, "level", None), PermissionLevel):
            lv = request.level
        resource = (decision.resolved_resource if decision and decision.resolved_resource else s("resource"))
        return self.audit.record(AuditEvent(
            type=type_, request_id=(decision.request_id if decision and decision.request_id else s("id")),
            tool=s("tool"), action=s("action"), resource=resource, level=lv.value if isinstance(lv, PermissionLevel) else None,
            status=decision.status.value if decision else None, rule=decision.matched_rule if decision else None,
            scope=decision.scope.value if decision and decision.scope else None, detail=detail, extra=extra or {}))

    def _deny(self, status: DecisionStatus, reason: str, request: Any, *, level: PermissionLevel | None = None,
              rule: str | None = None, considered: tuple[str, ...] = (), resource: str | None = None) -> PermissionDecision:
        rid = getattr(request, "id", None)
        return PermissionDecision(status, self.redact(reason), rid if isinstance(rid, str) else None, level, rule,
                                  None, considered, self.redact(resource) if resource else None)

    # -- evaluation (pure: no prompts, no audit, no approvals) ----------------------------------------------
    def _evaluate(self, request: Any) -> _Eval:
        if self.emergency.engaged:                                    # checked first: nothing is judged, nothing is approved while the stop is on
            return _Eval(self._deny(DecisionStatus.DENIED, f"emergency stop active ({self.emergency.reason}); everything is denied until it is reset", request))
        if self._budget is not None:                                  # right after the stop: a spent budget denies everything new (dry run: nothing is booked)
            why = self._budget.denial()
            if why:
                return _Eval(self._deny(DecisionStatus.DENIED, why, request, rule="invariant:budget"))
        if type(request) is not PermissionRequest:  # no subclasses: they could override validation or properties
            return _Eval(self._deny(DecisionStatus.INVALID_REQUEST, "not a PermissionRequest", None))
        try:
            PermissionRequest.validate(request)
        except InvalidRequestError as exc:
            return _Eval(self._deny(DecisionStatus.INVALID_REQUEST, f"invalid request: {exc}", request))

        floor = action_floor(request.action)
        level = max_level(request.level, floor)
        escalated = f" (action {request.action!r} implies at least {floor.value.upper()})" if level is not request.level else ""

        if level is Level.RED:
            why = f": {request.reason}" if request.reason else ""  # the tool's explanation (redacted by _deny)
            return _Eval(self._deny(DecisionStatus.DENIED, f"RED actions are never permitted{why}", request, level=level,
                                    rule="invariant:red"), level)
        if self._mode is PermissionMode.LOCKDOWN and level is not Level.GREEN:
            return _Eval(self._deny(DecisionStatus.DENIED, "lockdown mode: only GREEN actions are permitted",
                                    request, level=level, rule="invariant:lockdown"), level)

        resource: str | None = None
        try:
            if request.resource_type is ResourceType.PATH:
                check = self._guard.check(request.resource, modifying=level is not Level.GREEN)
                if not check.ok:
                    return _Eval(self._deny(DecisionStatus.DENIED, check.reason, request, level=level,
                                            rule=f"fs:{check.code}", resource=check.resolved), level)
                resource = check.resolved
            elif request.resource_type is ResourceType.DOMAIN:
                resource = normalize_host(request.resource)  # type: ignore[arg-type]
            elif request.resource_type is ResourceType.OTHER:
                resource = request.resource.strip()  # type: ignore[union-attr]
        except InvalidRequestError as exc:
            return _Eval(self._deny(DecisionStatus.INVALID_REQUEST, f"invalid resource: {exc}", request, level=level), level)

        try:
            verdict = self._policy.verdict(request, level, resource, self._guard)
        except Exception as exc:  # broken rule/path pattern: deny rather than guess
            return _Eval(self._deny(DecisionStatus.POLICY_ERROR, f"policy could not be evaluated ({type(exc).__name__})",
                                    request, level=level, resource=resource), level, resource)

        def decide(status: DecisionStatus, reason: str, scope: GrantScope | None = None) -> PermissionDecision:
            return PermissionDecision(status, self.redact(reason), request.id, level, verdict.rule, scope,
                                      verdict.considered, self.redact(resource) if resource else None)

        if verdict.effect is Effect.DENY:
            return _Eval(decide(DecisionStatus.DENIED, f"denied by rule {verdict.rule!r}"), level, resource)
        if verdict.effect is Effect.CONFIRM:
            return _Eval(decide(DecisionStatus.CONFIRMATION_REQUIRED,
                                f"rule {verdict.rule!r} requires confirmation every time"), level, resource, None, True)
        if level is Level.GREEN:
            return _Eval(decide(DecisionStatus.ALLOWED, "GREEN: safe action" + escalated, GrantScope.AUTOMATIC),
                         level, resource)
        # YELLOW
        if verdict.effect is Effect.ALLOW:
            return _Eval(decide(DecisionStatus.ALLOWED, f"allowed by configured rule {verdict.rule!r}",
                                GrantScope.PERSISTENT), level, resource)
        key = SessionKey(request.tool, request.action, request.resource_type, resource, level)
        if self._allow_session_grants and self._session.has(key):
            return _Eval(decide(DecisionStatus.ALLOWED, "allowed by an earlier session confirmation",
                                GrantScope.SESSION), level, resource, key)
        return _Eval(decide(DecisionStatus.CONFIRMATION_REQUIRED, "YELLOW: confirmation required" + escalated),
                     level, resource, key)

    def evaluate(self, request: Any) -> PermissionDecision:
        """Dry run: what would happen? No prompt, no audit entry, no approval is issued."""
        try:
            return self._evaluate(request).decision
        except Exception:
            return self._deny(DecisionStatus.INTERNAL_ERROR, "internal security error; action denied", request)

    # -- authorisation ---------------------------------------------------------------------------------
    def authorize(self, request: Any, *, caller_confirmed: bool = False, interactive: bool = True) -> PermissionDecision:
        """Full decision, including asking the user (if a provider is set and `interactive`). An ALLOWED decision
        carries a single-use approval that `execution_scope` consumes. Never raises."""
        try:
            return self._authorize(request, caller_confirmed, interactive)
        except Exception as exc:
            try:
                self._emit(AuditEventType.SECURITY_ERROR, request, detail=f"internal error in authorize: {type(exc).__name__}")
            except Exception:
                pass
            return self._deny(DecisionStatus.INTERNAL_ERROR, "internal security error; action denied (fail closed)", request)

    def _authorize(self, request: Any, caller_confirmed: bool, interactive: bool) -> PermissionDecision:
        ev = self._evaluate(request)
        d = ev.decision
        quiet = d.allowed and d.level is Level.GREEN and not self._audit_green  # don't log every harmless action
        if not quiet:
            self._emit(AuditEventType.PERMISSION_REQUESTED, request, level=ev.level or getattr(request, "level", None),
                       detail=self.redact(getattr(request, "reason", "") if isinstance(getattr(request, "reason", ""), str) else ""))

        if d.needs_confirmation:
            if caller_confirmed:
                if self._trust_caller_confirmation and not ev.via_confirm_rule:
                    d = replace(d, status=DecisionStatus.ALLOWED, scope=GrantScope.ASSERTED,
                                reason="confirmed by the caller (legacy registry)")
                else:
                    self._emit(AuditEventType.CALLER_CONFIRMATION_IGNORED, request, decision=d,
                               detail="a caller-supplied confirmation is not accepted; the user must confirm")
            if d.needs_confirmation and interactive and self._confirmation is not None:
                d = self._confirm(request, ev)

        if d.allowed:
            if not quiet:
                logged = self._emit(AuditEventType.PERMISSION_GRANTED, request, decision=d)
                if not logged and self._audit_strict and d.level is not Level.GREEN:
                    d = self._deny(DecisionStatus.INTERNAL_ERROR,
                                   "the audit log is unavailable; non-GREEN actions are denied (fail closed)",
                                   request, level=d.level, resource=d.resolved_resource)
                    self._emit(AuditEventType.PERMISSION_DENIED, request, decision=d)
                    return d
            if self._budget is not None:                       # booked only now, at the approval: declined/denied calls consume nothing
                why = self._budget.book()
                if why:
                    d = self._deny(DecisionStatus.DENIED, why, request, level=d.level, rule="invariant:budget", resource=d.resolved_resource)
                    self._emit(AuditEventType.PERMISSION_DENIED, request, decision=d)
                    self._note_budget_exhausted(request)
                    return d
            self._approve(request, d, ev.resource)
            return d
        self._emit(AuditEventType.PERMISSION_DENIED, request, decision=d)
        if d.matched_rule == "invariant:budget":
            self._note_budget_exhausted(request)
        return d

    def _note_budget_exhausted(self, request: Any) -> None:
        if self._budget is not None and self._budget.take_exhaustion_notice():
            self._emit(AuditEventType.BUDGET_EXHAUSTED, request, detail=self.redact(str(self._budget.usage()))[:300])

    def _confirm(self, request: PermissionRequest, first: _Eval) -> PermissionDecision:
        with self._confirm_lock:
            ev = self._evaluate(request)  # a concurrent request may have created a session grant meanwhile
            if not ev.decision.needs_confirmation:
                return ev.decision
            can_session = (self._allow_session_grants and ev.level is Level.YELLOW and not ev.via_confirm_rule
                           and ev.session_key is not None)
            context = self._redactor.redact_mapping(request.context)
            shown = ev.resource or request.resource
            if request.resource_type is ResourceType.PATH and ev.resource and ev.resource != request.resource:
                context["angefragter Pfad"] = self.redact(request.resource)
            creq = ConfirmationRequest(
                request_id=request.id, tool=self.redact(request.tool), action=self.redact(request.action),
                level=ev.level or request.level, resource=self.redact(shown) if shown else None,
                reason=self.redact(request.reason), context=context, session_allowed=can_session)
            self._emit(AuditEventType.CONFIRMATION_REQUESTED, request, decision=ev.decision)
            try:
                assert self._confirmation is not None
                choice = self._confirmation.confirm(creq)
            except Exception as exc:
                self._emit(AuditEventType.SECURITY_ERROR, request, detail=f"confirmation provider failed: {type(exc).__name__}")
                choice = ConfirmationChoice.DENY
            if not isinstance(choice, ConfirmationChoice):
                self._emit(AuditEventType.SECURITY_ERROR, request, detail="confirmation provider returned an invalid answer")
                choice = ConfirmationChoice.DENY
            if choice is ConfirmationChoice.DENY:
                d = replace(ev.decision, status=DecisionStatus.DENIED, reason="the user declined", matched_rule="user:declined")
                self._emit(AuditEventType.CONFIRMATION_REJECTED, request, decision=d)
                return d
            scope, note = GrantScope.ONCE, "the user confirmed this one call"
            if choice is ConfirmationChoice.ALLOW_SESSION:
                if can_session and ev.session_key is not None and self._session.add(ev.session_key):
                    scope, note = GrantScope.SESSION, "the user allowed this action on this resource for the session"
                    self._emit(AuditEventType.SESSION_GRANT_CREATED, request, decision=ev.decision,
                               detail="session permission for this exact action and resource")
                else:
                    note = "session permission not available here; treated as a one-time confirmation"
            d = replace(ev.decision, status=DecisionStatus.ALLOWED, scope=scope, reason=note, matched_rule="user:confirmed")
            self._emit(AuditEventType.CONFIRMATION_ACCEPTED, request, decision=d, detail=choice.value)
            return d

    # -- single-use approvals / execution scope -----------------------------------------------------------------
    @staticmethod
    def _digest(request: PermissionRequest) -> str:
        """What was approved: tool, action, level and resource. An approval is useless for any other request."""
        parts = (request.tool, request.action, request.level.value, request.resource_type.value, request.resource or "")
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()

    def _approve(self, request: PermissionRequest, decision: PermissionDecision, resource: str | None) -> None:
        now = self._clock()
        with self._lock:
            if len(self._approved) > 1000:
                self._approved = {k: v for k, v in self._approved.items() if v[0] > now}
            self._approved[request.id] = (now + APPROVAL_TTL_SECONDS, request.args_fingerprint, resource,
                                          self._digest(request), decision)

    @contextmanager
    def execution_scope(self, request: PermissionRequest, decision: PermissionDecision) -> Iterator[ExecutionGrant]:
        """Run the approved call inside this scope. Raises PermissionDeniedError unless `decision` is an ALLOWED
        decision this engine issued for `request`; the approval is consumed, so it covers exactly one execution."""
        with self._lock:
            entry = self._approved.pop(getattr(request, "id", None), None)
        if self.emergency.engaged:                                    # an approval issued just before the stop is void
            self._emit(AuditEventType.SECURITY_ERROR, request, detail="execution blocked: emergency stop active")
            raise PermissionDeniedError("emergency stop active")
        if self._budget is not None:                                  # the run time may have run out since the approval
            why = self._budget.time_denial()
            if why:
                self._emit(AuditEventType.SECURITY_ERROR, request, detail=f"execution blocked: {why}")
                raise PermissionDeniedError(why)
        valid = False
        try:
            valid = (entry is not None and type(request) is PermissionRequest and decision == entry[4]
                     and decision.allowed and decision.request_id == request.id and entry[0] > self._clock()
                     and entry[1] == request.args_fingerprint and entry[3] == self._digest(request))
        except Exception:  # a malformed request/decision is simply not approved
            valid = False
        if not valid:
            self._emit(AuditEventType.SECURITY_ERROR, request,
                       detail="execution attempted without a valid, unused approval")
            raise PermissionDeniedError("no valid approval for this execution")
        grant = ExecutionGrant(request.tool, request.action, request.args_fingerprint, request.id, entry[2], _seal=_SEAL)
        with _enter_scope(grant):
            yield grant

    def record_execution(self, request: PermissionRequest, decision: PermissionDecision, success: bool,
                         error: str | None = None) -> None:
        """Audit the outcome of a non-GREEN execution (GREEN is not logged: no log flooding)."""
        if decision.level is Level.GREEN and not self._audit_green:
            return
        self._emit(AuditEventType.EXECUTION_RESULT, request, decision=decision,
                   detail="success" if success else f"failed: {self.redact(error or '')[:200]}")

    # -- tool vetting --------------------------------------------------------------------------------------------
    def tool_problem(self, level: PermissionLevel | None, protected: bool) -> str | None:
        """Why a tool may not be registered/executed here, or None. In strict engines every non-GREEN
        (or undeclared) tool must be a ProtectedTool, whose run() cannot work outside an approved scope."""
        effective = level if level is not None else self._undeclared_level
        if self._require_protected_tools and effective is not Level.GREEN and not protected:
            return ("tools that are not declared GREEN must derive from ProtectedTool "
                    "(undeclared tools count as YELLOW)")
        return None

    def note_tool_registered(self, name: str, level: PermissionLevel | None) -> None:
        effective = level if level is not None else self._undeclared_level
        if effective is not Level.GREEN:
            self._emit(AuditEventType.TOOL_REGISTERED, None, detail=f"tool {name!r} registered at level {effective.value}",
                       level=effective, extra={"tool": name})

    # -- sessions & policy -----------------------------------------------------------------------------------------
    def revoke_session_grants(self, reason: str = "revoked") -> int:
        n = self._session.revoke_all()
        self._emit(AuditEventType.SESSION_GRANTS_REVOKED, None, detail=f"{reason}: {n} grant(s)")
        return n

    end_session = revoke_session_grants

    def session_grants(self) -> list[dict[str, str]]:
        return [{"tool": self.redact(k.tool), "action": self.redact(k.action), "level": k.level.value,
                 "resource": self.redact(k.resource) if k.resource else ""} for k in self._session.keys()]

    def update_policy(self, policy: Policy, source: str = "api") -> None:
        """Replace the policy (validated first; on error the old policy stays). Revokes session grants and audits."""
        policy.validate_paths(self._guard)
        with self._lock:
            old_ids = {r.id for r in self._policy.rules}
            self._policy = policy
        new_ids = {r.id for r in policy.rules}
        self._session.revoke_all()
        self._emit(AuditEventType.POLICY_CHANGED, None, detail=f"policy updated via {source}",
                   extra={"added": ",".join(sorted(new_ids - old_ids)), "removed": ",".join(sorted(old_ids - new_ids)),
                          "fingerprint": policy.fingerprint})

    def note_policy_loaded(self, source: str) -> None:
        if self._policy.rules:
            self._emit(AuditEventType.POLICY_LOADED, None, detail=f"policy loaded from {source}",
                       extra={"rules": str(len(self._policy.rules)), "fingerprint": self._policy.fingerprint})

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "roots": self._guard.allowed_roots, "denied_paths": self._guard.denied_paths,
                "rules": [r.to_dict() for r in self._policy.rules], "session_grants": self.session_grants(),
                "confirmation": type(self._confirmation).__name__ if self._confirmation else None,
                "session_grants_allowed": self._allow_session_grants, "policy_fingerprint": self._policy.fingerprint,
                "emergency_stop": {"engaged": self.emergency.engaged, "reason": self.emergency.reason},
                "budget": self._budget.usage() if self._budget is not None else None}
