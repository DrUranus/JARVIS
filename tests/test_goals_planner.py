"""GoalPlanner, plan validation and GoalEvaluator."""
from __future__ import annotations

import pytest

from jarvis.agents import AgentPlanner, AgentRegistry, AgentStatus, TaskStatus
from jarvis.agents.adapters import BrowserAgent, CodingAgent, ComputerAgent, ResearchAgent
from jarvis.goals import (Decision, Goal, GoalContext, GoalEvaluator, GoalPlanner, GoalStatus, GoalStep, GoalStepResult, InvalidPlanError,
                          PlanningError, StepStatus, Verdict, validate_plan)
from jarvis.goals.validation import longest_chain


def registry():
    reg = AgentRegistry()
    for a in (ResearchAgent(), BrowserAgent(), CodingAgent(), ComputerAgent()):
        reg.register(a)
    return reg


def plan(objective: str, ctx: dict | None = None, *, reg=None, max_steps: int = 20, **kw):
    reg = reg or registry()
    g = Goal(objective)
    return g, GoalPlanner(AgentPlanner(reg), **kw).plan(g, GoalContext(g.goal_id, objective, None, (), ctx or {}), max_steps)


# ---- planner ---------------------------------------------------------------------------------------------------------------------------
def test_web_goal_example_from_the_spec():
    g, steps = plan("Analysiere example.com und finde die Öffnungszeiten")
    assert [s.step_id for s in steps] == ["s1", "s2"]
    read, check = steps
    assert read.assigned_agent == "research" and read.required_capabilities == {"research.web"} and read.input == {"url": "https://example.com/"}
    assert check.is_evaluation and check.dependencies == ("s1",) and check.assigned_agent is None
    assert all(s.goal_id == g.goal_id and s.status is StepStatus.PENDING for s in steps)
    validate_plan(g, steps, max_steps=20)


def test_url_from_objective_or_context():
    assert plan("Lies https://example.org/info bitte")[1][0].input["url"] == "https://example.org/info"
    assert plan("Lies die Seite", {"url": "https://example.net/x"})[1][0].input["url"] == "https://example.net/x"


def test_coding_goal_chain_with_cleanup():
    g, steps = plan("Prüfe das Projekt und führe die Tests aus", {"workspace": "/w/proj", "runner": "python -m unittest"})
    ids = [s.step_id for s in steps]
    assert ids == ["s1", "s2", "s3", "s4"]
    analyse, test, check, close = steps
    assert analyse.assigned_agent == "coding" and analyse.required_capabilities == {"coding.read"}
    assert analyse.input["steps"][0] == {"action": "start", "workspace": "/w/proj"}
    assert test.required_capabilities == {"coding.test"} and test.input["steps"] == [{"action": "test", "runner": "python -m unittest"}]
    assert test.dependencies == ("s1",) and check.is_evaluation and check.dependencies == ("s2",)
    assert close.input["cleanup"] == "s1" and set(close.dependencies) == {"s1", "s2", "s3"}
    validate_plan(g, steps, max_steps=20)


def test_coding_goal_with_edits_writes_then_tests():
    edits = [{"path": "calc.py", "content": "x = 1\n", "mode": "overwrite"}]
    g, steps = plan("Ändere die Datei calc.py", {"workspace": "/w", "edits": edits})
    assert [s.required_capabilities for s in steps[:3]] == [{"coding.read"}, {"coding.write"}, {"coding.test"}]
    assert steps[1].input["steps"] == [{"action": "write", **edits[0]}]
    validate_plan(g, steps, max_steps=20)


def test_coding_fix_without_edits_is_not_invented():
    with pytest.raises(PlanningError, match="explicit edits"):
        plan("Behebe den Fehler im Code", {"workspace": "/w"})


def test_screen_goal_uses_only_screen_capability():
    g, steps = plan("Zeige mir die offenen Fenster")
    assert steps[0].assigned_agent == "computer" and steps[0].required_capabilities == {"computer.screen"}
    assert steps[0].input["steps"] == [{"tool": "screen", "action": "windows"}]
    with pytest.raises(PlanningError):
        plan("Klicke im Fenster auf OK")


def test_unknown_ambiguous_and_unplannable_goals():
    for obj, ctx in (("Hilf mir bei meinem Leben", {}), ("Mach etwas", {}), ("Lies example.com", {"workspace": "/w"})):
        with pytest.raises(PlanningError):
            plan(obj, ctx)


def test_no_matching_agent_is_a_planning_error_not_an_invented_one():
    reg = registry()
    reg.get("research").state.transition(AgentStatus.DISABLED, "off")
    with pytest.raises(PlanningError, match="no agent"):
        plan("Lies example.com", reg=reg)
    with pytest.raises(PlanningError):
        GoalPlanner(None).plan(Goal("x"), GoalContext("g", "x"), 5)


def test_max_steps_is_enforced_by_the_planner():
    with pytest.raises(PlanningError, match="limit"):
        plan("Prüfe das Projekt und führe die Tests aus", {"workspace": "/w"}, max_steps=2)


def test_edits_and_runner_are_validated():
    for ctx in ({"workspace": "/w", "edits": "x"}, {"workspace": "/w", "edits": [{"nopath": 1}]}, {"workspace": "/w", "runner": "rm -rf /"},
                {"workspace": "/w", "edits": [{"path": "a", "evil": 1}]}, {"workspace": "/w", "read_paths": ["a"] * 9}):
        with pytest.raises(PlanningError):
            plan("Prüfe das Projekt mit Tests", ctx)


def test_planner_only_uses_known_capabilities_and_existing_agents():
    for obj, ctx in (("Lies example.com", {}), ("Prüfe das Projekt mit Tests", {"workspace": "/w"}), ("Zeige die Fenster", {})):
        g, steps = plan(obj, ctx)
        for s in steps:
            assert s.required_capabilities <= {"research.web", "coding.read", "coding.write", "coding.test", "computer.screen", "browser.read"}
            assert s.assigned_agent in (None, "research", "coding", "computer")


# ---- validation ------------------------------------------------------------------------------------------------------------------------
def S(sid: str, deps=(), agent="research", **kw):
    kw.setdefault("input", {"url": "https://a.test/"})
    kw.setdefault("required_capabilities", frozenset({"research.web"}))
    return GoalStep(sid, "g-1", "do it", assigned_agent=agent, dependencies=tuple(deps), **kw)


G = Goal("x", goal_id="g-1")


def bad(steps, match=None, **kw):
    kw.setdefault("max_steps", 20)
    with pytest.raises(InvalidPlanError, match=match):
        validate_plan(G, steps, **kw)


def test_valid_plan_passes_and_is_returned_as_tuple():
    out = validate_plan(G, [S("a"), S("b", ["a"])], max_steps=5, agent_exists=lambda a: a == "research")
    assert isinstance(out, tuple) and len(out) == 2


def test_invalid_plans_are_rejected():
    bad([], "no steps")
    bad("steps", "no steps")  # type: ignore[arg-type]
    bad([S("a"), S("a")], "duplicate")
    bad([S("a", ["zz"])], "unknown step")
    bad([S("a", ["b"]), S("b", ["a"])], "cycle")
    bad([S("a", ["b"]), S("b", ["c"]), S("c", ["a"])], "cycle")
    bad([S("a"), S("b")], "at most", max_steps=1)
    bad([S("a", agent="ghost")], "unknown agent", agent_exists=lambda a: False)
    bad([S("a", agent=None)], "no agent")
    bad([S("a", required_capabilities=frozenset({"magic.wand"}))], "unknown capability")
    bad([S("a", required_capabilities=frozenset())], "no capability")
    bad([S("a", max_attempts=3)], "attempts", max_attempts=2)
    bad([S("a", timeout=999)], "timeout", max_step_timeout=10)
    bad([S("a", input={"url": "file:///etc/passwd"})], "url")
    bad([S("a", input={})], "steps")
    bad([S("a", input={"steps": ["x"]})], "tool steps")
    bad([S("a", input={"steps": [{"action": "click", "confirmed": True}]})], "forbidden")
    bad([S("a", input={"steps": [{"action": "x", "nested": {"skip_permissions": 1}}]})], "forbidden")
    bad([GoalStep("a", "other", "o", frozenset({"research.web"}), "research", input={"url": "https://a.test/"})], "another goal")
    bad([S("a", status=StepStatus.RUNNING)], "PENDING")
    bad([S("a", input={"steps": [{"action": "x"}], "cleanup": "zz"})], "cleanup")
    bad([GoalStep("e", "g-1", "check", frozenset(), None, ("a",), input={"evaluate": True}).with_status(StepStatus.RUNNING)], "PENDING")
    bad([GoalStep("e", "g-1", "check", frozenset(), None, (), input={"evaluate": True})], "depend")
    bad(["not a step"], "GoalStep")  # type: ignore[list-item]


def test_depth_limit():
    chain = [S("s0")] + [S(f"s{i}", [f"s{i - 1}"]) for i in range(1, 12)]
    bad(chain, "chain", max_depth=10)
    validate_plan(G, chain, max_steps=20, max_depth=12)
    assert longest_chain(chain) == 12


def test_very_deep_chain_validates_without_recursion_error():
    chain = [S("s0")] + [S(f"s{i}", [f"s{i - 1}"]) for i in range(1, 50)]
    assert longest_chain(chain) == 50
    bad(chain, "chain", max_steps=50)           # hard depth limit 20


def test_invalid_plan_is_never_partially_started():
    from goals_util import FakeAgent, rig, step
    agent = FakeAgent("fake")
    def make(goal):   # the second step names an agent that does not exist: the first one must not run either
        return [step(goal, "s1", "fake"), step(goal, "s2", "ghost", deps=("s1",))]
    engine, *_ = rig([agent], make)
    res = engine.run(engine.create("x").goal_id)
    assert res.status is GoalStatus.BLOCKED and res.reason_code == "invalid_plan" and not agent.tasks and res.steps == ()


# ---- evaluator ------------------------------------------------------------------------------------------------------------------------
def ST(sid, status, deps=(), **kw):
    s = GoalStep(sid, "g-1", "o", frozenset({"research.web"}), "research", tuple(deps), **kw)
    if status is StepStatus.PENDING:
        return s
    s = s.with_status(StepStatus.RUNNING if status is not StepStatus.BLOCKED else StepStatus.BLOCKED)
    if status in (StepStatus.RUNNING, StepStatus.BLOCKED):
        return s
    return s.with_result(GoalStepResult(sid, status, "r"))


E = GoalEvaluator()


def test_all_succeeded_reached():
    assert E.decide([ST("a", StepStatus.SUCCEEDED), ST("b", StepStatus.SUCCEEDED, ["a"])]).kind is Decision.REACHED


def test_next_and_partial():
    d = E.decide([ST("a", StepStatus.SUCCEEDED), ST("b", StepStatus.PENDING, ["a"]), ST("c", StepStatus.PENDING, ["b"])])
    assert d.kind is Decision.NEXT and d.ready == ("b",)
    d = E.decide([ST("a", StepStatus.PENDING), ST("b", StepStatus.PENDING)])
    assert d.ready == ("a", "b")                       # independent steps are recognised together (the orchestrator decides concurrency)


def test_wait_when_only_running():
    assert E.decide([ST("a", StepStatus.RUNNING), ST("b", StepStatus.PENDING, ["a"])]).kind is Decision.WAIT


def test_failed_blocked_timeout_cancel_decisions():
    assert E.decide([ST("a", StepStatus.FAILED), ST("b", StepStatus.PENDING, ["a"])]).kind is Decision.FAILED
    assert E.decide([ST("a", StepStatus.TIMEOUT)]).kind is Decision.FAILED
    assert E.decide([ST("a", StepStatus.BLOCKED)]).kind is Decision.BLOCKED
    assert E.decide([ST("a", StepStatus.FAILED), ST("b", StepStatus.RUNNING)]).kind is Decision.WAIT       # fail fast: no new steps, wait for running ones
    assert E.decide([ST("a", StepStatus.PENDING)], cancelled=True).kind is Decision.CANCELLED
    assert E.decide([ST("a", StepStatus.PENDING)], timed_out=True).kind is Decision.TIMEOUT
    assert E.decide([ST("a", StepStatus.SUCCEEDED)], cancelled=True, timed_out=True).kind is Decision.CANCELLED


def test_no_steps_and_unrunnable_steps():
    assert E.decide([]).kind is Decision.FAILED
    assert E.decide([ST("a", StepStatus.PENDING, ["zz"])]).kind is Decision.BLOCKED     # nothing can ever run


def test_dependency_blocking_is_transitive_and_has_no_bypass():
    steps = [ST("a", StepStatus.FAILED), ST("b", StepStatus.PENDING, ["a"]), ST("c", StepStatus.PENDING, ["b"]), ST("d", StepStatus.PENDING)]
    assert set(E.blocked_by_dependencies(steps)) == {"b", "c"}
    for bad_status in (StepStatus.BLOCKED, StepStatus.CANCELLED, StepStatus.TIMEOUT):
        assert E.blocked_by_dependencies([ST("a", bad_status), ST("b", StepStatus.PENDING, ["a"])]) == ("b",)
    assert E.blocked_by_dependencies([ST("a", StepStatus.SUCCEEDED), ST("b", StepStatus.PENDING, ["a"])]) == ()


def test_retry_decisions():
    s = ST("a", StepStatus.PENDING, max_attempts=2).with_status(StepStatus.RUNNING).with_attempt()
    assert E.judge(s, TaskStatus.FAILED, "timeout").kind is Verdict.RETRY
    assert E.judge(s, TaskStatus.FAILED, "agent_crashed").kind is Verdict.RETRY
    s2 = s.with_attempt()                               # attempts used up
    v = E.judge(s2, TaskStatus.FAILED, "timeout")
    assert v.kind is Verdict.FINAL and v.status is StepStatus.TIMEOUT
    assert E.judge(s, TaskStatus.FAILED, "permission_denied").kind is Verdict.FINAL
    assert E.judge(s, TaskStatus.FAILED, "something").status is StepStatus.FAILED
    assert E.judge(s, TaskStatus.BLOCKED, "permission_denied").status is StepStatus.BLOCKED
    assert E.judge(s, TaskStatus.CANCELLED, "cancelled").status is StepStatus.CANCELLED
    assert E.judge(s, TaskStatus.SUCCEEDED, None).kind is Verdict.DONE
    for weird in (TaskStatus.PENDING, TaskStatus.RUNNING):
        assert E.judge(s, weird, None).status is StepStatus.FAILED                   # never mistaken for success


def test_evaluation_step_check():
    ev = GoalStep("e", "g-1", "check", frozenset(), None, ("a",), input={"evaluate": True})
    ok = GoalStepResult("a", StepStatus.SUCCEEDED, "read 12 characters", {"text": "hello"})
    assert E.check_evaluation(ev, [ok])[0]
    assert not E.check_evaluation(ev, [])[0]
    assert not E.check_evaluation(ev, [GoalStepResult("a", StepStatus.SUCCEEDED, "read 0 characters", {"text": ""})])[0]
    assert not E.check_evaluation(ev, [GoalStepResult("a", StepStatus.FAILED, "x")])[0]


def test_evaluation_does_not_turn_a_reported_failure_into_success():
    ev = GoalStep("e", "g-1", "check", frozenset(), None, ("a",), input={"evaluate": True})
    failing_tests = GoalStepResult("a", StepStatus.SUCCEEDED, "1 step(s) done", {"steps": [{"action": "test", "ok": True, "output": {"passed": False}}]})
    ok, msg = E.check_evaluation(ev, [failing_tests])
    assert not ok and "failure" in msg
    assert not E.check_evaluation(ev, [GoalStepResult("a", StepStatus.SUCCEEDED, "x", {"steps": [{"action": "goto", "ok": False}]})])[0]
    assert E.check_evaluation(ev, [GoalStepResult("a", StepStatus.SUCCEEDED, "x", {"steps": [{"action": "test", "ok": True, "output": {"passed": True}}]})])[0]
