"""Financial calculations. Each returns a Metric: COMPUTED from the given numbers, or UNKNOWN with the reason (missing data, zero/negative
denominator, too few data points). Nothing is estimated or defaulted, and nothing here touches an account."""
from __future__ import annotations

import math
import statistics
from typing import Sequence

from jarvis.finance.errors import InvalidFinanceInput
from jarvis.finance.models import Direction, Metric, number


def _unknown(name: str, formula: str, why: str, **inputs: float) -> Metric:
    return Metric(name, None, formula, {k: v for k, v in inputs.items() if v is not None}, why)


def _have(**kw: object) -> str | None:
    missing = [k for k, v in kw.items() if v is None]
    return f"missing data: {', '.join(missing)}" if missing else None


def _num(v: float | None, what: str) -> float | None:
    return None if v is None else number(v, what)


def pe_ratio(price: float | None, eps: float | None) -> Metric:
    f = "price / earnings per share"
    if (m := _have(price=price, eps=eps)):
        return _unknown("P/E", f, m)
    price, eps = _num(price, "price"), _num(eps, "eps")
    if price <= 0:
        return _unknown("P/E", f, "price must be positive", price=price, eps=eps)
    if eps <= 0:
        return _unknown("P/E", f, "earnings per share is zero or negative: P/E is not meaningful", price=price, eps=eps)
    return Metric("P/E", price / eps, f, {"price": price, "eps": eps})


def ps_ratio(market_cap: float | None, revenue: float | None) -> Metric:
    f = "market cap / revenue"
    if (m := _have(market_cap=market_cap, revenue=revenue)):
        return _unknown("P/S", f, m)
    market_cap, revenue = _num(market_cap, "market_cap"), _num(revenue, "revenue")
    if market_cap <= 0 or revenue <= 0:
        return _unknown("P/S", f, "market cap and revenue must be positive", market_cap=market_cap, revenue=revenue)
    return Metric("P/S", market_cap / revenue, f, {"market_cap": market_cap, "revenue": revenue})


def ev_ebitda(market_cap: float | None, debt: float | None, cash: float | None, ebitda: float | None) -> Metric:
    f = "(market cap + debt - cash) / EBITDA"
    if (m := _have(market_cap=market_cap, debt=debt, cash=cash, ebitda=ebitda)):
        return _unknown("EV/EBITDA", f, m)
    mc, d, c, e = _num(market_cap, "market_cap"), _num(debt, "debt"), _num(cash, "cash"), _num(ebitda, "ebitda")
    if e <= 0:
        return _unknown("EV/EBITDA", f, "EBITDA is zero or negative: the multiple is not meaningful", market_cap=mc, debt=d, cash=c, ebitda=e)
    return Metric("EV/EBITDA", (mc + d - c) / e, f, {"market_cap": mc, "debt": d, "cash": c, "ebitda": e})


def growth(name: str, current: float | None, previous: float | None) -> Metric:
    f = "(current - previous) / |previous|"
    if (m := _have(current=current, previous=previous)):
        return _unknown(name, f, m)
    cur, prev = _num(current, "current"), _num(previous, "previous")
    if prev == 0:
        return _unknown(name, f, "the previous value is zero: growth is undefined", current=cur, previous=prev)
    return Metric(name, (cur - prev) / abs(prev), f, {"current": cur, "previous": prev})


def margin(name: str, profit: float | None, revenue: float | None) -> Metric:
    f = "profit / revenue"
    if (m := _have(profit=profit, revenue=revenue)):
        return _unknown(name, f, m)
    p, r = _num(profit, "profit"), _num(revenue, "revenue")
    if r <= 0:
        return _unknown(name, f, "revenue must be positive", profit=p, revenue=r)
    return Metric(name, p / r, f, {"profit": p, "revenue": r})


def debt_to_equity(debt: float | None, equity: float | None) -> Metric:
    f = "debt / equity"
    if (m := _have(debt=debt, equity=equity)):
        return _unknown("Debt/Equity", f, m)
    d, e = _num(debt, "debt"), _num(equity, "equity")
    if e <= 0:
        return _unknown("Debt/Equity", f, "equity is zero or negative: the ratio is not meaningful", debt=d, equity=e)
    return Metric("Debt/Equity", d / e, f, {"debt": d, "equity": e})


def free_cash_flow(operating_cash_flow: float | None, capex: float | None) -> Metric:
    f = "operating cash flow - capital expenditure"
    if (m := _have(operating_cash_flow=operating_cash_flow, capex=capex)):
        return _unknown("Free cash flow", f, m)
    o, c = _num(operating_cash_flow, "operating_cash_flow"), _num(capex, "capex")
    return Metric("Free cash flow", o - abs(c), f, {"operating_cash_flow": o, "capex": abs(c)})


def _series(prices: Sequence[float], what: str = "prices") -> list[float]:
    if not isinstance(prices, (list, tuple)):
        raise InvalidFinanceInput(f"{what} must be a list of numbers")
    return [number(p, what, positive=True) for p in prices]


def max_drawdown(prices: Sequence[float]) -> Metric:
    f = "largest peak-to-trough decline of the given prices"
    p = _series(prices)
    if len(p) < 2:
        return _unknown("Max drawdown", f, "at least 2 prices are needed")
    peak, worst = p[0], 0.0
    for x in p:
        peak = max(peak, x)
        worst = min(worst, (x - peak) / peak)
    return Metric("Max drawdown", worst, f, {"points": float(len(p))})


def volatility(prices: Sequence[float], periods_per_year: int | None = None) -> Metric:
    f = "standard deviation of simple period returns" + (f" x sqrt({periods_per_year})" if periods_per_year else "")
    p = _series(prices)
    if len(p) < 3:
        return _unknown("Volatility", f, "at least 3 prices are needed")
    rets = [(b - a) / a for a, b in zip(p, p[1:])]
    v = statistics.stdev(rets)
    if periods_per_year is not None:
        if not isinstance(periods_per_year, int) or isinstance(periods_per_year, bool) or not 1 <= periods_per_year <= 366:
            raise InvalidFinanceInput("periods_per_year must be within 1..366")
        v *= math.sqrt(periods_per_year)
    return Metric("Volatility", v, f, {"returns": float(len(rets))})


def risk_reward(direction: Direction | str, entry: float, stop: float, target: float) -> Metric:
    f = "|target - entry| / |entry - stop|"
    e, s, t = number(entry, "entry", positive=True), number(stop, "stop", positive=True), number(target, "target", positive=True)
    d = direction if isinstance(direction, Direction) else Direction(str(direction).lower())
    ok = (s < e < t) if d is Direction.LONG else (t < e < s)
    if not ok:
        return _unknown("Risk/Reward", f, f"inconsistent levels for a {d.value}: long needs stop < entry < target, short needs target < entry < stop", entry=e, stop=s, target=t)
    return Metric("Risk/Reward", abs(t - e) / abs(e - s), f, {"entry": e, "stop": s, "target": t})


def position_size(account: float, risk_pct: float, entry: float, stop: float) -> Metric:
    f = "(account x risk%) / |entry - stop|"
    a, r = number(account, "account", positive=True), number(risk_pct, "risk_pct", positive=True)
    e, s = number(entry, "entry", positive=True), number(stop, "stop", positive=True)
    if r > 100:
        raise InvalidFinanceInput("risk_pct must be within 0..100")
    if e == s:
        return _unknown("Position size", f, "entry and stop must differ", account=a, risk_pct=r, entry=e, stop=s)
    return Metric("Position size", (a * r / 100.0) / abs(e - s), f, {"account": a, "risk_pct": r, "entry": e, "stop": s})
