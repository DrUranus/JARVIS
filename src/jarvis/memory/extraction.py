"""Turns user text into a memory intent. Rule-based and explicit on purpose.

JARVIS only stores something when the user asks for it ("Merk dir, dass ..."). Everything else stays
temporary conversation context. Replace RuleBasedExtractor (e.g. with an LLM-based one) via the
MemoryExtractor interface without touching the Core.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from jarvis.memory.models import IMPORTANCE_DEFAULT, MemoryType


class IntentAction(str, Enum):
    REMEMBER = "remember"
    RECALL = "recall"
    FORGET = "forget"


@dataclass(frozen=True)
class MemoryIntent:
    action: IntentAction
    content: str = ""          # REMEMBER: what to store
    query: str = ""            # RECALL/FORGET: search text ('' = list recent)
    entry_id: str | None = None  # FORGET by id
    type: MemoryType = MemoryType.FACT
    importance: int = IMPORTANCE_DEFAULT


class MemoryExtractor(ABC):
    @abstractmethod
    def extract(self, text: str) -> MemoryIntent | None:
        """Return an intent if the text is a memory request, else None (-> normal processing)."""


_F = re.IGNORECASE | re.DOTALL
_LEAD = r"^\s*(?:jarvis[,:]?\s+)?"
_REMEMBER = re.compile(
    _LEAD + r"(?:kannst\s+du\s+dir\s+merken|merk(?:e)?\s+dir|merke|speichere(?:\s+(?:dir|ab))?|speicher\s+ab|"
            r"please\s+remember|remember|note\s+(?:down\s+)?that)\b[\s,:]*(?:dass\s+|that\s+)?(?P<c>.+?)\s*$", _F)
_FORGET = re.compile(
    _LEAD + r"(?:vergiss|forget|lösche?\s+(?:die\s+)?erinnerung|lösche?\s+aus\s+dem\s+gedächtnis)\b"
            r"[\s,:]*(?:dass\s+|that\s+|about\s+|über\s+)?(?P<q>.+?)\s*$", _F)
_RECALL = re.compile(
    _LEAD + r"(?:woran\s+erinnerst\s+du\s+dich|was\s+hast\s+du\s+(?:dir\s+)?gemerkt|"
            r"was\s+weißt\s+du\s+(?:alles\s+)?über\s+mich|what\s+do\s+you\s+remember|"
            r"what\s+do\s+you\s+know\s+about\s+me|what\s+have\s+you\s+remembered)\b(?P<q>.*)$", _F)
_ID = re.compile(r"^[0-9a-f]{12}$")

_TYPE_RULES: tuple[tuple[MemoryType, re.Pattern[str]], ...] = tuple((t, re.compile(rx, re.IGNORECASE)) for t, rx in (
    (MemoryType.DECISION, r"entscheid|beschlossen|decided|decision"),
    (MemoryType.GOAL, r"\bmein\s+ziel|ziel\s+ist|\bgoal\b|\bi\s+want\s+to\s+achieve"),
    (MemoryType.PREFERENCE, r"\bich\s+(?:mag|liebe|bevorzuge|hasse)\b|\bmag\s+ich\b|lieblings|favorit|"
                            r"\bi\s+(?:like|love|prefer|hate)\b|\bmy\s+favou?rite|bevorzug"),
    (MemoryType.PROJECT, r"\bprojekt|\bproject\b"),
    (MemoryType.SYSTEM, r"konfiguration|\bconfig\b|einstellung|\bsetting"),
    (MemoryType.RESOURCE, r"https?://|\b[\w./\\-]+\.(?:py|md|txt|csv|json|pdf|toml|yaml|yml)\b|^/|[A-Za-z]:\\"),
))
_IMPORTANT = re.compile(r"\bwichtig|\bimportant\b", re.IGNORECASE)


def infer_type(content: str) -> MemoryType:
    return next((t for t, rx in _TYPE_RULES if rx.search(content)), MemoryType.FACT)


class RuleBasedExtractor(MemoryExtractor):
    def extract(self, text: str) -> MemoryIntent | None:
        if m := _REMEMBER.match(text):
            content = m.group("c").strip()
            return MemoryIntent(IntentAction.REMEMBER, content=content, type=infer_type(content),
                                importance=8 if _IMPORTANT.search(content) else IMPORTANCE_DEFAULT)
        if m := _FORGET.match(text):
            q = m.group("q").strip().rstrip(".!?").strip()
            return MemoryIntent(IntentAction.FORGET, query=q, entry_id=q.lower() if _ID.match(q.lower()) else None)
        if m := _RECALL.match(text):
            return MemoryIntent(IntentAction.RECALL, query=m.group("q").strip().rstrip("?.! "))
        return None
