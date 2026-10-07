"""How research results travel to the Business and Finance agents: through the orchestrator's ordinary parent results (AgentTask.dependencies) or as an
explicit `research` block in the input. Only plain data is read; only successful research results count; sizes are bounded; nothing is executed."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

MAX_SOURCES, MAX_FIGURES, MAX_CLAIMS, MAX_CONFLICTS = 40, 400, 100, 40


@dataclass(frozen=True)
class ResearchData:
    sources: tuple[dict[str, Any], ...] = ()
    figures: tuple[dict[str, Any], ...] = ()
    claims: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    conflicts: tuple[dict[str, Any], ...] = ()
    uncertainties: tuple[str, ...] = ()

    @property
    def ok_sources(self) -> tuple[dict[str, Any], ...]:
        return tuple(s for s in self.sources if s.get("status") == "ok")

    @property
    def has_data(self) -> bool:
        return bool(self.ok_sources)


def _dicts(value: Any, limit: int) -> list[dict[str, Any]]:
    return [dict(v) for v in value[:limit] if isinstance(v, Mapping)] if isinstance(value, (list, tuple)) else []


def _good_figure(f: Mapping[str, Any]) -> bool:
    v = f.get("value")
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and isinstance(f.get("label"), str) and isinstance(f.get("unit"), str)


def collect(parent_results: Mapping[str, Any] | None, explicit: Any = None) -> ResearchData:
    blocks: list[Mapping[str, Any]] = []
    for pr in (parent_results or {}).values():
        status = getattr(getattr(pr, "status", None), "value", getattr(pr, "status", None))
        out = getattr(pr, "output", None)
        if status == "SUCCEEDED" and isinstance(out, Mapping) and out.get("kind") == "research_result":
            blocks.append(out)
    if isinstance(explicit, Mapping):
        blocks.append(explicit)
    sources: dict[str, dict[str, Any]] = {}
    figures: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    unc: list[str] = []
    for b in blocks:
        for s in _dicts(b.get("sources"), MAX_SOURCES):
            if isinstance(s.get("url"), str):
                sources.setdefault(s["url"], {k: s.get(k) for k in ("url", "title", "source", "retrieved_at", "relevance", "status", "note")})
        figures += [{k: f.get(k) for k in ("label", "value", "unit", "source_url", "context")} for f in _dicts(b.get("figures"), MAX_FIGURES) if _good_figure(f)]
        claims += _dicts(b.get("claims"), MAX_CLAIMS)
        conflicts += _dicts(b.get("conflicts"), MAX_CONFLICTS)
        unc += [str(u)[:200] for u in (b.get("uncertainties") or [])[:20]] if isinstance(b.get("uncertainties"), list) else []
    return ResearchData(tuple(list(sources.values())[:MAX_SOURCES]), tuple(figures[:MAX_FIGURES]), tuple(claims[:MAX_CLAIMS]),
                        tuple(conflicts[:MAX_CONFLICTS]), tuple(dict.fromkeys(unc))[:20])


def pick_figure(data: ResearchData, keyword: str, unit: str | None = None) -> dict[str, Any] | None:
    """The first sourced figure whose label contains the keyword (optionally with this unit); None when the research found no such number."""
    k = keyword.strip().lower()
    for f in data.figures:
        if k and k in str(f["label"]).lower() and (unit is None or f["unit"] == unit):
            return f
    return None
