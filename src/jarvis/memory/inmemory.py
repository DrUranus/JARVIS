"""Non-persistent backend: proves the interface is backend-neutral and keeps tests fast."""
from __future__ import annotations

import itertools
import threading
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from jarvis.errors import MemoryNotFoundError
from jarvis.memory import validation as v
from jarvis.memory.base import MemoryStore
from jarvis.memory.models import IMPORTANCE_DEFAULT, MemoryEntry, MemoryHit, MemoryType, new_id
from jarvis.memory.ranking import score, tokenize


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryStore(MemoryStore):
    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock
        self._items: dict[str, tuple[int, MemoryEntry]] = {}
        self._seq = itertools.count()
        self._lock = threading.RLock()

    def add(self, content, *, type=MemoryType.FACT, importance=IMPORTANCE_DEFAULT, tags=None, source=None,
            metadata: dict[str, Any] | None = None) -> MemoryEntry:
        now = self._clock()
        entry = MemoryEntry(
            id=new_id(), content=v.normalize_content(content), type=v.normalize_type(type),
            importance=v.normalize_importance(importance), tags=v.normalize_tags(tags),
            source=v.normalize_source(source), metadata=v.normalize_metadata(metadata),
            created_at=now, updated_at=now)
        with self._lock:
            self._items[entry.id] = (next(self._seq), entry)
        return entry

    def get(self, entry_id: str) -> MemoryEntry:
        with self._lock:
            try:
                return self._items[entry_id][1]
            except KeyError:
                raise MemoryNotFoundError(f"no memory with id {entry_id!r}") from None

    def _newest_first(self, type, tags) -> list[MemoryEntry]:
        t = v.normalize_type(type) if type is not None else None
        wanted = v.normalize_tags(tags)
        with self._lock:
            rows = sorted(self._items.values(), key=lambda r: (r[1].created_at, r[0]), reverse=True)
        return [e for _, e in rows
                if (t is None or e.type is t) and all(w in e.tags for w in wanted)]

    def search(self, query, *, limit=5, type=None, tags=None, min_importance=1) -> list[MemoryHit]:
        terms = tokenize(v.normalize_query(query))
        limit = v.normalize_limit(limit)
        min_importance = v.normalize_importance(min_importance)
        candidates = self._newest_first(type, tags)  # validates type/tags even for empty queries
        if not terms or limit == 0:
            return []
        hits = [MemoryHit(e, s) for e in candidates
                if e.importance >= min_importance and (s := score(e, terms)) > 0]
        hits.sort(key=lambda h: h.score, reverse=True)  # stable: ties stay newest-first
        return hits[:limit]

    def update(self, entry_id, *, content=None, type=None, importance=None, tags=None, source=None,
               metadata=None) -> MemoryEntry:
        with self._lock:
            seq, old = self._items.get(entry_id) or (None, None)
            if old is None:
                raise MemoryNotFoundError(f"no memory with id {entry_id!r}")
            changes: dict[str, Any] = {}
            if content is not None:
                changes["content"] = v.normalize_content(content)
            if type is not None:
                changes["type"] = v.normalize_type(type)
            if importance is not None:
                changes["importance"] = v.normalize_importance(importance)
            if tags is not None:
                changes["tags"] = v.normalize_tags(tags)
            if source is not None:
                changes["source"] = v.normalize_source(source)
            if metadata is not None:
                changes["metadata"] = v.normalize_metadata(metadata)
            new = replace(old, **changes, updated_at=max(self._clock(), old.created_at))
            self._items[entry_id] = (seq, new)
            return new

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            return self._items.pop(entry_id, None) is not None

    def recent(self, limit=10, *, type=None, tags=None, offset=0) -> list[MemoryEntry]:
        limit, offset = v.normalize_limit(limit), v.normalize_limit(offset)
        return self._newest_first(type, tags)[offset: offset + limit]

    def count(self, type=None) -> int:
        return len(self._newest_first(type, None))
