"""Goal, GoalStep and GoalStepResult: immutable snapshots with validated construction and validated status changes.
Free text (objective, summaries, outputs) never appears in a repr; serialisation is bounded and contains no step input values."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from jarvis.goals import policy as P
from jarvis.goals.errors import InvalidGoalError
from jarvis.goals.state import GoalStatus, StepStatus, check_goal_transition, check_step_transition


def new_goal_id() -> str:
    return "g-" + uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _plain_text(value: object, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not any(
        ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value)


@dataclass(frozen=True)
class Goal:
    objective: str = field(repr=False)
    goal_id: str = field(default_factory=new_goal_id)
    status: GoalStatus = GoalStatus.PENDING
    priority: int = 5
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    timeout: float | None = None            # seconds for the whole goal; None = the engine's configured default
    max_steps: int | None = None            # None = the engine's configured default (never above the hard limit)
    metadata: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not _plain_text(self.objective, P.MAX_OBJECTIVE):
            raise InvalidGoalError(f"objective must be 1..{P.MAX_OBJECTIVE} characters of plain text")
        if not P.valid_id(self.goal_id):
            raise InvalidGoalError("goal_id must be 1..64 characters of letters, digits, _ . -")
        if not isinstance(self.status, GoalStatus):
            raise InvalidGoalError("status must be a GoalStatus")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool) or not 1 <= self.priority <= 10:
            raise InvalidGoalError("priority must be an integer within 1..10")
        if self.timeout is not None and (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                                         or not 0 < self.timeout <= P.MAX_TIMEOUT):
            raise InvalidGoalError(f"timeout must be within 0..{P.MAX_TIMEOUT:g} seconds")
        if self.max_steps is not None and (isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int)
                                           or not 1 <= self.max_steps <= P.MAX_STEPS_HARD):
            raise InvalidGoalError(f"max_steps must be within 1..{P.MAX_STEPS_HARD}")
        if not isinstance(self.metadata, Mapping) or len(self.metadata) > P.MAX_METADATA_ITEMS or not all(
                isinstance(k, str) and isinstance(v, str) and len(k) <= 50 and len(v) <= 500 for k, v in self.metadata.items()):
            raise InvalidGoalError("metadata must be a small mapping of short strings")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_terminal(self) -> bool:
        from jarvis.goals.state import GOAL_TERMINAL
        return self.status in GOAL_TERMINAL

    def with_status(self, new: GoalStatus, now: datetime | None = None) -> "Goal":
        check_goal_transition(self.status, new)
        return replace(self, status=new, updated_at=now or utcnow())

    def to_dict(self) -> dict[str, Any]:
        return {"goal_id": self.goal_id, "objective": P.clip(self.objective, P.MAX_OBJECTIVE), "status": self.status.value,
                "priority": self.priority, "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(),
                "timeout": self.timeout, "max_steps": self.max_steps, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class GoalStepResult:
    step_id: str
    status: StepStatus
    summary: str = field(default="", repr=False)
    output: Any = field(default=None, repr=False)
    agent_id: str | None = None
    task_id: str | None = None
    duration: float = 0.0
    attempts: int = 1
    error_code: str | None = None
    attempt_log: tuple[Mapping[str, Any], ...] = field(default=(), repr=False)   # one entry per attempt: retries are visible

    def __post_init__(self) -> None:
        if not P.valid_id(self.step_id) or not isinstance(self.status, StepStatus):
            raise InvalidGoalError("a step result needs a valid step_id and a StepStatus")
        object.__setattr__(self, "summary", P.clip(self.summary if isinstance(self.summary, str) else str(self.summary), P.MAX_SUMMARY))
        try:
            P.check_plain(self.output, "output")
        except ValueError:
            object.__setattr__(self, "output", {"unserialisable": True})
        object.__setattr__(self, "output", P.limit_output(P.plain_copy(self.output)))
        if not isinstance(self.attempts, int) or isinstance(self.attempts, bool) or not 1 <= self.attempts <= P.MAX_ATTEMPTS_HARD:
            raise InvalidGoalError("attempts must be within 1..%d" % P.MAX_ATTEMPTS_HARD)
        if not isinstance(self.duration, (int, float)) or isinstance(self.duration, bool) or self.duration < 0 or self.duration != self.duration:
            object.__setattr__(self, "duration", 0.0)
        object.__setattr__(self, "attempt_log", tuple(dict(a) for a in list(self.attempt_log)[:P.MAX_ATTEMPTS_HARD]))

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "status": self.status.value, "summary": self.summary, "output": self.output, "agent_id": self.agent_id,
                "task_id": self.task_id, "duration": round(float(self.duration), 3), "attempts": self.attempts, "error_code": self.error_code,
                "attempt_log": [dict(a) for a in self.attempt_log]}


@dataclass(frozen=True)
class GoalStep:
    step_id: str
    goal_id: str
    objective: str = field(repr=False)
    required_capabilities: frozenset[str] = frozenset()
    assigned_agent: str | None = None       # None only for an "evaluate" step (checked by the goal layer itself)
    dependencies: tuple[str, ...] = ()
    status: StepStatus = StepStatus.PENDING
    result: GoalStepResult | None = field(default=None, repr=False)
    attempts: int = 0
    max_attempts: int = 1
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    input: Mapping[str, Any] = field(default_factory=dict, repr=False)   # structured, plain data for the agent task
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not P.valid_id(self.step_id) or not P.valid_id(self.goal_id):
            raise InvalidGoalError("step_id and goal_id must be 1..64 characters of letters, digits, _ . -")
        if not _plain_text(self.objective, P.MAX_OBJECTIVE):
            raise InvalidGoalError("a step objective must be plain text")
        caps = frozenset(self.required_capabilities)
        object.__setattr__(self, "required_capabilities", caps)
        if self.assigned_agent is not None and not isinstance(self.assigned_agent, str):
            raise InvalidGoalError("assigned_agent must be an agent id or None")
        deps = tuple(self.dependencies)
        if len(set(deps)) != len(deps) or self.step_id in deps or not all(P.valid_id(d) for d in deps):
            raise InvalidGoalError("dependencies must be distinct step ids (never the step itself)")
        object.__setattr__(self, "dependencies", deps)
        if not isinstance(self.status, StepStatus):
            raise InvalidGoalError("status must be a StepStatus")
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= P.MAX_ATTEMPTS_HARD:
            raise InvalidGoalError(f"max_attempts must be within 1..{P.MAX_ATTEMPTS_HARD}")
        if not isinstance(self.attempts, int) or isinstance(self.attempts, bool) or not 0 <= self.attempts <= self.max_attempts:
            raise InvalidGoalError("attempts must be within 0..max_attempts")
        if self.timeout is not None and (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                                         or not 0 < self.timeout <= P.MAX_STEP_TIMEOUT):
            raise InvalidGoalError(f"step timeout must be within 0..{P.MAX_STEP_TIMEOUT:g} seconds")
        if not isinstance(self.input, Mapping):
            raise InvalidGoalError("input must be a mapping")
        try:
            P.check_plain(self.input, "input")
        except ValueError as exc:
            raise InvalidGoalError(str(exc)) from None
        object.__setattr__(self, "input", P.plain_copy(self.input))

    @property
    def is_evaluation(self) -> bool:
        return self.assigned_agent is None and bool(self.input.get(P.EVALUATE))

    def with_status(self, new: StepStatus, now: datetime | None = None) -> "GoalStep":
        check_step_transition(self.status, new)
        return replace(self, status=new, updated_at=now or utcnow())

    def with_attempt(self, now: datetime | None = None) -> "GoalStep":
        if self.attempts >= self.max_attempts:
            raise InvalidGoalError("no attempts left")
        return replace(self, attempts=self.attempts + 1, updated_at=now or utcnow())

    def with_result(self, result: GoalStepResult, now: datetime | None = None) -> "GoalStep":
        """Final result: the step status becomes the result status (validated like any other transition)."""
        step = self.with_status(result.status, now)
        return replace(step, result=result)

    def to_dict(self) -> dict[str, Any]:
        """No input values (they can hold typed text or file contents): only which keys the step passes."""
        return {"step_id": self.step_id, "goal_id": self.goal_id, "objective": P.clip(self.objective, 300), "status": self.status.value,
                "required_capabilities": sorted(self.required_capabilities), "assigned_agent": self.assigned_agent,
                "dependencies": list(self.dependencies), "attempts": self.attempts, "max_attempts": self.max_attempts,
                "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(), "input_keys": sorted(self.input),
                "timeout": self.timeout, "result": self.result.to_dict() if self.result else None}


@dataclass(frozen=True)
class GoalResult:
    """What a finished (or running) goal looks like to the outside: a snapshot, bounded and redacted by the engine."""
    goal: Goal
    steps: tuple[GoalStep, ...] = ()
    summary: str = field(default="", repr=False)
    reason_code: str | None = None
    warnings: tuple[str, ...] = field(default=(), repr=False)
    duration: float = 0.0

    @property
    def status(self) -> GoalStatus:
        return self.goal.status

    @property
    def succeeded(self) -> bool:
        return self.goal.status is GoalStatus.SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal.to_dict(), "steps": [s.to_dict() for s in self.steps], "summary": self.summary,
                "reason_code": self.reason_code, "warnings": list(self.warnings), "duration": round(self.duration, 3)}
