"""WP04: Business-Finder ueber die Goal Engine - Vorlage `business_finder`, Kette Research -> Business -> Auswertung (Parent-Ergebnisse, keine Artefakt-Verdrahtung),
Planungsfehler, Abbruch/Not-Aus, Berechtigungen. Fake-Browser, kein Netz."""
from __future__ import annotations

import json

import pytest

from agents_util import FakeAgent, wait_event
from analysis_util import SHOP_A, SHOP_B, SHOP_C, make_rig, plain_orch
from browser_util import NO, ONCE
from jarvis.business.agent import BusinessAgent
from jarvis.goals import GoalEngine, GoalPlanner, GoalStatus, InvalidGoalError, StepStatus, check_user_context
from jarvis.goals import policy as GP
from jarvis.research.agent import ResearchAgent
from test_business_finder_units import FRAME, cand

G = GoalStatus
URLS = [SHOP_A, SHOP_B, SHOP_C]


def rig(tmp_path, answers=None):
    r = make_rig(tmp_path, answers, agents=[ResearchAgent(), BusinessAgent()])
    return r, GoalEngine(r.orch, GoalPlanner(r.planner), goal_timeout=60, step_timeout=30)


def go(engine, objective="Finde Geschäftsmodelle", **ctx):
    return engine.run(engine.create(objective, context={"template": "business_finder", **ctx}).goal_id)


def test_the_chain_is_research_then_one_business_finder_step_then_the_evaluation(tmp_path):
    r, e = rig(tmp_path)
    res = go(e, research={"urls": URLS, "questions": ["Preise Innenreinigung"]}, business={"frame": FRAME, "candidates": [cand()]})
    assert res.status is G.SUCCEEDED, res.summary
    assert [s.assigned_agent for s in res.steps] == ["research", "business", None]
    biz = res.steps[1].result.output
    assert biz["task"] == "business_finder" and {s["url"] for s in biz["sources"]} == set(URLS)                  # Research -> Business ueber Parent-Ergebnisse
    assert r.orch.describe(res.steps[1].result.task_id)["dependencies"] == [res.steps[0].result.task_id]
    assert biz["drafts"]["business_finder"]["candidates"][0]["break_even"]["status"] == "COMPUTED"
    assert len(json.dumps(biz)) <= GP.MAX_OUTPUT_CHARS and "preview" not in biz                                      # das Goal speichert das Ergebnis vollstaendig, nicht als Vorschau


def test_without_research_urls_the_finder_runs_on_given_data_only(tmp_path):
    r, e = rig(tmp_path)
    res = go(e, business={"frame": FRAME, "candidates": [cand(source_urls=[])]})
    assert res.status is G.SUCCEEDED and [s.assigned_agent for s in res.steps] == ["business", None]
    assert res.steps[0].result.output["confidence"]["level"] == "low" and not r.provider.calls


@pytest.mark.parametrize("ctx", [
    {}, {"business": {}}, {"business": {"candidates": [cand()]}}, {"business": {"frame": FRAME}}, {"business": {"frame": FRAME, "candidates": []}},
    {"business": {"frame": "x", "candidates": [cand()]}}, {"business": {"frame": FRAME, "candidates": "x"}},
    {"business": {"frame": FRAME, "candidates": [cand(name=f"M{i}") for i in range(6)]}},
    {"research": {"urls": [SHOP_A]}, "business": {"frame": FRAME, "candidates": [cand(source_urls=["https://other.example.com/"])]}},
])
def test_missing_or_oversized_input_is_refused_at_planning_and_nothing_runs(tmp_path, ctx):
    r, e = rig(tmp_path)
    try:
        res = go(e, **ctx)
    except InvalidGoalError:
        return
    assert res.status is G.BLOCKED and res.reason_code == "no_plan" and not r.orch.list() and not r.provider.calls
    assert "unknown template" not in res.summary                                                                 # abgelehnt wegen der Eingabe, nicht weil die Vorlage fehlt


def test_the_planner_adds_no_url_and_no_capability_beyond_the_given_ones():
    from jarvis.agents import AgentPlanner, AgentRegistry
    from jarvis.goals import Goal, GoalContext
    reg = AgentRegistry()
    for a in (ResearchAgent(), BusinessAgent()):
        reg.register(a)
    ctx = {"template": "business_finder", "research": {"urls": URLS}, "business": {"frame": FRAME, "candidates": [cand()]}}
    g = Goal("Finde Geschäftsmodelle")
    steps = GoalPlanner(AgentPlanner(reg)).plan(g, GoalContext(g.goal_id, g.objective, None, (), ctx), 20)
    assert [s.assigned_agent for s in steps] == ["research", "business", None]
    assert set().union(*(s.required_capabilities for s in steps)) == {"research.web", "business.analyze"}
    assert steps[0].input["urls"] == URLS and steps[1].input["kind"] == "business_finder" and steps[2].is_evaluation
    assert GP.known_urls([s.input for s in steps]) == frozenset(URLS)


def test_the_template_is_registered_and_bypass_keys_are_rejected():
    assert "business_finder" in GP.ANALYSIS_TEMPLATES and "business_finder" in GP.ANALYSIS_KINDS
    for ctx in ({"template": "business_finder", "business": {"frame": FRAME, "candidates": [cand()], "confirmed": True}},
                {"template": "business_finder", "business": {"frame": {**FRAME, "skip_permissions": True}, "candidates": [cand()]}}):
        with pytest.raises(InvalidGoalError):
            check_user_context(ctx)


def test_a_failed_research_step_blocks_the_finder_and_nothing_is_invented(tmp_path):
    r, e = rig(tmp_path)
    res = go(e, research={"urls": ["https://slow.example.com/"], "questions": ["x"]}, business={"frame": FRAME, "candidates": [cand(source_urls=["https://slow.example.com/"])]})
    s = {x.step_id: x for x in res.steps}
    assert res.status is G.FAILED and s["s2"].status is StepStatus.BLOCKED and not [t for t in r.orch.list() if t.agent_id == "business"]


def test_permission_denial_blocks_the_chain_without_retry(tmp_path):
    r, e = rig(tmp_path, [ONCE, NO])
    res = go(e, research={"urls": URLS}, business={"frame": FRAME, "candidates": [cand()]})
    s = {x.step_id: x for x in res.steps}
    assert res.status is G.BLOCKED and s["s1"].result.error_code == "permission_denied" and s["s1"].result.attempts == 1
    assert s["s2"].status is StepStatus.BLOCKED and not [t for t in r.orch.list() if t.agent_id == "business"]


def test_emergency_cancel_stops_the_chain_before_the_finder_runs():
    from jarvis.goals.fake import StaticPlanner, step

    class Spy(BusinessAgent):
        calls = 0

        def perform(self, task, ctx):
            Spy.calls += 1
            return super().perform(task, ctx)

    slow = FakeAgent("research", {"research.web"}, behavior="wait")
    o, _ = plain_orch([slow, Spy()], executor=None)
    e = GoalEngine(o, StaticPlanner(lambda g: [step(g, "s1", "research", caps=frozenset({"research.web"}), input={"kind": "research_web", "urls": [SHOP_A]}),
                                               step(g, "s2", "business", caps=frozenset({"business.analyze"}), deps=("s1",),
                                                    input={"kind": "business_finder", "frame": FRAME, "candidates": [cand()]}),
                                               step(g, "ev", None, deps=("s2",))]), cancel_wait=0.5)
    try:
        goal = e.create("Finder")
        e.start(goal.goal_id)
        wait_event(slow.started)
        e.cancel(goal.goal_id)
        assert e.wait(goal.goal_id, 10).status is G.CANCELLED and Spy.calls == 0
    finally:
        slow.release.set(); e.shutdown(1); o.shutdown(0.5)


def test_a_malformed_research_urls_value_is_refused_not_misread(tmp_path):
    r, e = rig(tmp_path)
    try:
        res = go(e, research={"urls": "https://wash-a.example.com/"}, business={"frame": FRAME, "candidates": [cand(source_urls=["h"])]})
    except InvalidGoalError:
        return
    assert res.status is G.BLOCKED and res.reason_code == "no_plan" and not r.orch.list()
