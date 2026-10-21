"""Goal Engine -> Research / Business / Finance agents: templates, chains with result hand-over, failure isolation, timeout, cancellation, permission denial."""
from __future__ import annotations

import json
import threading

import pytest

from agents_util import FakeAgent, wait_event
from analysis_util import SHOP_A, SHOP_B, SHOP_C, make_rig, make_web, plain_orch, research_output
from browser_util import NO, ONCE
from jarvis.business.agent import BusinessAgent
from jarvis.finance.agent import FinanceAgent
from jarvis.goals import GoalEngine, GoalPlanner, GoalStatus, InvalidGoalError, StepStatus, check_user_context
from jarvis.goals import policy as GP
from jarvis.research.agent import ResearchAgent

G = GoalStatus
RESEARCH = {"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": ["Preise Innenreinigung"]}
PLAN = {"offer": "Innenreinigung", "price": 50, "variable_cost": 15, "fixed_costs": 1200, "units": {"base": 40}, "investment": 5000}
COMPANY = {"name": "ACME", "price": 100, "eps": 5, "revenue": 5000, "net_income": 500}
IDEA = {"symbol": "AAPL", "direction": "long", "entry": 100, "stop": 95, "target": 115, "position_size": 20, "confidence": 0.6, "prices": [100, 116]}


def full_rig(tmp_path, answers=None, **kw):
    r = make_rig(tmp_path, answers, agents=[ResearchAgent(), BusinessAgent(), FinanceAgent()], **kw)
    engine = GoalEngine(r.orch, GoalPlanner(r.planner), goal_timeout=60, step_timeout=30)
    return r, engine


def go(engine, template, objective="Analyse", **ctx):
    g = engine.create(objective, context={"template": template, **ctx})
    return engine.run(g.goal_id)


def by(res):
    return {s.step_id: s for s in res.steps}


# ---- templates ----------------------------------------------------------------------------------------------------------------------------------------
def test_research_web_goal(tmp_path):
    r, e = full_rig(tmp_path)
    res = go(e, "research_web", "Recherchiere die Preise", research=RESEARCH)
    assert res.status is G.SUCCEEDED and [s.assigned_agent for s in res.steps] == ["research", None]
    assert res.steps[0].result.output["kind"] == "research_result" and len(res.steps[0].result.output["sources"]) == 3


def test_market_analysis_chain_research_to_business_with_source_propagation(tmp_path):
    r, e = full_rig(tmp_path)
    res = go(e, "market_analysis", "Analysiere den Markt", research=RESEARCH, business={"assumptions": {"region": "Köln"}})
    assert res.status is G.SUCCEEDED and [s.assigned_agent for s in res.steps] == ["research", "business", None]
    biz = res.steps[1].result.output
    assert {s["url"] for s in biz["sources"]} == {SHOP_A, SHOP_B, SHOP_C} and len(biz["competitors"]) == 3                       # research -> business hand-over


def test_dependencies_run_through_the_orchestrators_parent_results(tmp_path):
    r, e = full_rig(tmp_path)
    res = go(e, "competitor_analysis", "Vergleiche Wettbewerber", research=RESEARCH)
    research_task = res.steps[0].result.task_id
    desc = r.orch.describe(res.steps[1].result.task_id)
    assert desc["dependencies"] == [research_task]                                                        # the existing AgentTask.dependencies carry the hand-over
    assert len(res.steps[1].result.output["competitors"]) == 3 and res.status is G.SUCCEEDED


def test_business_plan_chain_research_business_finance(tmp_path):
    r, e = full_rig(tmp_path)
    res = go(e, "business_plan", "Untersuche den Markt, entwickle ein Geschäftsmodell und rechne die Wirtschaftlichkeit durch", research=RESEARCH,
             business={"plan": {**PLAN, "price": None, "price_label": "außenwäsche"}},
             finance={"kind": "scenario_analysis", "revenue": 50_000, "years": 3, "scenarios": {"bear": {"growth": 0.0, "margin": 0.05}, "base": {"growth": 0.08, "margin": 0.12}}})
    assert res.status is G.SUCCEEDED, res.summary
    assert [s.assigned_agent for s in res.steps] == ["research", "business", "finance", None]
    biz, fin = res.steps[1].result.output, res.steps[2].result.output
    assert biz["calculations"]["break_even"]["status"] == "COMPUTED" or "price" in " ".join(biz["unknowns"])
    assert fin["task"] == "scenario_analysis" and len(fin["scenarios"]) == 2 and fin["paper"] is True


def test_business_analysis_without_research(tmp_path):
    r, e = full_rig(tmp_path)
    rows = [{"period": "Q1", "revenue": 1000, "costs": 800}, {"period": "Q2", "revenue": 700, "costs": 900}]
    res = go(e, "business_analysis", "Analysiere meine Geschäftsdaten", business={"rows": rows})
    assert res.status is G.SUCCEEDED and [s.assigned_agent for s in res.steps] == ["business", None] and res.steps[0].result.output["risks"]
    assert not r.provider.calls                                                                           # no browser involved


def test_financial_company_and_paper_trade_templates(tmp_path):
    r, e = full_rig(tmp_path)
    assert go(e, "financial_analysis", "Analysiere diese Aktie", finance={"company": COMPANY}).status is G.SUCCEEDED
    c = go(e, "company_analysis", "Vergleiche diese Unternehmen", finance={"companies": [COMPANY, {**COMPANY, "name": "B", "eps": 2}]})
    assert c.status is G.SUCCEEDED and c.steps[0].result.output["comparison"]["P/E"]
    p = go(e, "paper_trade_analysis", "Paper-Trade analysieren", finance={"account": 10_000, "ideas": [IDEA]})
    assert p.status is G.SUCCEEDED and p.steps[0].result.output["trades"][0]["paper_trade"]["outcome"] == "target"


def test_finance_after_research_uses_sourced_figures(tmp_path):
    web = make_web()
    from jarvis.browser.providers.fake import FakeDoc
    web.add(FakeDoc("https://ir.example.com/", "IR", "ACME Geschäftsbericht. Umsatz 5.000 € und Nettogewinn 500 € im Jahr."))
    r, e = full_rig(tmp_path, web=web)
    res = go(e, "financial_analysis", "Analysiere ACME", research={"urls": ["https://ir.example.com/"], "questions": ["Umsatz Nettogewinn"]},
             finance={"company": {"name": "ACME", "from_research": {"revenue": "umsatz", "net_income": "nettogewinn"}}})
    m = {x["name"]: x for x in res.steps[1].result.output["metrics"]}
    assert res.status is G.SUCCEEDED and m["Net margin"]["value"] == pytest.approx(0.1) and res.steps[1].result.output["data_from_research"]["revenue"].startswith("https://ir.")


# ---- validation ---------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("template,ctx", [("nope", {}), ("research_web", {}), ("research_web", {"research": {"urls": []}}), ("market_analysis", {"business": {}}),
                                          ("business_analysis", {"business": {}}), ("business_plan", {"research": RESEARCH}), ("financial_analysis", {"finance": {}}),
                                          ("company_analysis", {"finance": {"companies": []}}), ("paper_trade_analysis", {}), ("research_web", {"research": "x"}),
                                          ("research_web", {"research": {f"k{i}": 1 for i in range(31)}})])
def test_templates_are_validated_and_nothing_runs_when_data_is_missing(tmp_path, template, ctx):
    r, e = full_rig(tmp_path)
    try:
        res = go(e, template, **ctx)
    except InvalidGoalError:
        return                                                                                              # refused at creation
    assert res.status is G.BLOCKED and res.reason_code == "no_plan" and not r.orch.list() and not r.provider.calls


def test_goal_context_rejects_bypass_keys_and_unknown_keys_inside_blocks():
    for ctx in ({"template": "research_web", "research": {"urls": ["https://a.test/"], "confirmed": True}}, {"template": "x", "finance": {"force": 1}},
                {"template": "business_plan", "business": {"plan": {"skip_permissions": True}}}, {"live": True}, {"template": "research_web", "broker": {}}):
        with pytest.raises(InvalidGoalError):
            check_user_context(ctx)


def test_templates_are_explicit_never_guessed_from_the_objective(tmp_path):
    r, e = full_rig(tmp_path)
    for objective in ("Analysiere diese Aktie", "Erstelle mir einen Businessplan", "Recherchiere den Markt"):
        res = e.run(e.create(objective).goal_id)
        assert res.status is G.BLOCKED and not r.orch.list()


def test_every_template_is_registered_and_known():
    assert set(GP.ANALYSIS_TEMPLATES) == {"research_web", "market_analysis", "competitor_analysis", "business_analysis", "business_plan", "financial_analysis", "company_analysis",
                                          "paper_trade_analysis"}
    assert set(GP.ANALYSIS_TEMPLATES) <= GP.ANALYSIS_KINDS


def test_plan_validation_rejects_unknown_kinds(tmp_path):
    from jarvis.goals.fake import StaticPlanner, step
    r = plain_orch([BusinessAgent()])[0]
    e = GoalEngine(r, StaticPlanner(lambda g: [step(g, "s1", "business", caps=frozenset({"business.analyze"}), input={"kind": "format_disk"})]))
    res = e.run(e.create("x").goal_id)
    assert res.status is G.BLOCKED and "unknown analysis kind" in res.summary


# ---- failure isolation / limits -----------------------------------------------------------------------------------------------------------------------
def test_a_failed_research_step_blocks_the_dependent_analysis_and_nothing_is_invented(tmp_path):
    r, e = full_rig(tmp_path)
    res = go(e, "market_analysis", "Analysiere", research={"urls": ["https://slow.example.com/"], "questions": ["x"]})
    s = by(res)
    assert res.status is G.FAILED and s["s1"].status is StepStatus.FAILED and s["s2"].status is StepStatus.BLOCKED and s["s2"].result.error_code == "dependency_failed"
    assert not [t for t in r.orch.list() if t.agent_id == "business"]


def test_an_invalid_analysis_step_does_not_affect_other_goals(tmp_path):
    r, e = full_rig(tmp_path)
    bad = go(e, "financial_analysis", finance={"company": {"price": -5, "eps": "x"}})
    good = go(e, "financial_analysis", finance={"company": COMPANY})
    assert bad.status is G.FAILED and bad.steps[0].result.error_code == "invalid_input" and good.status is G.SUCCEEDED
    assert bad.steps[0].result.attempts == 1                                                                 # invalid input is never retried


def test_permission_denial_blocks_the_whole_chain_without_retry(tmp_path):
    r, e = full_rig(tmp_path, [ONCE, NO])
    res = go(e, "market_analysis", "Analysiere", research=RESEARCH)
    s = by(res)
    assert res.status is G.BLOCKED and s["s1"].status is StepStatus.BLOCKED and s["s1"].result.error_code == "permission_denied" and s["s1"].result.attempts == 1
    assert s["s2"].status is StepStatus.BLOCKED and not [t for t in r.orch.list() if t.agent_id == "business"] and not r.provider.calls_named("page.goto")


def test_goal_timeout_and_cancellation_with_a_slow_analysis_agent():
    slow = FakeAgent("business", {"business.analyze"}, behavior="wait")
    o, reg = plain_orch([slow], executor=None)
    from jarvis.agents import AgentPlanner
    from jarvis.goals.fake import StaticPlanner, step
    e = GoalEngine(o, StaticPlanner(lambda g: [step(g, "s1", "business", caps=frozenset({"business.analyze"}), input={"kind": "market_analysis"}), step(g, "ev", None, deps=("s1",))]),
                   cancel_wait=0.5)
    try:
        res = e.run(e.create("x", timeout=0.3).goal_id)
        assert res.status is G.TIMEOUT and slow.cancel_calls
        slow2 = e.create("y")
        slow.started.clear(); slow.release.clear()
        e.start(slow2.goal_id)
        wait_event(slow.started)
        e.cancel(slow2.goal_id)
        assert e.wait(slow2.goal_id, 10).status is G.CANCELLED
    finally:
        slow.release.set(); e.shutdown(1); o.shutdown(0.5)


def test_results_stay_bounded_inside_goals(tmp_path):
    r, e = full_rig(tmp_path)
    res = go(e, "paper_trade_analysis", "x", finance={"account": 1e9, "ideas": [{**IDEA, "thesis": "x" * 400} for _ in range(40)]})
    assert res.status is G.SUCCEEDED and len(json.dumps(res.steps[0].result.output)) < 10_000


def test_goal_results_are_not_saved_anywhere(tmp_path):
    r, e = full_rig(tmp_path)
    res = go(e, "financial_analysis", finance={"company": COMPANY})
    assert res.succeeded and not hasattr(e, "memory") and not [n for n in vars(e) if "memory" in n.lower()]
