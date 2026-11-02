"""LLM-gestuetzte Zielzerlegung (llm-goal-planning): Fake-LLM statt Netzwerk. Die Vorlagen bleiben der Rueckfall; ein Kandidat gilt nur, wenn er die
bestehende Planpruefung besteht (Kandidatenpruefung + validate_plan) und nichts ueber die Vorlage hinaus fordert."""
from __future__ import annotations

import json

import pytest

from agents_util import FakeAgent, FakeClock, InlineExecutor, ManualScheduler
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry
from jarvis.agents.adapters import BrowserAgent, CodingAgent, ComputerAgent, ResearchAgent
from jarvis.agents.factory import AgentsSubsystem
from jarvis.config import Settings, load_settings
from jarvis.goals import Goal, GoalContext, GoalPlanner, PlanningError, validate_plan
from jarvis.goals import policy as GP
from jarvis.goals.factory import build_goals
from jarvis.goals.llm_planner import LLMDecomposer
from jarvis.llm.mock import MockProvider

OBJ = "Analysiere example.com und finde die Öffnungszeiten"
URL = "https://example.com/"
WS = {"workspace": "/w/proj"}
CODING_OBJ = "Prüfe das Projekt und führe die Tests aus"


def registry():
    reg = AgentRegistry()
    for a in (ResearchAgent(), BrowserAgent(), CodingAgent(), ComputerAgent()):
        reg.register(a)
    return reg


def web_candidate(**over):
    step = {"objective": "Recherchiere die Webseite example.com und fasse sie zusammen (Recherche, Quellen)", "capabilities": ["research.web"], "input_from": "s1"}
    step.update(over)
    return {"steps": [step, {"evaluate": True}], "rationale": "same work, own wording"}


class Rig:
    def __init__(self, reply, *, enabled=True, max_attempts=2):
        self.reply = reply
        self.provider = MockProvider(lambda req: reply if isinstance(reply, str) else json.dumps(reply))
        dec = LLMDecomposer(self.provider) if enabled else None
        self.planner = GoalPlanner(AgentPlanner(registry()), max_attempts=max_attempts, decomposer=dec)

    def plan(self, objective=OBJ, ctx=None, max_steps=20):
        g = Goal(objective)
        steps = self.planner.plan(g, GoalContext(g.goal_id, objective, None, (), ctx or {}), max_steps)
        return g, steps

    @property
    def calls(self):
        return len(self.provider.calls)


def template(objective=OBJ, ctx=None, max_steps=20):
    g = Goal(objective)
    return GoalPlanner(AgentPlanner(registry())).plan(g, GoalContext(g.goal_id, objective, None, (), ctx or {}), max_steps)


# ---- 1. Kandidat ersetzt Vorlage nur, wenn er besteht; sonst Rueckfall -------------------------------------------------------------------------
def test_a_valid_candidate_replaces_the_template():
    r = Rig(web_candidate())
    g, steps = r.plan()
    assert r.calls == 1 and steps != template()
    assert steps[0].objective == "Recherchiere die Webseite example.com und fasse sie zusammen (Recherche, Quellen)" and steps[0].input == {"url": URL}
    assert steps[0].assigned_agent == "research" and steps[-1].is_evaluation
    validate_plan(g, steps, max_steps=20)


def _shape(steps):
    return [(s.step_id, s.objective, s.required_capabilities, s.assigned_agent, s.dependencies, s.max_attempts, s.input) for s in steps]


@pytest.mark.parametrize("reply", ["not json", "", "[]", '{"steps": []}', '{"steps": "x"}', "{" * 5000])
def test_unusable_reply_falls_back_to_the_template(reply):
    r = Rig(reply)
    g, steps = r.plan()
    assert _shape(steps) == _shape(template())


def test_provider_failure_falls_back_to_the_template():
    class Boom:
        def complete_text(self, *a, **k):
            raise RuntimeError("down")
    p = GoalPlanner(AgentPlanner(registry()), decomposer=LLMDecomposer(Boom()))
    g = Goal(OBJ)
    steps = p.plan(g, GoalContext(g.goal_id, OBJ, None, (), {}), 20)
    assert _shape(steps) == _shape(template())


def test_coding_template_with_cleanup_survives_and_fallback_works():
    r = Rig("garbage")
    _, steps = r.plan(CODING_OBJ, WS)
    assert _shape(steps) == _shape(template(CODING_OBJ, WS)) and any(s.input.get("cleanup") for s in steps)


def test_screen_template_is_a_fallback_too():
    r = Rig("garbage")
    _, steps = r.plan("Mache einen Screenshot vom Bildschirm")
    assert steps[0].required_capabilities == {"computer.screen"}


def test_no_template_match_means_no_plan_and_the_model_is_not_asked():
    r = Rig(web_candidate())
    with pytest.raises(PlanningError, match="no plan"):
        r.plan("Mach irgendwas Schönes")
    assert r.calls == 0                      # the template baseline bounds what the model may do; without one nothing is planned


# ---- 2. je ein Test pro Verstoss ----------------------------------------------------------------------------------------------------------------
def test_violation_more_than_max_steps():
    many = [{"objective": f"Recherchiere die Webseite example.com Teil {i} (Recherche, Quellen)", "capabilities": ["research.web"], "input_from": "s1"} for i in range(5)]
    r = Rig({"steps": many + [{"evaluate": True}]})
    _, steps = r.plan(max_steps=3)
    assert _shape(steps) == _shape(template(max_steps=3))


def test_hard_step_limit_is_never_exceeded_even_with_a_bigger_setting():
    many = [{"objective": f"Recherchiere die Webseite example.com Teil {i} (Recherche, Quellen)", "capabilities": ["research.web"], "input_from": "s1"} for i in range(60)]
    r = Rig({"steps": many + [{"evaluate": True}]})
    _, steps = r.plan(max_steps=500)
    assert len(steps) <= GP.MAX_STEPS_HARD and _shape(steps) == _shape(template(max_steps=500))


def test_violation_attempts_cannot_be_chosen_by_the_model_and_stay_capped():
    r = Rig(web_candidate(max_attempts=99))
    _, steps = r.plan()
    assert _shape(steps) == _shape(template())
    r2 = Rig(web_candidate(), max_attempts=99)
    _, steps2 = r2.plan()
    assert all(s.max_attempts <= GP.MAX_ATTEMPTS_HARD for s in steps2)


def test_violation_new_capability():
    r = Rig(web_candidate(capabilities=["research.web", "computer.input"]))
    _, steps = r.plan()
    assert _shape(steps) == _shape(template())
    r = Rig(web_candidate(capabilities=["coding.write"]))
    _, steps = r.plan()
    assert _shape(steps) == _shape(template())


@pytest.mark.parametrize("key", ["tool", "tools", "agent", "agent_id", "assigned_agent"])
def test_violation_new_tool_or_agent(key):
    r = Rig(web_candidate(**{key: "ghost"}))
    _, steps = r.plan()
    assert _shape(steps) == _shape(template()) and all(s.assigned_agent in (None, "research") for s in steps)


@pytest.mark.parametrize("key", ["confirmed", "force", "bypass", "skip_permissions", "permission", "permissions"])
def test_violation_permission_bypass(key):
    r = Rig(web_candidate(input_from=None, input={"kind": "research_web", "urls": [URL], key: True}))
    _, steps = r.plan()
    assert _shape(steps) == _shape(template())
    r = Rig(web_candidate(**{key: True}))
    _, steps = r.plan()
    assert _shape(steps) == _shape(template())


def test_violation_new_url_for_research():
    r = Rig(web_candidate(input_from=None, input={"kind": "research_web", "urls": ["https://evil.example.net/"]}))
    _, steps = r.plan()
    assert _shape(steps) == _shape(template())


def test_violation_dropping_template_work():
    r = Rig({"steps": [{"evaluate": True}]})
    _, steps = r.plan(CODING_OBJ, WS)
    assert _shape(steps) == _shape(template(CODING_OBJ, WS))


def test_candidate_for_coding_may_reorder_but_keeps_all_capabilities():
    base = template(CODING_OBJ, WS)
    cand = [{"objective": "Analysiere das Projekt im Workspace (Code, Dateien, Projekt)", "capabilities": ["coding.read"], "input_from": "s1"},
            {"objective": "Führe die Tests des Projekts aus (Code, Tests, pytest)", "capabilities": ["coding.test"], "input_from": "s2", "depends_on": [0]},
            {"evaluate": True}]
    r = Rig({"steps": cand})
    g, steps = r.plan(CODING_OBJ, WS)
    assert {c for s in steps for c in s.required_capabilities} == {c for s in base for c in s.required_capabilities}
    assert any(s.input.get("cleanup") for s in steps)
    validate_plan(g, steps, max_steps=20)


# ---- 3. Standard aus, kein Selbststart, keine Lockerung -------------------------------------------------------------------------------------------
def test_off_by_default_in_code_and_toml():
    import tomllib
    from pathlib import Path
    assert Settings().goals.llm_planning is False
    path = Path(__file__).resolve().parents[1] / "config" / "jarvis.toml"
    toml = tomllib.loads(path.read_text(encoding="utf-8"))
    assert toml["goals"].get("llm_planning", False) is False and toml["goals"]["enabled"] is False     # the key may be absent: the code default applies
    assert load_settings(env={}).goals.llm_planning is False
    s = load_settings(path, env={})
    assert s.goals.llm_planning is False and s.goals.enabled is False


def test_planner_without_decomposer_never_calls_a_model():
    r = Rig(web_candidate(), enabled=False)
    _, steps = r.plan()
    assert r.calls == 0 and _shape(steps) == _shape(template())


def test_factory_wires_it_only_with_goals_and_setting_and_a_provider():
    reg = AgentRegistry()
    reg.register(FakeAgent("research", {"research.web"}))
    orch = AgentOrchestrator(reg, scheduler=ManualScheduler(), clock=FakeClock(), executor=InlineExecutor())
    agents = AgentsSubsystem("enabled", "", orch, AgentPlanner(reg), reg)
    on = load_settings(env={"JARVIS_GOALS_ENABLED": "true", "JARVIS_GOALS_LLM_PLANNING": "true"})
    off = load_settings(env={"JARVIS_GOALS_ENABLED": "true"})
    only_flag = load_settings(env={"JARVIS_GOALS_LLM_PLANNING": "true"})
    assert build_goals(on, agents, MockProvider()).planner.supports_llm_planning
    assert not build_goals(off, agents, MockProvider()).planner.supports_llm_planning
    assert not build_goals(on, agents, None).planner.supports_llm_planning and not build_goals(on, agents, object()).planner.supports_llm_planning
    assert build_goals(only_flag, agents, MockProvider()).status == "disabled"
    assert build_goals(on, agents, MockProvider()).describe()["llm_planning"] is True
    assert build_goals(off, agents, MockProvider()).describe()["llm_planning"] is False


def test_limits_are_unchanged():
    assert GP.MAX_STEPS_HARD == 50 and GP.MAX_ATTEMPTS_HARD == 5
    assert GP.REPLAN_KEYS == frozenset({"objective", "capabilities", "depends_on", "input", "input_from", "evaluate"})
    assert GP.MAX_REPLANS == 2


def test_decomposer_prompt_is_redacted_and_bounded_and_has_no_network_types():
    from jarvis.redaction import SecretDetector
    prov = MockProvider(lambda req: json.dumps(web_candidate()))
    dec = LLMDecomposer(prov, detector=SecretDetector(["hunter2hunter2"]))
    p = GoalPlanner(AgentPlanner(registry()), decomposer=dec)
    obj = "Analysiere example.com mit Passwort hunter2hunter2 " + "x" * 1500
    g = Goal(obj)
    p.plan(g, GoalContext(g.goal_id, obj, None, (), {}), 20)
    sent = json.dumps([c for c in prov.calls], default=str)
    assert "hunter2hunter2" not in sent and len(sent) < 20000
