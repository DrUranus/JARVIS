"""RepairPlanner: a conservative plan for ONE attempt - or a refusal. It never invents a fix: the edits come from a proposer
(v1: the candidates the user supplied explicitly) and every file they touch is checked against the repair rules.
A problem that is not understood, or a proposal that is not acceptable, yields PlanBlocked - never an invented repair."""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from jarvis.agents import policy as AP
from jarvis.self_repair import policy as P
from jarvis.self_repair.context import RepairContext
from jarvis.self_repair.errors import InvalidRepairError, PlanBlocked
from jarvis.self_repair.models import Diagnosis, RepairPlan, TestResult


class Proposer(Protocol):
    def propose(self, result: TestResult, diagnosis: Diagnosis, ctx: RepairContext, attempt_no: int) -> Mapping[str, Any] | None: ...


class SuppliedProposer:
    """Attempt n uses candidate n of the user. There is no hidden source of fixes: no LLM, no templates."""

    def propose(self, result: TestResult, diagnosis: Diagnosis, ctx: RepairContext, attempt_no: int) -> Mapping[str, Any] | None:
        return ctx.candidates[attempt_no - 1] if attempt_no <= len(ctx.candidates) else None


class RepairPlanner:
    def __init__(self, proposer: Proposer | None = None) -> None:
        self._proposer = proposer or SuppliedProposer()

    @staticmethod
    def check_candidate(cand: Mapping[str, Any]) -> list[str]:
        """Everything about ONE candidate that can be judged without running anything: forbidden keys, edit shape and every target path
        (separator-agnostic: backslash and slash are treated alike; '..' anywhere, absolute, UNC and drive paths are refused).
        Returns the declared target files."""
        bad = P.find_reserved(cand)
        if bad:
            raise PlanBlocked(f"the proposal contains the forbidden key {bad!r}")
        edits = cand.get("edits")
        if not isinstance(edits, (list, tuple)) or not 1 <= len(edits) <= P.MAX_EDITS or not all(isinstance(e, Mapping) for e in edits):
            raise PlanBlocked(f"a proposal needs 1..{P.MAX_EDITS} edits")
        for e in edits:
            if set(e) - P.EDIT_KEYS or not isinstance(e.get("path"), str):
                raise PlanBlocked(f"an edit may only use {sorted(P.EDIT_KEYS)} and needs a path")
            why = P.refuse_target(e["path"])
            if why:
                raise PlanBlocked(f"edit refused ({why})")
        paths = [e["path"] for e in edits]
        targets = cand.get("target_files") or list(dict.fromkeys(paths))
        if not isinstance(targets, (list, tuple)) or not all(isinstance(t, str) for t in targets):
            raise PlanBlocked("target_files must be a list of paths")
        for t in targets:
            why = P.refuse_target(t)
            if why:
                raise PlanBlocked(f"target file refused ({why})")
        declared = {P.norm_path(t) for t in targets}
        stray = sorted(p for p in paths if P.norm_path(p) not in declared)
        if stray:
            raise PlanBlocked(f"the edits touch files outside the declared target_files: {stray[:3]}")
        return list(targets)

    def preflight(self, ctx: RepairContext) -> None:
        """Judge ALL supplied candidates before the first test or repair step: an unacceptable candidate blocks the run up front."""
        for i, cand in enumerate(ctx.candidates, 1):
            try:
                self.check_candidate(cand)
            except PlanBlocked as exc:
                raise PlanBlocked(f"candidate {i}: {exc}") from None

    def plan(self, result: TestResult, diagnosis: Diagnosis, ctx: RepairContext, attempt_no: int) -> RepairPlan:
        if not diagnosis.repairable:
            raise PlanBlocked(f"{diagnosis.category.value} is not repaired automatically: {diagnosis.summary}")
        cand = self._proposer.propose(result, diagnosis, ctx, attempt_no)
        if cand is None:
            raise PlanBlocked("no repair proposal: this version writes no fix by itself; pass candidate edits (context 'candidates')")
        targets = self.check_candidate(cand)
        edits = cand["edits"]
        tests = tuple(diagnosis.failed_tests) or ctx.tests
        try:
            return RepairPlan(f"Behebe den Fehler in {', '.join(targets)[:200]} (Code, Datei)", tuple(targets), tuple(tests)[:P.MAX_TESTS],
                              frozenset({AP.CODING_READ, AP.CODING_WRITE, AP.CODING_TEST}),
                              str(cand.get("reason") or diagnosis.summary), tuple(dict(e) for e in edits))
        except InvalidRepairError as exc:
            raise PlanBlocked(str(exc)) from None


def targeted_args(plan: RepairPlan, ctx: RepairContext, failed: Sequence[str]) -> list[str]:
    """What the targeted re-test runs: the tests that failed (or, when the output named none, the tests the user named)."""
    return list(failed or plan.target_tests or ctx.tests)[: P.MAX_TESTS]
