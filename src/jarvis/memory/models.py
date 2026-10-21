"""Memory data model, independent of any storage backend."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    PREFERENCE = "preference"    # user preferences
    FACT = "fact"                # user-provided facts
    PROJECT = "project"
    GOAL = "goal"
    DECISION = "decision"
    TASK_RESULT = "task_result"  # outcome of earlier tasks
    CONVERSATION = "conversation"  # explicitly kept conversation context
    SYSTEM = "system"            # system/configuration information
    RESOURCE = "resource"        # reference to a file, URL or other resource


IMPORTANCE_MIN, IMPORTANCE_MAX, IMPORTANCE_DEFAULT = 1, 10, 5  # 10 = most important


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    content: str
    type: MemoryType
    importance: int
    created_at: datetime
    updated_at: datetime
    tags: tuple[str, ...] = ()
    source: str | None = None      # who/what created it: "user", "task:ab12cd34", "agent:research", ...
    metadata: dict[str, Any] = field(default_factory=dict)  # free-form, JSON-serialisable (e.g. {"path": "..."})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "content": self.content, "type": self.type.value, "importance": self.importance,
            "tags": list(self.tags), "source": self.source, "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class MemoryHit:
    """A search result. `score` is backend-specific but comparable within one result list,
    so semantic/vector backends can slot in later without changing callers."""
    entry: MemoryEntry
    score: float
