"""BusinessResult: findings, market data, competitors, opportunities, risks, assumptions, recommendations and sources - every number labelled
as GIVEN (by the user), FACT (stated by a source), INFERENCE (computed here from sourced/given data), ESTIMATE (an assumption) or UNKNOWN (no data).
Nothing is invented: where data is missing the entry says UNKNOWN. Bounded, JSON-compatible, no free text in reprs."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from jarvis.business.errors import InvalidBusinessInput


class Basis(str, Enum):
    GIVEN = "GIVEN"
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    ESTIMATE = "ESTIMATE"
    UNKNOWN = "UNKNOWN"


def clip(text: Any, limit: int) -> str:
    s = text if isinstance(text, str) else str(text)
    return s if len(s) <= limit else s[: max(0, limit - 1)] + "…"


def number(value: object, what: str, *, positive: bool = False, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e15:
        raise InvalidBusinessInput(f"{what} must be a finite number")
    if positive and value <= 0:
        raise InvalidBusinessInput(f"{what} must be greater than zero")
    if non_negative and value < 0:
        raise InvalidBusinessInput(f"{what} must not be negative")
    return float(value)


@dataclass(frozen=True)
class Entry:
    """One statement with its basis and sources (e.g. a finding, a risk, a recommendation)."""
    text: str = field(repr=False)
    basis: Basis
    sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"text": clip(self.text, 300), "basis": self.basis.value, "sources": [clip(s, 300) for s in self.sources[:5]]}


@dataclass(frozen=True)
class Assumption:
    name: str
    value: Any
    basis: Basis                      # GIVEN (user), ESTIMATE (derived assumption, says from what) or UNKNOWN
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        v = self.value if isinstance(self.value, (int, float, str, bool, type(None))) else str(self.value)
        return {"name": clip(self.name, 80), "value": clip(v, 200) if isinstance(v, str) else v, "basis": self.basis.value, "note": clip(self.note, 200)}


@dataclass(frozen=True)
class Competitor:
    name: str
    url: str = ""
    prices: dict[str, dict[str, Any]] = field(default_factory=dict)      # label -> {"value", "unit", "basis", "source"}
    offers: tuple[str, ...] = field(default=(), repr=False)
    positioning: str = "UNKNOWN"
    positioning_basis: Basis = Basis.UNKNOWN
    strengths: tuple[Entry, ...] = ()
    weaknesses: tuple[Entry, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": clip(self.name, 120), "url": clip(self.url, 300), "prices": {clip(k, 80): v for k, v in list(self.prices.items())[:30]},
                "offers": [clip(o, 200) for o in self.offers[:10]], "positioning": self.positioning, "positioning_basis": self.positioning_basis.value,
                "strengths": [e.to_dict() for e in self.strengths[:6]], "weaknesses": [e.to_dict() for e in self.weaknesses[:6]]}


@dataclass(frozen=True)
class BusinessResult:
    objective: str = field(repr=False)
    kind: str = ""
    summary: str = field(default="", repr=False)
    findings: tuple[Entry, ...] = ()
    market_data: dict[str, Any] = field(default_factory=dict)
    competitors: tuple[Competitor, ...] = ()
    opportunities: tuple[Entry, ...] = ()
    risks: tuple[Entry, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    recommendations: tuple[Entry, ...] = ()
    sources: tuple[dict[str, Any], ...] = ()
    confidence: dict[str, Any] = field(default_factory=lambda: {"level": "low", "score": 0.0, "reasons": []})
    calculations: dict[str, Any] = field(default_factory=dict)
    drafts: dict[str, Any] = field(default_factory=dict)
    unknowns: tuple[str, ...] = ()
    truncated: bool = False

    def to_dict(self, max_chars: int = 20_000) -> dict[str, Any]:
        keep = {"findings": len(self.findings), "competitors": len(self.competitors), "opportunities": len(self.opportunities), "risks": len(self.risks),
                "recommendations": len(self.recommendations), "sources": len(self.sources), "assumptions": len(self.assumptions)}
        truncated = self.truncated

        def build() -> dict[str, Any]:
            return {"kind": "business_result", "task": self.kind, "objective": clip(self.objective, 300), "summary": clip(self.summary, 800),
                    "findings": [e.to_dict() for e in self.findings[: keep["findings"]]], "market_data": self.market_data,
                    "competitors": [c.to_dict() for c in self.competitors[: keep["competitors"]]],
                    "opportunities": [e.to_dict() for e in self.opportunities[: keep["opportunities"]]], "risks": [e.to_dict() for e in self.risks[: keep["risks"]]],
                    "assumptions": [a.to_dict() for a in self.assumptions[: keep["assumptions"]]],
                    "recommendations": [e.to_dict() for e in self.recommendations[: keep["recommendations"]]],
                    "sources": [dict(s) for s in self.sources[: keep["sources"]]], "confidence": self.confidence, "calculations": self.calculations,
                    "drafts": self.drafts, "unknowns": [clip(u, 200) for u in self.unknowns[:30]], "truncated": truncated,
                    "note": "analysis and drafts only: nothing was sent, ordered or published"}

        out = build()
        for key in ("sources", "findings", "competitors", "recommendations", "risks", "opportunities", "assumptions"):
            while len(json.dumps(out)) > max_chars and keep[key] > 0:
                truncated = True
                keep[key] //= 2
                out = build()
        if len(json.dumps(out)) > max_chars:
            out = {k: out[k] for k in ("kind", "task", "objective", "summary", "confidence", "unknowns", "note")} | {"truncated": True}
        return out
