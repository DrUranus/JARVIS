"""Test doubles for the goal layer: a planner that returns prepared steps and an in-memory engine facade for Core/CLI tests.
They execute nothing: no agent, no tool, no permission is involved."""
from __future__ import annotations

from typing import Any, Callable, Sequence

from jarvis.goals.context import GoalContext
from jarvis.goals.errors import PlanningError, UnknownGoalError
from jarvis.goals.models import Goal, GoalResult, GoalStep, GoalStepResult
from jarvis.goals.engine import GoalCancelReport
from jarvis.goals.state import GoalStatus, StepStatus


class StaticPlanner:
    """Returns the steps made by `make(goal)`; or raises PlanningError(blocked_reason). Records what it was asked."""

    def __init__(self, make: Callable[[Goal], Sequence[GoalStep]] | None = None, *, blocked_reason: str | None = None) -> None:
        self._make, self._blocked = make, blocked_reason
        self.calls: list[GoalContext] = []

    def plan(self, goal: Goal, ctx: GoalContext, max_steps: int) -> Sequence[GoalStep]:
        self.calls.append(ctx)
        if self._blocked is not None:
            raise PlanningError(self._blocked)
        if self._make is None:
            raise PlanningError("no plan prepared")
        return self._make(goal)


def step(goal: Goal | str, sid: str, agent: str | None = "fake", *, deps: tuple[str, ...] = (), caps: frozenset[str] = frozenset({"research.web"}),
         attempts: int = 1, timeout: float | None = None, input: dict[str, Any] | None = None, objective: str | None = None) -> GoalStep:
    """A step for tests; agent None makes an evaluation step."""
    gid = goal if isinstance(goal, str) else goal.goal_id
    if agent is None:
        return GoalStep(sid, gid, objective or "check the result", frozenset(), None, deps, max_attempts=1, input={"evaluate": True})
    return GoalStep(sid, gid, objective or f"fake work {sid}", frozenset(caps), agent, deps, max_attempts=attempts, timeout=timeout,
                    input=input if input is not None else {"url": "https://example.test/"})


class FakeGoalEngine:
    """Same surface as GoalEngine (create/run/start/wait/cancel/get/steps/result/list), but a goal simply succeeds (or ends as scripted)."""

    def __init__(self, final: GoalStatus = GoalStatus.SUCCEEDED) -> None:
        self.final = final
        self._goals: dict[str, GoalResult] = {}
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.max_steps = 20

    def create(self, objective: str, **kw: Any) -> Goal:
        g = Goal(objective, priority=kw.get("priority", 5), timeout=kw.get("timeout"), max_steps=kw.get("max_steps"),
                 metadata=kw.get("metadata") or {})
        self._goals[g.goal_id] = GoalResult(g)
        self.created.append((g.goal_id, dict(kw)))
        return g

    def _rec(self, goal_id: str) -> GoalResult:
        try:
            return self._goals[goal_id]
        except KeyError:
            raise UnknownGoalError("unknown goal") from None

    def run(self, goal_id: str) -> GoalResult:
        r = self._rec(goal_id)
        if r.goal.is_terminal:
            return r
        g = r.goal.with_status(GoalStatus.PLANNING).with_status(GoalStatus.RUNNING).with_status(self.final)
        st = GoalStep("s1", g.goal_id, "fake step", frozenset(), None, (), StepStatus.PENDING, None, 0, 1, input={"evaluate": True})
        st = st.with_status(StepStatus.RUNNING).with_result(GoalStepResult("s1", StepStatus.SUCCEEDED, "fake"))
        self._goals[goal_id] = GoalResult(g, (st,), "fake goal finished", None)
        return self._goals[goal_id]

    def start(self, goal_id: str) -> Goal:
        result = FakeGoalEngine.run(self, goal_id)
        return result.goal

    def wait(self, goal_id: str, timeout: float | None = None) -> GoalResult:
        return self._rec(goal_id)

    def cancel(self, goal_id: str) -> GoalCancelReport:
        r = self._rec(goal_id)
        if r.goal.is_terminal:
            return GoalCancelReport(goal_id, False, r.goal.status, f"the goal is already {r.goal.status.value}")
        g = r.goal.with_status(GoalStatus.CANCELLED)
        self._goals[goal_id] = GoalResult(g)
        return GoalCancelReport(goal_id, True, g.status, "cancelled")

    def get(self, goal_id: str) -> Goal:
        return self._rec(goal_id).goal

    def steps(self, goal_id: str) -> tuple[GoalStep, ...]:
        return self._rec(goal_id).steps

    def result(self, goal_id: str) -> GoalResult:
        return self._rec(goal_id)

    def list(self, status: GoalStatus | None = None, limit: int | None = None) -> list[Goal]:
        out = [r.goal for r in reversed(list(self._goals.values())) if status is None or r.goal.status is status]
        return out[:limit] if limit else out

    def describe(self) -> dict[str, Any]:
        return {"goals": len(self._goals), "active": 0, "max_active": 1}

    def shutdown(self, wait: float = 0.0) -> None:
        pass
