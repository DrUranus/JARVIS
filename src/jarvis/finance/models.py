"""Finance data model: metrics that are either COMPUTED from given data or UNKNOWN (never guessed), trade ideas, paper trades, risk assessments,
positions and portfolio snapshots. Everything is plain, finite, bounded and JSON-compatible. Nothing here can move money."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from jarvis.finance.errors import InvalidFinanceInput

_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,11}")


def symbol(value: object) -> str:
    """'aapl' -> 'AAPL'. Anything that is not a plausible ticker is refused (no spaces, no URLs, no commands)."""
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value.upper()):
        raise InvalidFinanceInput("a symbol is 1..12 characters of letters, digits, '.' or '-' (no spaces or line breaks)")
    return value.upper()


def number(value: object, what: str, *, positive: bool = False, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e15:
        raise InvalidFinanceInput(f"{what} must be a finite number")
    if positive and value <= 0:
        raise InvalidFinanceInput(f"{what} must be greater than zero")
    if non_negative and value < 0:
        raise InvalidFinanceInput(f"{what} must not be negative")
    return float(value)


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class Metric:
    name: str
    value: float | None
    formula: str = ""
    inputs: dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def status(self) -> str:
        return "COMPUTED" if self.value is not None else "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": None if self.value is None else round(self.value, 6), "status": self.status, "formula": self.formula,
                "inputs": dict(self.inputs), "note": self.note}


@dataclass(frozen=True)
class RiskLimits:
    """Limits a paper trade must respect - and that a later real-money layer would have to respect. There is no leverage and no withdrawal."""
    max_risk_per_trade_pct: float = 1.0
    max_position_pct: float = 20.0
    max_total_exposure_pct: float = 100.0
    daily_loss_limit_pct: float = 3.0
    max_leverage: float = 1.0
    allow_withdrawals: bool = False

    def __post_init__(self) -> None:
        if self.max_leverage != 1.0 or self.allow_withdrawals:
            raise InvalidFinanceInput("leverage and withdrawals do not exist in this version")
        for name in ("max_risk_per_trade_pct", "max_position_pct", "max_total_exposure_pct", "daily_loss_limit_pct"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or not 0 < v <= 100:
                raise InvalidFinanceInput(f"{name} must be within 0..100")


@dataclass(frozen=True)
class TradeIdea:
    symbol: str
    direction: Direction
    entry: float
    stop: float
    target: float
    position_size: float                 # units
    confidence: float                    # 0..1, the user's/analysis' own estimate - not a probability JARVIS verified
    thesis: str = field(default="", repr=False)
    invalidations: tuple[str, ...] = field(default=(), repr=False)
    timestamp: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", symbol(self.symbol))
        d = self.direction if isinstance(self.direction, Direction) else Direction(str(self.direction).lower())
        object.__setattr__(self, "direction", d)
        for f in ("entry", "stop", "target", "position_size"):
            object.__setattr__(self, f, number(getattr(self, f), f, positive=True))
        if self.direction is Direction.LONG and not (self.stop < self.entry < self.target):
            raise InvalidFinanceInput("a long idea needs stop < entry < target")
        if self.direction is Direction.SHORT and not (self.target < self.entry < self.stop):
            raise InvalidFinanceInput("a short idea needs target < entry < stop")
        c = number(self.confidence, "confidence", non_negative=True)
        if c > 1:
            raise InvalidFinanceInput("confidence must be within 0..1")
        object.__setattr__(self, "confidence", c)
        object.__setattr__(self, "thesis", str(self.thesis)[:500])
        object.__setattr__(self, "invalidations", tuple(str(i)[:200] for i in list(self.invalidations)[:10]))
        object.__setattr__(self, "timestamp", self.timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def risk_amount(self) -> float:
        return self.risk_per_unit * self.position_size

    @property
    def risk_reward(self) -> float:
        return abs(self.target - self.entry) / self.risk_per_unit

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "direction": self.direction.value, "entry": self.entry, "stop": self.stop, "target": self.target,
                "position_size": self.position_size, "risk_amount": round(self.risk_amount, 4), "risk_reward": round(self.risk_reward, 4),
                "confidence": self.confidence, "thesis": self.thesis, "invalidations": list(self.invalidations), "timestamp": self.timestamp,
                "status": "IDEA - nothing was ordered"}


@dataclass(frozen=True)
class RiskAssessment:
    ok: bool
    violations: tuple[str, ...] = ()
    risk_amount: float = 0.0
    risk_pct_of_account: float | None = None
    position_pct_of_account: float | None = None
    risk_reward: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "violations": list(self.violations), "risk_amount": round(self.risk_amount, 4),
                "risk_pct_of_account": None if self.risk_pct_of_account is None else round(self.risk_pct_of_account, 4),
                "position_pct_of_account": None if self.position_pct_of_account is None else round(self.position_pct_of_account, 4),
                "risk_reward": None if self.risk_reward is None else round(self.risk_reward, 4)}


@dataclass(frozen=True)
class PaperTrade:
    """A SIMULATED trade: an idea walked through a given price path. No order exists anywhere."""
    idea: TradeIdea
    outcome: str                        # target | stop | open | not_entered
    exit_price: float | None
    pnl: float
    bars: int = 0
    paper: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"idea": self.idea.to_dict(), "outcome": self.outcome, "exit_price": self.exit_price, "pnl": round(self.pnl, 4), "bars": self.bars,
                "paper": True, "note": "simulated on the given prices; no order was placed"}


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float
    average_price: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", symbol(self.symbol))
        object.__setattr__(self, "quantity", number(self.quantity, "quantity", positive=True))
        object.__setattr__(self, "average_price", number(self.average_price, "average_price", positive=True))

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "quantity": self.quantity, "average_price": self.average_price}


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: float
    positions: tuple[tuple[Position, float | None], ...]          # (position, mark price or None when unknown)
    timestamp: str = ""

    @property
    def market_value(self) -> float | None:
        if any(p is None for _, p in self.positions):
            return None
        return sum(pos.quantity * price for pos, price in self.positions if price is not None)

    def to_dict(self) -> dict[str, Any]:
        mv = self.market_value
        rows = []
        for pos, price in self.positions:
            rows.append({**pos.to_dict(), "mark": price, "value": None if price is None else round(pos.quantity * price, 4),
                         "unrealized_pnl": None if price is None else round((price - pos.average_price) * pos.quantity, 4),
                         "status": "COMPUTED" if price is not None else "UNKNOWN"})
        return {"cash": self.cash, "positions": rows, "market_value": None if mv is None else round(mv, 4),
                "equity": None if mv is None else round(mv + self.cash, 4), "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "paper": True}
