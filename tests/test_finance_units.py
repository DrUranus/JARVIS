"""Finance layer: calculations, models, paper trading, risk limits and the FinanceAgent (through the real orchestrator)."""
from __future__ import annotations

import json
import math

import pytest

from agents_util import FakeAgent
from analysis_util import SHOP_A, plain_orch, research_output, run_with_parent
from jarvis.agents import AgentTask, TaskStatus
from jarvis.agents.context import AgentContext
from jarvis.finance import Direction, InvalidFinanceInput, PortfolioSnapshot, Position, RiskLimits, TradeIdea
from jarvis.finance import calc as C
from jarvis.finance import paper as PP
from jarvis.finance.agent import FinanceAgent
from jarvis.finance.models import number, symbol

S = TaskStatus
CAPS = {"finance.analyze"}


# ---- calculations ------------------------------------------------------------------------------------------------------------------------------------
def test_valuation_ratios_with_their_inputs():
    pe = C.pe_ratio(100, 5)
    assert pe.value == 20 and pe.status == "COMPUTED" and pe.inputs == {"price": 100.0, "eps": 5.0} and "price" in pe.formula
    assert C.ps_ratio(1000, 250).value == 4 and C.ev_ebitda(1000, 300, 100, 150).value == pytest.approx(1200 / 150)
    assert C.growth("g", 120, 100).value == pytest.approx(0.2) and C.growth("g", 80, -100).value == pytest.approx(1.8)
    assert C.margin("m", 25, 200).value == 0.125 and C.debt_to_equity(300, 600).value == 0.5 and C.free_cash_flow(500, -120).value == 380


@pytest.mark.parametrize("metric", [C.pe_ratio(100, 0), C.pe_ratio(100, -3), C.pe_ratio(0, 5), C.pe_ratio(None, 5), C.pe_ratio(100, None), C.ps_ratio(100, 0), C.ps_ratio(-1, 5),
                                    C.ps_ratio(None, None), C.ev_ebitda(1, 1, 1, 0), C.ev_ebitda(1, 1, 1, -5), C.ev_ebitda(1, None, 1, 5), C.growth("g", 5, 0), C.growth("g", None, 1),
                                    C.margin("m", 5, 0), C.margin("m", None, 5), C.debt_to_equity(5, 0), C.debt_to_equity(5, -1), C.free_cash_flow(None, 5)])
def test_missing_or_meaningless_data_is_unknown_with_a_reason(metric):
    d = metric.to_dict()
    assert d["status"] == "UNKNOWN" and d["value"] is None and d["note"]


@pytest.mark.parametrize("call", [lambda: C.pe_ratio(float("nan"), 5), lambda: C.pe_ratio(float("inf"), 5), lambda: C.pe_ratio("100", 5), lambda: C.pe_ratio(True, 5),
                                  lambda: C.ps_ratio(1e30, 5), lambda: C.growth("g", float("nan"), 1)])
def test_invalid_numbers_are_rejected(call):
    with pytest.raises(InvalidFinanceInput):
        call()


def test_drawdown_and_volatility():
    assert C.max_drawdown([100, 120, 90, 130]).value == pytest.approx(-0.25)
    assert C.max_drawdown([100, 110, 120]).value == 0
    assert C.max_drawdown([100]).status == "UNKNOWN"
    v = C.volatility([100, 101, 99, 102])
    assert v.value == pytest.approx(0.025202126697692506) and C.volatility([1, 2]).status == "UNKNOWN"
    assert C.volatility([100, 101, 99, 102], 252).value == pytest.approx(v.value * math.sqrt(252))
    for bad in ([100, 0, 5], [100, -1, 5], [100, float("nan"), 5], "x", [100, "a", 1]):
        with pytest.raises(InvalidFinanceInput):
            C.max_drawdown(bad)  # type: ignore[arg-type]
    for ppy in (0, 400, True, 1.5):
        with pytest.raises(InvalidFinanceInput):
            C.volatility([1, 2, 3], ppy)  # type: ignore[arg-type]


def test_risk_reward_and_position_sizing():
    assert C.risk_reward("long", 100, 95, 115).value == 3 and C.risk_reward("short", 100, 105, 85).value == 3
    for bad in (("long", 100, 105, 115), ("long", 100, 95, 90), ("short", 100, 95, 85), ("long", 100, 100, 110)):
        assert C.risk_reward(*bad).status == "UNKNOWN"
    assert C.position_size(10_000, 1, 100, 95).value == 20 and C.position_size(10_000, 1, 100, 100).status == "UNKNOWN"
    for call in (lambda: C.position_size(0, 1, 100, 95), lambda: C.position_size(-5, 1, 100, 95), lambda: C.position_size(1000, 0, 100, 95),
                 lambda: C.position_size(1000, 101, 100, 95), lambda: C.risk_reward("long", -1, 95, 115), lambda: C.risk_reward("sideways", 100, 95, 115)):
        with pytest.raises((InvalidFinanceInput, ValueError)):
            call()


# ---- models ---------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("sym", ["AAPL", "aapl", "BRK.B", "SAP.DE", "BTC-USD", "7203", "A"])
def test_valid_symbols(sym):
    assert symbol(sym) == sym.upper()


@pytest.mark.parametrize("sym", ["", " ", "A B", "AAPL;DROP", "http://x.y", "$(rm -rf)", "A" * 13, "../x", None, 5, "ÄÖ", "AAPL\n", "-AAPL"])
def test_malformed_symbols_are_refused(sym):
    with pytest.raises(InvalidFinanceInput):
        symbol(sym)


def idea(**kw):
    base = dict(symbol="AAPL", direction="long", entry=100, stop=95, target=115, position_size=20, confidence=0.6, thesis="t", invalidations=("close < 94",))
    base.update(kw)
    return TradeIdea(**base)


def test_trade_idea_fields_and_derived_values():
    i = idea()
    assert i.risk_amount == 100 and i.risk_reward == 3 and i.direction is Direction.LONG and i.timestamp
    d = i.to_dict()
    assert {"symbol", "direction", "entry", "stop", "target", "position_size", "risk_amount", "risk_reward", "confidence", "thesis", "invalidations", "timestamp"} <= set(d)
    assert "nothing was ordered" in d["status"] and "thesis" not in repr(i)
    s = idea(direction="SHORT", entry=100, stop=105, target=85)
    assert s.direction is Direction.SHORT and s.risk_reward == 3


@pytest.mark.parametrize("kw", [{"stop": 101}, {"target": 99}, {"stop": 100}, {"entry": 0}, {"entry": -1}, {"position_size": 0}, {"position_size": -1}, {"confidence": 1.5},
                                {"confidence": -0.1}, {"symbol": "A B"}, {"direction": "sideways"}, {"entry": float("nan")}, {"target": float("inf")},
                                {"direction": "short"}, {"stop": "95"}])
def test_invalid_trade_ideas_are_rejected(kw):
    with pytest.raises((InvalidFinanceInput, ValueError)):
        idea(**kw)


def test_risk_limits_cannot_enable_leverage_or_withdrawals():
    RiskLimits()
    for kw in ({"max_leverage": 2.0}, {"max_leverage": 1.5}, {"allow_withdrawals": True}, {"max_position_pct": 0}, {"max_position_pct": 101}, {"daily_loss_limit_pct": -1},
               {"max_risk_per_trade_pct": float("nan")}):
        with pytest.raises(InvalidFinanceInput):
            RiskLimits(**kw)


def test_number_helper():
    assert number(5, "x") == 5.0
    for bad in (True, "5", None, float("nan"), 1e16):
        with pytest.raises(InvalidFinanceInput):
            number(bad, "x")
    with pytest.raises(InvalidFinanceInput):
        number(0, "x", positive=True)
    with pytest.raises(InvalidFinanceInput):
        number(-1, "x", non_negative=True)


# ---- paper trading ------------------------------------------------------------------------------------------------------------------------------------
def test_assess_against_limits():
    lim = RiskLimits()
    ok = PP.assess(idea(), 10_000, lim)
    assert ok.ok and ok.risk_pct_of_account == 1.0 and ok.position_pct_of_account == 20.0 and ok.risk_reward == 3
    big = PP.assess(idea(position_size=100), 10_000, lim)
    assert not big.ok and any("per trade" in v for v in big.violations) and any("position" in v for v in big.violations)
    unknown = PP.assess(idea(), None, lim)
    assert not unknown.ok and "unknown" in unknown.violations[0]
    assert not PP.assess(idea(), 10_000, lim, open_exposure=95_000).ok                       # total exposure limit, no leverage
    with pytest.raises(InvalidFinanceInput):
        PP.assess(idea(), -5, lim)


def test_simulation_outcomes():
    i = idea()
    assert PP.simulate(i, [101, 100, 110, 116]).outcome == "target" and PP.simulate(i, [101, 100, 110, 116]).pnl == 300
    assert PP.simulate(i, [100, 96, 94]).outcome == "stop" and PP.simulate(i, [100, 96, 94]).pnl == -100
    assert PP.simulate(i, [90, 91, 92]).outcome == "not_entered" and PP.simulate(i, [90]).pnl == 0
    op = PP.simulate(i, [100, 102, 104])
    assert op.outcome == "open" and op.pnl == 80 and op.exit_price == 104
    assert PP.simulate(i, [{"high": 101, "low": 99}, {"high": 116, "low": 100}]).outcome == "target"
    assert PP.simulate(i, [{"high": 120, "low": 90}]).outcome == "stop"                       # stop and target in one bar: the conservative reading
    s = idea(direction="short", entry=100, stop=105, target=85)
    assert PP.simulate(s, [100, 90, 84]).outcome == "target" and PP.simulate(s, [100, 90, 84]).pnl == 300 and PP.simulate(s, [100, 106]).outcome == "stop"


@pytest.mark.parametrize("prices", [[], "x", None, [0], [-5], [float("nan")], [{"high": 1}], [{"high": 1, "low": 2}], ["a"]])
def test_simulation_rejects_bad_price_paths(prices):
    with pytest.raises(InvalidFinanceInput):
        PP.simulate(idea(), prices)  # type: ignore[arg-type]


def test_paper_trades_are_always_marked_paper():
    d = PP.simulate(idea(), [100, 116]).to_dict()
    assert d["paper"] is True and "no order was placed" in d["note"]


def test_snapshot_marks_and_unknown_prices():
    snap = PP.snapshot(1000, [Position("aapl", 10, 100), Position("MSFT", 5, 200)], {"AAPL": 110})
    d = snap.to_dict()
    assert d["market_value"] is None and d["equity"] is None and d["paper"] is True                  # one mark is unknown: no total is invented
    assert d["positions"][0]["unrealized_pnl"] == 100 and d["positions"][1]["status"] == "UNKNOWN"
    full = PP.snapshot(1000, [Position("AAPL", 10, 100)], {"AAPL": 110}).to_dict()
    assert full["market_value"] == 1100 and full["equity"] == 2100
    for bad in (lambda: Position("AAPL", 0, 1), lambda: Position("AAPL", 1, -1), lambda: Position("A B", 1, 1), lambda: PP.snapshot(-1, [], {}), lambda: PP.snapshot(0, [Position("A", 1, 1)], {"A": 0})):
        with pytest.raises(InvalidFinanceInput):
            bad()


def test_daily_loss_limit():
    losing = [PP.simulate(idea(), [100, 94]) for _ in range(4)]                                       # 4 x -100 on 10 000 = 4 %
    assert PP.daily_loss_exceeded(losing, 10_000, RiskLimits()) and not PP.daily_loss_exceeded(losing[:2], 10_000, RiskLimits())


# ---- the agent ----------------------------------------------------------------------------------------------------------------------------------------------
def rig(parent=None, **kw):
    agents = [FinanceAgent(**kw)]
    if parent is not None:
        agents.insert(0, FakeAgent("research", {"research.web"}, output=parent))
    return plain_orch(agents)[0]


def run(data, parent=None, **kw):
    return run_with_parent(rig(parent, **kw), "finance", CAPS, data, parent)


COMPANY = {"name": "ACME", "symbol": "acme", "price": 100, "eps": 5, "market_cap": 10_000, "revenue": 5_000, "revenue_previous": 4_000, "net_income": 500, "ebitda": 1_000,
           "debt": 2_000, "cash": 500, "equity": 4_000, "operating_cash_flow": 900, "capex": 300}


def test_financial_analysis_computes_every_metric_from_given_data():
    res = run({"kind": "financial_analysis", "company": COMPANY})
    o = res.output
    m = {x["name"]: x for x in o["metrics"]}
    assert res.status is S.SUCCEEDED and o["kind"] == "finance_result" and o["paper"] is True and "not financial advice" in o["disclaimer"]
    assert m["P/E"]["value"] == 20 and m["P/S"]["value"] == 2 and m["EV/EBITDA"]["value"] == pytest.approx(11.5)
    assert m["Revenue growth"]["value"] == 0.25 and m["Net margin"]["value"] == 0.1 and m["Debt/Equity"]["value"] == 0.5 and m["Free cash flow"]["value"] == 600
    assert all(x["status"] == "COMPUTED" and x["formula"] and x["inputs"] for x in m.values()) and o["company"]["symbol"] == "ACME"


def test_missing_data_stays_unknown_in_the_analysis():
    res = run({"kind": "financial_analysis", "company": {"name": "X", "price": 100}})
    m = {x["name"]: x for x in res.output["metrics"]}
    assert all(x["status"] == "UNKNOWN" for x in m.values()) and "0 of 8" in res.output["summary"] and "UNKNOWN" in res.output["summary"]


def test_sourced_figures_from_research_fill_missing_fields_with_their_source():
    out = research_output({SHOP_A: {"umsatz": 5000.0, "nettogewinn": 500.0}})
    res = run({"kind": "financial_analysis", "company": {"name": "X", "from_research": {"revenue": "umsatz", "net_income": "nettogewinn", "debt": "schulden"}}}, parent=out)
    o = res.output
    m = {x["name"]: x for x in o["metrics"]}
    assert m["Net margin"]["value"] == 0.1 and o["data_from_research"]["revenue"] == SHOP_A and "debt" not in o["data_from_research"]
    assert m["Debt/Equity"]["status"] == "UNKNOWN" and [s["url"] for s in o["sources"]] == [SHOP_A]                       # source propagation


def test_company_comparison_ranks_known_values_and_puts_unknown_last():
    b = {**COMPANY, "name": "BETA", "price": 60, "eps": 2}
    c = {"name": "GAMMA", "price": 10}
    res = run({"kind": "company_analysis", "companies": [COMPANY, b, c]})
    pe = res.output["comparison"]["P/E"]
    assert [r["company"] for r in pe] == ["ACME", "BETA", "GAMMA"] and pe[0]["value"] == 20 and pe[-1]["status"] == "UNKNOWN" and pe[1]["value"] == 30


def test_risk_analysis():
    res = run({"kind": "risk_analysis", "symbol": "aapl", "prices": [100, 120, 90, 130, 125], "periods_per_year": 252})
    m = {x["name"]: x for x in res.output["metrics"]}
    assert m["Max drawdown"]["value"] == pytest.approx(-0.25) and m["Total return"]["value"] == pytest.approx(0.25) and m["Volatility"]["status"] == "COMPUTED"
    assert run({"kind": "risk_analysis", "prices": [100]}).output["metrics"][1]["status"] == "UNKNOWN"


def test_scenario_analysis_uses_only_given_assumptions_and_flags_estimates():
    res = run({"kind": "scenario_analysis", "revenue": 1000, "years": 2, "multiple": 10, "scenarios": {"bear": {"growth": 0.0, "margin": 0.05}, "bull": {"growth": 0.5, "margin": 0.2}}})
    sc = {s["scenario"]: s for s in res.output["scenarios"]}
    assert sc["bear"]["revenue_end"] == 1000 and sc["bear"]["profit_end"] == 50 and sc["bull"]["revenue_end"] == 2250 and sc["bull"]["profit_end"] == 450
    assert sc["bull"]["assumptions"]["kind"] == "GIVEN" and sc["bull"]["value_estimate"]["status"] == "ESTIMATE" and "assumption" in sc["bull"]["value_estimate"]["basis"]
    assert "value_estimate" not in run({"kind": "scenario_analysis", "revenue": 1000, "scenarios": {"x": {"growth": 0.1, "margin": 0.1}}}).output["scenarios"][0]


def test_portfolio_analysis_weights_and_unknown_marks():
    res = run({"kind": "portfolio_analysis", "cash": 500, "positions": [{"symbol": "AAPL", "quantity": 10, "average_price": 100}, {"symbol": "MSFT", "quantity": 5, "average_price": 200}],
               "marks": {"AAPL": 110, "MSFT": 220}})
    o = res.output
    assert o["portfolio"]["equity"] == 2700 and o["largest_weight"] == pytest.approx(1100 / 2200) and sum(w["weight"] for w in o["weights"]) == pytest.approx(1)
    part = run({"kind": "portfolio_analysis", "positions": [{"symbol": "AAPL", "quantity": 1, "average_price": 1}], "marks": {}}).output
    assert part["portfolio"]["market_value"] is None and "UNKNOWN" in part["summary"]


def test_paper_trade_analysis_scenario():
    ideas = [{"symbol": "AAPL", "direction": "long", "entry": 100, "stop": 95, "target": 115, "position_size": 20, "confidence": 0.6, "thesis": "breakout", "prices": [100, 105, 116]},
             {"symbol": "MSFT", "direction": "long", "entry": 200, "stop": 190, "target": 230, "position_size": 100, "confidence": 0.5, "prices": [200, 250]},
             {"symbol": "TSLA", "direction": "short", "entry": 50, "stop": 52, "target": 44, "position_size": 40, "confidence": 0.4, "prices": [50, 53]}]
    res = run({"kind": "paper_trade_analysis", "account": 10_000, "ideas": ideas})
    t = res.output["trades"]
    assert t[0]["paper_trade"]["outcome"] == "target" and t[0]["paper_trade"]["pnl"] == 300 and t[0]["risk"]["ok"]
    assert t[1]["paper_trade"] is None and not t[1]["risk"]["ok"] and "not simulated" in t[1]["note"]                     # 1 000 risk on 10 000 > 1 %
    assert t[2]["paper_trade"]["outcome"] == "stop" and res.output["paper_pnl"] == 300 - 80 and res.output["limits"]["max_leverage"] == 1.0 and res.output["paper"] is True


def test_paper_trade_without_account_cannot_pass_the_risk_check():
    res = run({"kind": "paper_trade_analysis", "ideas": [{"symbol": "AAPL", "direction": "long", "entry": 100, "stop": 95, "target": 115, "position_size": 1, "prices": [100, 116]}]})
    assert res.output["trades"][0]["paper_trade"] is None and "unknown" in res.output["trades"][0]["risk"]["violations"][0]


@pytest.mark.parametrize("data", [{"kind": "financial_analysis"}, {"kind": "financial_analysis", "company": "x"}, {"kind": "financial_analysis", "company": {"price": "100"}},
                                  {"kind": "financial_analysis", "company": {"price": -1, "eps": float("1e30")}}, {"kind": "financial_analysis", "company": {"unknown_field": 1}},
                                  {"kind": "company_analysis", "companies": []}, {"kind": "risk_analysis", "prices": [100, 0, 5]}, {"kind": "scenario_analysis", "revenue": 0, "scenarios": {}},
                                  {"kind": "scenario_analysis", "revenue": 1, "scenarios": {"x": {"growth": 9, "margin": 0.1}}}, {"kind": "scenario_analysis", "revenue": 1, "years": 99, "scenarios": {}},
                                  {"kind": "portfolio_analysis", "positions": [{"symbol": "A B", "quantity": 1, "average_price": 1}]}, {"kind": "portfolio_analysis", "positions": ["x"]},
                                  {"kind": "paper_trade_analysis", "ideas": [{"symbol": "AAPL", "direction": "long", "entry": 100, "stop": 105, "target": 90, "position_size": 1}]},
                                  {"kind": "paper_trade_analysis", "ideas": ["x"]}, {"kind": "nope"}, {}])
def test_invalid_requests_fail_cleanly(data):
    res = run(data)
    assert res.status is S.FAILED and res.error_code == "invalid_input"


def test_step_limit_applies():
    res = run({"kind": "risk_analysis", "prices": list(range(1, 200))}, max_steps=50)
    assert res.status is S.FAILED and "at most 50" in res.error
    ok = run({"kind": "risk_analysis", "prices": list(range(1, 51))}, max_steps=50)
    assert ok.status is S.SUCCEEDED


def test_result_size_and_timeout_limits():
    ideas = [{"symbol": "AAPL", "direction": "long", "entry": 100, "stop": 99, "target": 101, "position_size": 1, "confidence": 0.5, "thesis": "x" * 400, "prices": [100, 101]}] * 40
    res = run({"kind": "paper_trade_analysis", "account": 1e9, "ideas": ideas}, max_steps=100, max_result_chars=3000)
    assert len(json.dumps(res.output)) <= 3000 and res.output.get("truncated") is True
    t = {"n": 0.0}

    def mono():
        t["n"] += 500.0
        return t["n"]
    slow = run_with_parent(plain_orch([FinanceAgent(timeout=100, monotonic=mono)])[0], "finance", CAPS, {"kind": "risk_analysis", "prices": [1, 2, 3]}, None)
    assert slow.status is S.FAILED and slow.error_code == "timeout"


def test_capability_is_required():
    out = FinanceAgent().perform(AgentTask("x", agent_id="finance", input={"kind": "risk_analysis", "prices": [1, 2, 3]}), AgentContext("t", "x", {}, frozenset({"business.analyze"})))
    assert out.status is S.BLOCKED and out.error_code == "capability_not_allowed"


def test_finance_agent_has_no_tools_and_cannot_use_any():
    assert FinanceAgent.tool_names == frozenset()
    fake = FakeAgent("finance", {"finance.analyze"}, tool_calls=[("broker", {"order": "buy"})])
    o, _ = plain_orch([fake])
    res = o.run(AgentTask("x", agent_id="finance", required_capabilities=frozenset(CAPS)))
    assert res.status is S.FAILED and res.error_code == "tool_access_denied"
