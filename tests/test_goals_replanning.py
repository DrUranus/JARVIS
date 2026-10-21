"""Controlled replanning end to end: real GoalEngine + real AgentOrchestrator + real GoalPlanner/AgentPlanner/validate_plan, a MOCK language model
(no network) and scripted agents. The model only ever sees redacted, bounded data and can only re-arrange what the goal already uses."""
from __future__ import annotations

import json

import pytest

from agents_util import FakeAgent, FakeClock, InlineExecutor, ManualScheduler, wait_event
from goals_util import HookAgent, MonoClock
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry
from jarvis.goals import GoalEngine, GoalPlanner, GoalStatus, StepStatus
from jarvis.goals import policy as GP
from jarvis.goals.fake import step
from jarvis.goals.replanner import LLMReplanner
from jarvis.errors import LLMError
from jarvis.llm.base import LLMProvider, LLMRequest, LLMResponse
from jarvis.llm.mock import MockProvider
from jarvis.redaction import SecretDetector

G = GoalStatus
URL_A, URL_B = "https://a.example.com/", "https://b.example.com/"
RESEARCH = "Recherchiere die Quellen und Informationen (Recherche, Quellen)"
SECRET = "hunter2hunter2"


def split(urls=(URL_A, URL_B), biz="s2"):
    """A valid, structurally different candidate: one research step per URL, then the business step reusing its old input."""
    cand = [{"objective": RESEARCH, "capabilities": ["research.web"], "input": {"kind": "research_web", "urls": [u]}, "depends_on": []} for u in urls]
    cand.append({"objective": "Erstelle die Marktanalyse (Geschäftsmodell)", "capabilities": ["business.analyze"], "input_from": biz, "depends_on": list(range(len(urls)))})
    cand.append({"evaluate": True})
    return {"steps": cand, "rationale": "read the sources one by one"}


class InitialPlanner(GoalPlanner):
    """The first plan is fixed (research of two URLs -> business analysis -> evaluation); replanning is the REAL GoalPlanner.replan."""

    def plan(self, goal, ctx, max_steps):
        return self._build(goal, [{"objective": RESEARCH, "caps": {"research.web"}, "input": {"kind": "research_web", "urls": [URL_A, URL_B]}},
                                  {"objective": "Erstelle die Marktanalyse (Geschäftsmodell)", "caps": {"business.analyze"}, "input": {"kind": "market_analysis"}},
                                  {"evaluate": True}])


class Rig:
    def __init__(self, replies, *, research=None, business=None, provider=None, replanner=True, max_attempts=2, clock=None, **engine_kw):
        self.research = research or FakeAgent("research", {"research.web"}, script=["failure"] * max_attempts, failure_code="step_failed")
        self.business = business or FakeAgent("business", {"business.analyze"})
        reg = AgentRegistry()
        reg.register(self.research)
        reg.register(self.business)
        self.orch = AgentOrchestrator(reg, scheduler=ManualScheduler(), clock=FakeClock(), executor=InlineExecutor())
        self.replies = list(replies)
        self.provider = provider or MockProvider(self._reply)
        replanner_obj = LLMReplanner(self.provider, detector=SecretDetector([SECRET])) if replanner else None
        self.planner = InitialPlanner(AgentPlanner(reg), max_attempts=max_attempts, replanner=replanner_obj)
        engine_kw.setdefault("cancel_wait", 0.3)
        self.engine = GoalEngine(self.orch, self.planner, max_attempts=max_attempts, detector=SecretDetector([SECRET]), clock=clock, **engine_kw)

    def _reply(self, request: LLMRequest) -> str:
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return r if isinstance(r, str) else json.dumps(r)

    def run(self, objective="Analysiere den Markt für Fahrzeugaufbereitung", **kw):
        return self.engine.run(self.engine.create(objective, **kw).goal_id)

    @property
    def calls(self):
        return len(self.provider.calls)


def ids(res):
    return [s.step_id for s in res.steps]


# ---- 1. success ----------------------------------------------------------------------------------------------------------------------------------
def test_alternative_plan_after_a_retryable_failure_reaches_the_goal():
    r = Rig([split()])
    res = r.run()
    assert res.status is G.SUCCEEDED and res.replans == 1 and r.calls == 1
    assert ids(res) == ["s1", "s2", "s3", "r1-s1", "r1-s2", "r1-s3", "r1-s4"]
    by = {s.step_id: s for s in res.steps}
    assert by["s1"].status is StepStatus.FAILED and by["s1"].result.attempts == 2 and by["s1"].result.error_code == "step_failed"          # the failure stays in the audit trail
    assert by["s2"].status is StepStatus.BLOCKED and by["s2"].result.error_code == "dependency_failed" and by["s3"].status is StepStatus.BLOCKED
    assert all(by[i].status is StepStatus.SUCCEEDED for i in ("r1-s1", "r1-s2", "r1-s3", "r1-s4"))
    assert "replan 1 accepted" in " ".join(res.warnings) and "after 1 replan" in res.summary and res.goal.objective == "Analysiere den Markt für Fahrzeugaufbereitung"
    assert [t.input.get("urls") for t in r.research.tasks[2:]] == [[URL_A], [URL_B]] and len(r.business.tasks) == 1                       # the new plan really ran


def test_the_new_plan_gets_its_dependencies_and_results_through_the_orchestrator():
    r = Rig([split()])
    res = r.run()
    biz = res.steps[-2].result
    assert res.status is G.SUCCEEDED and set(r.orch.describe(biz.task_id)["dependencies"]) == {res.steps[3].result.task_id, res.steps[4].result.task_id}


def test_the_model_sees_redacted_bounded_data_and_the_rules_not_outputs():
    r = Rig([split()], research=FakeAgent("research", {"research.web"}, script=["failure", "failure"], failure_code="step_failed", output={"text": "GEHEIMER-OUTPUT"}))
    r.run(f"Analysiere den Markt, Zugangscode {SECRET}")
    req = r.provider.calls[0]
    system, user = req.messages[0].content, req.messages[1].content
    assert SECRET not in system + user and "GEHEIMER-OUTPUT" not in user and req.temperature == 0.0 and req.max_tokens
    data = json.loads(user)
    assert data["goal"]["objective"].startswith("Analysiere den Markt") and data["data"]["failed_step"]["id"] == "s1" and data["data"]["failed_step"]["error_code"] == "step_failed"
    assert sorted(data["allowed_capabilities"]) == ["business.analyze", "research.web"] and data["max_steps"] <= 20 and data["attempt"] == 1
    assert [s["id"] for s in data["data"]["previous_plan"]] == ["s1", "s2", "s3"] and "untrusted" in system.lower() and "JSON" in system


# ---- 2. attempt limit -----------------------------------------------------------------------------------------------------------------------------
def test_at_most_two_additional_planning_attempts_even_if_all_are_rejected():
    r = Rig(["not json"])
    res = r.run()
    assert res.status is G.FAILED and r.calls == 2 and res.replans == 0 and len([w for w in res.warnings if "rejected" in w]) == 2
    assert {s.step_id for s in res.steps} == {"s1", "s2", "s3"} and not r.business.tasks


def test_two_accepted_plans_that_both_fail_end_the_goal_without_a_third_attempt():
    r = Rig([split(), split((URL_A,), biz="r1-s3")], research=FakeAgent("research", {"research.web"}, behavior="failure", failure_code="step_failed"), max_attempts=1)
    res = r.run()
    assert res.status is G.FAILED and res.replans == 2 and r.calls == 2
    assert [i for i in ids(res) if i.startswith("r2-")] and not [i for i in ids(res) if i.startswith("r3-")] and not r.business.tasks


def test_a_rejected_attempt_counts_and_the_model_hears_why():
    r = Rig(["nope", split()])
    res = r.run()
    assert res.status is G.SUCCEEDED and r.calls == 2 and res.replans == 1 and ids(res)[3].startswith("r2-")
    assert json.loads(r.provider.calls[1].messages[1].content)["data"]["rejected_previous_candidate"].startswith("the language model reply is not valid JSON")


# ---- 3./4. when NOT to replan --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("code", ["permission_denied", "invalid_input", "halted", "tool_unavailable", "capability_not_allowed", "agent_disabled", "unknown_agent"])
def test_fatal_error_codes_never_trigger_replanning(code):
    r = Rig([split()], research=FakeAgent("research", {"research.web"}, behavior="failure", failure_code=code))
    res = r.run()
    assert res.status is G.FAILED and r.calls == 0 and res.replans == 0 and ids(res) == ["s1", "s2", "s3"]


def test_a_permission_denial_blocks_without_replanning():
    r = Rig([split()], research=FakeAgent("research", {"research.web"}, behavior="blocked"))
    res = r.run()
    assert res.status is G.BLOCKED and r.calls == 0 and res.replans == 0


def test_an_unknown_error_code_is_not_retryable_and_not_replanned():
    r = Rig([split()], research=FakeAgent("research", {"research.web"}, behavior="failure", failure_code="mystery"))
    assert r.run().status is G.FAILED and r.calls == 0


def test_a_failed_evaluation_is_not_replanned_because_its_code_is_not_retryable():
    r = Rig([split()], research=FakeAgent("research", {"research.web"}, summary="", output=None), business=FakeAgent("business", {"business.analyze"}, summary="", output=None))
    res = r.run()
    assert res.status is G.FAILED and r.calls == 0 and res.steps[-1].result.error_code == "evaluation_failed"


def test_no_replanning_after_a_cancel():
    holder = {}
    research = HookAgent("research", {"research.web"}, behavior="failure", failure_code="step_failed", hook=lambda n: holder["engine"].cancel(holder["gid"]))
    r = Rig([split()], research=research)
    holder["engine"] = r.engine
    g = r.engine.create("Analysiere den Markt")
    holder["gid"] = g.goal_id
    res = r.engine.run(g.goal_id)
    assert res.status is G.CANCELLED and r.calls == 0 and res.replans == 0


def test_no_replanning_after_the_goal_timeout():
    clock = MonoClock()
    research = HookAgent("research", {"research.web"}, behavior="failure", failure_code="step_failed", hook=lambda n: setattr(clock, "t", clock.t + 10_000))
    r = Rig([split()], research=research, clock=clock, goal_timeout=60)
    res = r.run()
    assert res.status is G.TIMEOUT and r.calls == 0 and res.replans == 0


def test_cancel_or_timeout_while_the_model_is_thinking_discards_the_plan():
    holder = {}

    def slow_model(request):
        holder["engine"].cancel(holder["gid"])
        return json.dumps(split())
    r = Rig([], provider=MockProvider(slow_model))
    holder["engine"] = r.engine
    g = r.engine.create("Analysiere den Markt")
    holder["gid"] = g.goal_id
    res = r.engine.run(g.goal_id)
    assert res.status is G.CANCELLED and res.replans == 0 and not r.business.tasks and not [i for i in ids(res) if i.startswith("r")]
    clock = MonoClock()
    r2 = Rig([], provider=MockProvider(lambda req: (setattr(clock, "t", clock.t + 10_000), json.dumps(split()))[1]), clock=clock, goal_timeout=60)
    res2 = r2.run()
    assert res2.status in (G.TIMEOUT, G.FAILED) and res2.replans == 0 and not r2.business.tasks


def test_a_cancel_during_the_first_attempt_prevents_the_second():
    holder = {}

    def model(request):
        holder["engine"].cancel(holder["gid"])
        return "not json"
    r = Rig([], provider=MockProvider(model))
    holder["engine"] = r.engine
    g = r.engine.create("Analysiere den Markt")
    holder["gid"] = g.goal_id
    res = r.engine.run(g.goal_id)
    assert res.status is G.CANCELLED and r.calls == 1


# ---- 5.-9. invalid candidates ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("reply,why", [
    ("this is prose, not json", "not valid JSON"), ("", "no text"), ("[1, 2]", "JSON object"), ("{}", "non-empty list"), ('{"steps": "x"}', "non-empty list"),
    ('{"steps": [1]}', "non-empty list"), ('{"steps": [{"evaluate": true}], "extra": 1}', "JSON object"), ("x" * (GP.MAX_REPLAN_REPLY_CHARS + 1), "too long"),
    ("{" * 5000, "not valid JSON"), ('{"steps": [{"evaluate": true}]}', "no work step")])
def test_invalid_model_replies_are_rejected_and_the_goal_fails_safely(reply, why):
    r = Rig([reply])
    res = r.run()
    assert res.status is G.FAILED and res.replans == 0 and why in " ".join(res.warnings) and r.calls == 2 and not r.business.tasks


def test_json_in_a_code_fence_is_accepted():
    assert Rig(["```json\n" + json.dumps(split()) + "\n```"]).run().status is G.SUCCEEDED


def bad(mutate):
    d = split()
    mutate(d["steps"])
    return d


@pytest.mark.parametrize("candidate,why", [
    (bad(lambda s: s[0].update(capabilities=["coding.write"])), "outside the goal"),                       # unknown / unsupported capability
    (bad(lambda s: s[0].update(capabilities=["magic.wand"])), "outside the goal"),
    (bad(lambda s: s[0].update(capabilities=["research.web", "computer.input"])), "outside the goal"),
    (bad(lambda s: s[0].update(agent="ghost")), "only the keys"),                                          # the model cannot name agents
    (bad(lambda s: s[0].update(tools=["computer"])), "only the keys"),
    (bad(lambda s: s[0].update(permission="green")), "only the keys"),
    (bad(lambda s: s[0].update(confirmed=True)), "only the keys"),
    (bad(lambda s: s[0].update(input={"kind": "research_web", "urls": ["https://evil.example.org/"]})), "re-use URLs"),
    (bad(lambda s: s[2].update(depends_on=[2])), "EARLIER"),                                               # invalid dependency / self reference
    (bad(lambda s: s[2].update(depends_on=[7])), "EARLIER"),
    (bad(lambda s: s[0].update(depends_on=[1])), "EARLIER"),                                               # a cycle can only be written as a forward reference
    (bad(lambda s: s[2].update(depends_on=[0, 0])), "EARLIER"),
    (bad(lambda s: s.__setitem__(slice(None), s[:2] + [{"evaluate": True}])), "outstanding work"),         # drops the business part of the goal
    (bad(lambda s: s.__setitem__(slice(None), [{**s[2], "depends_on": []}, s[3]])), "outstanding work"),                         # drops the research part
    (bad(lambda s: s.__setitem__(slice(None), s * 8)), "1.."),                                            # too many steps
    (bad(lambda s: s[0].update(objective="x")), "objective"),
])
def test_unacceptable_candidates_end_the_goal_failed_and_nothing_of_them_runs(candidate, why):
    r = Rig([candidate])
    res = r.run()
    assert res.status is G.FAILED and res.replans == 0 and why in " ".join(res.warnings) and not r.business.tasks and len(r.research.tasks) == 2


def test_a_step_that_no_agent_can_do_is_refused():
    d = split()
    d["steps"][0]["objective"] = "Erstelle die Marktanalyse (Geschäftsmodell)"                              # business wording, research capability: the AgentPlanner finds nobody
    res = Rig([d]).run()
    assert res.status is G.FAILED and "no agent can do" in " ".join(res.warnings)


def test_a_plan_that_is_structurally_identical_is_rejected():
    same = {"steps": [{"objective": RESEARCH, "capabilities": ["research.web"], "input_from": "s1"},
                      {"objective": "Erstelle die Marktanalyse (Geschäftsmodell)", "capabilities": ["business.analyze"], "input_from": "s2"}, {"evaluate": True}]}
    r = Rig([same])
    res = r.run()
    assert res.status is G.FAILED and "same structure" in " ".join(res.warnings) and r.calls == 2 and res.replans == 0
    reworded = json.loads(json.dumps(same))
    reworded["steps"][0]["objective"] = "Recherchiere nochmal anders formuliert (Quellen, Recherche)"
    assert "same structure" in " ".join(Rig([reworded]).run().warnings)                                    # new wording is not a new plan


def test_an_accepted_replan_is_not_proposed_again():
    r = Rig([split(), split(biz="r1-s3")], research=FakeAgent("research", {"research.web"}, behavior="failure", failure_code="step_failed"), max_attempts=1)
    res = r.run()
    assert res.status is G.FAILED and res.replans == 1 and r.calls == 2 and "same structure" in " ".join(res.warnings)


class CyclicPlanner(GoalPlanner):
    """A buggy/hostile planner object: validate_plan must still catch what it returns."""

    def __init__(self, agents, kind):
        super().__init__(agents, replanner=lambda *a: [])
        self.kind = kind

    plan = InitialPlanner.plan

    def replan(self, goal, ctx, max_steps, feedback):
        a = lambda sid, deps=(): step(goal, sid, "research", deps=deps, input={"kind": "research_web", "urls": [URL_A]})  # noqa: E731
        if self.kind == "cycle":
            return (a("r1-a", ("r1-b",)), a("r1-b", ("r1-a",)))
        if self.kind == "duplicate":
            return (a("r1-a"), a("r1-a"))
        if self.kind == "unknown_agent":
            return (step(goal, "r1-a", "ghost", input={"kind": "research_web", "urls": [URL_A]}),)
        if self.kind == "unknown_cap":
            return (step(goal, "r1-a", "research", caps=frozenset({"magic.wand"}), input={"kind": "research_web", "urls": [URL_A]}),)
        if self.kind == "too_many":
            return tuple(a(f"r1-{i}") for i in range(60))
        if self.kind == "timeout":
            return (step(goal, "r1-a", "research", timeout=10 ** 6, input={"kind": "research_web", "urls": [URL_A]}),)
        if self.kind == "attempts":
            return (step(goal, "r1-a", "research", attempts=5, input={"kind": "research_web", "urls": [URL_A]}),)
        if self.kind == "bypass":
            return (step(goal, "r1-a", "research", input={"kind": "research_web", "urls": [URL_A], "confirmed": True}),)
        if self.kind == "bad_input":
            return (step(goal, "r1-a", "research", input={"nothing": 1}),)
        raise AssertionError(self.kind)


@pytest.mark.parametrize("kind,why", [("cycle", "cycle"), ("duplicate", "duplicate"), ("unknown_agent", "unknown agent"), ("unknown_cap", "unknown capability"),
                                      ("too_many", "at most"), ("timeout", "timeout"), ("attempts", "attempts"), ("bypass", "forbidden"), ("bad_input", "input needs")])
def test_validate_plan_stands_behind_the_planner(kind, why):
    r = Rig([])
    r.planner = CyclicPlanner(AgentPlanner(r.orch.registry), kind)
    r.engine._planner = r.planner
    res = r.run()
    assert res.status is G.FAILED and why in " ".join(res.warnings) and res.replans == 0 and not r.business.tasks and len(r.research.tasks) == 2


# ---- 10. provider failures ------------------------------------------------------------------------------------------------------------------------
class Broken(LLMProvider):
    name = "broken"

    def __init__(self, exc):
        self.exc, self.calls = exc, []

    def complete(self, request):
        self.calls.append(request)
        raise self.exc


@pytest.mark.parametrize("exc", [LLMError("HTTP 500 with token=abcdef1234567890"), RuntimeError(f"boom {SECRET}"), TimeoutError("slow"), KeyError("x")])
def test_a_failing_provider_is_handled_safely_and_leaks_nothing(exc):
    p = Broken(exc)
    r = Rig([], provider=p)
    res = r.run()
    text = " ".join(res.warnings) + res.summary + json.dumps(res.to_dict())
    assert res.status is G.FAILED and res.replans == 0 and len(p.calls) == 2 and "could not be used" in text
    assert SECRET not in text and "abcdef1234567890" not in text and not r.business.tasks


def test_a_provider_returning_a_non_string_is_rejected():
    class Weird(LLMProvider):
        name = "weird"

        def complete(self, request):
            return LLMResponse(content=12345)  # type: ignore[arg-type]
    res = Rig([], provider=Weird()).run()
    assert res.status is G.FAILED and res.replans == 0


# ---- 11. no provider, no replanning ------------------------------------------------------------------------------------------------------------------
def test_without_a_replanner_the_engine_behaves_exactly_as_before():
    r = Rig([split()], replanner=False)
    res = r.run()
    assert not r.planner.supports_replanning and res.status is G.FAILED and r.calls == 0 and res.replans == 0 and ids(res) == ["s1", "s2", "s3"] and not res.warnings
    assert r.engine.describe()["replanning"] is False


def test_the_factory_wires_replanning_only_with_the_setting_and_a_provider():
    from jarvis.agents.factory import AgentsSubsystem
    from jarvis.config import load_settings
    from jarvis.goals.factory import build_goals
    reg = AgentRegistry()
    reg.register(FakeAgent("research", {"research.web"}))
    orch = AgentOrchestrator(reg, scheduler=ManualScheduler(), clock=FakeClock(), executor=InlineExecutor())
    agents = AgentsSubsystem("enabled", "", orch, AgentPlanner(reg), reg)
    on = load_settings(env={"JARVIS_GOALS_ENABLED": "true", "JARVIS_GOALS_REPLANNING": "true"})
    off = load_settings(env={"JARVIS_GOALS_ENABLED": "true"})
    assert load_settings(env={}).goals.replanning is False
    assert build_goals(on, agents, MockProvider()).planner.supports_replanning
    assert not build_goals(on, agents, None).planner.supports_replanning and not build_goals(on, agents).planner.supports_replanning
    assert not build_goals(off, agents, MockProvider()).planner.supports_replanning                          # opt-in: the setting decides
    assert not build_goals(on, agents, object()).planner.supports_replanning                                 # not a usable provider
    assert build_goals(on, agents, MockProvider()).describe()["replanning"] is True


def test_bootstrap_passes_the_one_existing_provider(tmp_path):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from test_computer_integration import env_for
    off = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_BROWSER_ENABLED="false", JARVIS_CODING_ENABLED="false", JARVIS_COMPUTER_ENABLED="false")
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_GOALS_REPLANNING="true", **off)))
    planner = core.subsystems["goals"].planner
    assert planner.supports_replanning and planner._replanner._provider is core.provider                     # the SAME provider object, no second one
    (tmp_path / "p").mkdir()
    plain = build_core(load_settings(env=env_for(tmp_path / "p", **off)))
    assert not plain.subsystems["goals"].planner.supports_replanning                                          # opt-in


# ---- consistency ------------------------------------------------------------------------------------------------------------------------------------
def test_cleanup_runs_before_the_new_plan_and_the_old_plan_leaves_no_pending_step():
    class CodingPlanner(GoalPlanner):
        def plan(self, goal, ctx, max_steps):
            return self._build(goal, [{"objective": "Analysiere das Projekt im Workspace (Code, Dateien, Projekt)", "caps": {"coding.read"},
                                       "input": {"steps": [{"action": "start", "workspace": "/w"}]}},
                                      {"objective": "Führe die Tests des Projekts aus (Code, Tests, pytest)", "caps": {"coding.read"}, "input": {"steps": [{"action": "info"}]}},
                                      {"evaluate": True, "after": [1]},
                                      {"objective": "Beende die Projekt-Sitzung (Code, Projekt)", "caps": {"coding.read"}, "input": {"steps": [{"action": "stop"}]}, "cleanup_of": 0}])
    coding = FakeAgent("coding", {"coding.read"}, script=["ok", "failure", "failure", "ok"], failure_code="step_failed")
    reg = AgentRegistry()
    reg.register(coding)
    orch = AgentOrchestrator(reg, scheduler=ManualScheduler(), clock=FakeClock(), executor=InlineExecutor())
    cand = {"steps": [{"objective": "Analysiere das Projekt im Workspace (Code, Dateien, Projekt)", "capabilities": ["coding.read"], "input_from": "s1"},
                      {"objective": "Führe die Tests des Projekts aus (Code, Tests, pytest)", "capabilities": ["coding.read"], "input_from": "s2", "depends_on": []},
                      {"evaluate": True, "depends_on": [0, 1]}]}
    planner = CodingPlanner(AgentPlanner(reg), max_attempts=2, replanner=LLMReplanner(MockProvider(lambda r: json.dumps(cand))))
    engine = GoalEngine(orch, planner, max_attempts=2, cancel_wait=0.3)
    res = engine.run(engine.create("Prüfe das Projekt").goal_id)
    by = {s.step_id: s for s in res.steps}
    actions = [s["action"] for t in coding.tasks for s in t.input["steps"]]
    assert res.status is G.SUCCEEDED and res.replans == 1, (res.summary, res.warnings)
    assert actions == ["start", "info", "info", "stop", "start", "info", "stop"] or actions[:4] == ["start", "info", "info", "stop"]        # old session closed BEFORE the new one opens
    assert by["s4"].status is StepStatus.SUCCEEDED and by["r1-s4"].status is StepStatus.SUCCEEDED and not [s for s in res.steps if s.status is StepStatus.PENDING]


def test_a_failed_replan_still_cleans_up_and_ends_terminal():
    r = Rig(["garbage"])
    res = r.run()
    assert res.goal.is_terminal and all(s.status not in (StepStatus.PENDING, StepStatus.RUNNING) for s in res.steps)
    assert res.status is G.FAILED and r.engine.get(res.goal.goal_id).status is G.FAILED


def test_the_goal_never_goes_back_to_planning():
    seen = []
    r = Rig([split()])
    orig = r.engine._set_goal
    r.engine._set_goal = lambda rec, status: (seen.append(status), orig(rec, status))[1]
    res = r.run()
    assert res.status is G.SUCCEEDED and G.PLANNING not in seen                                             # RUNNING stays RUNNING/WAITING while replanning


def test_replans_are_visible_in_the_serialised_result():
    res = Rig([split()]).run()
    d = res.to_dict()
    assert d["replans"] == 1 and any(s["step_id"].startswith("r1-") for s in d["steps"]) and any("replan 1 accepted" in w for w in d["warnings"])
