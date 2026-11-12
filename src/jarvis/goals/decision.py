"""V2.1 (Mission 1): comparing at least three ways to do a task - a transparent, ordinal comparison. Pure logic.

Every approach is rated 1..5 on five criteria where HIGHER IS BETTER: quality (expected result quality), compute (5 = cheap), time (5 = fast), risk (5 = low error risk); the fifth,
permissions, is derived: 5 if everything it needs is already granted, 2 less per missing permission. A rating may be None (unknown): then the approach gets a RANGE (worst 1, best 5)
instead of a guessed number, and the comparison says whether the verdict depends on it. The result is a weighted mean with every contribution shown. These are ordinal judgements
supplied by the caller - no probabilities, no success guarantee - and nothing here grants a permission: missing ones are listed as approvals that would have to be asked for."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

CRITERIA = ("quality", "compute", "time", "risk", "permissions")
DEFAULT_WEIGHTS = {"quality": 3.0, "compute": 1.0, "time": 1.0, "risk": 2.0, "permissions": 1.0}
DISCLAIMER = "Ordinale Bewertung 1-5 aus den angegebenen Einschätzungen; keine Wahrscheinlichkeit, keine Erfolgsgarantie. Fehlende Berechtigungen sind nur als nötige Freigaben ausgewiesen."


def _rating(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError(f"{name} must be a whole number 1..5 or None (unknown)")
    return value


@dataclass(frozen=True)
class Approach:
    name: str
    quality: int | None
    compute: int | None
    time: int | None
    risk: int | None
    permissions: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 80:
            raise ValueError("an approach needs a short name")
        for c in CRITERIA[:4]:
            _rating(getattr(self, c), c)
        if not all(isinstance(p, str) and p for p in self.permissions):
            raise ValueError("permissions is a tuple of names")
        object.__setattr__(self, "permissions", tuple(self.permissions))


@dataclass(frozen=True)
class Rated:
    name: str
    score: float | None                  # None if a rating is unknown (see low/high)
    low: float
    high: float
    contributions: Mapping[str, float]   # per criterion, at the low end for unknown ratings; sums to the score when it is known
    ratings: Mapping[str, int | None]
    unknown: tuple[str, ...]
    needs_approval: tuple[str, ...]
    feasible: bool


@dataclass(frozen=True)
class Comparison:
    ranking: tuple[Rated, ...]
    decided: bool                        # the first place holds even in the worst case of every unknown rating
    tie: bool
    open_questions: tuple[str, ...]
    weights: Mapping[str, float]
    disclaimer: str = DISCLAIMER
    _by: Mapping[str, Rated] = field(default_factory=dict, repr=False)

    def explain(self, better: str, worse: str) -> str:
        """Why `better` ranks before `worse`: the weighted difference per criterion (known ratings only), largest first."""
        a, b = self._by[better], self._by[worse]
        total = sum(self.weights.values())
        parts = []
        for c in CRITERIA:
            ra, rb = a.ratings[c], b.ratings[c]
            if ra is None or rb is None:
                parts.append((0.0, f"{c}: unbekannt ({ra if ra is not None else '?'} gegen {rb if rb is not None else '?'})"))
            elif ra != rb:
                d = self.weights[c] * (ra - rb) / total
                parts.append((abs(d), f"{c} {d:+.3f} ({ra} gegen {rb}, Gewicht {self.weights[c]:g})"))
        parts.sort(key=lambda p: -p[0])
        head = f"{better} vor {worse}" if (a.low, a.high) != (b.low, b.high) else f"{better} und {worse} gleichauf (Reihenfolge nach Name)"
        return head + ": " + ("; ".join(p[1] for p in parts) or "keine Unterschiede in den Bewertungen")


def compare(approaches: Iterable[Approach], *, granted: Iterable[str], weights: Mapping[str, float] | None = None, approvals_possible: bool = True) -> Comparison:
    items = list(approaches)
    if len(items) < 3 or not all(isinstance(a, Approach) for a in items):
        raise ValueError("at least three approaches are compared")
    if len({a.name for a in items}) != len(items):
        raise ValueError("approach names must be unique")
    w = dict(DEFAULT_WEIGHTS)
    for k, v in (weights or {}).items():
        if k not in w or isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v != v or v == float("inf"):
            raise ValueError("weights: known criteria with finite values >= 0")
        w[k] = float(v)
    total = sum(w.values())
    if total <= 0:
        raise ValueError("at least one weight must be positive")
    have = set(granted)
    rated: list[Rated] = []
    for a in items:
        missing = tuple(p for p in a.permissions if p not in have)
        ratings: dict[str, int | None] = {c: getattr(a, c) for c in CRITERIA[:4]}
        ratings["permissions"] = max(1, 5 - 2 * len(missing))
        unknown = tuple(c for c in CRITERIA if ratings[c] is None)
        low = sum(w[c] * (ratings[c] or 1) for c in CRITERIA) / total
        high = sum(w[c] * (ratings[c] or 5) for c in CRITERIA) / total
        rated.append(Rated(a.name, None if unknown else low, low, high, {c: w[c] * (ratings[c] or 1) / total for c in CRITERIA}, ratings, unknown, missing,
                           feasible=approvals_possible or not missing))
    rated.sort(key=lambda r: (not r.feasible, -(r.low + r.high) / 2, r.name))
    top, rest = rated[0], [r for r in rated[1:] if r.feasible]
    decided = top.feasible and all(top.low >= r.high for r in rest)
    tie = bool(rest) and (top.low, top.high) == (rest[0].low, rest[0].high)
    questions = tuple(f"{r.name}: {', '.join(r.unknown)} unbekannt (Bewertung 1..5 offen)" for r in rated if r.unknown and r.feasible) if not decided else ()
    return Comparison(tuple(rated), decided, tie, questions, w, _by={r.name: r for r in rated})
