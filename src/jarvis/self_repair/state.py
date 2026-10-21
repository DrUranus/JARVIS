"""Lifecycles. Run: PENDING -> TESTING -> DIAGNOSING -> PLANNING -> REPAIRING -> RETESTING -> REGRESSION -> terminal, where a failed attempt
returns to DIAGNOSING for the next (bounded) attempt. A terminal status is final: there is no way back out of it."""
from __future__ import annotations

from enum import Enum

from jarvis.self_repair.errors import RepairStateError


class RepairStatus(str, Enum):
    PENDING = "PENDING"
    TESTING = "TESTING"
    DIAGNOSING = "DIAGNOSING"
    PLANNING = "PLANNING"
    REPAIRING = "REPAIRING"
    RETESTING = "RETESTING"
    REGRESSION = "REGRESSION"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class AttemptStatus(str, Enum):
    PENDING = "PENDING"
    REPAIRING = "REPAIRING"
    RETESTING = "RETESTING"
    REGRESSION = "REGRESSION"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


_R, _A = RepairStatus, AttemptStatus
RUN_TERMINAL = frozenset({_R.SUCCEEDED, _R.FAILED, _R.BLOCKED, _R.CANCELLED, _R.TIMEOUT})
ATTEMPT_TERMINAL = frozenset({_A.SUCCEEDED, _A.FAILED, _A.BLOCKED, _A.CANCELLED})
_END = frozenset({_R.FAILED, _R.BLOCKED, _R.CANCELLED, _R.TIMEOUT})
RUN_TRANSITIONS: dict[RepairStatus, frozenset[RepairStatus]] = {
    _R.PENDING: frozenset({_R.TESTING, _R.CANCELLED, _R.TIMEOUT}),
    _R.TESTING: frozenset({_R.DIAGNOSING, _R.SUCCEEDED}) | _END,
    _R.DIAGNOSING: frozenset({_R.PLANNING}) | _END,
    _R.PLANNING: frozenset({_R.REPAIRING}) | _END,
    _R.REPAIRING: frozenset({_R.RETESTING, _R.DIAGNOSING}) | _END,      # a repair that did not apply cleanly -> next attempt
    _R.RETESTING: frozenset({_R.REGRESSION, _R.DIAGNOSING}) | _END,
    _R.REGRESSION: frozenset({_R.SUCCEEDED, _R.DIAGNOSING}) | _END,
    **{s: frozenset() for s in RUN_TERMINAL},
}
ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    _A.PENDING: frozenset({_A.REPAIRING, _A.FAILED, _A.BLOCKED, _A.CANCELLED}),
    _A.REPAIRING: frozenset({_A.RETESTING, _A.FAILED, _A.BLOCKED, _A.CANCELLED}),
    _A.RETESTING: frozenset({_A.REGRESSION, _A.FAILED, _A.BLOCKED, _A.CANCELLED}),
    _A.REGRESSION: frozenset({_A.SUCCEEDED, _A.FAILED, _A.BLOCKED, _A.CANCELLED}),
    **{s: frozenset() for s in ATTEMPT_TERMINAL},
}


def check_run_transition(old: RepairStatus, new: RepairStatus) -> None:
    if new not in RUN_TRANSITIONS[old]:
        raise RepairStateError(f"illegal repair transition {old.value} -> {new.value}")


def check_attempt_transition(old: AttemptStatus, new: AttemptStatus) -> None:
    if new not in ATTEMPT_TRANSITIONS[old]:
        raise RepairStateError(f"illegal attempt transition {old.value} -> {new.value}")
