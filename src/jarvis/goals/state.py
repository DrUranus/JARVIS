"""Lifecycles. Goal: PENDING -> PLANNING -> RUNNING <-> WAITING -> terminal. Step: PENDING -> RUNNING -> terminal.
There is no way back: a terminal status is final, a step never returns to PENDING (a retry stays RUNNING and counts attempts),
a goal never returns to PLANNING. RUNNING <-> WAITING is the only cycle (working vs. waiting for agent results)."""
from __future__ import annotations

from enum import Enum

from jarvis.goals.errors import GoalStateError


class GoalStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


_G, _S = GoalStatus, StepStatus
GOAL_TERMINAL = frozenset({_G.SUCCEEDED, _G.FAILED, _G.BLOCKED, _G.CANCELLED, _G.TIMEOUT})
STEP_TERMINAL = frozenset({_S.SUCCEEDED, _S.FAILED, _S.BLOCKED, _S.CANCELLED, _S.TIMEOUT})
STEP_BAD = STEP_TERMINAL - {_S.SUCCEEDED}

_END = frozenset({_G.FAILED, _G.BLOCKED, _G.CANCELLED, _G.TIMEOUT})
GOAL_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    _G.PENDING: frozenset({_G.PLANNING, _G.CANCELLED, _G.TIMEOUT}),
    _G.PLANNING: frozenset({_G.RUNNING}) | _END,
    _G.RUNNING: frozenset({_G.WAITING, _G.SUCCEEDED}) | _END,
    _G.WAITING: frozenset({_G.RUNNING, _G.SUCCEEDED}) | _END,
    **{s: frozenset() for s in GOAL_TERMINAL},
}
STEP_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    _S.PENDING: frozenset({_S.RUNNING, _S.BLOCKED, _S.CANCELLED, _S.FAILED}),
    _S.RUNNING: frozenset({_S.SUCCEEDED, _S.FAILED, _S.BLOCKED, _S.CANCELLED, _S.TIMEOUT}),
    **{s: frozenset() for s in STEP_TERMINAL},
}


def check_goal_transition(old: GoalStatus, new: GoalStatus) -> None:
    if new not in GOAL_TRANSITIONS[old]:
        raise GoalStateError(f"illegal goal transition {old.value} -> {new.value}")


def check_step_transition(old: StepStatus, new: StepStatus) -> None:
    if new not in STEP_TRANSITIONS[old]:
        raise GoalStateError(f"illegal step transition {old.value} -> {new.value}")
