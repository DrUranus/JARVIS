"""Policy layer around any MemoryStore: secret filtering and configured limits.

It implements MemoryStore itself, so callers cannot tell it from a raw backend.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from jarvis.errors import MemoryLimitError
from jarvis.memory import validation as v
from jarvis.memory.base import MemoryStore
from jarvis.memory.guard import SecretGuard
from jarvis.memory.models import IMPORTANCE_DEFAULT, MemoryEntry, MemoryHit, MemoryType


class GuardedMemoryStore(MemoryStore):
    def __init__(self, inner: MemoryStore, guard: SecretGuard | None = None, *,
                 max_content_length: int = v.MAX_CONTENT_LENGTH, max_entries: int = 0) -> None:
        self._inner = inner
        self._guard = guard or SecretGuard()
        self._max_len, self._max_entries = max_content_length, max_entries

    @property
    def enabled(self) -> bool:
        return self._inner.enabled

    @property
    def inner(self) -> MemoryStore:
        return self._inner

    def _screen(self, content, tags, source, metadata) -> None:
        if content is not None:
            v.normalize_content(content, self._max_len)  # configured length limit
        self._guard.check(content if isinstance(content, str) else None, source if isinstance(source, str) else None)
        if tags is not None and not isinstance(tags, (str, bytes)):
            self._guard.check(*[t for t in tags if isinstance(t, str)])
        if metadata is not None:
            try:
                self._guard.check(json.dumps(metadata, ensure_ascii=False, default=str))
            except (TypeError, ValueError):
                pass  # the backend's validation reports unserialisable metadata

    def add(self, content: str, *, type: MemoryType | str = MemoryType.FACT, importance: int = IMPORTANCE_DEFAULT,
            tags: Iterable[str] | None = None, source: str | None = None,
            metadata: dict[str, Any] | None = None) -> MemoryEntry:
        tags = list(tags) if tags is not None and not isinstance(tags, (str, bytes)) and hasattr(tags, "__iter__") else tags
        self._screen(content, tags, source, metadata)
        if self._max_entries and self._inner.count() >= self._max_entries:
            raise MemoryLimitError(f"memory is full ({self._max_entries} entries); delete some first")
        return self._inner.add(content, type=type, importance=importance, tags=tags, source=source,
                               metadata=metadata)

    def get(self, entry_id: str) -> MemoryEntry:
        return self._inner.get(entry_id)

    def search(self, query: str, **kwargs: Any) -> list[MemoryHit]:
        return self._inner.search(query, **kwargs)

    def update(self, entry_id: str, *, content=None, type=None, importance=None, tags=None, source=None,
               metadata=None) -> MemoryEntry:
        tags = list(tags) if tags is not None and not isinstance(tags, (str, bytes)) and hasattr(tags, "__iter__") else tags
        self._screen(content, tags, source, metadata)
        return self._inner.update(entry_id, content=content, type=type, importance=importance, tags=tags,
                                  source=source, metadata=metadata)

    def delete(self, entry_id: str) -> bool:
        return self._inner.delete(entry_id)

    def recent(self, limit: int = 10, **kwargs: Any) -> list[MemoryEntry]:
        return self._inner.recent(limit, **kwargs)

    def count(self, type=None) -> int:
        return self._inner.count(type)

    def close(self) -> None:
        self._inner.close()
