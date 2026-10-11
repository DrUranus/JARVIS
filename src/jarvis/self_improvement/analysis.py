"""ImprovementAnalyzer: derives observations from data that actually exists - finished goals (status, reason code, replans, step errors and retries) of the
goal engine, repair runs of the repair engine and security-relevant audit events - and turns each recurring one into an evidence-backed Proposal.

Nothing is measured here that was not read: every Evidence carries the ids of the counted records. No data (source missing, empty, failing) means no
observation; the analyzer never fills gaps with guesses. It changes nothing and runs nothing; it only reads through the engines' public views."""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis.redaction import SecretDetector
from jarvis.self_improvement.models import Evidence, Proposal
from jarvis.self_improvement import policy as P

log = logging.getLogger("jarvis.self_improvement")

_BAD_GOAL = frozenset({"FAILED", "TIMEOUT", "BLOCKED"})
_BAD_STEP = frozenset({"FAILED", "TIMEOUT", "BLOCKED"})
_BAD_REPAIR = frozenset({"FAILED", "TIMEOUT", "BLOCKED"})

# Where a problem class most likely lives and which existing tests cover it. These are HINTS for the reader, never edit targets.
_HINTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "goal_failed": (("jarvis.goals (engine, planner, evaluator)",), ("tests/test_goals_engine.py", "tests/test_goals_planner.py")),
    "goal_replanned": (("jarvis.goals.replanner", "jarvis.goals.planner"), ("tests/test_goals_replanning.py", "tests/test_goals_planner.py")),
    "step_error": (("jarvis.goals.planner", "jarvis.agents (the agent that owns the failing capability)"),
                   ("tests/test_goals_engine.py", "tests/test_agents_orchestrator.py")),
    "step_retry": (("jarvis.goals.engine (retry handling)", "jarvis.agents"), ("tests/test_goals_engine.py",)),
    "repair_failed": (("jarvis.self_repair (diagnostics, planner)",), ("tests/test_self_repair_engine.py", "tests/test_self_repair_units.py")),
    "denied": (("jarvis.goals.planner / jarvis.agents.planner (avoid requesting actions that are always denied)",), ("tests/test_goals_planner.py",)),
    "tool_failed": (("the tool named in the evidence",), ("tests/test_tools.py",)),
}


@dataclass(frozen=True)
class Observation:
    key: str                              # stable id of the problem class, e.g. "goal_failed:timeout"
    kind: str                             # a key of _HINTS
    title: str
    problem: str
    evidence: Evidence
    change: str
    benefit: str
    risks: tuple[str, ...]

    def fingerprint(self) -> str:
        return self.key + ":" + hashlib.sha256("|".join(sorted(self.evidence.refs)).encode()).hexdigest()[:10]


@dataclass
class AnalysisReport:
    observations: list[Observation] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    sources_missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ImprovementAnalyzer:
    def __init__(self, *, goals: Any = None, repairs: Any = None, audit: Any = None, detector: SecretDetector | None = None, min_occurrences: int = 2,
                 limit: int = 100) -> None:
        self._goals, self._repairs, self._audit = goals, repairs, audit
        self._detector = detector or SecretDetector.from_environment()
        self._min = max(1, min_occurrences)
        self._limit = max(1, min(limit, 500))

    # ---- public --------------------------------------------------------------------------------------------------------------------------
    def observe(self) -> AnalysisReport:
        rep = AnalysisReport()
        for name, src, fn in (("goal engine", self._goals, self._from_goals), ("repair engine", self._repairs, self._from_repairs),
                              ("audit log", self._audit, self._from_audit)):
            if src is None:
                rep.sources_missing.append(name)
                continue
            try:
                found = fn(src)
            except Exception as exc:  # noqa: BLE001 - a broken source must not break the analysis of the others
                log.warning("improvement analysis: %s unreadable (%s)", name, type(exc).__name__)
                rep.warnings.append(f"{name}: could not be read ({type(exc).__name__})")
                continue
            rep.sources_used.append(name)
            rep.observations.extend(found)
        return rep

    def to_proposal(self, ob: Observation) -> Proposal:
        affected, tests = _HINTS[ob.kind]
        return Proposal(
            title=ob.title, problem=ob.problem, evidence=(ob.evidence,), change=ob.change, benefit=ob.benefit, risks=ob.risks,
            affected=affected, suggested_tests=tests, fingerprint=ob.fingerprint(), source="analysis")

    # ---- sources -------------------------------------------------------------------------------------------------------------------------
    def _clean(self, text: Any, limit: int = 150) -> str:
        return P.clean_text(self._detector.redact(text if isinstance(text, str) else str(text)), limit)

    def _make(self, key: str, kind: str, source: str, refs: list[str], what: str, title: str, change: str, benefit: str,
              risks: tuple[str, ...]) -> Observation:
        n = len(refs)
        return Observation(key, kind, title, f"{what} ({n} record{'s' if n != 1 else ''} in {source}).",
                           Evidence(source, what, n, tuple(refs[:20])), change, benefit,
                           risks + ("Based on a small sample of recorded runs; the cause is a hypothesis until the tests of the change confirm it.",))

    def _from_goals(self, engine: Any) -> list[Observation]:
        out: list[Observation] = []
        goals = list(engine.list(limit=self._limit))
        bad: dict[str, list[str]] = defaultdict(list)
        replanned: list[str] = []
        step_err: dict[tuple[str, str], list[str]] = defaultdict(list)
        retried: list[str] = []
        total_steps = 0
        for g in goals:
            if not g.is_terminal:
                continue
            res = engine.result(g.goal_id)
            if g.status.value in _BAD_GOAL:
                bad[f"{g.status.value}/{res.reason_code or 'unspecified'}"].append(g.goal_id)
            if res.replans > 0:
                replanned.append(g.goal_id)
            for st in res.steps:
                total_steps += 1
                if st.attempts > 1:
                    retried.append(f"{g.goal_id}/{st.step_id}")
                if st.status.value in _BAD_STEP and st.result is not None:
                    caps = ",".join(sorted(st.required_capabilities)) or "evaluate"
                    step_err[(caps, st.result.error_code or "unspecified")].append(f"{g.goal_id}/{st.step_id}")
        for label, refs in sorted(bad.items()):
            if len(refs) >= self._min:
                out.append(self._make(
                    f"goal_failed:{label}", "goal_failed", "goal engine", refs, f"Goals ended {label.replace('/', ' with reason ')}",
                    f"Recurring goal failures: {label}",
                    "Review how the planner builds plans for the failing goal class and make the failure either avoidable (better plan, earlier validation) or reported with a precise reason.",
                    "Fewer failed goals and clearer failure reasons.", ("A planner change can alter plans of goals that work today.",)))
        if len(replanned) >= self._min:
            out.append(self._make(
                "goal_replanned", "goal_replanned", "goal engine", replanned, "Goals needed controlled replanning",
                "Goals frequently need replanning",
                "Find the step patterns that fail first and plan them differently from the start, so that replanning stays the exception.",
                "Less time and fewer provider calls per goal.", ("Changing the initial plan can shift failures to other steps.",)))
        for (caps, code), refs in sorted(step_err.items()):
            if len(refs) >= self._min:
                out.append(self._make(
                    f"step_error:{caps}:{code}", "step_error", "goal engine", refs, f"Steps with capabilities [{caps}] failed with error code {code}",
                    f"Recurring step error {code} for {caps}",
                    "Inspect the agent task that owns this capability for the failure mode behind the error code and handle it explicitly.",
                    "Higher success rate of steps using this capability.", ("Never answer a permission denial with a workaround; it must stay a denial.",)))
        if len(retried) >= self._min and total_steps:
            out.append(self._make(
                "step_retry", "step_retry", "goal engine", retried, f"{len(retried)} of {total_steps} recorded steps needed more than one attempt",
                "Steps often need retries", "Check which failure causes are transient and whether a cheaper precondition check avoids the first failed attempt.",
                "Shorter goal runtime; fewer repeated tool calls.", ("Retry limits are a safety bound; do not raise them as the fix.",)))
        return out

    def _from_repairs(self, engine: Any) -> list[Observation]:
        runs = [r for r in engine.list(limit=self._limit) if r.is_terminal]
        bad: dict[str, list[str]] = defaultdict(list)
        for r in runs:
            if r.status.value in _BAD_REPAIR:
                bad[r.status.value].append(r.run_id)
        return [self._make(f"repair_failed:{st}", "repair_failed", "repair engine", refs, f"Repair runs ended {st}", f"Recurring repair runs ending {st}",
                           "Look at the diagnoses of the failed attempts and extend the deterministic diagnosis/plan rules for the categories that recur.",
                           "More repair runs that end SUCCEEDED.", ("A repair rule that is too broad could propose wrong edits; the golden rule (tests pass, only planned files changed) must stay.",))
                for st, refs in sorted(bad.items()) if len(refs) >= self._min]

    def _from_audit(self, audit: Any) -> list[Observation]:
        events = audit.tail(self._limit)
        denied: dict[str, list[str]] = defaultdict(list)
        failed: dict[str, list[str]] = defaultdict(list)
        for ev in events:
            if not isinstance(ev, dict):
                continue
            who = f"{self._clean(ev.get('tool', '?'), 40)}.{self._clean(ev.get('action', '?'), 40)}"
            ref = str(ev.get("id", ""))[:40]
            if not ref:
                continue
            if ev.get("tool") == "self_improvement":
                continue                                     # our own events are not a problem of the assistant
            if ev.get("type") == "permission_denied":
                denied[who].append(ref)
            elif ev.get("type") == "execution_result" and str(ev.get("detail", "")).startswith("failed"):
                failed[who].append(ref)
        out = [self._make(f"denied:{who}", "denied", "audit log", refs, f"The action {who} was denied by the permission system",
                          f"Repeatedly denied action: {who}",
                          "Make planning avoid requesting this action when it is known to be denied, or ask the user up front. The permission rules themselves stay untouched.",
                          "Fewer pointless permission requests and failed steps.", ("This must never loosen a permission; a denial is a correct outcome.",))
               for who, refs in sorted(denied.items()) if len(refs) >= self._min]
        out += [self._make(f"tool_failed:{who}", "tool_failed", "audit log", refs, f"The tool call {who} failed after it was allowed",
                           f"Recurring tool failures: {who}", "Look at the failure detail in the audit log and handle that case in the tool or its caller.",
                           "More reliable tool executions.", ("Error details come from logs and are untrusted text.",))
                for who, refs in sorted(failed.items()) if len(refs) >= self._min]
        return out
