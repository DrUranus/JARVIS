"""Paper trading: simulate an idea on a GIVEN price path, check it against the risk limits, take a portfolio snapshot. Pure arithmetic on the data
passed in - there is no broker, no order object and no connection to anything."""
from __future__ import annotations

from typing import Mapping, Sequence

from jarvis.finance.errors import InvalidFinanceInput
from jarvis.finance.models import (Direction, PaperTrade, PortfolioSnapshot, Position, RiskAssessment, RiskLimits, TradeIdea, number)


def assess(idea: TradeIdea, account: float | None, limits: RiskLimits, open_exposure: float = 0.0) -> RiskAssessment:
    """Does the idea respect the limits? With an unknown account size the percent checks are UNKNOWN (not passed silently): ok=False."""
    violations: list[str] = []
    if account is None:
        return RiskAssessment(False, ("the account size is unknown: the risk limits cannot be checked",), idea.risk_amount, None, None, idea.risk_reward)
    acc = number(account, "account", positive=True)
    risk_pct = idea.risk_amount / acc * 100.0
    pos_value = idea.entry * idea.position_size
    pos_pct = pos_value / acc * 100.0
    if risk_pct > limits.max_risk_per_trade_pct:
        violations.append(f"risk {risk_pct:.2f}% of the account exceeds the limit of {limits.max_risk_per_trade_pct:g}% per trade")
    if pos_pct > limits.max_position_pct:
        violations.append(f"position {pos_pct:.1f}% of the account exceeds the limit of {limits.max_position_pct:g}%")
    if (open_exposure + pos_value) / acc * 100.0 > limits.max_total_exposure_pct:
        violations.append(f"total exposure would exceed {limits.max_total_exposure_pct:g}% of the account (no leverage)")
    return RiskAssessment(not violations, tuple(violations), idea.risk_amount, risk_pct, pos_pct, idea.risk_reward)


def simulate(idea: TradeIdea, prices: Sequence[float | Mapping[str, float]]) -> PaperTrade:
    """Walk the idea through the bars. A bar is a close price or {"high": h, "low": l}. The entry must be touched first; within one bar a stop that is
    hit counts before a target (the conservative reading). Result: target | stop | open | not_entered."""
    if not isinstance(prices, (list, tuple)) or not prices:
        raise InvalidFinanceInput("prices must be a non-empty list")
    bars: list[tuple[float, float]] = []
    for b in prices:
        if isinstance(b, Mapping):
            hi, lo = number(b.get("high"), "high", positive=True), number(b.get("low"), "low", positive=True)
            if lo > hi:
                raise InvalidFinanceInput("a bar's low must not exceed its high")
        else:
            hi = lo = number(b, "price", positive=True)
        bars.append((hi, lo))
    long = idea.direction is Direction.LONG
    entered = False
    for i, (hi, lo) in enumerate(bars, 1):
        if not entered:
            if lo <= idea.entry <= hi:
                entered = True
            else:
                continue
        stop_hit = lo <= idea.stop if long else hi >= idea.stop
        target_hit = hi >= idea.target if long else lo <= idea.target
        if stop_hit:
            return PaperTrade(idea, "stop", idea.stop, _pnl(idea, idea.stop), i)
        if target_hit:
            return PaperTrade(idea, "target", idea.target, _pnl(idea, idea.target), i)
    if not entered:
        return PaperTrade(idea, "not_entered", None, 0.0, len(bars))
    last = bars[-1][0] if bars[-1][0] == bars[-1][1] else (bars[-1][0] + bars[-1][1]) / 2
    return PaperTrade(idea, "open", last, _pnl(idea, last), len(bars))


def _pnl(idea: TradeIdea, exit_price: float) -> float:
    move = exit_price - idea.entry if idea.direction is Direction.LONG else idea.entry - exit_price
    return move * idea.position_size


def snapshot(cash: float, positions: Sequence[Position], marks: Mapping[str, float]) -> PortfolioSnapshot:
    c = number(cash, "cash", non_negative=True)
    rows = []
    for p in positions:
        m = marks.get(p.symbol)
        rows.append((p, None if m is None else number(m, f"mark of {p.symbol}", positive=True)))
    return PortfolioSnapshot(c, tuple(rows))


def daily_loss_exceeded(trades: Sequence[PaperTrade], account: float, limits: RiskLimits) -> bool:
    acc = number(account, "account", positive=True)
    loss = -sum(t.pnl for t in trades if t.pnl < 0)
    return loss / acc * 100.0 >= limits.daily_loss_limit_pct
