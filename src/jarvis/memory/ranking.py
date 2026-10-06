"""Backend-neutral keyword relevance. A future vector backend replaces this, not the interface."""
from __future__ import annotations

import re

from jarvis.memory.models import MemoryEntry

MIN_TERM_LENGTH = 3
STOPWORDS = frozenset("""
der die das den dem des ein eine einen einem einer und oder aber ist sind war bin bist mein meine meinen meiner meinem
mich mir dich dir ich du wir ihr sie nicht auch von mit für auf aus bei nach über wie was wer wo wann welche welcher
welches mag habe hast hat dass wird kann soll the and for are was were you your his her its our this that with from
about what which who how when where does did have has had can will would should not but all any one
""".split())

_WORD = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Casefolded, de-duplicated search terms without stopwords and very short words."""
    seen: dict[str, None] = {}
    for w in _WORD.findall(text.casefold()):
        if len(w) >= MIN_TERM_LENGTH and w not in STOPWORDS:
            seen.setdefault(w)
    return list(seen)


def score(entry: MemoryEntry, terms: list[str]) -> float:
    """0 if no term matches. Otherwise: share of matched terms (+ tag bonus) + a small importance bonus.
    Terms match as substrings, so 'farbe' finds 'Lieblingsfarbe'."""
    if not terms:
        return 0.0
    text = entry.content.casefold()
    matched = tag_hits = 0
    for t in terms:
        in_tags = any(t in tag for tag in entry.tags)
        if t in text or in_tags:
            matched += 1
        if in_tags:
            tag_hits += 1
    if matched == 0:
        return 0.0
    n = len(terms)
    return matched / n + 0.25 * tag_hits / n + 0.01 * entry.importance
