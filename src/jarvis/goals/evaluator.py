"""GoalEvaluator: deterministic decisions - no LLM, no side effects. It looks at step states and says what happens next."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from jarvis.agents.state import TaskStatus
from jarvis.goals import policy as P
from jarvis.goals.models import GoalStep, GoalStepResult
from jarvis.goals.state import STEP_BAD, StepStatus


class Decision(str, Enum):
    REACHED = "reached"        # goal achieved -> SUCCEEDED
    NEXT = "next"              # there are steps ready to start
    WAIT = "wait"              # nothing to start, running steps will report
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


TERMINAL_DECISIONS = frozenset({Decision.REACHED, Decision.FAILED, Decision.BLOCKED, Decision.TIMEOUT, Decision.CANCELLED})


@dataclass(frozen=True)
class GoalDecision:
    kind: Decision
    reason: str = ""
    ready: tuple[str, ...] = ()


class Verdict(str, Enum):
    DONE = "done"
    RETRY = "retry"
    FINAL = "final"            # the step ends with the status given in StepVerdict.status


@dataclass(frozen=True)
class StepVerdict:
    kind: Verdict
    status: StepStatus = StepStatus.SUCCEEDED
    reason: str = ""


def is_cleanup(step: GoalStep) -> bool:
    return isinstance(step.input.get("cleanup"), str)


def _failed_checks(output: object) -> list[str]:
    """Tool steps of an agent task whose own result says 'not OK' although the call itself worked (a test run with passed=False)."""
    bad: list[str] = []
    steps = output.get("steps") if isinstance(output, dict) else None
    for i, st in enumerate(steps if isinstance(steps, list) else [], 1):
        if not isinstance(st, dict):
            continue
        out = st.get("output")
        if st.get("ok") is False or (isinstance(out, dict) and out.get("passed") is False):
            bad.append(f"{st.get('action') or 'step'} #{i} reported a failure")
    return bad


class GoalEvaluator:
    def judge(self, step: GoalStep, status: TaskStatus, code: str | None) -> StepVerdict:
        """What does one finished agent task mean for its step? Retries only for transient failures and only while attempts remain."""
        if status is TaskStatus.SUCCEEDED:
            return StepVerdict(Verdict.DONE)
        if status is TaskStatus.BLOCKED:
            return StepVerdict(Verdict.FINAL, StepStatus.BLOCKED, f"blocked ({code or 'blocked'}); not retried")
        if status is TaskStatus.CANCELLED:
            return StepVerdict(Verdict.FINAL, StepStatus.CANCELLED, "the agent task was cancelled")
        if status is TaskStatus.FAILED:
            if P.is_retryable(status, code) and step.attempts < step.max_attempts:
                return StepVerdict(Verdict.RETRY, reason=f"transient failure ({code}); retrying")
            return StepVerdict(Verdict.FINAL, StepStatus.TIMEOUT if code == "timeout" else StepStatus.FAILED,
                               f"failed ({code or 'failed'})" + ("" if P.is_retryable(status, code) else "; not retryable"))
        return StepVerdict(Verdict.FINAL, StepStatus.FAILED, "the agent returned an unexpected status")   # PENDING/RUNNING/garbage never count as success

    def blocked_by_dependencies(self, steps: Sequence[GoalStep]) -> tuple[str, ...]:
        """Pending steps that can never run because something they depend on ended badly (transitively). No dependency bypass."""
        status = {s.step_id: s.status for s in steps}
        out: list[str] = []
        changed = True
        while changed:
            changed = False
            for s in steps:
                if status[s.step_id] is StepStatus.PENDING and not is_cleanup(s) and any(status[d] in STEP_BAD for d in s.dependencies):
                    status[s.step_id] = StepStatus.BLOCKED
                    out.append(s.step_id)
                    changed = True
        return tuple(out)

    def decide(self, steps: Sequence[GoalStep], *, cancelled: bool = False, timed_out: bool = False) -> GoalDecision:
        if cancelled:
            return GoalDecision(Decision.CANCELLED, "the goal was cancelled")
        if timed_out:
            return GoalDecision(Decision.TIMEOUT, "the goal timeout was reached")
        core = [s for s in steps if not is_cleanup(s)]
        if not core:
            return GoalDecision(Decision.FAILED, "the goal has no steps")
        running = [s for s in core if s.status is StepStatus.RUNNING]
        bad = [s for s in core if s.status in STEP_BAD and not (s.result and (s.result.error_code or "").startswith("dependency_"))]
        if bad:
            if running:
                return GoalDecision(Decision.WAIT, "a step failed; waiting for the running steps")
            hard = [s for s in bad if s.status is not StepStatus.BLOCKED]
            if hard:
                return GoalDecision(Decision.FAILED, f"step {hard[0].step_id} ended {hard[0].status.value}")
            return GoalDecision(Decision.BLOCKED, f"step {bad[0].step_id} is blocked")
        if all(s.status is StepStatus.SUCCEEDED for s in core):
            return GoalDecision(Decision.REACHED, "all steps succeeded")
        done = {s.step_id for s in steps if s.status is StepStatus.SUCCEEDED}
        ready = tuple(s.step_id for s in core if s.status is StepStatus.PENDING and all(d in done for d in s.dependencies))
        if ready:
            return GoalDecision(Decision.NEXT, "", ready)
        if running:
            return GoalDecision(Decision.WAIT, "waiting for running steps")
        return GoalDecision(Decision.BLOCKED, "no remaining step can run")

    def check_evaluation(self, step: GoalStep, results: Sequence[GoalStepResult]) -> tuple[bool, str]:
        """An evaluation step passes when everything it depends on succeeded and produced something (a non-empty output or summary)."""
        if not results or len(results) < len(step.dependencies):
            return False, "the results to evaluate are missing"
        for r in results:
            if r.status is not StepStatus.SUCCEEDED:
                return False, f"step {r.step_id} did not succeed"
            problems = _failed_checks(r.output)
            if problems:
                return False, f"step {r.step_id}: {problems[0]}"
            out = r.output
            empty = out in (None, "", [], {}) or (isinstance(out, dict) and "text" in out and not str(out["text"]).strip())
            if empty and (not r.summary.strip() or (isinstance(out, dict) and "text" in out)):
                return False, f"step {r.step_id} produced no result"
        return True, f"{len(results)} result(s) checked"
