"""Memory that is switched off: reads are empty, writes raise a clear error."""
from __future__ import annotations

from jarvis.errors import MemoryDisabledError
from jarvis.memory.base import MemoryStore


class NullMemoryStore(MemoryStore):
    @property
    def enabled(self) -> bool:
        return False

    def _off(self, *a, **k):
        raise MemoryDisabledError("memory is disabled (memory.enabled = false)")

    add = get = update = _off

    def search(self, query, **kwargs):
        return []

    def delete(self, entry_id):
        return False

    def recent(self, limit=10, **kwargs):
        return []

    def count(self, type=None):
        return 0
