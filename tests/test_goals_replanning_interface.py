"""The optional replanning interface of GoalPlanner: callback in, validated steps out; the candidate is untrusted data."""
from __future__ import annotations

import pytest

from jarvis.agents import AgentPlanner, AgentRegistry
from jarvis.agents.fake import FakeAgent
from jarvis.goals import Goal, GoalContext, GoalPlanner, PlanningError, StepStatus
from jarvis.goals.fake import step

URL_A, URL_B = "https://a.example.com/", "https://b.example.com/"
RESEARCH = "Recherchiere die Quellen und Informationen (Recherche, Quellen)"


def registry():
    reg = AgentRegistry()
    reg.register(FakeAgent("research", {"research.web"}))
    reg.register(FakeAgent("business", {"business.analyze"}))
    return reg


def previous(goal):
    s1 = step(goal, "s1", "research", input={"kind": "research_web", "urls": [URL_A, URL_B]}, objective=RESEARCH)
    s2 = step(goal, "s2", "business", deps=("s1",), caps=frozenset({"business.analyze"}), input={"kind": "market_analysis"}, objective="Erstelle die Marktanalyse (Geschäftsmodell)")
    return (s1, s2, step(goal, "s3", None, deps=("s2",)))


def run_replan(raw, *, goal=None, attempt=1, max_steps=10, replanner=True):
    goal = goal or Goal("Analysiere den Markt")
    prev = tuple(s.with_status(StepStatus.RUNNING).with_result(__import__("jarvis.goals", fromlist=["GoalStepResult"]).GoalStepResult(s.step_id, StepStatus.FAILED if s.step_id == "s1" else StepStatus.BLOCKED, "x"))
                 if not s.is_evaluation and s.step_id == "s1" else s for s in previous(goal))
    seen = {}

    def cb(g, ctx, ms, fb):
        seen.update(goal=g, ctx=ctx, max_steps=ms, fb=fb)
        return raw
    planner = GoalPlanner(AgentPlanner(registry()), replanner=cb if replanner else None)
    return planner, seen, lambda: planner.replan(goal, GoalContext(goal.goal_id, goal.objective), max_steps, {"previous_plan": prev, "attempt": attempt})


def split_candidate():
    return [{"objective": RESEARCH, "capabilities": ["research.web"], "input": {"kind": "research_web", "urls": [URL_A]}},
            {"objective": RESEARCH, "capabilities": ["research.web"], "input": {"kind": "research_web", "urls": [URL_B]}, "depends_on": []},
            {"objective": "Erstelle die Marktanalyse (Geschäftsmodell)", "capabilities": ["business.analyze"], "input_from": "s2", "depends_on": [0, 1]},
            {"evaluate": True}]


def test_supports_replanning_only_with_a_replanner():
    assert GoalPlanner(AgentPlanner(registry()), replanner=lambda *a: []).supports_replanning
    assert not GoalPlanner(AgentPlanner(registry())).supports_replanning and not GoalPlanner(None, replanner=lambda *a: []).supports_replanning
    with pytest.raises(PlanningError, match="not available"):
        GoalPlanner(AgentPlanner(registry())).replan(Goal("x"), GoalContext("g-1", "x"), 5, {"previous_plan": ()})


def test_the_callback_gets_goal_context_limits_and_the_allowed_capabilities_only():
    planner, seen, call = run_replan(split_candidate())
    steps = call()
    fb = seen["fb"]
    assert seen["max_steps"] == 10 and fb["allowed_capabilities"] == frozenset({"research.web", "business.analyze"}) and fb["attempt"] == 1 and seen["goal"].objective == "Analysiere den Markt"
    assert [s.step_id for s in steps] == ["r1-s1", "r1-s2", "r1-s3", "r1-s4"]
    assert [s.assigned_agent for s in steps] == ["research", "research", "business", None]                      # agents come from the AgentPlanner, not from the candidate
    assert steps[2].dependencies == ("r1-s1", "r1-s2") and steps[3].is_evaluation and steps[3].dependencies == ("r1-s3",)
    assert steps[2].input == {"kind": "market_analysis"} and steps[0].input["urls"] == [URL_A]
    assert all(s.goal_id == seen["goal"].goal_id and s.status is StepStatus.PENDING for s in steps)


def test_an_evaluation_step_is_appended_when_the_candidate_has_none():
    _, _, call = run_replan(split_candidate()[:-1])
    steps = call()
    assert steps[-1].is_evaluation and steps[-1].dependencies == (steps[-2].step_id,)


@pytest.mark.parametrize("bad,why", [
    ([], "1..10 steps"), ("steps", "1..10 steps"), ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1", "agent": "ghost"}], "only the keys"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1", "tools": ["browser"]}], "only the keys"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1", "confirmed": True}], "only the keys"),
    ([{"objective": RESEARCH, "capabilities": ["coding.write"], "input_from": "s1"}], "outside the goal"),
    ([{"objective": RESEARCH, "capabilities": ["browser.read"], "input_from": "s1"}], "outside the goal"),
    ([{"objective": RESEARCH, "capabilities": ["magic.wand"], "input_from": "s1"}], "outside the goal"),
    ([{"objective": RESEARCH, "capabilities": ["research.web", "coding.write"], "input_from": "s1"}], "outside the goal"),
    ([{"objective": RESEARCH, "capabilities": [], "input_from": "s1"}], "capabilities"),
    ([{"objective": RESEARCH, "capabilities": "research.web", "input_from": "s1"}], "capabilities"),
    ([{"objective": "x", "capabilities": ["research.web"], "input_from": "s1"}], "objective"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"]}], "exactly one"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1", "input": {}}], "exactly one"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "zz"}], "input_from"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s3"}], "input_from"),                       # an evaluation step has no input to reuse
    ([{"objective": RESEARCH, "capabilities": ["business.analyze"], "input_from": "s1"}], "within those"),                  # reuse must keep the capabilities of the origin
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1", "depends_on": [3]}], "EARLIER"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1", "depends_on": [0]}], "EARLIER"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1", "depends_on": [-1]}], "EARLIER"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1", "depends_on": "0"}], "EARLIER"),
    ([{"evaluate": True}], "no work step"),
    ([{"evaluate": True}, {"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1"}], "last step"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1"}, {"evaluate": True, "objective": "x"}], "last step"),
    ([{"objective": "Erstelle die Marktanalyse (Geschäftsmodell)", "capabilities": ["business.analyze"], "input_from": "s2"}, {"evaluate": True}], "outstanding work"),   # drops the failed research
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input": {"kind": "research_web", "urls": ["https://evil.example.org/"]}}], "re-use URLs"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input": {"kind": "research_web", "urls": [URL_A], "confirmed": True}}], "invalid input"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input": {"kind": "research_web", "urls": [URL_A], "steps": []}}], "re-use URLs"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input": {"kind": "other", "urls": [URL_A]}}], "re-use URLs"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input": {"kind": "research_web", "urls": []}}], "re-use URLs"),
    ([{"objective": RESEARCH, "capabilities": ["research.web"], "input": "text"}], "invalid input"),
])
def test_unacceptable_candidates_are_refused(bad, why):
    _, _, call = run_replan(bad)
    with pytest.raises(PlanningError, match=why):
        call()


def test_a_step_no_agent_can_do_is_refused_by_the_agent_planner_not_guessed():
    cand = [{"objective": "Erstelle die Marktanalyse (Geschäftsmodell)", "capabilities": ["research.web"], "input_from": "s1"},
            {"objective": "Erstelle die Marktanalyse (Geschäftsmodell)", "capabilities": ["business.analyze"], "input_from": "s2"}, {"evaluate": True}]
    _, _, call = run_replan(cand)
    with pytest.raises(PlanningError, match="no agent can do"):
        call()


def test_a_candidate_cannot_exceed_the_step_limit():
    cand = [{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1"}] * 6 + [{"evaluate": True}]
    _, _, call = run_replan(cand, max_steps=5)
    with pytest.raises(PlanningError, match="1..5"):
        call()


def test_a_session_opened_by_a_reused_step_is_closed_again():
    goal = Goal("Prüfe das Projekt")
    reg = AgentRegistry()
    reg.register(FakeAgent("coding", {"coding.read"}))
    opener = step(goal, "s1", "coding", caps=frozenset({"coding.read"}), input={"steps": [{"action": "start", "workspace": "/w"}]}, objective="Analysiere das Projekt im Workspace (Code, Dateien, Projekt)")
    closer = step(goal, "s2", "coding", deps=("s1",), caps=frozenset({"coding.read"}), input={"steps": [{"action": "stop"}], "cleanup": "s1"}, objective="Beende die Projekt-Sitzung (Code, Projekt)")
    cand = [{"objective": "Analysiere das Projekt im Workspace (Code, Dateien, Projekt)", "capabilities": ["coding.read"], "input_from": "s1"}, {"evaluate": True}]
    planner = GoalPlanner(AgentPlanner(reg), replanner=lambda *a: cand)
    steps = planner.replan(goal, GoalContext(goal.goal_id, goal.objective), 10, {"previous_plan": (opener, closer), "attempt": 2})
    assert [s.step_id for s in steps] == ["r2-s1", "r2-s2", "r2-s3"] and steps[2].input["cleanup"] == "r2-s1" and steps[2].input["steps"] == [{"action": "stop"}]


def test_capabilities_the_goal_never_used_are_refused_even_if_an_agent_has_them():
    goal = Goal("Recherchiere")
    only_research = (step(goal, "s1", "research", input={"kind": "research_web", "urls": [URL_A]}, objective=RESEARCH).with_status(StepStatus.RUNNING),)
    cand = [{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1"},
            {"objective": "Erstelle die Marktanalyse (Geschäftsmodell)", "capabilities": ["business.analyze"], "input": {"kind": "market_analysis"}, "depends_on": [0]}, {"evaluate": True}]
    planner = GoalPlanner(AgentPlanner(registry()), replanner=lambda *a: cand)                            # the registry DOES have a business agent
    with pytest.raises(PlanningError, match="outside the goal"):
        planner.replan(goal, GoalContext(goal.goal_id, goal.objective), 10, {"previous_plan": only_research, "attempt": 1})


def test_the_model_cannot_write_input_for_steps_that_read_files_run_code_or_change_things():
    goal = Goal("Prüfe das Projekt")
    reg = AgentRegistry()
    reg.register(FakeAgent("coding", {"coding.read", "coding.write", "coding.test"}))
    prev = (step(goal, "s1", "coding", caps=frozenset({"coding.read", "coding.write", "coding.test"}), input={"steps": [{"action": "info"}]},
                 objective="Analysiere das Projekt im Workspace (Code, Dateien, Projekt)"),)
    for caps in (["coding.read"], ["coding.write"], ["coding.test"], ["coding.read", "coding.write"]):
        cand = [{"objective": "Analysiere das Projekt im Workspace (Code, Dateien, Projekt)", "capabilities": caps,
                 "input": {"steps": [{"action": "write", "path": "evil.py", "content": "boom"}]}}, {"evaluate": True}]
        with pytest.raises(PlanningError, match="input may only be written"):
            GoalPlanner(AgentPlanner(reg), replanner=lambda *a, c=cand: c).replan(goal, GoalContext(goal.goal_id, goal.objective), 10, {"previous_plan": prev, "attempt": 1})
    ok = [{"objective": "Analysiere das Projekt im Workspace (Code, Dateien, Projekt)", "capabilities": ["coding.read", "coding.write", "coding.test"], "input_from": "s1"}, {"evaluate": True}]
    assert GoalPlanner(AgentPlanner(reg), replanner=lambda *a: ok).replan(goal, GoalContext(goal.goal_id, goal.objective), 10, {"previous_plan": prev, "attempt": 1})
