"""E6: CostBudget.record_estimated and the optional session limit for estimated input tokens (additive; nothing else about CostBudget changes)."""
from __future__ import annotations

import threading
from decimal import Decimal

import pytest

from jarvis.llm.cost_budget import CostBudget, CostBudgetLimits, PriceTable, make_price

LIM = dict(max_calls=30, max_input_tokens_per_call=50_000, max_output_tokens_per_call=2048, max_tokens_session=100_000)


def budget(**kw):
    prices = kw.pop("prices", None)
    return CostBudget(CostBudgetLimits(**{**LIM, **kw}), prices)


def test_estimated_booking_counts_the_planned_maximum_and_marks_cost_unknown():
    b = budget()
    booking = b.record_estimated("m", 1000, 500)
    s = b.snapshot()
    assert (s.calls, s.input_tokens, s.output_tokens) == (1, 1000, 500)
    assert s.unknown_calls == 1 and not s.cost_complete
    assert booking.cost is None and booking.input_tokens == 1000 and booking.output_tokens == 500


def test_session_token_limit_binds_even_when_the_provider_reports_no_usage():
    b = budget(max_tokens_session=5000)
    b.record_estimated("m", 2000, 1000)
    b.record_estimated("m", 1500, 400)
    assert b.check("m", input_tokens=100, max_output_tokens=100).allowed is False
    assert "Sitzungs-Token" in b.check("m", input_tokens=100, max_output_tokens=100).reason


def test_estimates_never_overwrite_or_reduce_measured_values():
    b = budget()
    b.record("m", {"prompt_tokens": 700, "completion_tokens": 300})
    b.record_estimated("m", 10, 10)
    s = b.snapshot()
    assert (s.input_tokens, s.output_tokens, s.calls) == (710, 310, 2)


@pytest.mark.parametrize("bad", [(-1, 5), (5, -1), (True, 5), (5, 1.5), ("5", 5), (None, 5)])
def test_estimated_with_malformed_plan_values_books_nothing_wrong(bad):
    b = budget()
    b.record_estimated("m", *bad)
    s = b.snapshot()
    assert s.calls == 1 and s.input_tokens >= 0 and s.output_tokens >= 0       # the call is counted; a malformed number never reduces a counter
    assert s.unknown_calls == 1


def test_with_a_cost_limit_an_estimated_call_blocks_the_next_one_fail_closed():
    prices = PriceTable({"m": make_price("1", "2")})
    b = budget(max_cost=Decimal(100), prices=prices)
    assert b.check("m", input_tokens=10, max_output_tokens=10).allowed
    b.record_estimated("m", 10, 10)
    d = b.check("m", input_tokens=10, max_output_tokens=10)
    assert d.allowed is False and "unbekannte Kosten" in d.reason


def test_input_session_limit_is_optional_and_counts_estimated_and_measured_inputs():
    b = budget(max_input_tokens_session=1000)
    assert b.check("m", input_tokens=900, max_output_tokens=10).allowed
    b.record_estimated("m", 600, 10)
    b.record("m", {"input_tokens": 300, "output_tokens": 5})
    d = b.check("m", input_tokens=200, max_output_tokens=10)
    assert d.allowed is False and "Eingabe-Token der Sitzung" in d.reason
    assert budget().check("m", input_tokens=40_000, max_output_tokens=10).allowed          # unset: no session input limit


@pytest.mark.parametrize("bad", [0, -5, True, 1.5, "7", 2_000_000_000])
def test_input_session_limit_is_validated(bad):
    with pytest.raises(ValueError):
        budget(max_input_tokens_session=bad)


def test_from_mapping_accepts_the_new_optional_key():
    lim = CostBudgetLimits.from_mapping({**LIM, "max_input_tokens_session": 50_000})
    assert lim.max_input_tokens_session == 50_000


def test_estimated_booking_is_thread_safe():
    b = budget(max_calls=100_000, max_tokens_session=1_000_000_000)
    def work():
        for _ in range(500):
            b.record_estimated("m", 3, 2)
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    s = b.snapshot()
    assert (s.calls, s.input_tokens, s.output_tokens) == (4000, 12000, 8000)
