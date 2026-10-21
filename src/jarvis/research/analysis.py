"""Cross-check and synthesis: pure functions over what the sources said. Numbers that differ beyond a tolerance are a CONFLICT (all sides shown);
a statement found in two sources is marked corroborated; everything JARVIS computes itself is an INFERENCE and says so."""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from typing import Iterable

from jarvis.research import extract as X
from jarvis.research.models import Claim, ClaimKind, Conflict, Figure, Source, SourceStatus, clip

TOLERANCE = 0.10


def label_key(label: str) -> str:
    return " ".join(sorted({w for w in re.findall(r"[a-zäöüß]{3,}", label.lower()) if w not in X._STOP})) or "value"


def crosscheck(figures: Iterable[Figure], tolerance: float = TOLERANCE) -> list[Conflict]:
    groups: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for f in figures:
        groups[(label_key(f.label), f.unit)].setdefault(f.source_url, f.value)
    conflicts = []
    for (key, unit), by_source in groups.items():
        if len(by_source) < 2:
            continue
        vals = list(by_source.values())
        hi, lo = max(vals), min(vals)
        if hi > 0 and (hi - lo) / hi > tolerance:
            conflicts.append(Conflict(key, unit, tuple(sorted(by_source.items()))))
    return conflicts[:20]


def _tokens(s: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-zäöüß0-9]{2,}", s.lower()) if w not in X._STOP)


def _numbers(s: str) -> frozenset[str]:
    return frozenset(re.findall(r"\d+(?:[.,]\d+)*", s))


def build_claims(per_source: dict[str, list[str]], conflicts: list[Conflict], limit: int = 40) -> list[Claim]:
    """One claim per distinct statement; kind from the wording; a statement that carries a conflicting figure becomes UNCERTAIN."""
    conflicted = {(label_key(f_label), unit) for f_label, unit in ((c.label, c.unit) for c in conflicts)}
    claims: list[tuple[str, list[str], ClaimKind]] = []
    for url, sents in per_source.items():
        for s in sents:
            toks = _tokens(s)
            for entry in claims:
                other = _tokens(entry[0])
                # the same statement: similar wording AND exactly the same numbers (25 € and 27 € are two different statements)
                if toks and other and len(toks & other) / len(toks | other) >= 0.6 and _numbers(s) == _numbers(entry[0]):
                    if url not in entry[1]:
                        entry[1].append(url)
                    break
            else:
                claims.append((s, [url], X.classify(s)))
    out = []
    for text, urls, kind in claims:
        if kind is ClaimKind.FACT and any((label_key(f.label), f.unit) in conflicted for f in X.figures(text, urls[0])):
            kind = ClaimKind.UNCERTAIN
        out.append(Claim(text, kind, tuple(urls), len(urls) > 1))
    return out[:limit]


def price_inferences(figures: list[Figure], conflicts: list[Conflict]) -> list[Claim]:
    """Derived statements (INFERENCE): range and median of comparable figures from at least two sources. They say how they were computed."""
    groups: dict[tuple[str, str], list[Figure]] = defaultdict(list)
    for f in figures:
        groups[(label_key(f.label), f.unit)].append(f)
    bad = {(c.label, c.unit) for c in conflicts}
    out = []
    for (key, unit), fs in groups.items():
        urls = tuple(dict.fromkeys(f.source_url for f in fs))
        if len(urls) < 2 or (key, unit) in bad:
            continue
        vals = [f.value for f in fs]
        out.append(Claim(f"INFERENCE ({len(urls)} sources): '{key}' ranges from {min(vals):g} to {max(vals):g} {unit} (median {statistics.median(vals):g})",
                         ClaimKind.INFERENCE, urls[:5]))
    return out[:10]


def summarize(objective: str, sources: list[Source], claims: list[Claim], conflicts: list[Conflict]) -> str:
    ok = [s for s in sources if s.status is SourceStatus.OK]
    bad = len(sources) - len(ok)
    kinds = {k: sum(1 for c in claims if c.kind is k) for k in ClaimKind}
    parts = [f"{len(ok)} of {len(sources)} source(s) read" + (f", {bad} unavailable/blocked" if bad else ""),
             f"{kinds[ClaimKind.FACT]} fact(s), {kinds[ClaimKind.OPINION]} opinion(s), {kinds[ClaimKind.UNCERTAIN]} uncertain, {kinds[ClaimKind.INFERENCE]} inference(s)"]
    if conflicts:
        parts.append(f"{len(conflicts)} CONFLICT(s) between sources")
    if not ok:
        parts.append("nothing could be read: no result is claimed")
    return clip("; ".join(parts), 400)


def uncertainties(sources: list[Source], claims: list[Claim], conflicts: list[Conflict]) -> list[str]:
    out = [f"{s.url}: {s.status.value}" + (f" ({s.note})" if s.note else "") for s in sources if s.status is not SourceStatus.OK]
    single = sum(1 for c in claims if c.kind is ClaimKind.FACT and not c.corroborated)
    if single:
        out.append(f"{single} fact(s) rest on a single source")
    out += [f"CONFLICT on '{c.label}' ({c.unit}): " + " vs ".join(f"{v:g}" for _, v in c.entries) for c in conflicts]
    return out[:20]
