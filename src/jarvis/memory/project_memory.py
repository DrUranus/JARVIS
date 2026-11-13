"""V2.1 (Mission 3): project memory - pure, in-memory, not wired. Five kinds per project:

  working    short-term notes of a running task (removed with `end_task`, stale after a day)
  confirmed  long-term information somebody explicitly confirmed
  decision   goals and decisions of the project (never go stale by themselves)
  issue      known problems; repeated reports are counted, not duplicated
  knowledge  findings with their sources and time stamps (stale after 180 days)

Rules: projects are strictly separated (a record id is only valid inside its project). Secrets and credentials are refused through the shared SecretDetector; e-mail addresses,
phone numbers and IBANs are refused as unnecessary personal data. Equal statements are merged (sources collected). Contradicting statements for the same key are REPORTED with both
sides and a preference (confirmed > source quality > newer) but never resolved silently. Nothing is deleted when it gets old: it is marked stale. A correction keeps the old record
(superseded, with who and why); a wrong record can be retracted. "Learning" is limited to `suggestions`: recurring issues and confirmed records - never unconfirmed notes, and this
module changes no model weights, no configuration and no program. Persistence is a plain snapshot (`to_dict` / `from_dict`, re-validated on load); the caller decides where it lives."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Mapping

from jarvis.errors import MemoryNotFoundError, MemoryValidationError, SecretRejectedError
from jarvis.redaction import SecretDetector

KINDS = ("working", "confirmed", "decision", "issue", "knowledge")
MAX_AGE = {"working": timedelta(days=1), "knowledge": timedelta(days=180), "confirmed": timedelta(days=365), "issue": timedelta(days=365), "decision": None}
MAX_KEY, MAX_VALUE, MAX_SOURCE, MAX_SOURCES, DEFAULT_MAX_RECORDS = 120, 4000, 500, 10, 2000
VERSION = 1
_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")
_RESERVED = frozenset({"confirmed", "confirm", "force", "bypass", "skip_permissions", "unsafe", "grant", "approval"})
_PERSONAL = (("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")), ("phone", re.compile(r"(?:\+\d{1,3}[\s\-]?\d{2,5}[\s\-/]?\d{5,}|\b0\d{2,5}[\s\-/]\d{5,}\b)")),
             ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")))
_TOKEN = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=\-]{20,}")      # authorization header values; stricter than the shared detector, which is left unchanged
_FIELDS = ("id", "project", "kind", "key", "value", "sources", "quality", "created_at", "updated_at", "status", "confirmed", "supersedes", "seen", "task", "by", "reason")


@dataclass(frozen=True)
class Record:
    id: str
    project: str
    kind: str
    key: str
    value: str
    sources: tuple[str, ...]
    quality: int | None
    created_at: datetime
    updated_at: datetime
    status: str = "active"            # active | stale | superseded | retracted
    confirmed: bool = False
    supersedes: str | None = None
    seen: int = 1
    task: str | None = None
    by: str = ""
    reason: str = ""
    conflict: bool = False            # set on recall: another active record of the same key says something else

    def to_dict(self) -> dict[str, Any]:
        d = {f: getattr(self, f) for f in _FIELDS}
        d.update(sources=list(self.sources), created_at=self.created_at.isoformat(), updated_at=self.updated_at.isoformat())
        return d


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


class ProjectMemory:
    def __init__(self, *, detector: SecretDetector | None = None, max_records: int = DEFAULT_MAX_RECORDS) -> None:
        self._detector = detector or SecretDetector()
        self._max = max_records
        self._projects: dict[str, list[Record]] = {}

    # ---- validation ---------------------------------------------------------------------------------------------------------------------------
    def _text(self, value: Any, what: str, limit: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise MemoryValidationError(f"{what} must be 1..{limit} characters of plain text")
        kind = self._detector.find(value)
        if kind or _TOKEN.search(value):
            raise SecretRejectedError(f"refusing to store {what} that looks like a secret ({kind or 'authorization token'})")
        for name, pattern in _PERSONAL:
            if pattern.search(value):
                raise MemoryValidationError(f"refusing to store {what} with personal data ({name}); keep a neutral description instead")
        return value.strip()

    def _check(self, project: Any, kind: Any, key: Any, value: Any, source: Any, quality: Any) -> tuple[str, str, str]:
        if not isinstance(project, str) or not _PROJECT.match(project):
            raise MemoryValidationError("project must be a short lower-case identifier")
        if kind not in KINDS:
            raise MemoryValidationError(f"kind must be one of {KINDS}")
        key = self._text(key, "key", MAX_KEY)
        if key.lower() in _RESERVED:
            raise MemoryValidationError("this key is reserved")
        if quality is not None and (isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 5):
            raise MemoryValidationError("quality is a whole number 1..5 or None")
        return key, self._text(value, "value", MAX_VALUE), self._text(source, "source", MAX_SOURCE)

    def _find(self, project: str, record_id: str) -> tuple[list[Record], int]:
        rows = self._projects.get(project, [])
        for i, r in enumerate(rows):
            if r.id == record_id:
                return rows, i
        raise MemoryNotFoundError("no such record in this project")

    # ---- writing ------------------------------------------------------------------------------------------------------------------------------
    def add(self, project: str, kind: str, key: str, value: str, *, source: str, now: datetime, quality: int | None = None, task: str | None = None) -> Record:
        key, value, source = self._check(project, kind, key, value, source, quality)
        rows = self._projects.setdefault(project, [])
        for i, r in enumerate(rows):
            if r.status == "active" and (r.kind, r.key) == (kind, key) and _norm(r.value) == _norm(value):       # the same statement again: merge, do not duplicate
                rows[i] = replace(r, sources=tuple(dict.fromkeys(r.sources + (source,)))[:MAX_SOURCES], seen=r.seen + 1, updated_at=now,
                                  quality=r.quality if quality is None else max(quality, r.quality or 0))
                return rows[i]
        if len(rows) >= self._max:
            raise MemoryValidationError(f"this project already holds {self._max} records")
        rec = Record(uuid.uuid4().hex[:12], project, kind, key, value, (source,), quality, now, now, task=task, by=source)
        rows.append(rec)
        return rec

    def confirm(self, project: str, record_id: str, *, by: str, now: datetime) -> Record:
        """Somebody explicitly confirmed the record. A working note becomes long-term (`confirmed`); nothing is confirmed implicitly."""
        rows, i = self._find(project, record_id)
        r = rows[i]
        rows[i] = replace(r, confirmed=True, kind="confirmed" if r.kind == "working" else r.kind, task=None, updated_at=now, by=self._text(by, "by", 100))
        return rows[i]

    def correct(self, project: str, record_id: str, value: str, *, by: str, reason: str, now: datetime) -> Record:
        rows, i = self._find(project, record_id)
        old = rows[i]
        value, by = self._text(value, "value", MAX_VALUE), self._text(by, "by", 100)
        reason = self._text(reason, "reason", 300) if reason else ""
        rows[i] = replace(old, status="superseded")
        new = Record(uuid.uuid4().hex[:12], project, old.kind, old.key, value, (by,), None, now, now, confirmed=True, supersedes=old.id, by=by, reason=reason)
        rows.append(new)
        return new

    def retract(self, project: str, record_id: str, *, by: str, reason: str, now: datetime) -> Record:
        rows, i = self._find(project, record_id)
        rows[i] = replace(rows[i], status="retracted", updated_at=now, by=self._text(by, "by", 100), reason=self._text(reason, "reason", 300) if reason else "")
        return rows[i]

    def end_task(self, project: str, task: str) -> int:
        rows = self._projects.get(project, [])
        keep = [r for r in rows if not (r.kind == "working" and r.task == task)]
        self._projects[project] = keep
        return len(rows) - len(keep)

    def mark_stale(self, now: datetime) -> list[Record]:
        changed = []
        for rows in self._projects.values():
            for i, r in enumerate(rows):
                age = MAX_AGE[r.kind]
                if r.status == "active" and age is not None and now - r.updated_at > age:
                    rows[i] = replace(r, status="stale")
                    changed.append(rows[i])
        return changed

    # ---- reading ------------------------------------------------------------------------------------------------------------------------------
    def projects(self) -> list[str]:
        return sorted(p for p, rows in self._projects.items() if rows)

    def get(self, project: str, record_id: str) -> Record:
        rows, i = self._find(project, record_id)
        return rows[i]

    def _conflict_keys(self, project: str) -> dict[str, list[Record]]:
        groups: dict[str, list[Record]] = {}
        for r in self._projects.get(project, []):
            if r.status == "active" and r.kind in ("confirmed", "decision", "knowledge"):
                groups.setdefault(r.key, []).append(r)
        return {k: v for k, v in groups.items() if len({_norm(r.value) for r in v}) > 1}

    def recall(self, project: str, *, key: str | None = None, kind: str | None = None, include_stale: bool = False) -> list[Record]:
        wanted = ("active", "stale") if include_stale else ("active",)
        clashing = self._conflict_keys(project)
        return [replace(r, conflict=r.key in clashing and r.status == "active" and r.kind in ("confirmed", "decision", "knowledge"))
                for r in self._projects.get(project, []) if r.status in wanted and (key is None or r.key == key) and (kind is None or r.kind == kind)]

    def conflicts(self, project: str) -> list[dict[str, Any]]:
        out = []
        for key, rows in sorted(self._conflict_keys(project).items()):
            best = max(rows, key=lambda r: (r.confirmed, r.quality or 0, r.updated_at))
            rest = [r for r in rows if r is not best]
            why = "confirmed by " + (best.by or "user") if best.confirmed and not all(r.confirmed for r in rest) else \
                "higher source quality" if all((best.quality or 0) > (r.quality or 0) for r in rest) else "newer (same confirmation and source quality)"
            out.append({"key": key, "sides": [{"id": r.id, "value": r.value, "sources": list(r.sources), "quality": r.quality, "confirmed": r.confirmed,
                                               "updated_at": r.updated_at.isoformat()} for r in rows],
                        "preferred": {"id": best.id, "value": best.value, "why": why}, "resolved": False})
        return out

    def history(self, project: str, key: str) -> list[dict[str, Any]]:
        return [{"id": r.id, "value": r.value, "status": r.status, "at": r.created_at.isoformat(), "by": r.by or (r.sources[0] if r.sources else ""), "reason": r.reason}
                for r in self._projects.get(project, []) if r.key == key]

    def suggestions(self, project: str) -> list[dict[str, Any]]:
        """What earlier work suggests for the next task: recurring issues and confirmed records only."""
        rows = [r for r in self._projects.get(project, []) if r.status == "active"]
        issues = sorted((r for r in rows if r.kind == "issue" and r.seen >= 2), key=lambda r: (-r.seen, r.key))
        confirmed = sorted((r for r in rows if r.confirmed and r.kind != "issue"), key=lambda r: r.key)
        return [{"kind": "issue", "key": r.key, "seen": r.seen, "hint": r.value} for r in issues] + [{"kind": "confirmed", "key": r.key, "seen": r.seen, "hint": r.value} for r in confirmed]

    def overview(self) -> list[dict[str, Any]]:
        """Counts per project for read-only displays (Mission Control): active records by kind, open conflicts, stale records, suggestions. Never a key, value or source."""
        out = []
        for project in self.projects():
            rows = self._projects[project]
            counts: dict[str, int] = {}
            for r in rows:
                if r.status == "active":
                    counts[r.kind] = counts.get(r.kind, 0) + 1
            out.append({"project": project, "counts": dict(sorted(counts.items())), "conflicts": len(self._conflict_keys(project)), "stale": sum(1 for r in rows if r.status == "stale"),
                        "suggestions": len(self.suggestions(project))})
        return out

    # ---- snapshot -----------------------------------------------------------------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"version": VERSION, "projects": {p: [r.to_dict() for r in rows] for p, rows in sorted(self._projects.items()) if rows}}

    @classmethod
    def from_dict(cls, data: Any, **kw: Any) -> "ProjectMemory":
        if not isinstance(data, Mapping) or data.get("version") != VERSION or not isinstance(data.get("projects"), Mapping):
            raise MemoryValidationError("not a project memory snapshot of this version")
        m = cls(**kw)
        for project, rows in data["projects"].items():
            if not isinstance(rows, list):
                raise MemoryValidationError("snapshot: a project holds a list of records")
            out = []
            for raw in rows:
                if not isinstance(raw, Mapping) or set(raw) != set(_FIELDS) or raw.get("project") != project or raw.get("status") not in ("active", "stale", "superseded", "retracted"):
                    raise MemoryValidationError("snapshot: malformed record")
                try:
                    sources = raw["sources"]
                    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
                        raise ValueError
                    key, value, _ = m._check(project, raw["kind"], raw["key"], raw["value"], sources[0], raw["quality"])
                    out.append(Record(str(raw["id"])[:32], project, raw["kind"], key, value, tuple(m._text(s, "source", MAX_SOURCE) for s in sources), raw["quality"],
                                      datetime.fromisoformat(raw["created_at"]), datetime.fromisoformat(raw["updated_at"]), raw["status"], raw["confirmed"] is True,
                                      raw["supersedes"], int(raw["seen"]), raw["task"], str(raw["by"])[:100], str(raw["reason"])[:300]))
                except MemoryValidationError:
                    raise
                except (TypeError, ValueError, KeyError):
                    raise MemoryValidationError("snapshot: malformed record") from None
            if len(out) > m._max:
                raise MemoryValidationError("snapshot: too many records")
            m._projects[project] = out
        return m
