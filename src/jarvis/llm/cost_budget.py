"""WP02a (S-5): token and cost budget - pure data models and calculations. NOT enforced, NOT wired.

Nothing here wraps a provider, reads the configuration, touches the emergency stop or the permission engine; no production module imports it (a layering test keeps it that
way until an owner-approved wiring step). It answers three questions deterministically and without I/O:
  * what did a call use?  (`parse_usage` - provider usage dicts, defensive; missing or malformed numbers are UNKNOWN, never guessed)
  * what did it cost?     (`compute_cost` - exact `Decimal` arithmetic with an owner-maintained price table; no price or no token counts -> UNKNOWN (None))
  * may the next call happen? (`CostBudget.check` - call count, per-call token limits, session tokens, optional cost limit; FAIL-CLOSED when a cost limit is set but the
    price or an earlier cost is unknown)
Limits are frozen, have hard caps in code and no way to be raised at runtime; a new `CostBudget` is a new session. Nothing is persisted. Audit events carry numbers only.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Mapping

UNKNOWN = "UNKNOWN"
MAX_CALLS_HARD = 100_000
MAX_TOKENS_CALL_HARD = 1_000_000
MAX_TOKENS_SESSION_HARD = 1_000_000_000
MAX_COST_HARD = Decimal(1_000_000)
MAX_PRICE_PER_1K = Decimal(1_000_000)
_TOKEN_SANITY = 1_000_000_000_000      # a reported count above this is treated as malformed (UNKNOWN)
_PREC = 60
_KILO = Decimal(1000)


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _TOKEN_SANITY:
        return None
    return value


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def known(self) -> bool:
        return self.input_tokens is not None and self.output_tokens is not None


def parse_usage(usage: Any) -> TokenUsage:
    """Reads a provider `usage` mapping (OpenAI-style `prompt_tokens`/`completion_tokens` or `input_tokens`/`output_tokens`). A lone `total_tokens` is NOT split."""
    if isinstance(usage, TokenUsage):
        return usage
    if not isinstance(usage, Mapping):
        return TokenUsage()
    inp = _count(usage.get("prompt_tokens", usage.get("input_tokens")))
    out = _count(usage.get("completion_tokens", usage.get("output_tokens")))
    return TokenUsage(inp, out)


def _decimal(value: Any, what: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a number")
    try:
        if isinstance(value, Decimal):
            d = value
        elif isinstance(value, int):
            d = Decimal(value)
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"{what} must be finite")
            d = Decimal(str(value))
        elif isinstance(value, str):
            d = Decimal(value.strip())
        else:
            raise ValueError(f"{what} must be a number")
    except InvalidOperation:
        raise ValueError(f"{what} is not a valid number") from None
    if not d.is_finite():
        raise ValueError(f"{what} must be finite")
    return d


@dataclass(frozen=True)
class ModelPrice:
    input_per_1k: Decimal
    output_per_1k: Decimal


def make_price(input_per_1k: Any, output_per_1k: Any) -> ModelPrice:
    prices = []
    for name, v in (("input_per_1k", input_per_1k), ("output_per_1k", output_per_1k)):
        d = _decimal(v, name)
        if d < 0 or d > MAX_PRICE_PER_1K:
            raise ValueError(f"{name} must be between 0 and {MAX_PRICE_PER_1K}")
        prices.append(d)
    return ModelPrice(prices[0], prices[1])


def _model_label(model: Any) -> str:
    if isinstance(model, str) and 0 < len(model) <= 200 and not any(ord(c) < 32 for c in model):
        return model
    return "unbekannt"


class PriceTable:
    """Owner-maintained prices (currency-agnostic units per 1000 tokens). Unknown model -> None (cost UNKNOWN); nothing is estimated."""

    def __init__(self, prices: Mapping[str, ModelPrice] | None = None) -> None:
        self._prices = dict(prices or {})

    @classmethod
    def from_mapping(cls, data: Any) -> "PriceTable":
        if not isinstance(data, Mapping):
            raise ValueError("prices must be a mapping model -> {input_per_1k, output_per_1k}")
        out: dict[str, ModelPrice] = {}
        for model, entry in data.items():
            if not isinstance(model, str) or _model_label(model) != model:
                raise ValueError("model names must be non-empty text")
            if not isinstance(entry, Mapping) or set(entry) != {"input_per_1k", "output_per_1k"}:
                raise ValueError(f"price of {model!r} needs exactly input_per_1k and output_per_1k")
            out[model] = make_price(entry["input_per_1k"], entry["output_per_1k"])
        return cls(out)

    def get(self, model: Any) -> ModelPrice | None:
        return self._prices.get(model) if isinstance(model, str) else None


def compute_cost(usage: TokenUsage, price: ModelPrice | None) -> Decimal | None:
    """Exact cost, or None (UNKNOWN) without a price or without BOTH token counts."""
    if price is None or not usage.known:
        return None
    with localcontext() as ctx:
        ctx.prec = _PREC
        return Decimal(usage.input_tokens) * price.input_per_1k / _KILO + Decimal(usage.output_tokens) * price.output_per_1k / _KILO


def _limit_int(name: str, value: Any, hard: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= hard:
        raise ValueError(f"{name} must be a whole number between 1 and {hard}")
    return value


@dataclass(frozen=True)
class CostBudgetLimits:
    max_calls: int
    max_input_tokens_per_call: int
    max_output_tokens_per_call: int
    max_tokens_session: int
    max_cost: Decimal | None = None

    def __post_init__(self) -> None:
        _limit_int("max_calls", self.max_calls, MAX_CALLS_HARD)
        _limit_int("max_input_tokens_per_call", self.max_input_tokens_per_call, MAX_TOKENS_CALL_HARD)
        _limit_int("max_output_tokens_per_call", self.max_output_tokens_per_call, MAX_TOKENS_CALL_HARD)
        _limit_int("max_tokens_session", self.max_tokens_session, MAX_TOKENS_SESSION_HARD)
        if self.max_cost is not None:
            d = _decimal(self.max_cost, "max_cost")
            if not 0 < d <= MAX_COST_HARD:
                raise ValueError(f"max_cost must be greater than 0 and at most {MAX_COST_HARD}")
            object.__setattr__(self, "max_cost", d)

    _KEYS = ("max_calls", "max_input_tokens_per_call", "max_output_tokens_per_call", "max_tokens_session")

    @classmethod
    def from_mapping(cls, data: Any) -> "CostBudgetLimits":
        if not isinstance(data, Mapping):
            raise ValueError("limits must be a mapping")
        unknown = set(data) - set(cls._KEYS) - {"max_cost"}
        missing = [k for k in cls._KEYS if k not in data]
        if unknown or missing:
            raise ValueError(f"limits: unknown keys {sorted(map(str, unknown))} / missing {missing}")
        return cls(*(data[k] for k in cls._KEYS), max_cost=data.get("max_cost"))


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class Booking:
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cost: Decimal | None

    def event(self) -> dict[str, Any]:
        """Audit event: numbers only (UNKNOWN where unknown) - never prompts, answers or keys."""
        return {"event": "llm_usage", "model": self.model,
                "input_tokens": UNKNOWN if self.input_tokens is None else self.input_tokens,
                "output_tokens": UNKNOWN if self.output_tokens is None else self.output_tokens,
                "cost": UNKNOWN if self.cost is None else format(self.cost.normalize(), "f")}


@dataclass(frozen=True)
class Snapshot:
    calls: int
    input_tokens: int
    output_tokens: int
    cost: Decimal                 # sum of the KNOWN costs
    unknown_calls: int            # calls whose cost is unknown

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_complete(self) -> bool:
        return self.unknown_calls == 0


class CostBudget:
    """One session's budget. Thread-safe. No setter, no reset, no way to raise a limit."""

    def __init__(self, limits: CostBudgetLimits, prices: PriceTable | None = None) -> None:
        if not isinstance(limits, CostBudgetLimits):
            raise ValueError("limits must be CostBudgetLimits")
        self.limits = limits
        self._prices = prices or PriceTable()
        self._lock = threading.Lock()
        self._calls = self._in = self._out = self._unknown = 0
        self._cost = Decimal(0)

    @staticmethod
    def _plan(value: Any) -> int | None:
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def check(self, model: Any, *, input_tokens: int | None = None, max_output_tokens: int | None = None) -> Decision:
        """May the next call happen? Books nothing. Unknown planned numbers (None) are not guessed; the booking after the call decides then."""
        inp, out = self._plan(input_tokens), self._plan(max_output_tokens)
        if inp is None or out is None:
            return Decision(False, "LLM-Budget: ungültiger Planwert für Token")
        lim = self.limits
        with self._lock:
            if self._calls >= lim.max_calls:
                return Decision(False, f"LLM-Budget erschöpft: Aufrufe {self._calls}/{lim.max_calls}")
            if inp > lim.max_input_tokens_per_call:
                return Decision(False, f"LLM-Budget: Eingabe-Token {inp} über dem Limit {lim.max_input_tokens_per_call} je Aufruf")
            if out > lim.max_output_tokens_per_call:
                return Decision(False, f"LLM-Budget: Ausgabe-Token {out} über dem Limit {lim.max_output_tokens_per_call} je Aufruf")
            tokens = self._in + self._out
            if tokens >= lim.max_tokens_session or tokens + inp + out > lim.max_tokens_session:
                return Decision(False, f"LLM-Budget: Sitzungs-Token {tokens}+{inp + out} über dem Limit {lim.max_tokens_session}")
            if lim.max_cost is not None:
                price = self._prices.get(model)
                if price is None:
                    return Decision(False, "LLM-Budget: Kostenlimit gesetzt, aber der Preis des Modells fehlt (fail-closed)")
                if self._unknown:
                    return Decision(False, f"LLM-Budget: Kostenlimit gesetzt, aber {self._unknown} frühere Aufrufe haben unbekannte Kosten (fail-closed)")
                with localcontext() as ctx:
                    ctx.prec = _PREC
                    worst = Decimal(inp) * price.input_per_1k / _KILO + Decimal(out) * price.output_per_1k / _KILO
                    if self._cost >= lim.max_cost or self._cost + worst > lim.max_cost:
                        return Decision(False, f"LLM-Budget: Kosten {self._cost}+{worst} über dem Limit {lim.max_cost}")
        return Decision(True)

    def record(self, model: Any, usage: Any) -> Booking:
        """Books one finished call (always counted, even without usage). Malformed numbers are UNKNOWN and never reduce a counter."""
        u = parse_usage(usage)
        label = _model_label(model)
        cost = compute_cost(u, self._prices.get(label))
        with self._lock:
            self._calls += 1
            self._in += u.input_tokens or 0
            self._out += u.output_tokens or 0
            if cost is None:
                self._unknown += 1
            else:
                self._cost += cost
        return Booking(label, u.input_tokens, u.output_tokens, cost)

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(self._calls, self._in, self._out, self._cost, self._unknown)
