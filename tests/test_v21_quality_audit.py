"""V2.1 M7 - unabhaengige Evidenz fuer das Qualitaetstor (agents.quality_gate, Standard AUS) und Audit-Anbindung.

Fuer `business` und `strategist` zaehlt NIE ein vom Agenten selbst mitgebrachter Bericht: der Nachweis wird auf der Seite des Tors aus (1) den Ergebnissen der Elternaufgaben
(wirklich gelesene Quellen), (2) einer eigenen Neuberechnung (`business.calc`) und (3) dem Audit-Protokoll (Freigaben, Budgetausschoepfung) abgeleitet. Fehlende, nicht lesbare oder
widerspruechliche Audit-Daten sperren (BLOCKED). Das Tor fuehrt nichts aus und umgeht keine Berechtigung. Deterministisch, Fakes, kein Netz."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from agents_util import FakeAgent, FakeClock, InlineExecutor, ManualScheduler
from analysis_util import SHOP_A, SHOP_B, plain_orch, research_output
from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentTask, TaskStatus
from jarvis.business.agent import BusinessAgent
from jarvis.business.strategist_agent import StrategistAgent
from jarvis.permissions.audit import AuditEvent, AuditEventType, MemoryAuditSink
from jarvis.quality.gate import QualityGate
from jarvis.quality.reports import TYPED_AGENTS, build_report

S = TaskStatus
SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
PLAN = {"price": 120, "variable_cost": 30, "fixed_costs": 900, "investment": 5000, "units": {"base": 20}}
RESEARCH = research_output()


def calc_be(i):
    from jarvis.business import calc
    r = calc.break_even(i.get("fixed_costs"), i.get("price"), i.get("variable_cost"))
    return r["units"] if r["status"] == "COMPUTED" else None


def live_sink() -> MemoryAuditSink:
    """Ein arbeitendes Audit enthaelt immer Ereignisse (die Engine protokolliert jede Werkzeug-Registrierung); ein leeres gilt als nicht verfuegbar."""
    sink = MemoryAuditSink()
    sink.record(AuditEvent(AuditEventType.TOOL_REGISTERED, detail="tool 'echo' registered"))
    return sink


def gate(sink=None, agents=("business", "strategist"), **kw):
    sink = sink if sink is not None else live_sink()
    return QualityGate(agents, calculators={"break_even": calc_be}, audit_events=lambda: sink.tail(1000), **kw), sink


def rig(g, extra=()):
    reg = AgentRegistry()
    for a in (FakeAgent("research", {"research.web"}, output=RESEARCH), BusinessAgent(), StrategistAgent(), *extra):
        reg.register(a)
    return AgentOrchestrator(reg, clock=FakeClock(), scheduler=ManualScheduler(), executor=InlineExecutor(), quality_gate=g)


def run(o, agent, caps, data, parent=True, task_id="child"):
    deps = ()
    if parent:
        pid = "parent-" + task_id
        o.submit(AgentTask("Recherche", agent_id="research", required_capabilities=frozenset({"research.web"}), task_id=pid))
        o.start(pid)
        deps = (pid,)
    return o.run(AgentTask("Analyse", agent_id=agent, input=data, required_capabilities=frozenset(caps), dependencies=deps, task_id=task_id))


MARKET = {"kind": "market_analysis"}
BIZ = {"business.analyze"}
STRAT = {"business.strategy"}


# ---- Positivpfad: unabhaengige Evidenz vorhanden ----------------------------------------------------------------------------------------------------------
def test_a_business_result_backed_by_parent_research_and_recomputable_numbers_is_accepted():
    g, _ = gate()
    o = rig(g)
    assert run(o, "business", BIZ, MARKET).status is S.SUCCEEDED
    assert run(o, "business", BIZ, {"kind": "business_plan", "plan": PLAN}, task_id="c2").status is S.SUCCEEDED


def test_strategist_results_are_accepted_when_they_are_well_formed():
    g, _ = gate()
    o = rig(g)
    ideas = [{"name": "A", "ratings": {c: {"value": 4, "basis": "FACT"} for c in __import__("jarvis.business.finder", fromlist=["CRITERIA"]).CRITERIA}}]
    assert run(o, "strategist", STRAT, {"kind": "rank", "items": ideas}, parent=False).status is S.SUCCEEDED
    model = {"price": {"value": 80, "basis": "GIVEN"}, "variable_cost": {"value": 20, "basis": "ESTIMATE"}, "fixed_costs_month": {"value": 300, "basis": "GIVEN"},
             "startup_capital": {"value": 1500, "basis": "GIVEN"}, "units_month": {"base": {"value": 10, "basis": "ESTIMATE"}}}
    assert run(o, "strategist", STRAT, {"kind": "financial_model", "model": model}, parent=False, task_id="c2").status is S.SUCCEEDED


# ---- eigener Bericht des Agenten zaehlt nicht -----------------------------------------------------------------------------------------------------------------
def test_a_quality_report_carried_by_the_agent_is_ignored_for_the_typed_agents():
    forged = {"requirements": [{"id": "r1"}], "coverage": {"r1": ["s1"]}, "statements": [{"id": "s1", "basis": "ESTIMATE"}], "required_fields": {"x": 1}}
    assert build_report("business", {"kind": "business_result", "quality_report": forged, "summary": ""}, {"parents": []}) is not forged
    g, _ = gate()
    o = rig(g)
    r = run(o, "business", BIZ, MARKET, parent=False)                           # keine Elternrecherche -> Quellen nicht unabhaengig belegt
    assert r.status is S.BLOCKED and r.error_code == "quality_rejected" and "requirements" in r.output["quality"]["failed"]


# ---- erfundene / nicht gelesene Quellen ----------------------------------------------------------------------------------------------------------------------
def test_a_cited_source_that_no_parent_task_read_is_rejected():
    out = {"kind": "business_result", "task": "market_analysis", "summary": "ok", "findings": [{"text": "Preis 10 EUR", "basis": "FACT", "sources": ["https://erfunden.example/x"]}],
           "sources": [{"url": "https://erfunden.example/x", "status": "ok"}], "calculations": {}, "confidence": {"level": "high"}, "unknowns": []}
    ctx = {"task_id": "c", "parents": [{"task_id": "p", "agent_id": "research", "status": "SUCCEEDED", "output": RESEARCH}]}
    d = gate()[0].check("business", "SUCCEEDED", out, ctx)
    assert d.accepted is False and "sources" in d.failed


def test_a_source_the_research_agent_could_not_read_does_not_count_either():
    bad = research_output(status_by_url={SHOP_A: "failed"})
    out = {"kind": "business_result", "task": "market_analysis", "summary": "ok", "findings": [{"text": "x", "basis": "FACT", "sources": [SHOP_A]}], "calculations": {}, "confidence": {"level": "low"}, "unknowns": []}
    ctx = {"task_id": "c", "parents": [{"task_id": "p", "agent_id": "research", "status": "SUCCEEDED", "output": bad}]}
    assert gate()[0].check("business", "SUCCEEDED", out, ctx).accepted is False


def test_parents_that_did_not_succeed_provide_no_evidence():
    ctx = {"task_id": "c", "parents": [{"task_id": "p", "agent_id": "research", "status": "FAILED", "output": RESEARCH}]}
    out = {"kind": "business_result", "task": "market_analysis", "summary": "ok", "findings": [{"text": "x", "basis": "FACT", "sources": [SHOP_A]}], "calculations": {}, "confidence": {"level": "low"}, "unknowns": []}
    assert gate()[0].check("business", "SUCCEEDED", out, ctx).accepted is False


# ---- Rechnung wird neu berechnet ------------------------------------------------------------------------------------------------------------------------------
def test_a_tampered_calculation_is_caught_by_recomputation():
    g, _ = gate()
    o = rig(g)
    ok = run(o, "business", BIZ, {"kind": "business_plan", "plan": PLAN})
    assert ok.status is S.SUCCEEDED
    out = copy.deepcopy(ok.output)
    out["calculations"]["break_even"]["units"] = 3.0
    ctx = {"task_id": "c", "parents": [{"task_id": "p", "agent_id": "research", "status": "SUCCEEDED", "output": RESEARCH}]}
    d = g.check("business", "SUCCEEDED", out, ctx)
    assert d.accepted is False and "calculations" in d.failed
    assert g.check("business", "SUCCEEDED", ok.output, ctx).accepted is True


# ---- Audit: fehlend, nicht lesbar, widerspruechlich ------------------------------------------------------------------------------------------------------------
def test_without_an_audit_source_typed_agents_are_blocked_fail_closed():
    g = QualityGate(("business",), calculators={"break_even": calc_be})
    r = run(rig(g), "business", BIZ, MARKET)
    assert r.status is S.BLOCKED and r.error_code == "quality_audit_unavailable"


def test_an_unreadable_audit_source_blocks_and_hides_internals():
    def boom():
        raise OSError("platte kaputt sk-" + "a1" * 12)
    g = QualityGate(("business",), calculators={"break_even": calc_be}, audit_events=boom)
    r = run(rig(g), "business", BIZ, MARKET)
    assert r.status is S.BLOCKED and r.error_code == "quality_audit_unavailable" and "sk-" not in json.dumps([r.error, r.summary, r.output])


@pytest.mark.parametrize("events", ["kaputt", [1, 2], [{"type": "confirmation_accepted"}], None])
def test_malformed_audit_data_blocks(events):
    g = QualityGate(("business",), calculators={"break_even": calc_be}, audit_events=lambda: events)
    assert run(rig(g), "business", BIZ, MARKET).status is S.BLOCKED


def test_contradicting_approvals_in_the_audit_block_even_for_a_clean_result():
    sink = live_sink()
    for t in (AuditEventType.CONFIRMATION_ACCEPTED, AuditEventType.CONFIRMATION_REJECTED):
        sink.record(AuditEvent(t, request_id="q1", tool="mail", action="send"))
    g, _ = gate(sink)
    r = run(rig(g), "business", BIZ, MARKET)
    assert r.status is S.BLOCKED and r.error_code == "quality_audit_inconsistent"


def test_an_exhausted_budget_recorded_in_the_audit_blocks_the_result_whatever_the_agent_says():
    sink = live_sink()
    g, _ = gate(sink)
    o = rig(g)
    sink.record(AuditEvent(AuditEventType.BUDGET_EXHAUSTED, tool="agent", action="business", status="blocked", extra={"task_id": "child", "limit": "tool_calls"}))
    r = run(o, "business", BIZ, MARKET)
    assert r.status is S.BLOCKED and r.error_code == "quality_rejected" and "budgets" in r.output["quality"]["failed"]
    other = live_sink()
    other.record(AuditEvent(AuditEventType.BUDGET_EXHAUSTED, tool="agent", action="business", status="blocked", extra={"task_id": "anderer", "limit": "tool_calls"}))
    assert run(rig(gate(other)[0]), "business", BIZ, MARKET).status is S.SUCCEEDED          # nur die eigene Aufgabe zaehlt


def test_a_result_that_claims_an_action_needs_a_matching_accepted_confirmation_in_the_audit():
    out = {"kind": "business_result", "task": "market_analysis", "summary": "ok", "findings": [{"text": "x", "basis": "GIVEN", "sources": []}], "calculations": {}, "confidence": {"level": "low"},
           "unknowns": [], "actions": [{"id": "a1", "type": "send_email"}]}
    ctx = {"task_id": "c", "parents": [{"task_id": "p", "agent_id": "research", "status": "SUCCEEDED", "output": RESEARCH}]}
    g, sink = gate()
    d = g.check("business", "SUCCEEDED", out, ctx)
    assert d.accepted is False and "approvals" in d.failed                                   # keine Freigabe im Audit -> nicht angenommen


def test_blueprint_steps_that_are_not_proposals_are_rejected_and_external_ones_must_stay_blocked():
    g, _ = gate()
    base = {"kind": "strategist_result", "task": "blueprint", "result": {"name": "x", "days_30": [{"text": "a", "status": "proposed", "requires_owner_approval": True},
                                                                                                {"text": "Gewerbe anmelden", "status": "blocked_external", "requires_owner_approval": True}], "days_90": []},
            "sources": [], "note": "n"}
    assert g.check("strategist", "SUCCEEDED", base, {"task_id": "c", "parents": []}).accepted is True
    for bad_step in ({"text": "a", "status": "done", "requires_owner_approval": True}, {"text": "a", "status": "proposed", "requires_owner_approval": False}, {"text": "a", "status": "executed"}):
        bad = copy.deepcopy(base)
        bad["result"]["days_30"].append(bad_step)
        assert g.check("strategist", "SUCCEEDED", bad, {"task_id": "c", "parents": []}).accepted is False


# ---- Unbekannte/unpassende Ergebnisse, Grenzen -------------------------------------------------------------------------------------------------------------
def test_unknown_result_shapes_for_typed_agents_are_unverified():
    g, _ = gate()
    for out in (None, "text", {"kind": "etwas_anderes"}, {"kind": "business_result"}, {"kind": "strategist_result", "task": "rank", "result": None}):
        assert g.check("business" if (isinstance(out, dict) and out.get("kind") == "business_result") else "strategist", "SUCCEEDED", out, {"task_id": "c", "parents": []}).accepted is False


def test_other_agents_keep_the_explicit_report_path_and_the_typed_set_is_exactly_these_two():
    assert TYPED_AGENTS == ("business", "strategist")
    assert build_report("research", {"quality_report": {"x": 1}}, {}) is None


def test_the_gate_and_its_reports_run_nothing_and_stay_pure():
    for rel in ("quality/gate.py", "quality/reports.py"):
        t = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        mods = {a.name.split(".")[0] for n in ast.walk(t) if isinstance(n, ast.Import) for a in n.names} | {(n.module or "").split(".")[0] for n in ast.walk(t) if isinstance(n, ast.ImportFrom)}
        assert not mods & {"os", "sys", "subprocess", "socket", "threading", "pathlib", "sqlite3", "importlib", "http", "urllib"}, (rel, mods)
        assert not [n for n in ast.walk(t) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("eval", "exec", "compile", "__import__", "open")], rel
        assert not [n.module for n in ast.walk(t) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith(("jarvis.permissions", "jarvis.tools", "jarvis.agents", "jarvis.business", "jarvis.bootstrap"))], rel


def test_the_factory_gets_only_the_quality_gate_import_and_no_dynamic_import():
    t = ast.parse((SRC / "agents" / "factory.py").read_text(encoding="utf-8"))
    q = sorted(n.module for n in ast.walk(t) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("jarvis.quality"))
    assert q == ["jarvis.quality.gate"]
    assert not [n for n in ast.walk(t) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("__import__", "eval", "exec", "compile")]
    assert not [n for n in ast.walk(t) if isinstance(n, ast.Attribute) and n.attr in ("import_module", "__import__")]
    assert "importlib" not in (SRC / "agents" / "factory.py").read_text(encoding="utf-8")


def test_the_gate_stays_off_by_default_and_bootstrap_is_untouched_by_this_package():
    from jarvis.config import Settings
    assert Settings().agents.quality_gate is False and Settings().agents.quality_gate_agents == ()
    from test_v21_bootstrap_wiring import real, wiring_problems
    assert wiring_problems(real()) == []


# ---- Fabrik: die Audit-Quelle wird nur uebergeben, nie erfunden --------------------------------------------------------------------------------------------
def test_the_factory_hands_the_audit_tail_to_the_gate_and_without_it_the_typed_agents_stay_blocked(tmp_path):
    from jarvis.agents.factory import build_agents
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from test_computer_integration import env_for
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_SECURITY_CONFIRMATION="deny", JARVIS_CODING_ENABLED="false",
                  JARVIS_COMPUTER_ENABLED="false", JARVIS_BUSINESS_ENABLED="true", JARVIS_AGENTS_QUALITY_GATE="true", JARVIS_AGENTS_QUALITY_GATE_AGENTS="business")
    settings = load_settings(env=env)
    core = build_core(settings)
    plan = {"kind": "business_plan", "plan": PLAN}
    sink = live_sink()
    with_audit = build_agents(settings, core.tools, core.memory, core.tasks, core.subsystems, audit_tail=sink.tail)
    r = with_audit.delegate("Plan", plan, agent_id="business", required_capabilities=frozenset({"business.analyze"}))
    assert r.status is S.SUCCEEDED
    sink.record(AuditEvent(AuditEventType.BUDGET_EXHAUSTED, tool="agent", action="business", status="blocked", extra={"task_id": r.task_id}))          # nachtraeglich: nur das Task-Id zaehlt
    without = build_agents(settings, core.tools, core.memory, core.tasks, core.subsystems)
    r2 = without.delegate("Plan", plan, agent_id="business", required_capabilities=frozenset({"business.analyze"}))
    assert r2.status is S.BLOCKED and r2.error_code == "quality_audit_unavailable"
    assert core.subsystems["agents"].orchestrator._quality_gate is not None                      # wie in bootstrap gebaut: Gate ja, Audit-Quelle noch nicht (bewusst)


# ---- Audit ohne jedes Ereignis / mit beschaedigten Zeilen gilt nicht als Evidenz -------------------------------------------------------------------------------------
def test_an_audit_without_any_event_is_unavailable_not_clean():
    g = QualityGate(("business",), calculators={"break_even": calc_be}, audit_events=lambda: [])
    r = run(rig(g), "business", BIZ, MARKET)
    assert r.status is S.BLOCKED and r.error_code == "quality_audit_unavailable"            # unlesbare/fehlende Datei und "nichts passiert" sind von aussen nicht zu unterscheiden


def test_an_unreadable_audit_line_makes_the_audit_inconsistent():
    g = QualityGate(("business",), calculators={"break_even": calc_be}, audit_events=lambda: [{"type": "tool_registered"}, {"type": "unreadable_line"}])
    r = run(rig(g), "business", BIZ, MARKET)
    assert r.status is S.BLOCKED and r.error_code == "quality_audit_inconsistent"


# ---- Ende zu Ende ueber build_core mit dem ECHTEN Audit-Protokoll (bootstrap-Verdrahtung) --------------------------------------------------------------------
def gated_core(tmp_path, **extra):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from test_computer_integration import env_for
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_SECURITY_CONFIRMATION="deny", JARVIS_CODING_ENABLED="false",
                  JARVIS_COMPUTER_ENABLED="false", JARVIS_BUSINESS_ENABLED="true", JARVIS_AGENTS_QUALITY_GATE="true", JARVIS_AGENTS_QUALITY_GATE_AGENTS="business", **extra)
    settings = load_settings(env=env)
    return build_core(settings), settings


def delegate(core, task_id):
    return core.subsystems["agents"].delegate("Plan", {"kind": "business_plan", "plan": PLAN}, agent_id="business", required_capabilities=frozenset({"business.analyze"}), task_id=task_id)


def test_with_the_real_audit_wired_by_bootstrap_a_clean_result_is_accepted(tmp_path):
    core, _ = gated_core(tmp_path)
    assert core.subsystems["agents"].orchestrator._quality_gate is not None
    assert delegate(core, "ok1").status is S.SUCCEEDED


def test_with_the_audit_switched_off_the_typed_agents_stay_blocked(tmp_path):
    core, _ = gated_core(tmp_path, JARVIS_SECURITY_AUDIT_ENABLED="false", JARVIS_SECURITY_AUDIT_STRICT="false")
    r = delegate(core, "x1")
    assert r.status is S.BLOCKED and r.error_code == "quality_audit_unavailable"


def test_a_damaged_audit_line_blocks(tmp_path):
    core, settings = gated_core(tmp_path)
    with open(settings.effective_audit_path, "a", encoding="utf-8") as fh:
        fh.write("{das ist kein json\n")
    r = delegate(core, "x2")
    assert r.status is S.BLOCKED and r.error_code == "quality_audit_inconsistent"


def test_contradicting_confirmations_recorded_in_the_real_audit_block(tmp_path):
    core, _ = gated_core(tmp_path)
    for t in (AuditEventType.CONFIRMATION_ACCEPTED, AuditEventType.CONFIRMATION_REJECTED):
        assert core.permissions.audit.record(AuditEvent(t, request_id="q9", tool="mail", action="send"))
    r = delegate(core, "x3")
    assert r.status is S.BLOCKED and r.error_code == "quality_audit_inconsistent"


def test_a_budget_exhaustion_recorded_for_exactly_this_task_blocks_and_no_secret_leaks(tmp_path):
    core, _ = gated_core(tmp_path)
    secret = "sk-" + "a1" * 12
    core.permissions.audit.record(AuditEvent(AuditEventType.BUDGET_EXHAUSTED, tool="agent", action="business", status="blocked", detail="x " + secret, extra={"task_id": "x4", "limit": "tool_calls"}))
    r = delegate(core, "x4")
    assert r.status is S.BLOCKED and r.error_code == "quality_rejected" and "budgets" in r.output["quality"]["failed"]
    assert secret not in json.dumps([r.error, r.summary, r.output])
    assert delegate(core, "x5").status is S.SUCCEEDED                                  # eine andere Aufgabe ist davon nicht betroffen


def test_the_gate_stays_off_without_the_switch_even_with_the_audit_wired(tmp_path):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from test_computer_integration import env_for
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_SECURITY_CONFIRMATION="deny",
                                                 JARVIS_CODING_ENABLED="false", JARVIS_COMPUTER_ENABLED="false", JARVIS_BUSINESS_ENABLED="true")))
    assert core.subsystems["agents"].orchestrator._quality_gate is None
    assert delegate(core, "free").status is S.SUCCEEDED
