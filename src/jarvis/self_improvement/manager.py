"""ImprovementManager: the public API and the only writer of proposals. It owns the lifecycle (state.py), the audit trail, the cancel flags and the
decision which component may do what:

  analyze()                  read-only analysis -> proposals (DETECTED -> PROPOSED)
  prepare() / test()         isolated branch + worktree, then the validation pipeline (PROPOSED -> PREPARED -> TESTED | FAILED | BLOCKED)
  submit_for_approval()      TESTED -> READY_FOR_APPROVAL
  approve()                  asks the USER through the ApprovalGate (READY_FOR_APPROVAL -> APPROVED); nothing else can set APPROVED
  activate() / rollback()    fast-forward / revert of exactly the approved commit; activation is off unless self_improvement.allow_activation

Models (the writer) only ever contribute text that is validated; they never call approve/activate and never change a status."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from jarvis.permissions.audit import AuditEvent, AuditEventType
from jarvis.redaction import SecretDetector
from jarvis.self_improvement import policy as P
from jarvis.self_improvement.analysis import ImprovementAnalyzer
from jarvis.self_improvement.approval import ApprovalGate
from jarvis.self_improvement.errors import (ApprovalError, ChangeBlocked, ImprovementError, ImprovementStateError, InvalidProposalError, PreparationError)
from jarvis.self_improvement.llm import LLMImprovementWriter
from jarvis.self_improvement.models import Approval, Evidence, Proposal, StageReport, utcnow
from jarvis.self_improvement.pipeline import ValidationPipeline
from jarvis.self_improvement.state import ProposalStatus as S
from jarvis.self_improvement.store import ProposalStore
from jarvis.self_improvement.workspace import GitWorkspace, PreparedChange, Worktree

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
    def __init__(self, store: ProposalStore, *, analyzer: ImprovementAnalyzer | None = None, workspace: GitWorkspace | None = None,
                 pipeline: ValidationPipeline | None = None, gate: ApprovalGate | None = None, audit: Any = None, writer: LLMImprovementWriter | None = None,
                 allow_prepare: bool = False, allow_activation: bool = False, max_edits: int = 5, strict_audit: bool = True,
                 detector: SecretDetector | None = None) -> None:
        self._store, self._analyzer, self._ws, self._pipe, self._gate = store, analyzer, workspace, pipeline, gate
        self._audit, self._writer = audit, writer
        self.allow_prepare, self.allow_activation, self.max_edits = allow_prepare, allow_activation, max(1, min(max_edits, P.MAX_EDITS_HARD))
        self._strict_audit = strict_audit and audit is not None
        self._detector = detector or SecretDetector.from_environment()
        self._lock = threading.RLock()
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
        return {"proposals": len(items), "by_status": counts, "prepare": self.allow_prepare and self._ws is not None,
                "activation": self.allow_activation, "llm": bool(self._writer and self._writer.available), "approval_channel": self._gate.channel if self._gate else "none"}

    # ---- audit / transitions -------------------------------------------------------------------------------------------------------------
    def _emit(self, p: Proposal, action: str, status: str, detail: str = "", extra: Mapping[str, str] | None = None) -> bool:
        if self._audit is None:
            return True
        try:
            ok = bool(self._audit.record(AuditEvent(AuditEventType.IMPROVEMENT, tool="self_improvement", action=action, resource=p.proposal_id,
                                                    status=status, detail=detail[:300], extra=dict(extra or {}))))
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            log.error("audit of %s %s failed", action, p.proposal_id)
        return ok

    def _must_audit(self, p: Proposal, action: str, detail: str = "") -> None:
        """Approval, activation and rollback are only done if the audit trail accepts the event first (fail closed)."""
        if not self._emit(p, action + "_requested", "pending", detail) and self._strict_audit:
            raise ImprovementError("the audit log is unavailable: this action is refused (fail closed)")

    def _move(self, p: Proposal, new: S, actor: str, note: str = "", **changes: Any) -> Proposal:
        moved = p.moved(new, actor, self._detector.redact(note), **changes)
        self._store.save(moved)
        self._emit(moved, new.value.lower(), "ok", note, {"from": p.status.value, "actor": actor})
        return moved

    def _lock_for(self, proposal_id: str) -> threading.Event:
        with self._lock:
            if proposal_id in self._busy:
                raise ImprovementStateError("another operation on this proposal is still running")
            ev = self._busy[proposal_id] = threading.Event()
            return ev

    def _release(self, proposal_id: str) -> None:
        with self._lock:
            self._busy.pop(proposal_id, None)

    def cancel(self, proposal_id: str) -> bool:
        """Ask the running preparation/test of this proposal to stop (its processes are killed). False if nothing runs."""
        with self._lock:
            ev = self._busy.get(proposal_id)
        if ev is None:
            return False
        ev.set()
        self._emit(self._store.get(proposal_id), "cancel_requested", "ok")
        return True

    # ---- 1/2: detect and propose ---------------------------------------------------------------------------------------------------------
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
                self._store.save(p)
                self._emit(p, "detected", "ok", ob.key, {"source": p.source})
                p = self._move(p, S.PROPOSED, "llm" if ob.key in refined else "analysis", "improvement proposed")
                rep.created.append(p)
            except InvalidProposalError as exc:
                rep.warnings.append(f"{ob.key}: proposal refused ({exc})")
        return rep

    def propose(self, title: str, problem: str, *, change: str = "", benefit: str = "", risks: Sequence[str] = (), affected: Sequence[str] = (),
                suggested_tests: Sequence[str] = ()) -> Proposal:
        """A proposal written by the user. It carries no evidence claim; it cannot be mistaken for an analysed one (source = user)."""
        p = Proposal(title=title, problem=problem, change=change, benefit=benefit, risks=tuple(risks), affected=tuple(affected),
                     suggested_tests=tuple(suggested_tests), source="user")
        self._store.save(p)
        self._emit(p, "detected", "ok", "", {"source": "user"})
        return self._move(p, S.PROPOSED, "user", "proposed by the user")

    # ---- 3: prepare ----------------------------------------------------------------------------------------------------------------------
    def prepare(self, proposal_id: str, edits: Sequence[Mapping[str, str]] | None = None, *, files: Sequence[str] = ()) -> Proposal:
        """Prepare the change in its own branch/worktree. `edits` come from the user; without them `files` + the language model draft the edits
        (still validated by the same rules). The active branch and working tree are not touched."""
        p = self._store.get(proposal_id)
        if p.status not in (S.PROPOSED, S.FAILED):
            raise ImprovementStateError(f"a proposal in status {p.status.value} cannot be prepared")
        if not self.allow_prepare or self._ws is None:
            raise ImprovementError("preparing changes is off (self_improvement.allow_prepare = true and a repository are required)")
        cancel = self._lock_for(proposal_id)
        wt: Worktree | None = None
        try:
            if p.status is S.FAILED:
                self._ws.discard(p.proposal_id, p.branch)
                p = self._move(p, S.PROPOSED, "user", "retry after failure", branch="", base_commit="", head_commit="", diff_digest="", stages=(), changed_files=(), approval=None)
            try:
                if edits is not None:
                    clean = P.validate_edits(list(edits), self.max_edits)
                    self._screen(p, clean)
                wt = self._ws.create_worktree(p.proposal_id, cancel)
                if edits is None:
                    clean = self._draft(p, wt, files)
                    self._screen(p, clean)
                change = self._ws.apply_and_commit(wt, clean, f"self-improvement {p.proposal_id}: prepared change (not activated)", cancel)
            except ChangeBlocked as exc:
                if wt:
                    self._ws.discard(p.proposal_id, wt.branch)
                return self._move(p, S.BLOCKED, "system", f"manual review required: {exc}", reason=str(exc))
            except (ValueError, ImprovementError) as exc:
                if wt:
                    self._ws.discard(p.proposal_id, wt.branch)
                return self._move(p, S.FAILED, "system", f"preparation failed: {exc}", reason=str(exc))
            except Exception as exc:  # noqa: BLE001 - whatever goes wrong while preparing ends in a recorded, safe state
                if wt:
                    self._ws.discard(p.proposal_id, wt.branch)
                log.warning("preparation of %s crashed (%s)", p.proposal_id, type(exc).__name__)
                return self._move(p, S.FAILED, "system", f"preparation failed ({type(exc).__name__})", reason=type(exc).__name__)
            return self._move(p, S.PREPARED, "system", f"prepared on branch {wt.branch}", edits=tuple(clean), branch=wt.branch, base_commit=wt.base_commit,
                              head_commit=change.head_commit, diff_digest=change.diff_digest, diff_stat=change.stat, changed_files=change.changed_files)
        finally:
            self._release(proposal_id)

    def _screen(self, p: Proposal, edits: Sequence[Mapping[str, str]]) -> None:
        why = P.check_edits_allowed(edits)
        if why:
            raise ChangeBlocked(why)

    def _draft(self, p: Proposal, wt: Worktree, files: Sequence[str]) -> tuple[dict[str, str], ...]:
        if self._writer is None or not self._writer.available:
            raise PreparationError("no edits were given and no language model provider is available")
        if not files:
            raise PreparationError("name the files the change may touch (files=...)")
        contents: dict[str, str] = {}
        for f in list(files)[:P.MAX_FILES]:
            contents[f] = self._ws.read_file(wt, f)        # path rules and confinement are enforced here (ChangeBlocked for protected files)
        return self._writer.draft_edits(p, contents, self.max_edits)

    # ---- 4: test -------------------------------------------------------------------------------------------------------------------------
    def test(self, proposal_id: str) -> Proposal:
        p = self._store.get(proposal_id)
        if p.status is not S.PREPARED:
            raise ImprovementStateError(f"only a PREPARED proposal can be tested (is {p.status.value})")
        if self._ws is None or self._pipe is None:
            raise ImprovementError("no test pipeline is configured")
        cancel = self._lock_for(proposal_id)
        try:
            try:
                wt = self._ws.worktree_for(p.proposal_id, p.branch, p.base_commit)
                change = self._ws.describe_change(wt, cancel)
                if change.diff_digest != p.diff_digest or change.head_commit != p.head_commit:
                    raise PreparationError("the prepared change was modified after preparation")
                result = self._pipe.run(change, p.suggested_tests, cancel)
            except ChangeBlocked as exc:
                return self._move(p, S.BLOCKED, "system", f"manual review required: {exc}", reason=str(exc))
            except Exception as exc:  # noqa: BLE001
                return self._move(p, S.FAILED, "system", f"testing failed: {exc}"[:300], reason=str(exc)[:300] or type(exc).__name__)
            p = p.evolve(stages=tuple(result.stages))
            if result.blocked:
                self._ws.discard(p.proposal_id, p.branch)
                return self._move(p, S.BLOCKED, "system", f"manual review required: {result.blocked}", reason=result.blocked)
            if result.passed:
                return self._move(p, S.TESTED, "system", "every validation stage executed and passed")
            return self._move(p, S.FAILED, "system", ("cancelled: " if result.cancelled else "tests did not pass: ") + result.failure, reason=result.failure)
        finally:
            self._release(proposal_id)

    # ---- 5/6: approval -------------------------------------------------------------------------------------------------------------------
    def submit_for_approval(self, proposal_id: str) -> Proposal:
        p = self._store.get(proposal_id)
        if p.status is not S.TESTED or not p.tests_passed:
            raise ImprovementStateError("only a TESTED proposal whose stages all executed and passed can be submitted")
        return self._move(p, S.READY_FOR_APPROVAL, "system", "waiting for the user's approval")

    def reject(self, proposal_id: str, reason: str = "") -> Proposal:
        p = self._store.get(proposal_id)
        if p.status is S.ACTIVATED:
            raise ImprovementStateError("an activated change is reverted with rollback, not rejected")
        moved = self._move(p, S.REJECTED, "user", reason or "rejected by the user", reason=reason or "rejected by the user")
        if self._ws is not None and p.branch:
            self._ws.discard(p.proposal_id, p.branch)
        return moved

    def approve(self, proposal_id: str) -> Proposal:
        """Ask the user. The approval is bound to the exact commit and diff digest shown; it is the only way to reach APPROVED."""
        p = self._store.get(proposal_id)
        if p.status is not S.READY_FOR_APPROVAL:
            raise ApprovalError(f"approval needs status READY_FOR_APPROVAL (is {p.status.value})")
        if not p.tests_passed:
            raise ApprovalError("the tests did not all execute and pass: approval is blocked")
        if self._gate is None or self._ws is None:
            raise ApprovalError("no approval channel is configured")
        self._verify_unchanged(p)
        self._must_audit(p, "approve", p.diff_digest)
        ctx = {"Titel": p.title, "Branch": p.branch, "Commit": p.head_commit[:12], "Diff-Digest": p.diff_digest, "Dateien": ", ".join(p.changed_files),
               "Tests": ", ".join(f"{s.name}={'ok' if s.passed else 'FAIL'}" for s in p.stages)}
        if not self._gate.ask("approve_change", p.proposal_id, "Prepared change was tested in an isolated branch. Approving does not activate it yet.", ctx):
            self._emit(p, "approve", "denied", "the user did not approve")
            raise ApprovalError("the change was not approved by the user")
        return self._move(p, S.APPROVED, "user", f"approved via {self._gate.channel}",
                          approval=Approval(utcnow(), self._gate.channel, p.head_commit, p.diff_digest))

    def _verify_unchanged(self, p: Proposal) -> PreparedChange:
        try:
            wt = self._ws.worktree_for(p.proposal_id, p.branch, p.base_commit)
            change = self._ws.describe_change(wt)
        except (ImprovementError, OSError) as exc:
            raise ApprovalError(f"the prepared change cannot be verified: {exc}") from None
        if change.head_commit != p.head_commit or change.diff_digest != p.diff_digest:
            raise ApprovalError("the prepared change differs from the one that was tested")
        return change

    # ---- 7: activate / roll back ---------------------------------------------------------------------------------------------------------
    def activate(self, proposal_id: str) -> Proposal:
        p = self._store.get(proposal_id)
        if p.status is not S.APPROVED or p.approval is None:
            raise ApprovalError(f"activation needs an explicit user approval (status is {p.status.value})")
        if not self.allow_activation:
            raise ApprovalError("activation is disabled (self_improvement.allow_activation = false)")
        if p.approval.head_commit != p.head_commit or p.approval.diff_digest != p.diff_digest or not p.tests_passed:
            raise ApprovalError("the approval does not match the prepared and tested change")
        if self._ws is None:
            raise ApprovalError("no repository is configured")
        self._verify_unchanged(p)
        self._must_audit(p, "activate", p.head_commit)
        try:
            self._ws.fast_forward(p.branch, p.base_commit, p.head_commit)
        except ImprovementError as exc:
            self._emit(p, "activate", "failed", str(exc))
            raise
        self._ws.discard(p.proposal_id, "")          # the worktree is no longer needed; the branch stays as the record
        return self._move(p, S.ACTIVATED, "user", f"merged {p.head_commit[:12]} into the active branch (restart JARVIS to load it)")

    def rollback(self, proposal_id: str) -> Proposal:
        p = self._store.get(proposal_id)
        if p.status is not S.ACTIVATED:
            raise ImprovementStateError(f"only an ACTIVATED change can be rolled back (is {p.status.value})")
        if self._ws is None:
            raise ImprovementError("no repository is configured")
        if self._gate is None or not self._gate.ask("rollback_change", p.proposal_id, "Revert a previously activated improvement (adds a revert commit).",
                                                    {"Titel": p.title, "Commit": p.head_commit[:12]}):
            raise ApprovalError("the rollback was not confirmed by the user")
        self._must_audit(p, "rollback", p.head_commit)
        new_head = self._ws.revert(p.head_commit)
        return self._move(p, S.ROLLED_BACK, "user", f"reverted by commit {new_head[:12]}")
