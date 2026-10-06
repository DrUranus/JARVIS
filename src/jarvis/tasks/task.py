"""Task model: a unit of work with status, subtasks, result and error."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from jarvis.errors import TaskError


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})

_S = TaskStatus
_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    _S.PENDING: frozenset({_S.PLANNING, _S.RUNNING, _S.CANCELLED, _S.FAILED}),
    _S.PLANNING: frozenset({_S.PENDING, _S.RUNNING, _S.WAITING, _S.FAILED, _S.CANCELLED}),
    _S.RUNNING: frozenset({_S.WAITING, _S.COMPLETED, _S.FAILED, _S.CANCELLED, _S.PLANNING}),
    _S.WAITING: frozenset({_S.RUNNING, _S.PLANNING, _S.FAILED, _S.CANCELLED}),
    _S.COMPLETED: frozenset(),
    _S.FAILED: frozenset({_S.PENDING}),  # retry
    _S.CANCELLED: frozenset(),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Task:
    description: str
    priority: int = 5  # 1 (highest) .. 10 (lowest)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    subtasks: list["Task"] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    required_tools: list[str] = field(default_factory=list)
    required_agents: list[str] = field(default_factory=list)
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise TaskError("task description must not be empty")
        if not 1 <= self.priority <= 10:
            raise TaskError("priority must be within 1..10")

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    def transition(self, new: TaskStatus) -> None:
        if new is self.status:
            return
        if new not in _TRANSITIONS[self.status]:
            raise TaskError(f"illegal transition {self.status.value} -> {new.value} (task {self.id})")
        self.status = new
        self.updated_at = _now()

    def complete(self, result: Any = None) -> None:
        self.transition(TaskStatus.COMPLETED)
        self.result = result

    def fail(self, error: str) -> None:
        self.transition(TaskStatus.FAILED)
        self.error = error

    def add_subtask(self, description: str, **kwargs: Any) -> "Task":
        sub = Task(description=description, parent_id=self.id, **kwargs)
        self.subtasks.append(sub)
        return sub

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "description": self.description, "status": self.status.value,
            "priority": self.priority, "created_at": self.created_at.isoformat(),
            "result": self.result, "error": self.error,
            "required_tools": list(self.required_tools), "required_agents": list(self.required_agents),
            "subtasks": [s.to_dict() for s in self.subtasks],
        }
