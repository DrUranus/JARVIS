"""SQLite store for finished work (standard library only). Local file, parameterised queries throughout.

* The file and schema are created on the first write; reads on a missing database return empty results.
* A corrupt or foreign database is reported as HistoryError and never overwritten.
* Every text is redacted (secrets -> [REDACTED]) and shortened before it is written; the number of rows is capped (oldest dropped first).
"""
from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jarvis.errors import HistoryError
from jarvis.redaction import SecretDetector

KINDS = ("goal", "agent_task", "repair", "task")
MAX_ENTRIES_HARD = 100_000
MAX_TEXT_HARD = 2000
_ID = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
_STATUS = re.compile(r"[A-Z_]{1,32}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    kind        TEXT NOT NULL,
    ref_id      TEXT NOT NULL,
    status      TEXT NOT NULL,
    summary     TEXT NOT NULL,
    error       TEXT,
    created_at  TEXT,
    started_at  TEXT,
    finished_at TEXT,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_history_recorded ON history(recorded_at);
"""


@dataclass(frozen=True)
class HistoryEntry:
    kind: str
    ref_id: str
    status: str
    summary: str
    error: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    recorded_at: datetime


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


class HistoryStore:
    def __init__(self, path: str | Path, *, max_entries: int = 500, max_text_length: int = 300, detector: SecretDetector | None = None) -> None:
        if not isinstance(max_entries, int) or isinstance(max_entries, bool) or not 1 <= max_entries <= MAX_ENTRIES_HARD:
            raise HistoryError(f"max_entries must be within 1..{MAX_ENTRIES_HARD}")
        if not isinstance(max_text_length, int) or isinstance(max_text_length, bool) or not 1 <= max_text_length <= MAX_TEXT_HARD:
            raise HistoryError(f"max_text_length must be within 1..{MAX_TEXT_HARD}")
        self._path = Path(path).expanduser()
        self._max_entries, self._max_text = max_entries, max_text_length
        self._detector = detector or SecretDetector.from_environment()
        self._lock = threading.RLock()

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def close(self) -> None:
        """Connections are short-lived (one per operation); nothing stays open."""

    def _text(self, value: object) -> str:
        return " ".join(self._detector.redact(value).split())[:self._max_text]

    def _open(self, make: bool) -> sqlite3.Connection | None:
        if not self._path.exists():
            if not make:
                return None
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise HistoryError(f"cannot create history directory {self._path.parent}: {exc}") from exc
        try:
            return sqlite3.connect(str(self._path), timeout=5.0, check_same_thread=False)
        except sqlite3.Error as exc:
            raise HistoryError(f"cannot open history database {self._path}: {exc}") from exc

    def add(self, kind: str, ref_id: str, status: str, summary: str = "", error: str | None = None, *, created_at: datetime | None = None,
            started_at: datetime | None = None, finished_at: datetime | None = None) -> None:
        self.add_many([(kind, ref_id, status, summary, error, created_at, started_at, finished_at)])

    def add_many(self, items: list[tuple]) -> None:
        """Upsert finished items in one transaction; an item whose stored content is identical is left untouched (keeps its position)."""
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for kind, ref_id, status, summary, error, created, started, finished in items:
            if kind not in KINDS:
                raise HistoryError(f"unknown kind {kind!r}")
            if not isinstance(ref_id, str) or not _ID.fullmatch(ref_id) or self._detector.find(ref_id):
                raise HistoryError("invalid id")
            if not isinstance(status, str) or not _STATUS.fullmatch(status):
                raise HistoryError("invalid status")
            rows.append((kind, ref_id, status, self._text(summary), self._text(error) if error else None,
                         _iso(created), _iso(started), _iso(finished), now))
        if not rows:
            return
        with self._lock:
            conn = self._open(make=True)
            try:
                with conn:
                    conn.executescript(_SCHEMA)
                    conn.executemany(
                        "INSERT INTO history (kind, ref_id, status, summary, error, created_at, started_at, finished_at, recorded_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?)"
                        " ON CONFLICT(kind, ref_id) DO UPDATE SET status=excluded.status, summary=excluded.summary, error=excluded.error,"
                        " created_at=excluded.created_at, started_at=excluded.started_at, finished_at=excluded.finished_at,"
                        " recorded_at=excluded.recorded_at"
                        " WHERE status IS NOT excluded.status OR summary IS NOT excluded.summary OR error IS NOT excluded.error", rows)
                    conn.execute("DELETE FROM history WHERE rowid NOT IN (SELECT rowid FROM history ORDER BY recorded_at DESC, rowid DESC LIMIT ?)",
                                 (self._max_entries,))
            except sqlite3.Error as exc:
                raise HistoryError(f"history database error: {exc}") from exc
            finally:
                conn.close()

    def list(self, limit: int = 20, kind: str | None = None) -> list[HistoryEntry]:
        """Newest first. A missing database (or one without the table) is an empty history."""
        limit = max(1, min(int(limit), self._max_entries))
        with self._lock:
            conn = self._open(make=False)
            if conn is None:
                return []
            try:
                with closing(conn):
                    sql = "SELECT kind, ref_id, status, summary, error, created_at, started_at, finished_at, recorded_at FROM history"
                    args: tuple = ()
                    if kind is not None:
                        sql, args = sql + " WHERE kind = ?", (kind,)
                    rows = conn.execute(sql + " ORDER BY recorded_at DESC, rowid DESC LIMIT ?", args + (limit,)).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc):
                    return []
                raise HistoryError(f"history database error: {exc}") from exc
            except sqlite3.Error as exc:
                raise HistoryError(f"history database error: {exc}") from exc
        return [HistoryEntry(r[0], r[1], r[2], r[3], r[4], _parse(r[5]), _parse(r[6]), _parse(r[7]), _parse(r[8])) for r in rows]

    def count(self) -> int:
        with self._lock:
            conn = self._open(make=False)
            if conn is None:
                return 0
            try:
                with closing(conn):
                    return int(conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc):
                    return 0
                raise HistoryError(f"history database error: {exc}") from exc
            except sqlite3.Error as exc:
                raise HistoryError(f"history database error: {exc}") from exc
