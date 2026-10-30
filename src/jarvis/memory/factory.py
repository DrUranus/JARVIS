"""Backend registry (same pattern as llm/voice). The only module that knows concrete backends."""
from __future__ import annotations

from typing import Callable

from jarvis.config import MemorySettings
from jarvis.errors import MemoryStoreError
from jarvis.memory.base import MemoryStore
from jarvis.memory.guard import SecretGuard
from jarvis.memory.guarded import GuardedMemoryStore
from jarvis.memory.inmemory import InMemoryStore
from jarvis.memory.null import NullMemoryStore
from jarvis.memory.semantic import SemanticInMemoryStore, SemanticSqliteStore
from jarvis.memory.sqlite_store import SqliteMemoryStore

BackendFactory = Callable[[MemorySettings], MemoryStore]
_BACKENDS: dict[str, BackendFactory] = {}


def register_backend(name: str, factory: BackendFactory) -> None:
    _BACKENDS[name.lower()] = factory


def available_backends() -> list[str]:
    return sorted(_BACKENDS)


register_backend("sqlite", lambda s: SqliteMemoryStore(s.path))
register_backend("memory", lambda s: InMemoryStore())
register_backend("semantic", lambda s: SemanticSqliteStore(s.path))  # SQLite + lokale TF-IDF-Suche (netzfrei)
register_backend("semantic-memory", lambda s: SemanticInMemoryStore())


def create_memory(settings: MemorySettings, guard: SecretGuard | None = None) -> MemoryStore:
    """Build the configured store, wrapped with secret filtering and limits.
    Returns a NullMemoryStore when memory is disabled."""
    if not settings.enabled:
        return NullMemoryStore()
    try:
        factory = _BACKENDS[settings.backend.lower()]
    except KeyError:
        raise MemoryStoreError(f"unknown memory backend {settings.backend!r}; available: {available_backends()}") from None
    return GuardedMemoryStore(factory(settings), guard or SecretGuard.from_environment(),
                              max_content_length=settings.max_content_length, max_entries=settings.max_entries)
