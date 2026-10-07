"""Lifecycles. Agent: AVAILABLE/BUSY/DISABLED/FAILED. Task: PENDING -> RUNNING -> terminal. Illegal transitions raise StateError."""
from __future__ import annotations

import threading
from enum import Enum

from jarvis.agents.errors import StateError


class AgentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    DISABLED = "DISABLED"
    FAILED = "FAILED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


TERMINAL = frozenset({TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED})

_A, _T = AgentStatus, TaskStatus
AGENT_TRANSITIONS: dict[AgentStatus, frozenset[AgentStatus]] = {
    _A.AVAILABLE: frozenset({_A.BUSY, _A.DISABLED}),
    _A.BUSY: frozenset({_A.AVAILABLE, _A.FAILED, _A.DISABLED}),   # DISABLED while busy: the running task finishes, nothing new starts
    _A.FAILED: frozenset({_A.AVAILABLE, _A.DISABLED}),            # recovery is explicit (reset) or after the stuck work returned
    _A.DISABLED: frozenset({_A.AVAILABLE}),
}
TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    _T.PENDING: frozenset({_T.RUNNING, _T.CANCELLED, _T.BLOCKED, _T.FAILED}),
    _T.RUNNING: frozenset({_T.SUCCEEDED, _T.FAILED, _T.CANCELLED, _T.BLOCKED}),
    _T.SUCCEEDED: frozenset(), _T.FAILED: frozenset(), _T.CANCELLED: frozenset(), _T.BLOCKED: frozenset(),
}


def check_agent_transition(old: AgentStatus, new: AgentStatus) -> None:
    if new not in AGENT_TRANSITIONS[old]:
        raise StateError(f"illegal agent transition {old.value} -> {new.value}")


def check_task_transition(old: TaskStatus, new: TaskStatus) -> None:
    if new not in TASK_TRANSITIONS[old]:
        raise StateError(f"illegal task transition {old.value} -> {new.value}")


class AgentState:
    """Thread-safe agent status with validated transitions. Owned by the Agent object, changed only by the orchestrator/registry."""

    def __init__(self, initial: AgentStatus = AgentStatus.AVAILABLE) -> None:
        self._status = initial
        self._reason = ""
        self._lock = threading.Lock()

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def reason(self) -> str:
        return self._reason

    def transition(self, new: AgentStatus, reason: str = "") -> AgentStatus:
        with self._lock:
            check_agent_transition(self._status, new)
            self._status = new
            self._reason = reason[:200]
            return new

    def try_transition(self, new: AgentStatus, reason: str = "") -> bool:
        try:
            self.transition(new, reason)
            return True
        except StateError:
            return False

    def claim(self) -> bool:
        """AVAILABLE -> BUSY atomically; False if the agent cannot take a task (busy, disabled, failed)."""
        with self._lock:
            if self._status is not AgentStatus.AVAILABLE:
                return False
            self._status = AgentStatus.BUSY
            self._reason = ""
            return True
