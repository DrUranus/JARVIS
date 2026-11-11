"""V2-03: Projektkontext - begrenzter, geschwaerzter Hintergrund fuer ein Projekt, NUR LESEND und noch nirgends angebunden.

Eine reine Funktion auf einem schmalen Leseprotokoll (`recent`): keine Schreibmethode des Speichers wird je aufgerufen, nichts wird veraendert, es gibt kein
Werkzeug, keinen Hintergrundlauf, keine Netzwerk- oder Prozesszugriffe. Eintraege gehoeren zu einem Projekt ueber das Tag `project:<name>` (Namenskonvention,
keine Schemaaenderung). Das Ergebnis ist ein unveraenderliches Datenobjekt: Text einzeilig, vorher geschwaerzt, hart auf Zeichen- und Elementbudget begrenzt.
Jede Fehlerquelle ergibt weniger Kontext, nie eine Ausnahme. Die Anbindung (opt-in ueber `explicit_user_context`/`memory_query`) braucht eine eigene Freigabe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from jarvis.memory.models import MemoryEntry, MemoryType
from jarvis.redaction import SecretDetector

MAX_CHAR_BUDGET = 8000
MAX_ITEMS = 50
MAX_ITEM_CHARS = 300
MAX_SOURCE_CHARS = 60
KINDS: tuple[MemoryType, ...] = (MemoryType.PROJECT, MemoryType.DECISION, MemoryType.RESOURCE, MemoryType.TASK_RESULT)
_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SPACE = re.compile(r"\s+")


class ProjectMemoryReader(Protocol):
    """Nur Lesen: Schreibmethoden des Speichers sind ueber dieses Protokoll nicht erreichbar."""

    def recent(self, limit: int = 10, *, type: Any = None, tags: Iterable[str] | None = None, offset: int = 0) -> list[MemoryEntry]: ...


@dataclass(frozen=True)
class ContextItem:
    kind: str
    text: str
    source: str
    timestamp: str


@dataclass(frozen=True)
class ProjectContext:
    project: str
    items: tuple[ContextItem, ...] = ()
    truncated: bool = False
    chars: int = 0


def _clamp(value: Any, hard: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, min(value, hard))


def _plain(text: Any, det: SecretDetector, limit: int) -> str:
    """Erst schwaerzen, dann einzeilig machen und kuerzen: nie ein halb geschwaerzter Text."""
    return _SPACE.sub(" ", det.redact(text if isinstance(text, str) else "")).strip()[:limit]


def build_project_context(project: Any, memory: ProjectMemoryReader, *, char_budget: int = 2000, max_items: int = 10,
                          detector: SecretDetector | None = None) -> ProjectContext:
    if not isinstance(project, str) or not _NAME.fullmatch(project):
        return ProjectContext(project="")
    budget = _clamp(char_budget, MAX_CHAR_BUDGET, 0)
    limit = _clamp(max_items, MAX_ITEMS, 0)
    det = detector or SecretDetector.from_environment()
    tag = f"project:{project}"
    found: dict[str, MemoryEntry] = {}
    for kind in KINDS:
        try:
            rows = memory.recent(limit + 1, type=kind, tags=[tag])
            for e in list(rows)[: limit + 1]:
                if isinstance(e, MemoryEntry) and isinstance(e.content, str) and e.id not in found:
                    found[e.id] = e
        except Exception:  # noqa: BLE001 - eine defekte Quelle verkleinert nur den Kontext
            continue
    ordered = sorted(found.values(), key=lambda e: (-int(e.importance), -e.created_at.timestamp(), e.id))
    items: list[ContextItem] = []
    used = 0
    truncated = False
    for e in ordered:
        if len(items) >= limit:
            truncated = True
            break
        text = _plain(e.content, det, min(MAX_ITEM_CHARS, budget))
        if not text:
            continue
        if used + len(text) > budget:
            truncated = True
            break
        if len(e.content) > len(text):
            truncated = True
        items.append(ContextItem(e.type.value, text, _plain(e.source or "", det, MAX_SOURCE_CHARS), e.created_at.isoformat()))
        used += len(text)
    return ProjectContext(project, tuple(items), truncated, used)
