"""E6: [llm_budget] configuration - additive, OFF by default, validated fail-closed."""
from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.config import ConfigError, LlmBudgetSettings, Settings, load_settings


def toml(tmp_path, body):
    f = tmp_path / "c.toml"
    f.write_text(body, encoding="utf-8")
    return f


def test_defaults_are_off_and_the_owner_development_values():
    s = Settings()
    b = s.llm_budget
    assert b == LlmBudgetSettings() and b.enabled is False
    assert (b.max_calls, b.max_output_tokens_per_call, b.max_input_tokens_session, b.max_tokens_session) == (30, 2048, 50_000, 100_000)
    assert b.max_input_tokens_per_call == 50_000 and b.max_cost == "" and b.prices == ()
    s.validate()


def test_shipped_jarvis_toml_keeps_it_off(tmp_path):
    from pathlib import Path
    cfg = Path(__file__).resolve().parent.parent / "config" / "jarvis.toml"
    assert load_settings(cfg, env={}).llm_budget.enabled is False


def test_loads_from_toml_and_env(tmp_path):
    f = toml(tmp_path, '[llm_budget]\nenabled = true\nmax_calls = 10\nmax_cost = "2.50"\nprices = ["m;0.001;0.002"]\n')
    s = load_settings(f, env={})
    assert s.llm_budget.enabled and s.llm_budget.max_calls == 10 and s.llm_budget.max_cost == "2.50" and s.llm_budget.prices == ("m;0.001;0.002",)
    assert load_settings(env={"JARVIS_LLM_BUDGET_ENABLED": "true"}).llm_budget.enabled is True


@pytest.mark.parametrize("field,value", [
    ("max_calls", 0), ("max_calls", 100_001), ("max_calls", -1),
    ("max_input_tokens_per_call", 0), ("max_output_tokens_per_call", 1_000_001),
    ("max_input_tokens_session", 0), ("max_tokens_session", 1_000_000_001),
    ("max_cost", "abc"), ("max_cost", "-1"), ("max_cost", "0"), ("max_cost", "1e400"), ("max_cost", "1000001"), ("max_cost", "NaN"),
    ("prices", ("m;1",)), ("prices", ("m;a;b",)), ("prices", ("m;-1;1",)), ("prices", (";1;1",)), ("prices", ("m;1;1", "m;2;2")), ("prices", ("m;NaN;1",)),
])
def test_invalid_values_are_rejected(field, value):
    s = replace(Settings(), llm_budget=replace(LlmBudgetSettings(), **{field: value}))
    with pytest.raises(ConfigError, match="llm_budget"):
        s.validate()


def test_floats_in_toml_for_money_are_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(toml(tmp_path, "[llm_budget]\nmax_cost = 2.5\n"), env={}).validate()


def test_per_call_input_may_not_exceed_session_input_or_total():
    bad = replace(LlmBudgetSettings(), max_input_tokens_per_call=60_000, max_input_tokens_session=50_000)
    with pytest.raises(ConfigError, match="llm_budget"):
        replace(Settings(), llm_budget=bad).validate()
    bad = replace(LlmBudgetSettings(), max_tokens_session=1000, max_input_tokens_session=2000)
    with pytest.raises(ConfigError, match="llm_budget"):
        replace(Settings(), llm_budget=bad).validate()


def test_limits_and_prices_convert_to_the_budget_models():
    b = replace(LlmBudgetSettings(), max_cost="3.5", prices=("gpt-x;0.5;1.5",))
    limits, prices = b.to_limits(), b.to_prices()
    assert str(limits.max_cost) == "3.5" and limits.max_calls == 30
    assert str(prices.get("gpt-x").output_per_1k) == "1.5" and prices.get("other") is None
