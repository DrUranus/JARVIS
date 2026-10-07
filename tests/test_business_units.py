"""Business layer: calculations, models and the BusinessAgent (through the real orchestrator, with research results handed over as parent tasks)."""
from __future__ import annotations

import json

import pytest

from agents_util import FakeAgent
from analysis_util import SHOP_A, SHOP_B, SHOP_C, plain_orch, research_output, run_with_parent
from jarvis.agents import AgentTask, TaskStatus
from jarvis.agents.context import AgentContext
from jarvis.business import Assumption, Basis, BusinessResult, Competitor, Entry, InvalidBusinessInput
from jarvis.business import calc as K
from jarvis.business.agent import BusinessAgent

S = TaskStatus
CAPS = {"business.analyze"}


def rig(**kw):
    parent = FakeAgent("research", {"research.web"}, output=kw.pop("parent", research_output()))
    return plain_orch([parent, BusinessAgent(**kw)])[0]


def run(data, parent=True, orch=None, **kw):
    out = research_output() if parent is True else (parent or None)
    o = orch or rig(parent=out or research_output(), **kw)
    return run_with_parent(o, "business", CAPS, data, out)


# ---- calculations ----------------------------------------------------------------------------------------------------------------------------------
def test_break_even():
    b = K.break_even(1200, 50, 15)
    assert b["status"] == "COMPUTED" and b["units"] == pytest.approx(1200 / 35) and b["revenue"] == pytest.approx(50 * 1200 / 35) and b["contribution_margin"] == 35
    assert b["inputs"] == {"fixed_costs": 1200.0, "price": 50.0, "variable_cost": 15.0}


@pytest.mark.parametrize("args", [(1200, 15, 15), (1200, 10, 15), (None, 50, 15), (1200, None, 15), (1200, 50, None)])
def test_break_even_is_unknown_not_invented(args):
    b = K.break_even(*args)
    assert b["status"] == "UNKNOWN" and b["reason"] and "units" not in b


@pytest.mark.parametrize("args", [(-1, 50, 15), (1200, 0, 15), (1200, -5, 15), (1200, 50, -1), (float("nan"), 50, 15), (1200, float("inf"), 15), (True, 50, 15), ("1200", 50, 15)])
def test_invalid_numbers_are_rejected(args):
    with pytest.raises(InvalidBusinessInput):
        K.break_even(*args)


def test_scenarios_and_payback():
    s = K.scenarios(50, 15, 1200, {"base": 40, "low": 20})
    assert s["base"]["profit"] == 200 and s["low"]["profit"] == 20 * 35 - 1200 and s["low"]["margin"] == pytest.approx((700 - 1200) / 1000)
    assert K.scenario(50, 15, 1200, 0)["margin"] is None
    assert K.payback_months(5000, 250)["months"] == 20 and K.payback_months(5000, 0)["status"] == "UNKNOWN" and K.payback_months(None, 5)["status"] == "UNKNOWN"
    for bad in ({}, "x", {f"s{i}": 1 for i in range(7)}):
        with pytest.raises(InvalidBusinessInput):
            K.scenarios(50, 15, 1200, bad)  # type: ignore[arg-type]


def test_price_stats_and_period_findings():
    st = K.price_stats([50, 80, 52.5])
    assert st["min"] == 50 and st["max"] == 80 and st["median"] == 52.5 and st["n"] == 3 and st["spread_pct"] == pytest.approx(37.5)
    assert K.price_stats([])["status"] == "UNKNOWN"
    r = K.period_findings([{"period": "Q1", "revenue": 1000, "costs": 800}, {"period": "Q2", "revenue": 800, "costs": 900}])
    assert r["loss_periods"] == ["Q2"] and r["revenue_change"] == pytest.approx(-0.2) and r["cost_change"] == pytest.approx(0.125)
    assert K.period_findings([])["status"] == "UNKNOWN"
    with pytest.raises(InvalidBusinessInput):
        K.period_findings(["x"])  # type: ignore[list-item]


# ---- models ------------------------------------------------------------------------------------------------------------------------------------------
def test_result_is_bounded_and_serialisable():
    r = BusinessResult("obj", "market_analysis", "s" * 3000, tuple(Entry("x" * 600, Basis.FACT, ("u",) * 9) for _ in range(300)),
                       sources=tuple({"url": f"u{i}"} for i in range(300)))
    d = r.to_dict(5000)
    assert len(json.dumps(d)) <= 5000 and d["truncated"] is True and d["kind"] == "business_result"
    assert "x" * 100 not in repr(r)
    assert Assumption("a", {"nested": 1}, Basis.GIVEN).to_dict()["value"] == "{'nested': 1}"
    assert Competitor("c").to_dict()["positioning"] == "UNKNOWN"


# ---- market / competitor analysis ----------------------------------------------------------------------------------------------------------------------
def test_market_analysis_from_research_has_labelled_sourced_content():
    res = run({"kind": "market_analysis", "assumptions": {"region": "Köln"}})
    o = res.output
    assert res.status is S.SUCCEEDED and o["kind"] == "business_result" and o["task"] == "market_analysis"
    assert len(o["sources"]) == 3 and {s["url"] for s in o["sources"]} == {SHOP_A, SHOP_B, SHOP_C}                       # source propagation
    assert len(o["competitors"]) == 3 and o["market_data"]["market_size"]["status"] == "UNKNOWN"                           # no invented market size
    assert any("market size" in u for u in o["unknowns"])
    po = o["market_data"]["price_overview"]["innenreinigung (EUR)"]
    assert po["min"] == 50 and po["max"] == 80 and po["basis"] == "INFERENCE" and po["n"] == 3
    assert {"name": "region", "value": "Köln", "basis": "GIVEN", "note": "stated by the user"} == o["assumptions"][0]
    assert all(e["basis"] in {"GIVEN", "FACT", "INFERENCE", "ESTIMATE", "UNKNOWN"} for k in ("findings", "opportunities", "risks", "recommendations") for e in o[k])
    assert o["confidence"]["level"] in ("low", "medium", "high") and 0 <= o["confidence"]["score"] <= 1 and o["confidence"]["reasons"]


def test_market_size_is_only_reported_when_a_source_states_it():
    out = research_output({SHOP_A: {"marktvolumen": 2_000_000.0, "innenreinigung": 50.0}})
    res = run_with_parent(rig(parent=out), "business", CAPS, {"kind": "market_analysis"}, out)
    ms = res.output["market_data"]["market_size"]
    assert ms["status"] == "FACT" and ms["values"][0]["value"] == 2_000_000.0 and ms["values"][0]["source"] == SHOP_A


def test_competitor_analysis_positions_competitors_as_labelled_inference():
    res = run({"kind": "competitor_analysis", "competitors": [{"name": "Glanzwerk", "url": SHOP_B}]})
    comps = {c["url"]: c for c in res.output["competitors"]}
    assert comps[SHOP_B]["name"] == "Glanzwerk" and comps[SHOP_B]["positioning"] == "premium" and comps[SHOP_B]["positioning_basis"] == "INFERENCE"
    assert comps[SHOP_A]["positioning"] in ("budget", "mid") and any("highest price" in w["text"] for w in comps[SHOP_B]["weaknesses"])
    assert any("lowest price" in s["text"] for c in comps.values() for s in c["strengths"])
    assert all(p["basis"] == "FACT" and p["source"] for c in comps.values() for p in c["prices"].values())


def test_positioning_needs_enough_competitors():
    out = research_output({SHOP_A: {"innenreinigung": 50.0}, SHOP_B: {"innenreinigung": 80.0}})
    res = run_with_parent(rig(parent=out), "business", CAPS, {"kind": "competitor_analysis"}, out)
    assert all(c["positioning"] == "UNKNOWN" for c in res.output["competitors"]) and any("UNKNOWN" in u for u in res.output["unknowns"])
    assert any("fewer than 3" in r["text"] or "very few" in r["text"] for r in res.output["risks"])


def test_conflicts_and_failed_sources_lower_confidence_and_are_named_as_risks():
    clean = run({"kind": "market_analysis"}, parent=research_output({SHOP_A: {"x": 1.0}, SHOP_B: {"x": 1.0}, SHOP_C: {"x": 1.0}, "https://d.example.com/": {"x": 1.0}}))
    c = [{"status": "CONFLICT", "label": "innenreinigung", "unit": "EUR", "entries": []}]
    messy = run({"kind": "market_analysis"}, parent=research_output(conflicts=c))
    assert messy.output["confidence"]["score"] < clean.output["confidence"]["score"] and any("conflict" in r["text"] for r in messy.output["risks"])
    none = run({"kind": "market_analysis"}, parent=research_output({SHOP_A: {"x": 1.0}}, status_by_url={SHOP_A: "unavailable"}))
    assert none.output["confidence"]["level"] == "low" and any("no research data" in u for u in none.output["unknowns"])


def test_analysis_without_any_research_is_unknown_not_fabricated():
    res = run({"kind": "market_analysis"}, parent=False)
    o = res.output
    assert res.status is S.SUCCEEDED and o["competitors"] == [] and o["sources"] == [] and o["market_data"]["market_size"]["status"] == "UNKNOWN" and o["confidence"]["level"] == "low"


def test_failed_research_parent_is_not_used():
    bad = FakeAgent("research", {"research.web"}, behavior="failure")
    o, _ = plain_orch([bad, BusinessAgent()])
    parent = AgentTask("Recherchiere", agent_id="research", required_capabilities=frozenset({"research.web"}), task_id="p1")
    o.submit(parent); o.start("p1")
    res = o.run(AgentTask("Analyse", agent_id="business", input={"kind": "market_analysis"}, required_capabilities=frozenset(CAPS), dependencies=("p1",)))
    assert res.status is S.BLOCKED and res.error_code == "dependency_failed"                                                # the orchestrator refuses; nothing is made up


def test_explicit_research_block_works_without_a_parent_task():
    res = run({"kind": "competitor_analysis", "research": research_output()}, parent=False)
    assert len(res.output["competitors"]) == 3


# ---- business plan -----------------------------------------------------------------------------------------------------------------------------------
PLAN = {"offer": "Innenreinigung", "target_audience": "Pendler", "price": 50, "variable_cost": 15, "fixed_costs": 1200, "units": {"pessimistic": 20, "base": 40, "optimistic": 70},
        "investment": 5000}


def test_business_plan_calculates_and_labels_assumptions():
    res = run({"kind": "business_plan", "plan": PLAN}, parent=False)
    o = res.output
    be = o["calculations"]["break_even"]
    assert be["status"] == "COMPUTED" and be["units"] == pytest.approx(1200 / 35)
    assert o["calculations"]["scenarios"]["base"]["profit"] == 200 and o["calculations"]["payback"]["months"] == 25
    assert {a["name"] for a in o["assumptions"]} >= {"price", "variable_cost", "fixed_costs", "investment"} and all(a["basis"] == "GIVEN" for a in o["assumptions"])
    assert o["drafts"]["business_model"]["offer"] == "Innenreinigung" and o["unknowns"] == []
    assert any("assumed unit volumes" in r["text"] for r in o["risks"]) and o["recommendations"]


def test_business_plan_with_missing_data_is_unknown_not_guessed():
    res = run({"kind": "business_plan", "plan": {"offer": "X", "price": 50}}, parent=False)
    o = res.output
    assert o["calculations"]["break_even"]["status"] == "UNKNOWN" and o["calculations"]["scenarios"]["status"] == "UNKNOWN" and len(o["unknowns"]) >= 3


def test_price_from_research_is_a_flagged_estimate_and_never_from_conflicting_sources():
    plan = {**PLAN, "price_label": "außenwäsche"}
    plan.pop("price")
    ok = run({"kind": "business_plan", "plan": plan}, parent=research_output({SHOP_A: {"außenwäsche": 25.0}, SHOP_B: {"außenwäsche": 26.0}}))
    price = next(a for a in ok.output["assumptions"] if a["name"] == "price")
    assert price["basis"] == "ESTIMATE" and SHOP_A in price["note"] and ok.output["calculations"]["break_even"]["status"] == "COMPUTED"
    conflict = [{"status": "CONFLICT", "label": "außenwäsche", "unit": "EUR", "entries": []}]
    bad = run({"kind": "business_plan", "plan": plan}, parent=research_output({SHOP_A: {"außenwäsche": 25.0}, SHOP_B: {"außenwäsche": 60.0}}, conflicts=conflict))
    assert bad.output["calculations"]["break_even"]["status"] == "UNKNOWN" and any("conflict" in u for u in bad.output["unknowns"])


@pytest.mark.parametrize("plan", [{"price": -5}, {"price": 0}, {"price": "50"}, {"price": 50, "variable_cost": -1}, "plan",
                                  {"price": 50, "variable_cost": 10, "fixed_costs": 100, "units": {}}, {"price": 50, "variable_cost": 10, "fixed_costs": 100, "units": {"a": -1}}])
def test_business_plan_rejects_invalid_numbers(plan):
    res = run({"kind": "business_plan", "plan": plan}, parent=False)
    assert res.status is S.FAILED and res.error_code == "invalid_input"


# ---- business data / marketing / leads ----------------------------------------------------------------------------------------------------------------
def test_business_data_analysis_finds_weak_points():
    rows = [{"period": "Q1", "revenue": 10000, "costs": 8000}, {"period": "Q2", "revenue": 8000, "costs": 8500}, {"period": "Q3", "revenue": 7000, "costs": 8800}]
    o = run({"kind": "business_analysis", "rows": rows}, parent=False).output
    text = " ".join(r["text"] for r in o["risks"])
    assert "Q2" in text and "Q3" in text and "revenue fell" in text and "costs grew faster" in text
    assert run({"kind": "business_analysis", "rows": []}, parent=False).output["unknowns"]


def test_marketing_drafts_are_drafts_from_given_facts_only():
    o = run({"kind": "marketing_draft", "marketing": {"audience": "Pendler", "offer": "Innenreinigung", "usp": ["Abholservice", "Festpreis"]}}).output
    d = o["drafts"]
    assert d["status"].startswith("DRAFT") and "Pendler" in d["ad_drafts"][0] and "Abholservice" in d["social_drafts"][0] and d["landing_page_outline"] and d["content_ideas"]
    assert d["seo_keywords"]["basis"] in ("INFERENCE", "UNKNOWN") and "nothing was published" in o["note"] or "nothing was" in o["note"]
    missing = run({"kind": "marketing_draft", "marketing": {"offer": "X"}}, parent=False).output
    assert "audience" in " ".join(missing["unknowns"]) and missing["drafts"] == {}


def test_lead_list_is_prepared_and_sends_nothing():
    o = run({"kind": "lead_list"}).output
    assert len(o["drafts"]["leads"]) == 3 and o["drafts"]["outreach"] == "NOT SENT" and all(l["basis"] == "FACT" and l["url"] for l in o["drafts"]["leads"])
    assert "YELLOW" in o["findings"][0]["text"] and "explicit confirmation" in o["findings"][0]["text"]


# ---- limits / safety ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["send_email", "email", "send_message", "dm", "outreach", "cold_outreach", "send_offer", "contract", "payment", "publish", "post", "purchase", "contact"])
def test_external_actions_are_not_possible(kind):
    res = run({"kind": kind, "to": "a@b.de", "text": "hi"}, parent=False)
    assert res.status is S.BLOCKED and res.error_code == "external_action_not_supported"


def test_unknown_kind_missing_capability_and_oversized_input():
    assert run({"kind": "magic"}, parent=False).error_code == "invalid_input" and run({}, parent=False).error_code == "invalid_input"
    out = BusinessAgent().perform(AgentTask("x", agent_id="business", input={"kind": "market_analysis"}), AgentContext("t", "x", {}, frozenset({"research.web"})))
    assert out.status is S.BLOCKED and out.error_code == "capability_not_allowed"
    big = run({"kind": "business_analysis", "rows": [{"period": str(i), "revenue": 1, "costs": 1} for i in range(50)]}, parent=False, max_steps=10)
    assert big.status is S.FAILED and "at most 10" in big.error


def test_result_size_limit_and_timeout():
    res = run({"kind": "business_analysis", "rows": [{"period": f"P{i}", "revenue": 100, "costs": 200} for i in range(20)]}, parent=False, max_result_chars=1500)
    assert len(json.dumps(res.output)) <= 1500
    t = {"n": 0.0}

    def mono():
        t["n"] += 500.0
        return t["n"]
    slow = run({"kind": "market_analysis"}, parent=False, orch=plain_orch([BusinessAgent(timeout=100, monotonic=mono)])[0])
    assert slow.status is S.FAILED and slow.error_code == "timeout"


def test_business_agent_has_no_tools_and_cannot_use_any():
    assert BusinessAgent.tool_names == frozenset()
    fake = FakeAgent("business", {"business.analyze"}, tool_calls=[("email", {"to": "x"})])      # even a misbehaving business agent has no gateway access
    o, _ = plain_orch([fake])
    res = o.run(AgentTask("x", agent_id="business", required_capabilities=frozenset(CAPS)))
    assert res.status is S.FAILED and res.error_code == "tool_access_denied"
