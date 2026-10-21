"""SQLite backend (standard library only). Local file, parameterised queries throughout.

* The file and schema are created on the first write; reads on a missing database return empty results.
* A corrupt or foreign database is reported as MemoryStoreError and never overwritten.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from jarvis.errors import MemoryNotFoundError, MemoryStoreError
from jarvis.memory import validation as v
from jarvis.memory.base import MemoryStore
from jarvis.memory.models import IMPORTANCE_DEFAULT, MemoryEntry, MemoryHit, MemoryType, new_id
from jarvis.memory.ranking import score, tokenize

SCHEMA_VERSION = 1
CANDIDATE_LIMIT = 500  # newest N matching rows are ranked in Python

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    search_text TEXT NOT NULL,
    type        TEXT NOT NULL,
    importance  INTEGER NOT NULL,
    source      TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_tags (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    tag       TEXT NOT NULL,
    PRIMARY KEY (memory_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_memories_type_created ON memories(type, created_at);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memory_tags_tag ON memory_tags(tag);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqliteMemoryStore(MemoryStore):
    def __init__(self, path: str | Path, *, clock: Callable[[], datetime] = _utcnow, timeout: float = 5.0) -> None:
        self._memory_db = str(path) == ":memory:"
        self._path = Path(":memory:") if self._memory_db else Path(path).expanduser()
        self._clock, self._timeout = clock, timeout
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    # -- connection management --------------------------------------------------------------
    def _connect(self, create: bool) -> sqlite3.Connection | None:
        """Return the connection, or None if the database does not exist and `create` is False."""
        if self._conn is not None:
            return self._conn
        if not self._memory_db and not self._path.exists():
            if not create:
                return None
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise MemoryStoreError(f"cannot create memory directory {self._path.parent}: {exc}") from exc
        elif self._memory_db and not create:
            return None
        try:
            conn = sqlite3.connect(str(self._path), timeout=self._timeout, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._init_schema(conn)
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"cannot open memory database {self._path}: {exc}") from exc
        self._conn = conn
        return conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise sqlite3.DatabaseError(f"database schema v{version} is newer than supported v{SCHEMA_VERSION}")
        if version < SCHEMA_VERSION:
            with conn:
                conn.executescript(_SCHEMA)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")  # constant, not user input

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    def __enter__(self) -> "SqliteMemoryStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _run(self, create: bool, fn):
        """Run fn(conn) under the lock; translate sqlite errors. fn is not called if there is no database."""
        with self._lock:
            conn = self._connect(create)
            if conn is None:
                return None
            try:
                return fn(conn)
            except sqlite3.Error as exc:
                raise MemoryStoreError(f"memory database error: {exc}") from exc

    # -- row mapping --------------------------------------------------------------------------
    @staticmethod
    def _entries(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[MemoryEntry]:
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        tags: dict[str, list[str]] = {i: [] for i in ids}
        marks = ",".join("?" * len(ids))
        for r in conn.execute(f"SELECT memory_id, tag FROM memory_tags WHERE memory_id IN ({marks}) "  # noqa: S608
                              "ORDER BY rowid", ids):
            tags[r["memory_id"]].append(r["tag"])
        out = []
        for r in rows:
            try:
                meta = json.loads(r["metadata"])
                out.append(MemoryEntry(
                    id=r["id"], content=r["content"], type=MemoryType(r["type"]), importance=r["importance"],
                    tags=tuple(tags[r["id"]]), source=r["source"], metadata=meta if isinstance(meta, dict) else {},
                    created_at=datetime.fromisoformat(r["created_at"]),
                    updated_at=datetime.fromisoformat(r["updated_at"])))
            except (ValueError, TypeError) as exc:
                raise sqlite3.DatabaseError(f"corrupt row {r['id']}: {exc}") from exc
        return out

    @staticmethod
    def _filters(type, tags, min_importance: int = 1) -> tuple[str, list[Any]]:
        clauses, params = ["importance >= ?"], [min_importance]
        if type is not None:
            clauses.append("type = ?")
            params.append(v.normalize_type(type).value)
        for tag in v.normalize_tags(tags):
            clauses.append("EXISTS (SELECT 1 FROM memory_tags t WHERE t.memory_id = memories.id AND t.tag = ?)")
            params.append(tag)
        return " AND ".join(clauses), params

    # -- MemoryStore ----------------------------------------------------------------------------
    def add(self, content, *, type=MemoryType.FACT, importance=IMPORTANCE_DEFAULT, tags=None, source=None,
            metadata: dict[str, Any] | None = None) -> MemoryEntry:
        now = self._clock()
        entry = MemoryEntry(
            id=new_id(), content=v.normalize_content(content), type=v.normalize_type(type),
            importance=v.normalize_importance(importance), tags=v.normalize_tags(tags),
            source=v.normalize_source(source), metadata=v.normalize_metadata(metadata),
            created_at=now, updated_at=now)

        def op(conn: sqlite3.Connection) -> MemoryEntry:
            with conn:
                self._insert(conn, entry)
            return entry

        return self._run(True, op)

    @staticmethod
    def _insert(conn: sqlite3.Connection, e: MemoryEntry) -> None:
        conn.execute(
            "INSERT INTO memories (id, content, search_text, type, importance, source, metadata, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e.id, e.content, e.content.casefold(), e.type.value, e.importance, e.source,
             json.dumps(e.metadata, ensure_ascii=False), e.created_at.isoformat(), e.updated_at.isoformat()))
        conn.executemany("INSERT INTO memory_tags (memory_id, tag) VALUES (?, ?)", [(e.id, t) for t in e.tags])

    def get(self, entry_id: str) -> MemoryEntry:
        def op(conn: sqlite3.Connection) -> MemoryEntry | None:
            rows = conn.execute("SELECT * FROM memories WHERE id = ?", (str(entry_id),)).fetchall()
            return self._entries(conn, rows)[0] if rows else None

        entry = self._run(False, op)
        if entry is None:
            raise MemoryNotFoundError(f"no memory with id {entry_id!r}")
        return entry

    def search(self, query, *, limit=5, type=None, tags=None, min_importance=1) -> list[MemoryHit]:
        terms = tokenize(v.normalize_query(query))
        limit = v.normalize_limit(limit)
        min_importance = v.normalize_importance(min_importance)
        where, params = self._filters(type, tags, min_importance)
        if not terms or limit == 0:
            return []
        match = " OR ".join(["search_text LIKE ? ESCAPE '\\'"] * len(terms)
                            + ["EXISTS (SELECT 1 FROM memory_tags t WHERE t.memory_id = memories.id "
                               "AND t.tag LIKE ? ESCAPE '\\')"] * len(terms))
        params = [*params, *[_like(t) for t in terms], *[_like(t) for t in terms]]

        def op(conn: sqlite3.Connection) -> list[MemoryHit]:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {where} AND ({match}) "  # noqa: S608 - only fixed fragments, values bound
                "ORDER BY created_at DESC, rowid DESC LIMIT ?", [*params, CANDIDATE_LIMIT]).fetchall()
            hits = [MemoryHit(e, s) for e in self._entries(conn, rows) if (s := score(e, terms)) > 0]
            hits.sort(key=lambda h: h.score, reverse=True)  # stable: ties stay newest-first
            return hits[:limit]

        return self._run(False, op) or []

    def update(self, entry_id, *, content=None, type=None, importance=None, tags=None, source=None,
               metadata=None) -> MemoryEntry:
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

        def op(conn: sqlite3.Connection) -> MemoryEntry | None:
            rows = conn.execute("SELECT * FROM memories WHERE id = ?", (str(entry_id),)).fetchall()
            if not rows:
                return None
            old = self._entries(conn, rows)[0]
            new = replace(old, **changes, updated_at=max(self._clock(), old.created_at))
            with conn:
                conn.execute(
                    "UPDATE memories SET content = ?, search_text = ?, type = ?, importance = ?, source = ?, "
                    "metadata = ?, updated_at = ? WHERE id = ?",
                    (new.content, new.content.casefold(), new.type.value, new.importance, new.source,
                     json.dumps(new.metadata, ensure_ascii=False), new.updated_at.isoformat(), new.id))
                if "tags" in changes:
                    conn.execute("DELETE FROM memory_tags WHERE memory_id = ?", (new.id,))
                    conn.executemany("INSERT INTO memory_tags (memory_id, tag) VALUES (?, ?)",
                                     [(new.id, t) for t in new.tags])
            return new

        entry = self._run(False, op)
        if entry is None:
            raise MemoryNotFoundError(f"no memory with id {entry_id!r}")
        return entry

    def delete(self, entry_id: str) -> bool:
        def op(conn: sqlite3.Connection) -> bool:
            with conn:
                return conn.execute("DELETE FROM memories WHERE id = ?", (str(entry_id),)).rowcount > 0

        return bool(self._run(False, op))

    def recent(self, limit=10, *, type=None, tags=None, offset=0) -> list[MemoryEntry]:
        limit, offset = v.normalize_limit(limit), v.normalize_limit(offset)
        where, params = self._filters(type, tags)

        def op(conn: sqlite3.Connection) -> list[MemoryEntry]:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {where} "  # noqa: S608
                "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            return self._entries(conn, rows)

        return self._run(False, op) or []

    def count(self, type=None) -> int:
        where, params = self._filters(type, None)

        def op(conn: sqlite3.Connection) -> int:
            return conn.execute(f"SELECT COUNT(*) FROM memories WHERE {where}", params).fetchone()[0]  # noqa: S608

        return self._run(False, op) or 0
