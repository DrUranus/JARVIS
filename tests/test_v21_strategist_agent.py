"""V2.1 Aufgabe 1: der Business Strategist als eigener Agent (id `strategist`, Faehigkeit `business.strategy`, keine Tools, standardmaessig aus).

Der Agent ist nur die Huelle um den reinen Kern `jarvis.business.strategist`; jede Rechnung kommt aus `business.calc` (keine zweite Rechenmaschine). Er sendet, kauft und
veroeffentlicht nichts und hat kein Werkzeug: Berechtigungen, Budgets und Not-Aus gelten ueber den bestehenden Orchestrator."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from agents_util import FakeAgent
from analysis_util import plain_orch, research_output, run_with_parent
from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentStatus, AgentTask, TaskStatus
from jarvis.agents import policy as AP
from jarvis.agents.agent import validate_agent
from jarvis.agents.planner import AgentPlanner
from jarvis.bootstrap import build_core
from jarvis.business.agent import BusinessAgent
from jarvis.business.strategist_agent import StrategistAgent
from jarvis.config import BusinessSettings, Settings, load_settings
from test_computer_integration import env_for

S = TaskStatus
CAPS = {"business.strategy"}
REPO = Path(__file__).resolve().parent.parent
PROFILE = {"skills": ["python", "webdesign"], "interests": ["automatisierung"], "hours_per_week": 12, "start_budget_limit": 500}
MODEL = {"price": {"value": 80, "basis": "GIVEN"}, "variable_cost": {"value": 20, "basis": "ESTIMATE"}, "fixed_costs_month": {"value": 300, "basis": "GIVEN"},
         "startup_capital": {"value": 1500, "basis": "GIVEN"}, "units_month": {"base": {"value": 10, "basis": "ESTIMATE"}}, "ramp_months": 2, "months": 12}
from jarvis.business import finder  # noqa: E402


def rated(name, **vals):
    return {"name": name, "ratings": {c: {"value": vals.get(c, 3), "basis": "FACT"} for c in finder.CRITERIA}}


IDEAS = [rated("A", demand=5, risk=4), rated("B", demand=2, risk=2)]


def rig(parent=True, **kw):
    return plain_orch([FakeAgent("research", {"research.web"}, output=research_output()), StrategistAgent(**kw)])[0]


def run(data, orch=None, with_parent=False, **kw):
    return run_with_parent(orch or rig(**kw), "strategist", CAPS, data, research_output() if with_parent else None)


# ---- Vertrag der Agentenarchitektur -------------------------------------------------------------------------------------------------------------------
def test_it_is_a_valid_agent_with_its_own_capability_and_no_tools():
    a = StrategistAgent()
    validate_agent(a)
    assert a.id == "strategist" and a.capabilities == frozenset({"business.strategy"}) and a.tool_names == frozenset() and a.produces == frozenset()
    assert AP.BUSINESS_STRATEGY == "business.strategy" and AP.BUSINESS_STRATEGY in AP.KNOWN_CAPABILITIES and AP.BUSINESS_ANALYZE in AP.KNOWN_CAPABILITIES


def test_the_existing_agents_and_their_capabilities_are_unchanged():
    assert BusinessAgent().capabilities == frozenset({"business.analyze"}) and BusinessAgent().id == "business"
    reg = AgentRegistry()
    reg.register(BusinessAgent())
    reg.register(StrategistAgent())
    assert [a.id for a in reg.find(frozenset({"business.analyze"}))] == ["business"] and [a.id for a in reg.find(frozenset({"business.strategy"}))] == ["strategist"]


def test_the_planner_never_picks_the_strategist_by_keywords_it_must_be_named():
    reg = AgentRegistry()
    for a in (BusinessAgent(), StrategistAgent()):
        reg.register(a)
    for objective in ("Erstelle eine Marktanalyse", "Businessplan mit Break-even", "Welche Geschäftsidee passt zu mir?", "strategist", "Business Strategist Rangfolge"):
        assert AgentPlanner(reg).select(objective).agent_id != "strategist"


# ---- Standard: aus ----------------------------------------------------------------------------------------------------------------------------------------
def test_off_by_default_in_code_and_in_the_shipped_config():
    assert BusinessSettings().strategist is False and Settings().business.strategist is False
    assert load_settings(REPO / "config" / "jarvis.toml", env={}).business.strategist is False


ON = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_SECURITY_CONFIRMATION="deny",
          JARVIS_CODING_ENABLED="false", JARVIS_COMPUTER_ENABLED="false")


def test_not_registered_unless_switched_on_and_business_agent_is_independent(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, **ON, JARVIS_BUSINESS_ENABLED="true")))
    reg = core.subsystems["agents"].registry
    assert reg.has("business") and not reg.has("strategist")
    core = build_core(load_settings(env=env_for(tmp_path, **ON, JARVIS_BUSINESS_STRATEGIST="true")))
    reg = core.subsystems["agents"].registry
    assert reg.has("strategist") and reg.get("strategist").status is AgentStatus.AVAILABLE and not reg.has("business")
    assert reg.get("strategist").tool_names == frozenset() and "strategist" not in core.tools.names()


def test_without_the_agent_layer_nothing_is_built(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_BUSINESS_STRATEGIST="true")))
    assert core.subsystems["agents"].status == "disabled" and core.subsystems["agents"].registry is None


# ---- Aufgabenarten ------------------------------------------------------------------------------------------------------------------------------------------
def test_discover_returns_hypotheses_with_research_questions_and_no_market_figures():
    r = run({"kind": "discover", "profile": PROFILE, "limit": 3})
    assert r.status is S.SUCCEEDED and r.output["kind"] == "strategist_result" and r.output["task"] == "discover"
    items = r.output["result"]
    assert 1 <= len(items) <= 3 and all(i["basis"] == "HYPOTHESIS" and i["research_questions"] for i in items)
    assert "nothing was sent" in r.output["note"]


def test_research_brief_is_a_draft_that_needs_approval():
    r = run({"kind": "research_brief", "archetype": "web_design", "region": "Leipzig"})
    out = r.output["result"]
    assert r.status is S.SUCCEEDED and out["status"] == "draft" and out["requires_owner_approval"] is True and "demand" in out["topics"]


def test_financial_model_reuses_the_business_calculations():
    from jarvis.business import calc
    r = run({"kind": "financial_model", "model": MODEL})
    m = r.output["result"]
    assert r.status is S.SUCCEEDED and m["break_even"] == calc.break_even(300, 80, 20) and m["basis"] == "ESTIMATE" and m["liquidity"]["status"] == "COMPUTED"


def test_rank_and_explain_are_deterministic_and_explained():
    r = run({"kind": "rank", "items": IDEAS})
    assert [x["name"] for x in r.output["result"]["ranking"]] == ["A", "B"]
    e = run({"kind": "explain", "a": IDEAS[0], "b": IDEAS[1]})
    assert e.status is S.SUCCEEDED and e.output["result"].startswith("A vor B")


def test_blueprint_marks_external_steps_as_blocked_and_everything_as_proposal():
    from jarvis.business.strategist import financial_model
    r = run({"kind": "blueprint", "name": "Webdesign", "model": financial_model(MODEL), "archetype": "web_design", "next_steps": ["Gewerbe anmelden", "Entwurf der Preisliste"]})
    bp = r.output["result"]
    steps = {t["text"]: t["status"] for t in bp["days_30"]}
    assert r.status is S.SUCCEEDED and steps["Gewerbe anmelden"] == "blocked_external" and steps["Entwurf der Preisliste"] == "proposed"
    assert all(t["requires_owner_approval"] for t in bp["days_30"] + bp["days_90"])


def test_blueprint_accepts_the_model_inputs_directly_and_computes_it_first():
    r = run({"kind": "blueprint", "name": "Webdesign", "model_input": MODEL, "archetype": "web_design"})
    assert r.status is S.SUCCEEDED and r.output["result"]["basis"] == "ESTIMATE"


def test_audit_reports_indexes_and_codes_never_the_text():
    stmts = [{"text": "Der Markt waechst", "basis": "FACT"}, {"text": "ok", "basis": "ESTIMATE"}]
    r = run({"kind": "audit", "statements": stmts})
    assert r.output["result"] == [{"index": 0, "code": "fact_without_source"}] and "waechst" not in json.dumps(r.output)


def test_research_sources_of_a_parent_task_are_carried_over_not_fetched():
    r = run({"kind": "rank", "items": IDEAS}, with_parent=True)
    assert r.status is S.SUCCEEDED and r.output["sources"] and all("url" in s for s in r.output["sources"])
    assert run({"kind": "rank", "items": IDEAS}).output["sources"] == []


# ---- Grenzen ---------------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["send", "send_email", "outreach", "cold_outreach", "publish", "payment", "contract", "order", "offer", "register_business"])
def test_external_actions_are_refused_before_anything_is_computed(kind):
    r = run({"kind": kind, "to": "x@example.com", "model": MODEL})
    assert r.status is S.BLOCKED and r.error_code == "external_action_not_supported"


def test_unknown_kind_and_invalid_input_fail_cleanly_with_german_free_codes():
    assert run({"kind": "nope"}).error_code == "invalid_input"
    assert run({"kind": "financial_model", "model": {"price": {"value": -1, "basis": "GIVEN"}}}).error_code == "invalid_input"
    assert run({"kind": "discover", "profile": {"bogus": 1}}).error_code == "invalid_input"
    assert run({"kind": "rank", "items": []}).error_code == "invalid_input"


def test_the_capability_must_be_granted_for_the_task():
    orch = plain_orch([StrategistAgent()])[0]
    r = orch.run(AgentTask("x", agent_id="strategist", input={"kind": "rank", "items": IDEAS}, required_capabilities=frozenset({"research.web"})))
    assert r.status is S.BLOCKED and r.error_code == "capability_missing"
    a = StrategistAgent()
    from jarvis.agents.context import AgentContext
    out = a.perform(AgentTask("x", agent_id="strategist", input={"kind": "rank", "items": IDEAS}), AgentContext("t", "x", {}, frozenset({"business.analyze"})))
    assert out.error_code == "capability_not_allowed"


def test_an_agent_without_tools_has_no_gateway_access_even_if_it_tried():
    fake = FakeAgent("strategist", {"business.strategy"}, tool_calls=[("email", {"to": "x"})])
    orch = plain_orch([fake])[0]
    r = orch.run(AgentTask("x", agent_id="strategist", required_capabilities=frozenset(CAPS)))
    assert r.status is S.FAILED and r.error_code == "tool_access_denied"


def test_too_many_items_respect_the_step_limit():
    many = [rated(f"i{i}") for i in range(30)]
    assert run({"kind": "rank", "items": many}, max_steps=5).error_code == "invalid_input"


def test_cancellation_before_start_of_work_is_honoured():
    a = StrategistAgent()
    from jarvis.agents.context import AgentContext
    import threading
    ev = threading.Event()
    ev.set()
    out = a.perform(AgentTask("x", agent_id="strategist", input={"kind": "rank", "items": IDEAS}), AgentContext("t", "x", {}, frozenset(CAPS), cancel_event=ev))
    assert out.status is S.CANCELLED


def test_a_secret_in_an_input_text_is_not_repeated_in_the_output():
    secret = "sk-" + "a1" * 12
    r = run({"kind": "rank", "items": [rated(f"Idee {secret}")]})
    assert secret not in json.dumps(r.output) + (r.summary or "")


def test_the_result_stays_within_the_configured_size():
    r = run({"kind": "discover", "profile": PROFILE, "limit": 8}, max_result_chars=1500)
    assert r.status is S.SUCCEEDED and len(json.dumps(r.output)) <= 1500 + 400


# ---- Artefakte: bewusst noch nicht (E5-Waechtertests erlauben nur Orchestrator und Recherche-Uebergabe) -------------------------------------------------------
def test_no_artifacts_are_produced_and_the_e5_allowlist_is_untouched():
    r = run({"kind": "rank", "items": IDEAS})
    assert "artifacts" not in r.output and StrategistAgent().produces == frozenset()
    assert "agents.artifacts" not in (REPO / "src" / "jarvis" / "business" / "strategist_agent.py").read_text(encoding="utf-8")


# ---- Schichtung (wie die uebrigen Analyse-Pakete) ------------------------------------------------------------------------------------------------------------
def test_the_new_module_follows_the_layering_rules():
    src = (REPO / "src" / "jarvis" / "business" / "strategist_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    banned = ("jarvis.permissions", "jarvis.tools", "jarvis.agents.orchestrator", "jarvis.agents.registry", "jarvis.agents.factory", "jarvis.bootstrap", "jarvis.finance", "subprocess", "socket", "os")
    assert not [m for m in mods if m == "os" or m.startswith(banned)]
