"""E6: BudgetedProvider - the enforcing wrapper around any LLMProvider. Fakes only: no network, no real keys."""
from __future__ import annotations

import threading
from decimal import Decimal

import pytest

from jarvis.errors import LLMError
from jarvis.llm.base import LLMProvider, LLMRequest, LLMResponse, Message
from jarvis.llm.budgeted import BudgetedProvider, estimate_input_tokens
from jarvis.llm.cost_budget import CostBudget, CostBudgetLimits, PriceTable, make_price


class Fake(LLMProvider):
    name = "fake"

    def __init__(self, usage=None, fail=None):
        self.calls: list[LLMRequest] = []
        self.usage = {} if usage is None else usage
        self.fail = fail

    def complete(self, request):
        self.calls.append(request)
        if self.fail:
            raise self.fail
        return LLMResponse("antwort", model=request.model or "m", usage=self.usage)


class Stop:
    def __init__(self, engaged=False):
        self.engaged = engaged
        self.reason = "test"


def make(inner=None, *, stop=None, audit=None, prices=None, default_max=1024, **lim):
    base = dict(max_calls=30, max_input_tokens_per_call=50_000, max_output_tokens_per_call=2048, max_tokens_session=100_000, max_input_tokens_session=50_000)
    budget = CostBudget(CostBudgetLimits(**{**base, **lim}), prices)
    inner = inner or Fake()
    events = [] if audit is None else audit
    return BudgetedProvider(inner, budget, default_model="m", default_max_tokens=default_max, emergency=stop or Stop(), audit=events.append), inner, budget, events


def req(text="hallo", **kw):
    return LLMRequest([Message.user(text)], **kw)


def test_allowed_call_is_passed_through_one_to_one_and_booked():
    p, inner, b, _ = make(Fake(usage={"prompt_tokens": 12, "completion_tokens": 7}))
    r = req(max_tokens=100)
    out = p.complete(r)
    assert inner.calls == [r] and inner.calls[0] is r and out.content == "antwort"
    s = b.snapshot()
    assert (s.calls, s.input_tokens, s.output_tokens, s.unknown_calls) == (1, 12, 7, 0 + 1)  # no price -> cost unknown, tokens measured


def test_name_and_complete_text_use_the_same_path():
    p, inner, b, _ = make(Fake(), max_calls=1)
    assert p.name == "fake"
    assert p.complete_text("sys", "usr", max_tokens=50) == "antwort"
    with pytest.raises(LLMError, match="LLM-Budget"):
        p.complete_text("sys", "usr", max_tokens=50)
    assert len(inner.calls) == 1


def test_call_limit_is_the_thirty_default_style_hard_stop():
    p, inner, _, _ = make(max_calls=3)
    for _ in range(3):
        p.complete(req(max_tokens=10))
    with pytest.raises(LLMError, match="Aufrufe 3/3"):
        p.complete(req(max_tokens=10))
    assert len(inner.calls) == 3


def test_output_limit_comes_from_the_request_and_falls_back_to_the_configured_max_tokens():
    p, inner, _, _ = make(max_output_tokens_per_call=2048, default_max=4096)
    with pytest.raises(LLMError, match="Ausgabe-Token 4096"):
        p.complete(req())                      # max_tokens=None -> llm.max_tokens (4096) is what the provider would use
    with pytest.raises(LLMError, match="Ausgabe-Token 3000"):
        p.complete(req(max_tokens=3000))
    assert inner.calls == []
    p.complete(req(max_tokens=2048))
    assert len(inner.calls) == 1


def test_a_stricter_existing_limit_stays():
    p, inner, _, _ = make(max_output_tokens_per_call=2048, default_max=512)
    p.complete(req())
    assert inner.calls and inner.calls[0].max_tokens is None          # request is never rewritten


def test_input_estimate_is_chars_over_three_rounded_up_and_only_an_estimate():
    assert estimate_input_tokens([Message.user("a" * 9), Message.system("b" * 1)]) == 4
    assert estimate_input_tokens([]) == 0


def test_estimated_input_over_the_per_call_limit_is_refused_before_the_call():
    p, inner, _, _ = make(max_input_tokens_per_call=100)
    with pytest.raises(LLMError, match="Eingabe-Token"):
        p.complete(req("x" * 400, max_tokens=10))
    assert inner.calls == []


def test_session_token_limit_binds_without_usage_from_the_provider():
    p, inner, b, _ = make(max_tokens_session=300, max_input_tokens_session=300)
    p.complete(req("x" * 30, max_tokens=100))          # ~10 in + 100 out booked as estimate
    p.complete(req("x" * 30, max_tokens=100))
    with pytest.raises(LLMError, match="Sitzungs-Token"):
        p.complete(req("x" * 30, max_tokens=100))
    assert len(inner.calls) == 2
    assert b.snapshot().tokens >= 220


def test_session_input_limit_binds():
    p, inner, _, _ = make(max_input_tokens_session=50, max_tokens_session=100_000)
    p.complete(req("x" * 90, max_tokens=10))           # 30
    with pytest.raises(LLMError, match="Eingabe-Token der Sitzung"):
        p.complete(req("x" * 90, max_tokens=10))
    assert len(inner.calls) == 1


def test_cost_limit_with_missing_price_refuses_fail_closed():
    p, inner, _, _ = make(max_cost=Decimal(5))
    with pytest.raises(LLMError, match="Preis des Modells fehlt"):
        p.complete(req(max_tokens=10))
    assert inner.calls == []


def test_cost_limit_with_price_allows_until_the_limit_then_refuses():
    prices = PriceTable({"m": make_price("1", "1")})          # 1 per 1k tokens
    p, inner, b, _ = make(Fake(usage={"prompt_tokens": 1000, "completion_tokens": 1000}), prices=prices, max_cost=Decimal("2.05"))
    p.complete(req(max_tokens=100))
    with pytest.raises(LLMError, match="Kosten"):
        p.complete(req(max_tokens=100))
    assert b.snapshot().cost == Decimal(2) and len(inner.calls) == 1


def test_cost_limit_set_and_usage_unknown_blocks_the_next_call():
    prices = PriceTable({"m": make_price("1", "1")})
    p, inner, _, _ = make(Fake(usage={}), prices=prices, max_cost=Decimal("100"))
    p.complete(req(max_tokens=10))
    with pytest.raises(LLMError, match="unbekannte Kosten"):
        p.complete(req(max_tokens=10))


def test_without_a_cost_limit_there_is_no_cost_check():
    p, inner, _, _ = make()
    for _ in range(3):
        p.complete(req(max_tokens=10))
    assert len(inner.calls) == 3


def test_emergency_stop_refuses_before_anything_else_and_is_only_read():
    stop = Stop(engaged=True)
    p, inner, b, _ = make(stop=stop)
    with pytest.raises(LLMError, match="LLM-Budget: Not-Aus"):
        p.complete(req(max_tokens=10))
    assert inner.calls == [] and b.snapshot().calls == 0
    assert stop.engaged is True                                  # never reset, never touched


def test_a_failed_provider_call_is_still_counted_conservatively_and_reraised():
    p, inner, b, _ = make(Fake(fail=LLMError("boom")))
    with pytest.raises(LLMError, match="boom"):
        p.complete(req(max_tokens=100))
    s = b.snapshot()
    assert s.calls == 1 and s.output_tokens == 100


def test_refusal_message_and_audit_carry_no_prompt_answer_or_key():
    secret = "sk-SECRET-PROMPT-TEXT-xyz"
    p, _, _, events = make(max_calls=1)
    p.complete(req(secret, max_tokens=10))
    with pytest.raises(LLMError) as ei:
        p.complete(req(secret, max_tokens=10))
    assert secret not in str(ei.value) and str(ei.value).startswith("LLM-Budget")
    assert events and all(secret not in repr(e) for e in events)
    assert events[0]["reason"].startswith("LLM-Budget") and "calls" in events[0]


def test_denials_are_audited_once_and_counted():
    p, _, _, events = make(max_calls=1)
    p.complete(req(max_tokens=10))
    for _ in range(4):
        with pytest.raises(LLMError):
            p.complete(req(max_tokens=10))
    assert len(events) == 1 and p.status()["refused"] == 4


def test_no_retry_and_no_fallback_to_another_model():
    p, inner, _, _ = make(max_calls=1)
    p.complete(req(max_tokens=10, model="m"))
    with pytest.raises(LLMError):
        p.complete(req(max_tokens=10, model="other"))
    assert [c.model for c in inner.calls] == ["m"]


def test_status_reports_numbers_and_unknown():
    p, _, _, _ = make(Fake(usage={"prompt_tokens": 5, "completion_tokens": 5}))
    p.complete(req(max_tokens=10))
    st = p.status()
    assert st["calls"] == 1 and st["tokens"] == 10 and st["cost"] == "UNKNOWN" and st["cost_complete"] is False


def test_concurrent_callers_cannot_exceed_the_call_limit():
    p, inner, _, _ = make(max_calls=5)
    errors, ok = [], []
    def work():
        try:
            p.complete(req(max_tokens=10)); ok.append(1)
        except LLMError as e:
            errors.append(e)
    ts = [threading.Thread(target=work) for _ in range(20)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(ok) == 5 and len(errors) == 15 and len(inner.calls) == 5


def test_budget_cannot_be_raised_through_the_wrapper():
    p, _, b, _ = make()
    assert not hasattr(p, "raise_limit") and not hasattr(p, "reset")
    with pytest.raises(Exception):
        b.limits.max_calls = 10 ** 6                                  # frozen
