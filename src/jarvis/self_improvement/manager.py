"""ImprovementManager: the public API and the only writer of proposals.

In this version only the PROPOSAL workflow is live: analyze() (read-only analysis of real run data), propose(), reject(), list()/get() and the status machine.
Everything that would prepare, test, merge or revert CODE (prepare, test, activate, rollback) first asks the ExecutionGuard and raises ExecutionDisabled - the
guard has no production unlock (see isolation.py). The approval gate and the activation logic are implemented and tested against fake, non-executing workspaces so
that they exist, are correct and fail closed when isolation is eventually proven; they are not reachable today because no proposal can reach TESTED.

Concurrency: every state-changing operation takes a per-proposal lock (non-blocking: a second concurrent operation is refused), re-reads the proposal from the
store, checks the status it expects and writes with compare-and-swap (`rev`), so neither two threads nor two processes can overwrite each other.
Audit: approve, activate and rollback need a working audit trail and refuse without one."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

from jarvis.permissions.audit import AuditEvent, AuditEventType
from jarvis.redaction import SecretDetector
from jarvis.self_improvement import policy as P
from jarvis.self_improvement.analysis import ImprovementAnalyzer
from jarvis.self_improvement.approval import ApprovalGate
from jarvis.self_improvement.errors import (ApprovalError, ChangeBlocked, ConcurrentUpdateError, ImprovementError, ImprovementStateError, InvalidProposalError,
                                            PreparationError)
from jarvis.self_improvement.isolation import ExecutionGuard
from jarvis.self_improvement.llm import LLMImprovementWriter
from jarvis.self_improvement.models import Approval, Proposal, utcnow
from jarvis.self_improvement.pipeline import ValidationPipeline
from jarvis.self_improvement.review import ReviewedChange, approval_view
from jarvis.self_improvement.state import ProposalStatus as S
from jarvis.self_improvement.store import ProposalStore

log = logging.getLogger("jarvis.self_improvement")


@dataclass
class AnalyzeReport:
    created: list[Proposal] = field(default_factory=list)
    known: int = 0
    sources_used: list[str] = field(default_factory=list)
    sources_missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used_llm: bool = False


class ImprovementManager:
    def __init__(self, store: ProposalStore, *, analyzer: ImprovementAnalyzer | None = None, workspace: Any = None, pipeline: ValidationPipeline | None = None,
                 gate: ApprovalGate | None = None, audit: Any = None, writer: LLMImprovementWriter | None = None, guard: ExecutionGuard | None = None,
                 max_edits: int = 5, detector: SecretDetector | None = None) -> None:
        self._store, self._analyzer, self._ws, self._pipe, self._gate = store, analyzer, workspace, pipeline, gate
        self._audit, self._writer = audit, writer
        self._guard = guard or ExecutionGuard.locked()
        self.max_edits = max(1, min(max_edits, P.MAX_EDITS_HARD))
        self._detector = detector or SecretDetector.from_environment()
        self._lock = threading.Lock()
        self._busy: dict[str, threading.Event] = {}

    # ---- views ---------------------------------------------------------------------------------------------------------------------------
    def get(self, proposal_id: str) -> Proposal:
        return self._store.get(proposal_id)

    def list(self, status: S | None = None, limit: int | None = None) -> list[Proposal]:
        items = [p for p in self._store.list() if status is None or p.status is status]
        return items[:limit] if limit else items

    def describe(self) -> dict[str, Any]:
        items = self._store.list()
        counts: dict[str, int] = {}
        for p in items:
            counts[p.status.value] = counts.get(p.status.value, 0) + 1
        return {"proposals": len(items), "by_status": counts, "code_execution": self._guard.allowed, "execution_note": "" if self._guard.allowed else self._guard.reason(),
                "llm": bool(self._writer and self._writer.available), "approval_channel": self._gate.channel if self._gate else "none"}

    # ---- audit ---------------------------------------------------------------------------------------------------------------------------
    def _emit(self, p: Proposal, action: str, status: str, detail: str = "", extra: Mapping[str, str] | None = None) -> bool:
        if self._audit is None:
            return False
        try:
            return bool(self._audit.record(AuditEvent(AuditEventType.IMPROVEMENT, tool="self_improvement", action=action, resource=p.proposal_id, status=status,
                                                      detail=self._detector.redact(detail)[:300], extra=dict(extra or {}))))
        except Exception:  # noqa: BLE001
            return False

    def _audit_ready(self) -> bool:
        sinks = getattr(self._audit, "sinks", None)
        return self._audit is not None and (sinks is None or len(sinks) > 0)

    def _must_audit(self, p: Proposal, action: str, detail: str = "") -> None:
        """Approval, activation and rollback only happen if the intent was recorded first. No audit logger, no sink, or a failing sink: refused (fail closed)."""
        if not self._audit_ready() or not self._emit(p, action + "_requested", "pending", detail):
            raise ImprovementError("no working audit trail: this action is refused (fail closed)")

    # ---- locking and transitions ---------------------------------------------------------------------------------------------------------
    @contextmanager
    def _exclusive(self, proposal_id: str) -> Iterator[threading.Event]:
        with self._lock:
            if proposal_id in self._busy:
                raise ImprovementStateError("another operation on this proposal is still running")
            ev = self._busy[proposal_id] = threading.Event()
        try:
            yield ev
        finally:
            with self._lock:
                self._busy.pop(proposal_id, None)

    def _commit(self, proposal_id: str, expect: S | Sequence[S], new: S, actor: str, note: str = "", **changes: Any) -> Proposal:
        """Re-read, check the expected status, validate the transition and write with compare-and-swap. Nothing is ever written from a stale copy."""
        cur = self._store.get(proposal_id)
        allowed = (expect,) if isinstance(expect, S) else tuple(expect)
        if cur.status not in allowed:
            raise ImprovementStateError(f"the proposal is {cur.status.value}, expected {' or '.join(a.value for a in allowed)}")
        saved = self._store.save(cur.moved(new, actor, self._detector.redact(note), **changes))
        self._emit(saved, new.value.lower(), "ok", note, {"from": cur.status.value, "actor": actor})
        return saved

    def cancel(self, proposal_id: str) -> bool:
        with self._lock:
            ev = self._busy.get(proposal_id)
        if ev is None:
            return False
        ev.set()
        self._emit(self._store.get(proposal_id), "cancel_requested", "ok")
        return True

    # ---- 1/2: detect and propose (live) ----------------------------------------------------------------------------------------------------
    def analyze(self, *, use_llm: bool = False) -> AnalyzeReport:
        rep = AnalyzeReport()
        if self._analyzer is None:
            rep.warnings.append("no analyzer configured")
            return rep
        found = self._analyzer.observe()
        rep.sources_used, rep.sources_missing, rep.warnings = found.sources_used, found.sources_missing, list(found.warnings)
        existing = self._store.list()
        seen_fp = {p.fingerprint for p in existing if p.fingerprint}
        open_keys = {p.fingerprint.rsplit(":", 1)[0] for p in existing if p.fingerprint and not p.is_terminal}
        fresh = []
        for ob in found.observations:
            if ob.fingerprint() in seen_fp or ob.key in open_keys:
                rep.known += 1
            else:
                fresh.append(ob)
        refined: dict[str, dict[str, Any]] = {}
        if use_llm and fresh:
            if self._writer is None or not self._writer.available:
                rep.warnings.append("no language model provider: deterministic proposals only")
            else:
                try:
                    refined = self._writer.refine(fresh)
                    rep.used_llm = bool(refined)
                    if not refined:
                        rep.warnings.append("the language model reply contained no usable proposal: deterministic text kept")
                except ImprovementError as exc:
                    rep.warnings.append(f"language model not used: {exc}")
        for ob in fresh:
            try:
                p = self._analyzer.to_proposal(ob)
                if ob.key in refined:
                    p = p.evolve(**refined[ob.key])
                p = self._store.save(p)
                self._emit(p, "detected", "ok", ob.key, {"source": p.source})
                rep.created.append(self._commit(p.proposal_id, S.DETECTED, S.PROPOSED, "llm" if ob.key in refined else "analysis", "improvement proposed"))
            except InvalidProposalError as exc:
                rep.warnings.append(f"{ob.key}: proposal refused ({exc})")
        return rep

    def propose(self, title: str, problem: str, *, change: str = "", benefit: str = "", risks: Sequence[str] = (), affected: Sequence[str] = (),
                suggested_tests: Sequence[str] = ()) -> Proposal:
        """A proposal written by the user: text only, no evidence claim (source = user)."""
        p = self._store.save(Proposal(title=title, problem=problem, change=change, benefit=benefit, risks=tuple(risks), affected=tuple(affected),
                                      suggested_tests=tuple(suggested_tests), source="user"))
        self._emit(p, "detected", "ok", "", {"source": "user"})
        return self._commit(p.proposal_id, S.DETECTED, S.PROPOSED, "user", "proposed by the user")

    def reject(self, proposal_id: str, reason: str = "") -> Proposal:
        with self._exclusive(proposal_id):
            cur = self._store.get(proposal_id)
            if cur.status is S.ACTIVATED:
                raise ImprovementStateError("an activated change is reverted with rollback, not rejected")
            why = P.clean_text(reason or "rejected by the user", 300)
            moved = self._commit(proposal_id, cur.status, S.REJECTED, "user", why, reason=why)
            if self._ws is not None and cur.branch:
                self._ws.discard(cur.proposal_id, cur.branch)
            return moved

    # ---- 3: prepare (disabled) -------------------------------------------------------------------------------------------------------------
    def prepare(self, proposal_id: str, edits: Sequence[Mapping[str, str]] | None = None, *, files: Sequence[str] = ()) -> Proposal:
        self._guard.require("preparing a change")
        if self._ws is None:
            raise ImprovementError("no repository is configured")
        with self._exclusive(proposal_id) as cancel:
            p = self._store.get(proposal_id)
            if p.status not in (S.PROPOSED, S.FAILED):
                raise ImprovementStateError(f"a proposal in status {p.status.value} cannot be prepared")
            if p.status is S.FAILED:
                self._ws.discard(p.proposal_id, p.branch)
                p = self._commit(proposal_id, S.FAILED, S.PROPOSED, "user", "retry after failure", branch="", base_commit="", head_commit="", diff_digest="",
                                 stages=(), changed_files=(), approval=None, tested_manifest="")
            wt = None
            try:
                clean = P.validate_edits(list(edits), self.max_edits) if edits is not None else None
                if clean is not None:
                    self._check_targets(clean)
                wt = self._ws.create_worktree(p.proposal_id, cancel)
                if clean is None:
                    clean = self._draft(p, wt, files)
                    self._check_targets(clean)
                change = self._ws.apply_and_commit(wt, clean, f"self-improvement {p.proposal_id}: prepared change (not activated)", cancel)
            except ChangeBlocked as exc:
                if wt:
                    self._ws.discard(p.proposal_id, wt.branch)
                return self._commit(proposal_id, S.PROPOSED, S.BLOCKED, "system", f"manual review required: {exc}", reason=str(exc))
            except (ValueError, ImprovementError) as exc:
                if wt:
                    self._ws.discard(p.proposal_id, wt.branch)
                return self._commit(proposal_id, S.PROPOSED, S.FAILED, "system", f"preparation failed: {exc}", reason=str(exc))
            except Exception as exc:  # noqa: BLE001
                if wt:
                    self._ws.discard(p.proposal_id, wt.branch)
                log.warning("preparation of %s crashed (%s)", p.proposal_id, type(exc).__name__)
                return self._commit(proposal_id, S.PROPOSED, S.FAILED, "system", f"preparation failed ({type(exc).__name__})", reason=type(exc).__name__)
            return self._commit(proposal_id, S.PROPOSED, S.PREPARED, "system", f"prepared on branch {wt.branch}", edits=tuple(clean), branch=wt.branch,
                                base_commit=wt.base_commit, head_commit=change.head_commit, diff_digest=change.diff_digest, diff_stat=change.stat,
                                changed_files=change.changed_files)

    @staticmethod
    def _check_targets(edits: Sequence[Mapping[str, str]]) -> None:
        why = P.check_targets(edits)
        if why:
            raise ChangeBlocked(why)

    def _draft(self, p: Proposal, wt: Any, files: Sequence[str]) -> tuple[dict[str, str], ...]:
        if self._writer is None or not self._writer.available:
            raise PreparationError("no edits were given and no language model provider is available")
        if not files:
            raise PreparationError("name the files the change may touch (files=...)")
        contents = {f: self._ws.read_file(wt, f) for f in list(files)[:P.MAX_FILES]}      # allow-list + canonical path enforced here
        return self._writer.draft_edits(p, contents, self.max_edits)

    # ---- 4: review and test (disabled) -----------------------------------------------------------------------------------------------------
    def _reviewed(self, p: Proposal, cancel: threading.Event | None = None) -> ReviewedChange:
        """The change as it is NOW in git, rebuilt from metadata and blobs and compared with what was recorded. Any difference raises."""
        self._ws.worktree_for(p.proposal_id, p.branch, p.base_commit) if p.branch else None
        change = self._ws.review(p.base_commit, p.head_commit, cancel)
        if change.diff_digest != p.diff_digest or change.head_commit != p.head_commit:
            raise ApprovalError("the prepared change differs from the one that was reviewed")
        if self._ws.branch_tip(p.branch) != p.head_commit:
            raise ApprovalError("the improvement branch moved after it was reviewed")
        return change

    def _manifest_matches(self, p: Proposal) -> None:
        exp = self._ws.export_commit(p.head_commit)
        try:
            if not p.tested_manifest or exp.manifest_sha256 != p.tested_manifest:
                raise ApprovalError("the content of the commit differs from the content that was tested")
        finally:
            self._ws.remove_export(exp.path)

    def test(self, proposal_id: str) -> Proposal:
        self._guard.require("testing a change")
        if self._ws is None or self._pipe is None:
            raise ImprovementError("no test pipeline is configured")
        with self._exclusive(proposal_id) as cancel:
            p = self._store.get(proposal_id)
            if p.status is not S.PREPARED:
                raise ImprovementStateError(f"only a PREPARED proposal can be tested (is {p.status.value})")
            exp = None
            try:
                change = self._reviewed(p, cancel)
                exp = self._ws.export_commit(p.head_commit, cancel)
                result = self._pipe.run(change, p.suggested_tests, exp, cancel)
                again = self._reviewed(p, cancel)                       # the branch must be unchanged after the run
                if again.diff_digest != change.diff_digest:
                    raise ApprovalError("the improvement branch changed during the test run")
            except ChangeBlocked as exc:
                return self._commit(proposal_id, S.PREPARED, S.BLOCKED, "system", f"manual review required: {exc}", reason=str(exc))
            except Exception as exc:  # noqa: BLE001
                return self._commit(proposal_id, S.PREPARED, S.FAILED, "system", f"testing failed: {exc}"[:300], reason=(str(exc) or type(exc).__name__)[:300])
            finally:
                if exp is not None:
                    self._ws.remove_export(exp.path)
            if result.blocked:
                self._ws.discard(p.proposal_id, p.branch)
                return self._commit(proposal_id, S.PREPARED, S.BLOCKED, "system", f"manual review required: {result.blocked}", reason=result.blocked, stages=tuple(result.stages))
            if result.passed:
                return self._commit(proposal_id, S.PREPARED, S.TESTED, "system", "every validation stage executed and passed", stages=tuple(result.stages),
                                    tested_manifest=result.manifest)
            return self._commit(proposal_id, S.PREPARED, S.FAILED, "system", ("cancelled: " if result.cancelled else "tests did not pass: ") + result.failure,
                                reason=result.failure, stages=tuple(result.stages))

    # ---- 5/6: approval ---------------------------------------------------------------------------------------------------------------------
    def submit_for_approval(self, proposal_id: str) -> Proposal:
        with self._exclusive(proposal_id):
            p = self._store.get(proposal_id)
            if p.status is not S.TESTED or not p.tests_passed or not p.tested_manifest:
                raise ImprovementStateError("only a TESTED proposal whose stages all executed and passed can be submitted")
            return self._commit(proposal_id, S.TESTED, S.READY_FOR_APPROVAL, "system", "waiting for the user's approval")

    def _review_context(self, p: Proposal, change: ReviewedChange, action: str) -> dict[str, str]:
        return approval_view(p.title, p.problem, change, [(s.name, s.executed, s.passed) for s in p.stages], action)

    def approve(self, proposal_id: str) -> Proposal:
        """Show the user the COMPLETE reviewed diff and ask. The approval is bound to commit, diff digest, tested file manifest and the exact text shown."""
        with self._exclusive(proposal_id):
            p = self._store.get(proposal_id)
            if p.status is not S.READY_FOR_APPROVAL:
                raise ApprovalError(f"approval needs status READY_FOR_APPROVAL (is {p.status.value})")
            if not p.tests_passed or not p.tested_manifest:
                raise ApprovalError("the tests did not all execute and pass: approval is blocked")
            if self._gate is None or self._ws is None:
                raise ApprovalError("no approval channel is configured")
            try:
                change = self._reviewed(p)
                self._manifest_matches(p)
            except ChangeBlocked as exc:
                raise ApprovalError(f"the change cannot be shown completely or is not acceptable: {exc}") from None
            except PreparationError as exc:
                raise ApprovalError(f"the prepared change cannot be verified: {exc}") from None
            self._must_audit(p, "approve", p.diff_digest)
            ctx = self._review_context(p, change, "APPROVE this exact change (approving does not activate it)")
            if not self._gate.ask("approve_change", p.proposal_id, "Review the complete diff below. Nothing is activated by approving.", ctx):
                self._emit(p, "approve", "denied", "the user did not approve")
                raise ApprovalError("the change was not approved by the user")
            return self._commit(proposal_id, S.READY_FOR_APPROVAL, S.APPROVED, "user", f"approved via {self._gate.channel}",
                                approval=Approval(utcnow(), self._gate.channel, p.head_commit, p.diff_digest, change.view_digest))

    # ---- 7: activate / roll back (disabled) ------------------------------------------------------------------------------------------------
    def activate(self, proposal_id: str) -> Proposal:
        """A stored approval is NOT enough: the user is asked again, with the diff, at the moment of activation."""
        self._guard.require("activating a change")
        with self._exclusive(proposal_id):
            p = self._store.get(proposal_id)
            if p.status is not S.APPROVED or p.approval is None:
                raise ApprovalError(f"activation needs an explicit user approval (status is {p.status.value})")
            a = p.approval
            if a.head_commit != p.head_commit or a.diff_digest != p.diff_digest or not p.tests_passed or not p.tested_manifest:
                raise ApprovalError("the approval does not match the reviewed and tested change")
            if self._ws is None or self._gate is None:
                raise ApprovalError("no repository or approval channel is configured")
            try:
                change = self._reviewed(p)
                self._manifest_matches(p)
            except ChangeBlocked as exc:
                raise ApprovalError(f"the change cannot be shown completely or is not acceptable: {exc}") from None
            if a.view_digest != change.view_digest:
                raise ApprovalError("the diff shown at approval time differs from the diff that would be activated")
            self._must_audit(p, "activate", p.head_commit)
            ctx = self._review_context(p, change, "ACTIVATE this exact change in the active branch")
            if not self._gate.ask("activate_change", p.proposal_id, "Final confirmation: this merges the change below into the active branch.", ctx):
                self._emit(p, "activate", "denied", "the user did not confirm the activation")
                raise ApprovalError("the activation was not confirmed by the user")
            try:
                self._ws.fast_forward(p.branch, p.base_commit, p.head_commit)
            except ImprovementError as exc:
                self._emit(p, "activate", "failed", str(exc))
                raise
            self._ws.discard(p.proposal_id, "")
            return self._commit(proposal_id, S.APPROVED, S.ACTIVATED, "user", f"merged {p.head_commit[:12]} into the active branch (restart JARVIS to load it)")

    def rollback(self, proposal_id: str) -> Proposal:
        self._guard.require("rolling back a change")
        with self._exclusive(proposal_id):
            p = self._store.get(proposal_id)
            if p.status is not S.ACTIVATED:
                raise ImprovementStateError(f"only an ACTIVATED change can be rolled back (is {p.status.value})")
            if self._ws is None or self._gate is None:
                raise ImprovementError("no repository or approval channel is configured")
            self._must_audit(p, "rollback", p.head_commit)
            if not self._gate.ask("rollback_change", p.proposal_id, "Revert a previously activated improvement (adds a revert commit).",
                                  {"[JARVIS] Aktion": "ROLLBACK", "[JARVIS] Commit": p.head_commit[:12], "[unverifizierter Text] Titel": P.one_line(p.title, 120)}):
                raise ApprovalError("the rollback was not confirmed by the user")
            new_head = self._ws.revert(p.head_commit)
            return self._commit(proposal_id, S.ACTIVATED, S.ROLLED_BACK, "user", f"reverted by commit {new_head[:12]}")
