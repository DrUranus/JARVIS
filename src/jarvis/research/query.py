"""Search terms and source choice for the web research (no network, no model, no state).

What may leave the machine is only the search text: it is derived from the user's research question, stripped of anything that looks private (file paths, e-mail
addresses, URLs with credentials, long digit/hex strings), redacted with the secret detector and shortened to the provider limit. Conversation history, memory and
files are never part of it. The terms are produced by simple, deterministic rules (no LLM call) so that the same question always gives the same search text."""
from __future__ import annotations

import re
from typing import Any, Sequence

from jarvis.redaction import SecretDetector

_PREFIX = re.compile(
    r"^\s*(?:bitte\s+)?(?:recherchier\w*|suche\w*|finde(?:\s+\w+)?\s+heraus|informier\w*\s+dich|research|find\s+out|look\s+up|search\s+for)\b"
    r"[\s:,\-]*(?:(?:mir|uns|bitte|doch|einmal|mal|kurz)\s+)*(?:(?:über|ueber|zu|nach|um|about|for)\s+)?", re.IGNORECASE)
_TAIL = re.compile(r"\s+(?:und|and|dann|danach|sowie)\s+(?:fasse|erstelle|schreibe|nenne|gib|liste|speichere|sende|schicke|summari[sz]e|write|list|give|save|send)\b.*$",
                   re.IGNORECASE | re.DOTALL)
_PRIVATE = re.compile(r"(?:[A-Za-z]:[\\/]\S*|(?:~|\.{1,2})?[\\/](?:home|users|etc|var|tmp|usr)[\\/]\S*|\\\\\S+|\S+@\S+\.\S+|https?://\S+|\b[0-9A-Fa-f]{24,}\b|\b\d{9,}\b)", re.IGNORECASE)
MAX_QUERY_CHARS = 300          # same limit as the search service (checked there again)
_WORD = re.compile(r"[\wäöüÄÖÜß-]{3,}", re.UNICODE)
STOP = frozenset("und oder der die das den dem des ein eine einen einem eines ist sind war wird werden mit von für fuer auf aus bei nach über ueber zum zur zur wie was wer wo "
                 "the and for with from that this are was were about what who how which".split())


class NoSearchTerms(ValueError):
    """The question contains nothing that can be searched (empty after removing private parts)."""


def search_terms(question: str, detector: SecretDetector | None = None) -> str:
    """The search text for a research question. Raises NoSearchTerms if nothing usable is left."""
    if not isinstance(question, str):
        raise NoSearchTerms("the question must be text")
    text = " ".join(question.split())
    text = _PREFIX.sub("", text, count=1)
    text = _TAIL.sub("", text)
    text = _PRIVATE.sub(" ", text)
    text = (detector or SecretDetector.from_environment()).redact(text)
    text = re.sub(r"\[REDACTED[^\]]*\]|<redacted>|\*{3,}", " ", text, flags=re.IGNORECASE)
    text = "".join(c for c in text if ord(c) >= 32 and ord(c) != 127)
    text = " ".join(text.strip(" .,:;!?-\"'").split())
    if len(text) > MAX_QUERY_CHARS:
        text = text[:MAX_QUERY_CHARS].rsplit(" ", 1)[0]
    if not _WORD.search(text):
        raise NoSearchTerms("no searchable terms are left after removing private parts")
    return text


def keywords(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text) if w.lower() not in STOP]


def choose_sources(hits: Sequence[Any], terms: str, limit: int, per_host: int = 2) -> list[Any]:
    """Relevant, varied sources: rank by overlap of the search words with title and excerpt (stable for equal scores), at most `per_host` per host, at most `limit`.
    The hits (objects with title, url, excerpt) were already accepted by the URL policy; this only chooses among them."""
    kws = set(keywords(terms))

    def score(h: Any) -> int:
        hay = set(keywords(h.title + " " + h.excerpt))
        return len(kws & hay)

    ranked = sorted(enumerate(hits), key=lambda p: (-score(p[1]), p[0]))
    chosen: list[Any] = []
    hosts: dict[str, int] = {}
    for _, h in ranked:
        host = re.sub(r"^\w+://([^/:?#]+).*$", r"\1", h.url).lower()
        if hosts.get(host, 0) >= per_host:
            continue
        hosts[host] = hosts.get(host, 0) + 1
        chosen.append(h)
        if len(chosen) >= max(1, limit):
            break
    return chosen
