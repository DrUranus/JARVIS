"""AgentResult (what the orchestrator stores and hands to other agents) and AgentOutcome (what an agent returns)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from jarvis.agents.errors import InvalidTaskError
from jarvis.agents.models import check_json
from jarvis.agents.state import TERMINAL, TaskStatus


@dataclass(frozen=True)
class AgentOutcome:
    """The structured answer of an agent. Exceptions are not an interface: an agent reports failure here."""
    status: TaskStatus
    summary: str = ""
    output: Any = None
    error: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, TaskStatus) or self.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            raise InvalidTaskError("an outcome must be SUCCEEDED, FAILED, CANCELLED or BLOCKED")
        if not isinstance(self.summary, str):
            raise InvalidTaskError("summary must be text")
        check_json(self.output, "output")

    @classmethod
    def ok(cls, summary: str = "", output: Any = None) -> "AgentOutcome":
        return cls(TaskStatus.SUCCEEDED, summary, output)

    @classmethod
    def failed(cls, error: str, *, code: str = "failed", summary: str = "", output: Any = None) -> "AgentOutcome":
        return cls(TaskStatus.FAILED, summary or error, output, error, code)

    @classmethod
    def blocked(cls, error: str, *, code: str = "blocked", output: Any = None) -> "AgentOutcome":
        return cls(TaskStatus.BLOCKED, error, output, error, code)

    @classmethod
    def cancelled(cls, summary: str = "cancelled") -> "AgentOutcome":
        return cls(TaskStatus.CANCELLED, summary, None, None, "cancelled")


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    agent_id: str | None
    status: TaskStatus
    summary: str = field(default="", repr=False)   # free text may contain anything: never in a repr
    output: Any = field(default=None, repr=False)
    error: str | None = field(default=None, repr=False)
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def succeeded(self) -> bool:
        return self.status is TaskStatus.SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "agent_id": self.agent_id, "status": self.status.value, "summary": self.summary,
                "output": self.output, "error": self.error, "error_code": self.error_code,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "finished_at": self.finished_at.isoformat() if self.finished_at else None}
