"""Lokales, netzfreies Suchverfahren: gehashte TF-IDF-Vektoren ueber Zeichen-3/4-Gramme (nur Standardbibliothek).

* Kein Netzwerk, kein Modell, keine Abhaengigkeit. Die Vektoren entstehen pro Suche aus den Kandidaten und werden nicht gespeichert.
* Zeichen-N-Gramme finden Flexionen und Komposita ('Farben' ~ 'Lieblingsfarbe', 'servers' ~ 'server').
* Speicherung, Validierung und Filter bleiben die der bekannten Backends; nur `search` ist anders.
"""
from __future__ import annotations

import math
import unicodedata
import zlib
from collections import Counter
from typing import Sequence

from jarvis.memory import validation as v
from jarvis.memory.inmemory import InMemoryStore
from jarvis.memory.models import MemoryEntry, MemoryHit
from jarvis.memory.ranking import tokenize
from jarvis.memory.sqlite_store import CANDIDATE_LIMIT, SqliteMemoryStore

NGRAM_SIZES = (3, 4)  # laengere Fragmente gewichten echte Wortstaemme staerker als Zufallstreffer
DIMENSIONS = 4096    # Hash-Buckets je Vektor
MIN_SCORE = 0.12     # darunter gilt ein Eintrag nicht als Treffer
TAG_WEIGHT = 2       # Tags zaehlen doppelt


def _fold(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


def _features(text: str, tags: Sequence[str] = ()) -> Counter[int]:
    counts: Counter[int] = Counter()
    for weight, source in ((1, text), (TAG_WEIGHT, " ".join(tags))):
        for word in tokenize(source):
            padded = f"^{_fold(word)}$"
            for size in NGRAM_SIZES:
                for i in range(len(padded) - size + 1):
                    counts[zlib.crc32(padded[i:i + size].encode("utf-8")) % DIMENSIONS] += weight
    return counts


def rank_semantic(entries: Sequence[MemoryEntry], query: str, limit: int) -> list[MemoryHit]:
    """Kosinus-Aehnlichkeit gewichteter N-Gramm-Vektoren; `entries` newest-first, Gleichstand bleibt so."""
    q = _features(query)
    if not q or not entries or limit <= 0:
        return []
    docs = [_features(e.content, e.tags) for e in entries]
    n = len(docs)
    df: Counter[int] = Counter()
    for d in docs:
        df.update(d.keys())

    def weigh(c: Counter[int]) -> dict[int, float]:
        return {k: (1 + math.log(tf)) * (math.log((1 + n) / (1 + df.get(k, 0))) + 1) for k, tf in c.items()}

    qv = weigh(q)
    qn = math.sqrt(sum(x * x for x in qv.values()))
    hits: list[MemoryHit] = []
    for entry, d in zip(entries, docs):
        dv = weigh(d)
        dn = math.sqrt(sum(x * x for x in dv.values()))
        if not dn:
            continue
        cos = sum(x * dv.get(k, 0.0) for k, x in qv.items()) / (qn * dn)
        if cos >= MIN_SCORE:
            hits.append(MemoryHit(entry, cos + 0.01 * entry.importance))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


class SemanticInMemoryStore(InMemoryStore):
    """Nicht persistent, mit semantischer Suche."""

    def search(self, query, *, limit=5, type=None, tags=None, min_importance=1) -> list[MemoryHit]:
        q = v.normalize_query(query)
        limit = v.normalize_limit(limit)
        min_importance = v.normalize_importance(min_importance)
        candidates = self._newest_first(type, tags)  # validiert type/tags auch bei leerer Anfrage
        pool = [e for e in candidates if e.importance >= min_importance][:CANDIDATE_LIMIT]
        return rank_semantic(pool, q, limit)


class SemanticSqliteStore(SqliteMemoryStore):
    """Persistent (SQLite wie bisher), mit semantischer Suche ueber die neuesten CANDIDATE_LIMIT Kandidaten."""

    def search(self, query, *, limit=5, type=None, tags=None, min_importance=1) -> list[MemoryHit]:
        q = v.normalize_query(query)
        limit = v.normalize_limit(limit)
        min_importance = v.normalize_importance(min_importance)
        where, params = self._filters(type, tags, min_importance)
        if not _features(q) or limit == 0:
            return []

        def op(conn):
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {where} "  # noqa: S608 - only fixed fragments, values bound
                "ORDER BY created_at DESC, rowid DESC LIMIT ?", [*params, CANDIDATE_LIMIT]).fetchall()
            return rank_semantic(self._entries(conn, rows), q, limit)

        return self._run(False, op) or []
