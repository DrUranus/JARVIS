"""Business calculations on given numbers. Each result says what it was computed from; impossible cases (no contribution margin, no data) are UNKNOWN
with the reason, never a made-up number."""
from __future__ import annotations

import statistics
from typing import Any, Sequence

from jarvis.business.errors import InvalidBusinessInput
from jarvis.business.models import number


def unknown(why: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "reason": why}


def break_even(fixed_costs: float | None, price: float | None, variable_cost: float | None) -> dict[str, Any]:
    if fixed_costs is None or price is None or variable_cost is None:
        missing = [n for n, v in (("fixed_costs", fixed_costs), ("price", price), ("variable_cost", variable_cost)) if v is None]
        return unknown(f"missing data: {', '.join(missing)}")
    f, p, v = number(fixed_costs, "fixed_costs", non_negative=True), number(price, "price", positive=True), number(variable_cost, "variable_cost", non_negative=True)
    cm = p - v
    if cm <= 0:
        return unknown(f"the contribution margin per unit is {cm:g} (price {p:g} <= variable cost {v:g}): break-even is never reached")
    units = f / cm
    return {"status": "COMPUTED", "units": units, "revenue": units * p, "contribution_margin": cm, "formula": "fixed costs / (price - variable cost)",
            "inputs": {"fixed_costs": f, "price": p, "variable_cost": v}}


def scenario(price: float, variable_cost: float, fixed_costs: float, units: float) -> dict[str, Any]:
    p, v, f = number(price, "price", positive=True), number(variable_cost, "variable_cost", non_negative=True), number(fixed_costs, "fixed_costs", non_negative=True)
    u = number(units, "units", non_negative=True)
    revenue, cost = p * u, f + v * u
    profit = revenue - cost
    return {"units": u, "revenue": revenue, "costs": cost, "profit": profit, "margin": None if revenue == 0 else profit / revenue}


def scenarios(price: float, variable_cost: float, fixed_costs: float, units: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(units, dict) or not 1 <= len(units) <= 6:
        raise InvalidBusinessInput("units is an object with 1..6 named scenarios, e.g. {'pessimistic': 20, 'base': 40, 'optimistic': 60}")
    return {str(k)[:30]: scenario(price, variable_cost, fixed_costs, v) for k, v in units.items()}


def payback_months(investment: float | None, monthly_profit: float | None) -> dict[str, Any]:
    if investment is None or monthly_profit is None:
        return unknown("missing data: investment or monthly profit")
    i, m = number(investment, "investment", non_negative=True), number(monthly_profit, "monthly_profit")
    if m <= 0:
        return unknown("the monthly profit is zero or negative: the investment is never paid back at this level")
    return {"status": "COMPUTED", "months": i / m, "formula": "investment / monthly profit", "inputs": {"investment": i, "monthly_profit": m}}


def price_stats(values: Sequence[float]) -> dict[str, Any]:
    vals = [number(v, "price", non_negative=True) for v in values]
    if not vals:
        return unknown("no prices")
    med = statistics.median(vals)
    return {"status": "COMPUTED", "n": len(vals), "min": min(vals), "median": med, "mean": statistics.fmean(vals), "max": max(vals),
            "spread_pct": None if max(vals) == 0 else (max(vals) - min(vals)) / max(vals) * 100}


def period_findings(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Revenue / cost rows per period -> margins, trend, loss-making periods. Needs at least one complete row."""
    clean = []
    for r in rows:
        if not isinstance(r, dict):
            raise InvalidBusinessInput("a row is an object with period, revenue and costs")
        clean.append((str(r.get("period", len(clean) + 1))[:30], number(r.get("revenue"), "revenue", non_negative=True), number(r.get("costs"), "costs", non_negative=True)))
    if not clean:
        return unknown("no rows")
    table = [{"period": p, "revenue": rev, "costs": c, "profit": rev - c, "margin": None if rev == 0 else (rev - c) / rev} for p, rev, c in clean]
    out: dict[str, Any] = {"status": "COMPUTED", "rows": table, "loss_periods": [t["period"] for t in table if t["profit"] < 0]}
    if len(table) >= 2 and table[0]["revenue"] > 0:
        out["revenue_change"] = (table[-1]["revenue"] - table[0]["revenue"]) / table[0]["revenue"]
        out["cost_change"] = None if table[0]["costs"] == 0 else (table[-1]["costs"] - table[0]["costs"]) / table[0]["costs"]
    return out
