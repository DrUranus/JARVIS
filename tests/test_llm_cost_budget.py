"""WP02a (S-5): Token- und Kostenbudget - reine Datenmodelle und Berechnungen, NICHT durchgesetzt und NICHT verdrahtet.

Kein Provider-Wrapper, keine Konfiguration, kein Notaus-Eingriff: nur Modelle (Nutzung, Preis, Grenzen, Buchung) mit exakter Dezimalrechnung, UNKNOWN statt Schaetzung und
Fail-closed-Pruefung. Reine Logik, kein Netzwerk, keine Datei, keine Plattformabhaengigkeit."""
from __future__ import annotations

import ast
import dataclasses
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from jarvis.llm import cost_budget as cb
from jarvis.llm.cost_budget import (UNKNOWN, CostBudget, CostBudgetLimits, ModelPrice, PriceTable, TokenUsage, compute_cost, make_price, parse_usage)

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
MODULE = SRC / "llm" / "cost_budget.py"


def limits(**kw):
    base = dict(max_calls=5, max_input_tokens_per_call=1000, max_output_tokens_per_call=500, max_tokens_session=3000)
    base.update(kw)
    return CostBudgetLimits(**base)


# ---- Nutzung lesen ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("usage,expected", [
    ({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, (10, 5)),
    ({"input_tokens": 7, "output_tokens": 3}, (7, 3)),
    ({"prompt_tokens": 10}, (10, None)),
    ({"total_tokens": 15}, (None, None)),
    ({}, (None, None)), (None, (None, None)), ("x", (None, None)), ([], (None, None)),
    ({"prompt_tokens": -1, "completion_tokens": 2}, (None, 2)),
    ({"prompt_tokens": True, "completion_tokens": "5"}, (None, None)),
    ({"prompt_tokens": 1.5, "completion_tokens": float("nan")}, (None, None)),
    ({"prompt_tokens": 10**13, "completion_tokens": 1}, (None, 1)),
])
def test_usage_is_read_defensively_and_unknown_is_not_guessed(usage, expected):
    u = parse_usage(usage)
    assert (u.input_tokens, u.output_tokens) == expected


def test_total_tokens_alone_does_not_split_into_input_and_output():
    u = parse_usage({"total_tokens": 100})
    assert u.input_tokens is None and u.output_tokens is None and not u.known


# ---- Preise und Kosten ------------------------------------------------------------------------------------------------------------------------------
def test_prices_accept_text_numbers_and_decimals_but_nothing_else():
    p = make_price("0.5", 1.5)
    assert p == ModelPrice(Decimal("0.5"), Decimal("1.5"))
    for bad in (-1, "-0.1", "abc", None, True, float("inf"), float("nan"), Decimal("NaN"), Decimal("Infinity"), [1], {"a": 1}, 10**12):
        with pytest.raises(ValueError):
            make_price(bad, 1)
    with pytest.raises(ValueError):
        make_price(1, bad)


def test_costs_are_exact_decimals_not_floats():
    price = make_price("0.1", "0.2")
    assert compute_cost(TokenUsage(1000, 1000), price) == Decimal("0.3")           # mit Gleitkomma waere 0.30000000000000004
    assert compute_cost(TokenUsage(500, 250), make_price(2, 4)) == Decimal("2")     # 0.5*2 + 0.25*4
    assert compute_cost(TokenUsage(0, 0), price) == Decimal("0")


def test_cost_is_unknown_without_a_price_or_without_both_token_counts():
    assert compute_cost(TokenUsage(10, 10), None) is None
    assert compute_cost(TokenUsage(10, None), make_price(1, 1)) is None
    assert compute_cost(TokenUsage(None, 10), make_price(1, 1)) is None
    assert compute_cost(TokenUsage(None, None), make_price(1, 1)) is None


def test_price_table_from_mapping_and_unknown_models():
    t = PriceTable.from_mapping({"m1": {"input_per_1k": "1", "output_per_1k": "2"}})
    assert t.get("m1") == make_price(1, 2) and t.get("other") is None and t.get(None) is None
    for bad in ({"m": {"input_per_1k": 1}}, {"m": {"input_per_1k": 1, "output_per_1k": 1, "extra": 1}}, {"": {"input_per_1k": 1, "output_per_1k": 1}},
                {"m": 5}, {5: {"input_per_1k": 1, "output_per_1k": 1}}, "x"):
        with pytest.raises(ValueError):
            PriceTable.from_mapping(bad)


# ---- Grenzen ----------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [
    ("max_calls", 0), ("max_calls", -1), ("max_calls", True), ("max_calls", 1.5), ("max_calls", cb.MAX_CALLS_HARD + 1),
    ("max_input_tokens_per_call", 0), ("max_input_tokens_per_call", cb.MAX_TOKENS_CALL_HARD + 1),
    ("max_output_tokens_per_call", -5), ("max_tokens_session", 0), ("max_tokens_session", cb.MAX_TOKENS_SESSION_HARD + 1),
    ("max_cost", Decimal("-1")), ("max_cost", Decimal("NaN")), ("max_cost", "abc"), ("max_cost", 0),
])
def test_limits_reject_nonsense_and_values_above_the_hard_caps(field, value):
    with pytest.raises(ValueError):
        limits(**{field: value})


def test_limits_from_mapping_rejects_unknown_and_missing_keys():
    ok = {"max_calls": 3, "max_input_tokens_per_call": 10, "max_output_tokens_per_call": 10, "max_tokens_session": 100}
    assert CostBudgetLimits.from_mapping(ok).max_calls == 3
    for bad in ({**ok, "max_calls_x": 1}, {k: v for k, v in ok.items() if k != "max_calls"}, "x", None, {**ok, "max_cost": "bad"}):
        with pytest.raises(ValueError):
            CostBudgetLimits.from_mapping(bad)


def test_limits_cannot_be_raised_afterwards():
    b = CostBudget(limits())
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.limits.max_calls = 10**6          # type: ignore[misc]
    assert not any(hasattr(b, n) for n in ("set_limits", "raise_limits", "reset", "increase", "limits_override"))


# ---- Vorabpruefung und Buchung ----------------------------------------------------------------------------------------------------------------------
def test_check_allows_within_limits_and_refuses_per_call_limits():
    b = CostBudget(limits())
    assert b.check("m", input_tokens=1000, max_output_tokens=500).allowed
    d = b.check("m", input_tokens=1001)
    assert not d.allowed and "Eingabe" in d.reason
    d = b.check("m", max_output_tokens=501)
    assert not d.allowed and "Ausgabe" in d.reason
    assert not b.check("m", input_tokens=-1).allowed and not b.check("m", input_tokens=True).allowed       # unsinnige Planwerte: abgelehnt
    assert b.check("m").allowed                                                                              # ohne Planwerte entscheidet die Buchung danach


def test_calls_are_counted_even_without_usage_and_the_call_limit_is_final():
    b = CostBudget(limits(max_calls=2))
    for _ in range(2):
        assert b.check("m").allowed
        b.record("m", None)                                                    # Anbieter lieferte keine Nutzung
    d = b.check("m")
    assert not d.allowed and "Aufrufe" in d.reason
    s = b.snapshot()
    assert s.calls == 2 and s.unknown_calls == 2 and s.tokens == 0


def test_session_token_limit_uses_booked_and_planned_tokens():
    b = CostBudget(limits(max_tokens_session=1500))
    b.record("m", {"prompt_tokens": 800, "completion_tokens": 400})            # 1200 gebucht
    assert b.check("m", input_tokens=200, max_output_tokens=100).allowed        # 1200 + 300 = 1500
    d = b.check("m", input_tokens=200, max_output_tokens=101)
    assert not d.allowed and "Token" in d.reason
    b.record("m", {"prompt_tokens": 200, "completion_tokens": 100})
    assert not b.check("m").allowed                                            # erschoepft


def test_record_returns_a_booking_with_unknown_instead_of_estimates():
    b = CostBudget(limits(), PriceTable.from_mapping({"known": {"input_per_1k": 1, "output_per_1k": 2}}))
    k = b.record("known", {"prompt_tokens": 1000, "completion_tokens": 500})
    assert k.cost == Decimal("2") and k.input_tokens == 1000 and k.output_tokens == 500
    u = b.record("other", {"prompt_tokens": 10, "completion_tokens": 10})
    assert u.cost is None
    n = b.record("known", {"total_tokens": 99})
    assert n.cost is None and n.input_tokens is None
    s = b.snapshot()
    assert s.calls == 3 and s.cost == Decimal("2") and not s.cost_complete and s.unknown_calls == 2


def test_cost_limit_fails_closed_when_the_price_is_missing():
    b = CostBudget(limits(max_cost=Decimal("1")), PriceTable.from_mapping({"known": {"input_per_1k": 1, "output_per_1k": 1}}))
    d = b.check("other", input_tokens=10)
    assert not d.allowed and "Preis" in d.reason
    assert b.check("known", input_tokens=100, max_output_tokens=100).allowed


def test_cost_limit_uses_worst_case_of_the_planned_call_and_booked_cost():
    b = CostBudget(limits(max_cost=Decimal("1")), PriceTable.from_mapping({"m": {"input_per_1k": 1, "output_per_1k": 1}}))
    assert b.check("m", input_tokens=500, max_output_tokens=500).allowed                 # 1.0 genau am Limit
    assert not b.check("m", input_tokens=500, max_output_tokens=501).allowed             # 1.001 > 1
    b.record("m", {"prompt_tokens": 600, "completion_tokens": 400})                      # 1.0 gebucht
    d = b.check("m")
    assert not d.allowed and "Kosten" in d.reason


def test_cost_limit_without_planned_tokens_still_stops_at_exhaustion():
    b = CostBudget(limits(max_cost=Decimal("0.5")), PriceTable.from_mapping({"m": {"input_per_1k": 1, "output_per_1k": 0}}))
    assert b.check("m").allowed
    b.record("m", {"prompt_tokens": 500, "completion_tokens": 0})
    assert not b.check("m").allowed


def test_cost_limit_fails_closed_after_a_call_with_unknown_cost():
    b = CostBudget(limits(max_cost=Decimal("10")), PriceTable.from_mapping({"m": {"input_per_1k": 1, "output_per_1k": 1}}))
    assert b.check("m", input_tokens=10, max_output_tokens=10).allowed
    b.record("m", None)                                                         # Anbieter lieferte keine Nutzung -> Kosten unbekannt
    d = b.check("m", input_tokens=10, max_output_tokens=10)
    assert not d.allowed and "unbekannte Kosten" in d.reason


def test_negative_or_wrong_typed_bookings_do_not_reduce_the_counters():
    b = CostBudget(limits())
    b.record("m", {"prompt_tokens": -500, "completion_tokens": -500})
    b.record(None, {"prompt_tokens": 5, "completion_tokens": 5})                          # Modell fehlt: gebucht unter "unbekannt"
    s = b.snapshot()
    assert s.calls == 2 and s.tokens == 10 and s.input_tokens == 5


def test_bookings_are_thread_safe():
    b = CostBudget(limits(max_calls=10_000, max_tokens_session=10**9))
    def work():
        for _ in range(100):
            b.record("m", {"prompt_tokens": 1, "completion_tokens": 2})
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    s = b.snapshot()
    assert s.calls == 800 and s.input_tokens == 800 and s.output_tokens == 1600


def test_audit_event_has_numbers_only_never_content():
    b = CostBudget(limits(), PriceTable.from_mapping({"m": {"input_per_1k": 1, "output_per_1k": 1}}))
    e = b.record("m", {"prompt_tokens": 1000, "completion_tokens": 1000}).event()
    assert e == {"event": "llm_usage", "model": "m", "input_tokens": 1000, "output_tokens": 1000, "cost": "2"}
    u = b.record("x", {}).event()
    assert u["input_tokens"] == UNKNOWN and u["output_tokens"] == UNKNOWN and u["cost"] == UNKNOWN
    assert set(e) == {"event", "model", "input_tokens", "output_tokens", "cost"}


def test_snapshot_is_immutable_and_independent():
    b = CostBudget(limits())
    s = b.snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.calls = 5                                                            # type: ignore[misc]
    b.record("m", {"prompt_tokens": 1, "completion_tokens": 1})
    assert s.calls == 0 and b.snapshot().calls == 1


# ---- Struktur: unverdrahtet, rein ---------------------------------------------------------------------------------------------------------------------
def test_module_is_pure_and_money_never_uses_float_arithmetic():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {x.name.split(".")[0] for x in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert not (mods & {"os", "pathlib", "subprocess", "socket", "http", "urllib", "requests", "httpx", "shutil", "sqlite3", "asyncio", "time", "datetime"}), mods
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "float" not in calls and not (calls & {"open", "exec", "eval"})


def test_only_the_approved_e6_modules_import_it():
    allowed = {MODULE, SRC / "llm" / "budgeted.py", SRC / "config.py", SRC / "bootstrap.py"}          # E6: wrapper, its settings conversion, the composition root
    for path in SRC.rglob("*.py"):
        if path in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        assert "llm.cost_budget" not in text and "from jarvis.llm import cost_budget" not in text, path
