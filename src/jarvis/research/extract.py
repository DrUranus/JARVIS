"""Deterministic extraction from page text: relevant passages, numbers with their label, and a first classification of a statement
(FACT / OPINION / UNCERTAIN). No LLM; nothing is invented - a figure exists only if it stands in the text."""
from __future__ import annotations

import re

from jarvis.research.models import ClaimKind, Figure, clip

_STOP = frozenset("""der die das den dem des ein eine einer eines und oder aber mit für von zu im in am an auf aus bei nach über unter ist sind war wird werden hat haben
wie was wer wo wann welche welcher dass nicht auch noch nur mehr sehr mein meine dein ihre unser find finde mir mich dir the a an and or of for to in on at is are was
be by with from that this these those what which who how when where about into your our their its it as""".split())
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_OPINION = re.compile(r"\b(beste[rsn]?|best|number one|nummer 1|marktführer|führend\w*|leading|unschlagbar\w*|einzigartig\w*|premium|top[- ]\w+|"
                      r"wir empfehlen|i think|ich glaube|meiner meinung|in my opinion|vorzüglich|perfekt\w*|revolution\w*|hervorragend\w*)\b", re.I)
_HEDGE = re.compile(r"\b(vielleicht|angeblich|möglicherweise|vermutlich|soll\b|könnte|might|reportedly|allegedly|rumou?r\w*|unconfirmed|unbestätigt|approximately unknown)\b", re.I)
_NUM = r"(?:\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_MONEY_AFTER = re.compile(rf"(?P<num>{_NUM})\s?(?P<cur>€|eur\b|euro\b|\$|usd\b|dollar\b)", re.I)
_MONEY_BEFORE = re.compile(rf"(?P<cur>€|\$)\s?(?P<num>{_NUM})", re.I)
_PERCENT = re.compile(rf"(?P<num>{_NUM})\s?(?P<cur>%|prozent\b|percent\b)", re.I)
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{2,}")
MAX_FIGURES_PER_PAGE = 60


def keywords(texts: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for t in texts:
        for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", t.lower()):
            if w not in _STOP:
                seen[w] = None
    return list(seen)[:40]


def relevance(text: str, kws: list[str]) -> float:
    if not kws:
        return 0.0
    low = text.lower()
    return round(sum(1 for k in kws if k in low) / len(kws), 3)


def sentences(text: str, limit: int = 400) -> list[str]:
    out = []
    for s in _SENT.split(text):
        s = " ".join(s.split())
        if 12 <= len(s) <= 600:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def passages(text: str, kws: list[str], limit: int = 8) -> list[str]:
    scored = []
    for i, s in enumerate(sentences(text)):
        low = s.lower()
        hits = sum(1 for k in kws if k in low)
        if hits or _MONEY_AFTER.search(s) or _MONEY_BEFORE.search(s):
            scored.append((-hits - (0.5 if _MONEY_AFTER.search(s) or _MONEY_BEFORE.search(s) else 0), i, clip(s, 300)))
    scored.sort()
    return [s for _, _, s in scored[:limit]]


def classify(sentence: str) -> ClaimKind:
    if _HEDGE.search(sentence):
        return ClaimKind.UNCERTAIN
    if _OPINION.search(sentence):
        return ClaimKind.OPINION
    return ClaimKind.FACT


def parse_number(raw: str) -> float | None:
    """'1.299,00' -> 1299.0, '1,299.00' -> 1299.0, '49,90' -> 49.9, '1 299' -> 1299.0; None when it is not a plain number."""
    s = raw.strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + tail if len(tail) == 3 and head else s.replace(",", ".")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.rpartition(".")[2]) == 3 and len(s.partition(".")[0]) <= 3):
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v == v and abs(v) < 1e15 else None


def _unit(cur: str) -> str:
    c = cur.lower()
    return "EUR" if c in ("€", "eur", "euro") else "USD" if c in ("$", "usd", "dollar") else "%"


def label_before(text: str, start: int) -> str:
    segment = re.split(r"[.!?\n;]", text[max(0, start - 70): start])[-1]          # only the current sentence names the figure
    words = _WORD.findall(segment)
    words = [w for w in words if w.lower() not in _STOP][-4:]
    return " ".join(words).lower() or "value"


def figures(text: str, source_url: str) -> list[Figure]:
    found: list[Figure] = []
    spans: set[int] = set()
    for rx in (_MONEY_AFTER, _MONEY_BEFORE, _PERCENT):
        for m in rx.finditer(text):
            if m.start() in spans:
                continue
            spans.add(m.start())
            value = parse_number(m.group("num"))
            if value is None:
                continue
            ctx = text[max(0, m.start() - 60): m.end() + 30].replace("\n", " ")
            found.append(Figure(label_before(text, m.start() if rx is not _MONEY_BEFORE else m.start()), value, _unit(m.group("cur")), source_url, " ".join(ctx.split())))
            if len(found) >= MAX_FIGURES_PER_PAGE:
                return found
    return found
