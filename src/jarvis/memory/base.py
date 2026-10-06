"""The memory abstraction. Core, agents and tools depend on this, never on a concrete backend."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from jarvis.memory.models import IMPORTANCE_DEFAULT, MemoryEntry, MemoryHit, MemoryType


class MemoryStore(ABC):
    """Contract for every memory backend (SQLite today; vector/semantic, remote... later).

    All methods raise subclasses of MemoryStoreError on failure and never leak backend exceptions.
    """

    @property
    def enabled(self) -> bool:
        return True

    @abstractmethod
    def add(self, content: str, *, type: MemoryType | str = MemoryType.FACT, importance: int = IMPORTANCE_DEFAULT,
            tags: Iterable[str] | None = None, source: str | None = None,
            metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a new memory and return it (with generated id and timestamps)."""

    @abstractmethod
    def get(self, entry_id: str) -> MemoryEntry:
        """Return one entry. Raises MemoryNotFoundError."""

    @abstractmethod
    def search(self, query: str, *, limit: int = 5, type: MemoryType | str | None = None,
               tags: Iterable[str] | None = None, min_importance: int = 1) -> list[MemoryHit]:
        """Relevance-ranked entries matching the query (best first). Empty/stopword-only query -> []."""

    @abstractmethod
    def update(self, entry_id: str, *, content: str | None = None, type: MemoryType | str | None = None,
               importance: int | None = None, tags: Iterable[str] | None = None, source: str | None = None,
               metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Change the given fields (None = keep) and bump updated_at. Raises MemoryNotFoundError."""

    @abstractmethod
    def delete(self, entry_id: str) -> bool:
        """Delete an entry. True if it existed, False otherwise (idempotent)."""

    @abstractmethod
    def recent(self, limit: int = 10, *, type: MemoryType | str | None = None,
               tags: Iterable[str] | None = None, offset: int = 0) -> list[MemoryEntry]:
        """Entries ordered by creation time, newest first (also serves as paginated listing)."""

    @abstractmethod
    def count(self, type: MemoryType | str | None = None) -> int: ...

    def close(self) -> None:
        """Release resources. Safe to call repeatedly."""
