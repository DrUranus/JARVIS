"""SQLite journal for goals, agent tasks and their steps (standard library only). Local file, parameterised queries throughout.

* The file and schema are created on the first write; reads on a missing database return empty results.
* A corrupt or foreign database is reported as JournalError and never overwritten, moved or repaired.
* Every text is redacted (secrets -> [REDACTED]) and shortened before it is written; entries, steps per entry and evidence items are capped.
* Each step carries a `side_effect` flag (True = it may change something outside JARVIS). Storing and reading only.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jarvis.errors import JournalError
from jarvis.redaction import SecretDetector

KINDS = ("goal", "agent_task")
MAX_ENTRIES_HARD = 100_000
MAX_STEPS_HARD = 200
MAX_TEXT_HARD = 2000
MAX_EVIDENCE_HARD = 20
_ID = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
_STATUS = re.compile(r"[A-Z_]{1,32}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_entries (
    kind        TEXT NOT NULL,
    ref_id      TEXT NOT NULL,
    status      TEXT NOT NULL,
    text        TEXT NOT NULL,
    result      TEXT NOT NULL DEFAULT '',
    evidence    TEXT NOT NULL DEFAULT '[]',
    error       TEXT,
    created_at  TEXT,
    started_at  TEXT,
    finished_at TEXT,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
CREATE TABLE IF NOT EXISTS journal_steps (
    kind        TEXT NOT NULL,
    ref_id      TEXT NOT NULL,
    step_no     INTEGER NOT NULL,
    step_id     TEXT NOT NULL,
    status      TEXT NOT NULL,
    text        TEXT NOT NULL,
    side_effect INTEGER NOT NULL,
    result      TEXT NOT NULL DEFAULT '',
    evidence    TEXT NOT NULL DEFAULT '[]',
    error       TEXT,
    started_at  TEXT,
    finished_at TEXT,
    PRIMARY KEY (kind, ref_id, step_no)
);
CREATE INDEX IF NOT EXISTS idx_journal_recorded ON journal_entries(recorded_at);
"""
_TABLES = ("journal_entries", "journal_steps")


@dataclass(frozen=True)
class JournalStep:
    step_no: int
    step_id: str
    status: str
    text: str
    side_effect: bool
    result: str
    evidence: tuple[str, ...]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class JournalEntry:
    kind: str
    ref_id: str
    status: str
    text: str
    result: str
    evidence: tuple[str, ...]
    error: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    recorded_at: datetime
    steps: tuple[JournalStep, ...] = ()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _bounded(name: str, value: object, hard: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= hard:
        raise JournalError(f"{name} must be within 1..{hard}")
    return value


class JournalStore:
    def __init__(self, path: str | Path, *, max_entries: int = 500, max_steps_per_entry: int = 50, max_text_length: int = 300,
                 max_evidence: int = 5, detector: SecretDetector | None = None) -> None:
        self._max_entries = _bounded("max_entries", max_entries, MAX_ENTRIES_HARD)
        self._max_steps = _bounded("max_steps_per_entry", max_steps_per_entry, MAX_STEPS_HARD)
        self._max_text = _bounded("max_text_length", max_text_length, MAX_TEXT_HARD)
        self._max_evidence = _bounded("max_evidence", max_evidence, MAX_EVIDENCE_HARD)
        self._path = Path(path).expanduser()
        self._detector = detector or SecretDetector.from_environment()
        self._lock = threading.RLock()

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def max_text_length(self) -> int:
        return self._max_text

    def close(self) -> None:
        """Connections are short-lived (one per operation); nothing stays open."""

    def _text(self, value: object) -> str:
        return " ".join(self._detector.redact(value).split())[:self._max_text]

    def _evidence(self, items: object) -> str:
        seq = [items] if isinstance(items, str) else list(items or ())
        return json.dumps([self._text(i) for i in seq[:self._max_evidence]], ensure_ascii=False)

    def _check_ref(self, kind: str, ref_id: object) -> None:
        if kind not in KINDS:
            raise JournalError(f"unknown kind {kind!r}")
        if not isinstance(ref_id, str) or not _ID.fullmatch(ref_id) or self._detector.find(ref_id):
            raise JournalError("invalid id")

    def _open(self, make: bool) -> sqlite3.Connection | None:
        if not self._path.exists():
            if not make:
                return None
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise JournalError(f"cannot create journal directory {self._path.parent}: {exc}") from exc
        try:
            return sqlite3.connect(str(self._path), timeout=5.0, check_same_thread=False)
        except sqlite3.Error as exc:
            raise JournalError(f"cannot open journal database {self._path}: {exc}") from exc

    # -- writing ----------------------------------------------------------------------------------------
    def record(self, kind: str, ref_id: str, status: str, text: str = "", *, result: str = "", evidence: object = (), error: str | None = None,
               created_at: datetime | None = None, started_at: datetime | None = None, finished_at: datetime | None = None,
               steps: list[dict] | tuple[dict, ...] = ()) -> None:
        """Upsert one goal/task together with its steps (replacing the stored steps of that entry) in one transaction.
        A step dict has: step_id, status, text, side_effect (bool, required), and optionally result, evidence, error, started_at, finished_at.
        The step number is the position in `steps` (1-based); more than `max_steps_per_entry` steps are cut off."""
        self._check_ref(kind, ref_id)
        if not isinstance(status, str) or not _STATUS.fullmatch(status):
            raise JournalError("invalid status")
        step_rows = []
        for no, st in enumerate(list(steps)[:self._max_steps], 1):
            sid, sstat, side = st.get("step_id"), st.get("status"), st.get("side_effect")
            if not isinstance(sid, str) or not _ID.fullmatch(sid) or self._detector.find(sid):
                raise JournalError("invalid step id")
            if not isinstance(sstat, str) or not _STATUS.fullmatch(sstat):
                raise JournalError("invalid step status")
            if not isinstance(side, bool):
                raise JournalError("side_effect must be a bool for every step")
            step_rows.append((kind, ref_id, no, sid, sstat, self._text(st.get("text", "")), int(side), self._text(st.get("result", "")),
                              self._evidence(st.get("evidence", ())), self._text(st["error"]) if st.get("error") else None,
                              _iso(st.get("started_at")), _iso(st.get("finished_at"))))
        row = (kind, ref_id, status, self._text(text), self._text(result), self._evidence(evidence), self._text(error) if error else None,
               _iso(created_at), _iso(started_at), _iso(finished_at), datetime.now(timezone.utc).isoformat())
        with self._lock:
            conn = self._open(make=True)
            try:
                with conn:
                    conn.executescript(_SCHEMA)
                    conn.execute("INSERT INTO journal_entries (kind, ref_id, status, text, result, evidence, error, created_at, started_at,"
                                 " finished_at, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                                 " ON CONFLICT(kind, ref_id) DO UPDATE SET status=excluded.status, text=excluded.text, result=excluded.result,"
                                 " evidence=excluded.evidence, error=excluded.error, created_at=excluded.created_at,"
                                 " started_at=excluded.started_at, finished_at=excluded.finished_at, recorded_at=excluded.recorded_at", row)
                    conn.execute("DELETE FROM journal_steps WHERE kind = ? AND ref_id = ?", (kind, ref_id))
                    conn.executemany("INSERT INTO journal_steps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", step_rows)
                    conn.execute("DELETE FROM journal_entries WHERE rowid NOT IN"
                                 " (SELECT rowid FROM journal_entries ORDER BY recorded_at DESC, rowid DESC LIMIT ?)", (self._max_entries,))
                    conn.execute("DELETE FROM journal_steps WHERE NOT EXISTS (SELECT 1 FROM journal_entries e"
                                 " WHERE e.kind = journal_steps.kind AND e.ref_id = journal_steps.ref_id)")
            except sqlite3.Error as exc:
                raise JournalError(f"journal database error: {exc}") from exc
            finally:
                conn.close()

    # -- reading ----------------------------------------------------------------------------------------
    def _read(self, fn):
        with self._lock:
            conn = self._open(make=False)
            if conn is None:
                return None
            try:
                with closing(conn):
                    return fn(conn)
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc):
                    return None
                raise JournalError(f"journal database error: {exc}") from exc
            except sqlite3.Error as exc:
                raise JournalError(f"journal database error: {exc}") from exc

    @staticmethod
    def _steps(conn: sqlite3.Connection, kind: str, ref_id: str) -> tuple[JournalStep, ...]:
        rows = conn.execute("SELECT step_no, step_id, status, text, side_effect, result, evidence, error, started_at, finished_at"
                            " FROM journal_steps WHERE kind = ? AND ref_id = ? ORDER BY step_no", (kind, ref_id)).fetchall()
        return tuple(JournalStep(r[0], r[1], r[2], r[3], bool(r[4]), r[5], tuple(json.loads(r[6])), r[7], _parse(r[8]), _parse(r[9])) for r in rows)

    @staticmethod
    def _entry(conn: sqlite3.Connection, r: tuple) -> JournalEntry:
        return JournalEntry(r[0], r[1], r[2], r[3], r[4], tuple(json.loads(r[5])), r[6], _parse(r[7]), _parse(r[8]), _parse(r[9]), _parse(r[10]),
                            JournalStore._steps(conn, r[0], r[1]))

    _COLS = "kind, ref_id, status, text, result, evidence, error, created_at, started_at, finished_at, recorded_at"

    def list(self, limit: int = 20, kind: str | None = None) -> list[JournalEntry]:
        """Newest first, each with its steps. A missing database (or one without the tables) is an empty journal."""
        limit = max(1, min(int(limit), self._max_entries))

        def query(conn):
            sql, args = f"SELECT {self._COLS} FROM journal_entries", ()
            if kind is not None:
                sql, args = sql + " WHERE kind = ?", (kind,)
            return [self._entry(conn, r) for r in conn.execute(sql + " ORDER BY recorded_at DESC, rowid DESC LIMIT ?", args + (limit,)).fetchall()]
        return self._read(query) or []

    def get(self, kind: str, ref_id: str) -> JournalEntry | None:
        def query(conn):
            r = conn.execute(f"SELECT {self._COLS} FROM journal_entries WHERE kind = ? AND ref_id = ?", (kind, ref_id)).fetchone()
            return self._entry(conn, r) if r else None
        return self._read(query)

    def count(self) -> int:
        return self._read(lambda c: int(c.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0])) or 0
