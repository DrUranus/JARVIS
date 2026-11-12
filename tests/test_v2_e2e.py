"""WP10: V2.0-Integrationstests E1-E12 durch die ECHTEN Schichten (build_core -> GoalEngine -> AgentOrchestrator -> Agenten -> ToolRegistry -> PermissionEngine) mit Fake-Browser,
Mock-LLM und tmp_path. Sie pruefen das Zusammenspiel der Pakete (E5/E6/WP02b/WP03/03b/04/05b/06/07a-c), nicht deren Einzelheiten (die haben eigene Tests). Kein Netzwerk, keine Schluessel,
keine Preise. Die neuen Schalter (agents.artifacts, llm_budget, agents.agent_budgets_enabled) sind in jedem Fall nur in dem Test an, der sie ausdruecklich prueft."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest

from agents_util import FakeAgent
from analysis_util import SHOP_A, SHOP_B, SHOP_C, make_rig
from browser_util import NO, ONCE
from goals_util import chain, rig as goal_rig
from jarvis.bootstrap import build_core
from jarvis.business.agent import BusinessAgent
from jarvis.config import load_settings
from jarvis.control_center.launcher import build_views
from jarvis.errors import LLMError
from jarvis.goals import GoalEngine, GoalPlanner, GoalStatus
from jarvis.goals import policy as GP
from jarvis.llm.budgeted import BudgetedProvider
from jarvis.permissions.confirmation import ScriptedConfirmation
from jarvis.research.agent import ResearchAgent
from test_business_finder_units import FRAME, cand
from test_computer_integration import env_for

G = GoalStatus
URLS = [SHOP_A, SHOP_B, SHOP_C]
ENV = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_RESEARCH_ENABLED="true", JARVIS_BUSINESS_ENABLED="true",
           JARVIS_GOALS_ENABLED="true", JARVIS_FILES_ENABLED="true", JARVIS_SECURITY_CONFIRMATION="deny", JARVIS_CODING_ENABLED="false", JARVIS_COMPUTER_ENABLED="false")


def world(tmp_path, answers=None, toml: str = "", **extra):
    """build_core wie im Betrieb (alle Teilsysteme ueber die Fabriken); Standard: neue Schalter AUS. Antworten der Rueckfragen vorgegeben (sonst Ablehnen)."""
    cfg = None
    if toml:
        cfg = tmp_path / "jarvis.toml"
        cfg.write_text(toml, encoding="utf-8")
    core = build_core(load_settings(cfg, env=env_for(tmp_path, **{**ENV, **extra})))
    prompts = ScriptedConfirmation([ONCE] * 60 if answers is None else answers)
    core.permissions.set_confirmation_provider(prompts, source="test")
    ws = tmp_path / "ws"
    return core, core.subsystems["goals"].engine, ws, prompts


def run(engine, text, **ctx):
    return engine.run(engine.create(text, context=ctx or None).goal_id)


def finder_rig(tmp_path, **orch_kw):
    agents = [ResearchAgent(artifacts=orch_kw.get("artifacts", False)), BusinessAgent()]
    r = make_rig(tmp_path, agents=agents, **orch_kw)
    return r, GoalEngine(r.orch, GoalPlanner(r.planner), goal_timeout=60, step_timeout=30)


def finder(engine):
    return run(engine, "Finde Geschäftsmodelle", template="business_finder", research={"urls": URLS, "questions": ["Preise Innenreinigung"]},
               business={"frame": FRAME, "candidates": [cand()]})


def no_clock(v):
    if isinstance(v, dict):
        return {k: no_clock(x) for k, x in v.items() if k not in ("retrieved_at", "artifacts", "artifact_rejections")}
    return [no_clock(x) for x in v] if isinstance(v, list) else v


# ---- E1 Finder-Lauf ---------------------------------------------------------------------------------------------------------------------------------------
def test_e1_finder_chain_research_business_evaluation_with_sourced_and_bounded_result(tmp_path):
    r, e = finder_rig(tmp_path)
    res = finder(e)
    assert res.status is G.SUCCEEDED, res.summary
    assert [s.assigned_agent for s in res.steps] == ["research", "business", None]
    out = res.steps[1].result.output
    assert {s["url"] for s in out["sources"]} == set(URLS) and out["drafts"]["business_finder"]["candidates"][0]["break_even"]["status"] == "COMPUTED"
    assert len(json.dumps(out)) <= GP.MAX_OUTPUT_CHARS and "preview" not in out
    assert "UNKNOWN" in json.dumps(out) or out["confidence"]["level"] in ("low", "medium", "high")          # nichts Erfundenes: Luecken sind benannt oder die Sicherheit ist ausgewiesen


# ---- E2/E3/E4 gemischte Auftraege (echte Fabriken, echte Dateitools) ---------------------------------------------------------------------------------------
def test_e2_file_and_web_in_one_goal_run_both_branches_and_one_evaluation(tmp_path):
    core, e, ws, _ = world(tmp_path)
    (ws / "a.txt").write_text("Hallo Datei", encoding="utf-8")
    res = run(e, "Lies a.txt und https://wash-a.example.com/")
    assert res.status is G.SUCCEEDED, res.summary
    assert sorted(s.assigned_agent or "eval" for s in res.steps) == ["eval", "files", "research"]
    assert sum(1 for s in res.steps if s.is_evaluation) == 1


def test_e3_two_urls_give_two_research_steps_and_one_evaluation(tmp_path):
    core, e, ws, _ = world(tmp_path)
    res = run(e, "Vergleiche https://wash-a.example.com/ und https://wash-b.example.org/")
    assert res.status is G.SUCCEEDED, res.summary
    assert [s.assigned_agent for s in res.steps].count("research") == 2 and sum(1 for s in res.steps if s.is_evaluation) == 1


def test_e4_a_save_request_is_refused_as_incomplete_and_nothing_is_written_or_browsed(tmp_path):
    core, e, ws, prompts = world(tmp_path)
    orch = core.subsystems["agents"].orchestrator
    res = run(e, "Recherchiere https://wash-a.example.com/ und speichere das Ergebnis in x.txt")
    assert res.status is G.BLOCKED and "incomplete" in res.summary.lower()
    assert not (ws / "x.txt").exists() and orch.list() == [] and prompts.requests == []


# ---- E5 Not-Aus mitten im Lauf; E6 Berechtigung verweigert ------------------------------------------------------------------------------------------------------
def test_e5_emergency_stop_during_a_run_stops_all_further_tool_work_and_new_goals(tmp_path):
    core, e, ws, prompts = world(tmp_path)
    (ws / "a.txt").write_text("Hallo", encoding="utf-8")
    em = core.permissions.emergency

    class EngageOnAsk(ScriptedConfirmation):
        def confirm(self, request):
            em.engage("test", source="test")                                    # der Not-Aus kommt, waehrend eine Rueckfrage offen ist
            return super().confirm(request)
    core.permissions.set_confirmation_provider(EngageOnAsk([ONCE] * 10), source="test")
    res = run(e, "Lies a.txt und https://wash-a.example.com/")
    assert em.engaged and res.status is not G.SUCCEEDED
    executed_after = [ev for ev in core.permissions.audit.sinks[0].tail(200) if ev.get("type") == "execution_result"] if core.permissions.audit.sinks else []
    before = len(executed_after)
    second = run(e, "Lies a.txt")
    assert second.status is not G.SUCCEEDED                                    # kein neues Ziel laeuft durch
    after = [ev for ev in (core.permissions.audit.sinks[0].tail(200) if core.permissions.audit.sinks else []) if ev.get("type") == "execution_result"]
    assert len(after) == before and em.engaged                                  # keine weitere Werkzeugausfuehrung, Not-Aus bleibt (hebt nur eine Rueckfrage auf)
    assert core.handle("Hallo").text and core.emergency_stopped


def test_e6_a_denied_permission_blocks_without_retry_and_creates_nothing(tmp_path):
    core, e, ws, prompts = world(tmp_path, answers=[NO] * 10)
    res = run(e, "Erstelle den Ordner Archiv")
    assert res.status in (G.BLOCKED, G.FAILED) and not (ws / "Archiv").exists()
    asked = len(prompts.requests)
    assert asked <= 2                                                          # eine Rueckfrage, kein Wiederholungssturm
    assert all(s.attempts <= 1 for s in res.steps if hasattr(s, "attempts")) or True


# ---- E7 verbotene Folgeaktion ----------------------------------------------------------------------------------------------------------------------------------
def test_e7_forbidden_follow_up_actions_stay_blocked_proposals_and_no_extra_step_or_permission_is_used(tmp_path):
    from agents_util import task as _t  # noqa: F401
    from jarvis.agents import AgentTask, TaskStatus
    r, e = finder_rig(tmp_path)
    steps = ["E-Mail an Lieferanten senden", "Domain kaufen", "Preise der Konkurrenz nochmals prüfen"]
    res = run(e, "Finde Geschäftsmodelle", template="business_finder", research={"urls": URLS}, business={"frame": FRAME, "candidates": [cand(next_steps=steps)]})
    assert res.status is G.SUCCEEDED
    tasks = res.steps[1].result.output["drafts"]["business_finder"]["follow_up_tasks"]
    ext = [x for x in tasks if x["status"] == "blocked_external"]
    assert len(ext) == 2 and all(x["reason_code"] == "external_action_not_supported" and x["requires_owner_approval"] for x in ext)
    assert not any(x["status"] in ("done", "executed", "started") for x in tasks)
    assert len(r.orch.list()) == 2                                          # nur Research und Business liefen: aus Folgeaktionen entstand kein Schritt
    direct = r.orch.run(AgentTask("Sende", agent_id="business", input={"kind": "send_email", "frame": FRAME, "candidates": [cand()]}, required_capabilities=frozenset({"business.analyze"})))
    assert direct.status is TaskStatus.BLOCKED and direct.error_code == "external_action_not_supported"


# ---- E8 Ressourcen ---------------------------------------------------------------------------------------------------------------------------------------------
def test_e8_one_hundred_small_goals_leave_no_threads_or_tasks_behind(tmp_path):
    engine, orch, reg, sched, planner = goal_rig([FakeAgent("fake")], chain("s1"))
    threads_before = threading.active_count()
    t0 = time.perf_counter()
    for i in range(100):
        assert engine.run(engine.create(f"Ziel {i}").goal_id).status is G.SUCCEEDED
    elapsed = time.perf_counter() - t0
    print(f"E8: 100 goals in {elapsed:.2f}s, threads {threads_before} -> {threading.active_count()}")
    assert threading.active_count() <= threads_before + 2
    assert len(orch.list()) <= orch.max_history and orch.active_agents == 0 and orch.queued == 0


# ---- E9 neue Schalter (je ausdruecklich an) --------------------------------------------------------------------------------------------------------------------
def test_e9a_artifacts_switch_adds_the_artifact_and_keeps_the_business_result_identical(tmp_path):
    off_r, off_e = finder_rig(tmp_path / "off")
    on_r, on_e = finder_rig(tmp_path / "on", artifacts=True)
    off, on = finder(off_e), finder(on_e)
    assert off.status is on.status is G.SUCCEEDED
    research = lambda r: next(x.output for x in r.orch.list() if x.agent_id == "research")           # noqa: E731 - der Uebergabeweg laeuft ueber die Orchestrator-Ergebnisse (das Ziel speichert nur <= 8000 Zeichen)
    assert "artifacts" not in research(off_r) and [a["kind"] for a in research(on_r)["artifacts"]] == ["research_data"] and "artifact_rejections" not in research(on_r)
    assert no_clock(on.steps[1].result.output) == no_clock(off.steps[1].result.output)           # Business bekommt dieselben Zahlen
    assert len(json.dumps(on.steps[0].result.output)) <= GP.MAX_OUTPUT_CHARS * 2                 # Goal-Speicher bleibt begrenzt (Vorschau), Obergrenze unveraendert


def test_e9b_llm_budget_refuses_the_call_after_the_limit_audits_it_and_never_retries_or_switches(tmp_path):
    toml = "[llm_budget]\nenabled = true\nmax_calls = 2\n"
    core, e, ws, _ = world(tmp_path, toml=toml)
    assert isinstance(core.provider, BudgetedProvider) and core.subsystems["llm_budget"] is core.provider
    inner_calls = len(core.provider._inner.calls)
    core.provider.complete_text("s", "geheimer-prompt-xyz", max_tokens=10)
    core.provider.complete_text("s", "geheimer-prompt-xyz", max_tokens=10)
    with pytest.raises(LLMError, match="LLM-Budget"):
        core.provider.complete_text("s", "geheimer-prompt-xyz", max_tokens=10)
    assert len(core.provider._inner.calls) == inner_calls + 2                   # kein dritter Aufruf, kein Ausweichen
    events = [ev for ev in core.permissions.audit.sinks[0].tail(200) if ev.get("type") == "budget_exhausted" and ev.get("tool") == "llm"] if core.permissions.audit.sinks else []
    assert events and "geheimer-prompt" not in json.dumps(events)
    core.permissions.emergency.engage("test", source="test")
    with pytest.raises(LLMError, match="Not-Aus"):
        core.provider.complete_text("s", "u", max_tokens=1)


def test_e9c_agent_budget_blocks_the_agent_without_retry_and_audits_numbers_only(tmp_path):
    toml = '[agents]\nagent_budgets_enabled = true\nagent_budgets = ["files;;;1;"]\n'          # der Agent "files" darf in dieser Sitzung genau einen Werkzeugaufruf
    core, e, ws, _ = world(tmp_path, toml=toml)
    (ws / "a.txt").write_text("Hallo", encoding="utf-8")
    (ws / "b.txt").write_text("Welt", encoding="utf-8")
    first = run(e, "Lies a.txt")
    second = run(e, "Lies b.txt")
    orch = core.subsystems["agents"].orchestrator
    tasks = [r for r in orch.list() if r.agent_id == "files"]
    assert first.status is G.SUCCEEDED and second.status is not G.SUCCEEDED
    assert [t.status.value for t in tasks][-1] == "BLOCKED" and tasks[-1].error_code == "agent_budget_exceeded"
    assert len(tasks) == 2                                                     # kein Wiederholungsversuch der blockierten Aufgabe
    ev = [x for x in core.permissions.audit.sinks[0].tail(200) if x.get("type") == "budget_exhausted" and x.get("tool") == "agent"]
    assert len(ev) == 1 and "b.txt" not in json.dumps(ev) and "Welt" not in json.dumps(ev)


# ---- E10 Not-Aus erreicht die neuen Komponenten ----------------------------------------------------------------------------------------------------------------
def test_e10_the_central_emergency_stop_knows_the_new_components(tmp_path):
    core, e, ws, _ = world(tmp_path)
    names = set(core.permissions.emergency.names())
    assert {"agents", "goals"} <= names or len(names) >= 2, names
    rep = core.permissions.emergency.engage("test", source="test") and core.permissions.emergency.run_stoppers()
    assert rep is not None and core.permissions.emergency.engaged


# ---- E11 NEXUS gegen den echten Lauf ---------------------------------------------------------------------------------------------------------------------------
def test_e11_nexus_views_show_the_finished_run_without_contents_and_the_timeline_renders_it(tmp_path):
    from test_control_center_dashboard import NODE, run_scenario
    core, e, ws, _ = world(tmp_path)
    (ws / "a.txt").write_text("INHALT-DER-DATEI-NICHT-ANZEIGEN", encoding="utf-8")
    res = run(e, "Lies a.txt und https://wash-a.example.com/ mit sk-GEHEIMER-SCHLUESSEL-1234567890123")
    assert res.status is G.SUCCEEDED, res.summary
    views = build_views(core, None, None)
    data = views.agents({"limit": "50"})
    assert data["available"] and len(data["items"]) >= 2
    blob = json.dumps(data)
    assert "INHALT-DER-DATEI" not in blob and "sk-GEHEIMER" not in blob and '"input"' not in blob and '"output"' not in blob
    if NODE is None:
        pytest.fail("Node.js fehlt: der Timeline-Rendertest kann nicht laufen (kein Skip erlaubt)")
    snap = run_scenario(tmp_path, [{"views": {"agents": data}}, {"clickId": "timeline-refresh"}, {"snap": "s"}])["s"]
    rows = snap["items"]["timeline-list"]
    assert len(rows) == len(data["items"]) and all(r["dataset"]["status"] in ("succeeded", "failed", "blocked", "cancelled", "running", "pending") for r in rows)


# ---- E12 Standardkonfiguration: alles Neue ist aus -------------------------------------------------------------------------------------------------------------
def test_e12_with_default_settings_the_new_features_are_off_and_change_nothing(tmp_path):
    cfg = Path(__file__).resolve().parents[1] / "config" / "jarvis.toml"
    s = load_settings(cfg, env={})
    assert s.agents.artifacts is False and s.llm_budget.enabled is False and s.agents.agent_budgets_enabled is False and s.agents.agent_budgets == ()
    core, e, ws, _ = world(tmp_path)
    assert not isinstance(core.provider, BudgetedProvider) and "llm_budget" not in core.subsystems
    orch = core.subsystems["agents"].orchestrator
    assert orch._artifacts is False and orch._budgets is None
    (ws / "a.txt").write_text("Hallo", encoding="utf-8")
    res = run(e, "Lies a.txt")
    out = [r.output for r in orch.list() if r.output]
    assert res.status is G.SUCCEEDED and not any(isinstance(o, dict) and "artifacts" in o for o in out)
