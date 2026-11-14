"""V2.1 M7 als Qualitaetstor im Orchestrator (agents.quality_gate, Standard AUS).

Ein Agent gilt nie allein wegen seiner Erfolgsmeldung als erfolgreich: ist das Tor fuer einen Agenten eingeschaltet, wird ein SUCCEEDED-Ergebnis nur uebernommen, wenn es einen
strukturierten Nachweis (`quality_report`) mitbringt und die Quality Engine ihn annimmt; sonst BLOCKED (`quality_unverified` / `quality_rejected` / `quality_unavailable`).
Das Tor aendert weder Berechtigungen noch Budgets noch den Not-Aus: es liest nur das Ergebnis. Deterministisch, Fakes."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from agents_util import FakeAgent, FakeClock, InlineExecutor, ManualScheduler
from jarvis.agent_budgets import AgentBudgets
from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentTask, TaskStatus
from jarvis.config import ConfigError, Settings, load_settings
from jarvis.permissions.emergency import EmergencyStop
from jarvis.quality.gate import QualityGate
from jarvis.tools.base import ToolResult
from test_v21_quality_engine import AUDIT, break_even, good

S = TaskStatus
SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
SECRET = "sk-" + "a1" * 12


def gate(*agents, **kw):
    kw.setdefault("calculators", {"break_even": break_even})
    kw.setdefault("file_exists", lambda p: True)
    kw.setdefault("audit_events", lambda: AUDIT)
    return QualityGate(agents or ("a",), **kw)


def orch(agents, quality_gate=None, **kw):
    reg = AgentRegistry()
    for a in agents:
        reg.register(a)
    return AgentOrchestrator(reg, clock=FakeClock(), scheduler=ManualScheduler(), executor=InlineExecutor(), quality_gate=quality_gate, **kw)


def run(agent, g, task_id="t1", **kw):
    o = orch([agent], g, **kw)
    return o.run(AgentTask("x", agent_id=agent.id, task_id=task_id))


# ---- das Tor selbst ---------------------------------------------------------------------------------------------------------------------------------------
def test_a_result_without_evidence_is_unverified_whatever_the_agent_claims():
    d = gate().check("a", "SUCCEEDED", {"answer": 42, "accepted": True, "verdict": "ACCEPTED", "quality": {"accepted": True}})
    assert d.accepted is False and d.code == "quality_unverified" and d.self_reported == "SUCCEEDED"
    assert gate().check("a", "SUCCEEDED", None).code == "quality_unverified"


def test_an_agent_cannot_vouch_for_itself_inside_its_report():
    r = dict(good(), status="FAILED", accepted=True, verdict={"accepted": True})
    r["requirements"] = []                                                     # nichts verlangt -> nicht annehmbar
    d = gate().check("a", "SUCCEEDED", {"quality_report": r})
    assert d.accepted is False and "requirements" in d.failed


def test_a_complete_evidenced_report_is_accepted():
    d = gate().check("a", "SUCCEEDED", {"quality_report": good()})
    assert d.accepted is True and d.failed == () and d.unknown == () and d.code == "quality_accepted"


def test_failed_or_unknown_checks_reject_and_the_decision_names_only_codes():
    r = good()
    r["statements"][0]["sources"] = ["https://nie-gelesen.example/x"]
    d = gate().check("a", "SUCCEEDED", {"quality_report": r})
    assert d.accepted is False and d.code == "quality_rejected" and "sources" in d.failed
    unknown = gate(file_exists=None).check("a", "SUCCEEDED", {"quality_report": good()})                    # Dateien nicht pruefbar -> nicht angenommen
    assert unknown.accepted is False and "files" in unknown.unknown


def test_the_engine_failing_is_fail_closed_and_hides_internals():
    def boom(_):
        raise RuntimeError("geheim " + SECRET)
    d = gate(calculators={"break_even": boom}).check("a", "SUCCEEDED", {"quality_report": good()})
    assert d.accepted is False and SECRET not in json.dumps(d.__dict__, default=str)
    d2 = QualityGate(("a",), file_exists=lambda p: (_ for _ in ()).throw(OSError(SECRET))).check("a", "SUCCEEDED", {"quality_report": good()})
    assert d2.accepted is False and SECRET not in json.dumps(d2.__dict__, default=str)


def test_only_listed_agents_are_gated_and_an_empty_list_gates_nothing():
    g = gate("a")
    assert g.applies("a") and not g.applies("b") and not QualityGate(()).applies("a")


# ---- im Orchestrator ----------------------------------------------------------------------------------------------------------------------------------------
def test_without_the_gate_the_result_is_byte_identical_to_before():
    a = FakeAgent("a", output={"answer": 42}, summary="fertig")
    r = run(a, None)
    assert r.status is S.SUCCEEDED and r.output == {"answer": 42} and r.summary == "fertig"


def test_an_unverified_success_is_not_a_success_and_its_output_is_not_passed_on():
    r = run(FakeAgent("a", output={"answer": 42}), gate())
    assert r.status is S.BLOCKED and r.error_code == "quality_unverified" and "answer" not in json.dumps(r.output)
    assert r.output["quality"]["accepted"] is False and r.output["quality"]["self_reported"] == "SUCCEEDED"


def test_an_evidenced_result_passes_with_its_output_unchanged():
    out = {"answer": 42, "quality_report": good()}
    r = run(FakeAgent("a", output=out), gate())
    assert r.status is S.SUCCEEDED and r.output["answer"] == 42


def test_a_rejected_result_blocks_and_its_dependents_never_run():
    bad = dict(good(), requirements=[])
    a, b = FakeAgent("a", output={"quality_report": bad}), FakeAgent("b")
    o = orch([a, b], gate("a"))
    o.submit(AgentTask("erst", agent_id="a", task_id="t1"))
    o.submit(AgentTask("danach", agent_id="b", task_id="t2", dependencies=("t1",)))
    o.start("t1")
    o.start("t2")
    assert o.get("t1").error_code == "quality_rejected" and o.get("t2").status is S.BLOCKED and o.get("t2").error_code == "dependency_failed" and b.tasks == []


def test_ungated_agents_and_non_success_outcomes_are_untouched():
    r = run(FakeAgent("b", output={"x": 1}), gate("a"))
    assert r.status is S.SUCCEEDED
    f = run(FakeAgent("a", behavior="failure", failure_code="fake_failure"), gate())
    assert f.status is S.FAILED and f.error_code == "fake_failure"


def test_a_gate_that_raises_blocks_fail_closed():
    class Broken:
        def applies(self, agent_id):
            return True

        def check(self, *a):
            raise RuntimeError("kaputt " + SECRET)
    r = run(FakeAgent("a", output={"quality_report": good()}), Broken())
    assert r.status is S.BLOCKED and r.error_code == "quality_unavailable" and SECRET not in json.dumps([r.error, r.summary, r.output])


def test_the_gate_leaves_budgets_and_the_emergency_stop_as_they_are():
    class Tools:
        def __contains__(self, n):
            return True

        def execute(self, n, **kw):
            return ToolResult.ok("x")
    greedy = FakeAgent("a", tool_names=frozenset({"browser"}), tool_calls=[("browser", {})] * 5, output={"quality_report": good()})
    budgets = AgentBudgets.from_entries(["a;;;2;"], global_timeout=300.0, global_tool_calls=200)
    r = run(greedy, gate(), tools=Tools(), agent_budgets=budgets)
    assert r.error_code == "agent_budget_exceeded"                                          # das Budget greift vor dem Tor
    em = EmergencyStop()
    em.engage("t", "t")
    called = []

    class Spy(QualityGate):
        def check(self, *a):
            called.append(a)
            return super().check(*a)
    r2 = run(FakeAgent("a", output={"quality_report": good()}), Spy(("a",)), stop_guard=lambda: "Notaus" if em.engaged else None)
    assert r2.error_code == "emergency_stop" and called == []                               # nach dem Halt wird nichts gestartet, nichts bewertet


# ---- Konfiguration und Verdrahtung ---------------------------------------------------------------------------------------------------------------------------
def test_off_by_default_in_code_and_toml_and_unknown_keys_stay_refused():
    s = Settings().agents
    assert s.quality_gate is False and s.quality_gate_agents == ()
    assert load_settings(Path(__file__).resolve().parents[1] / "config" / "jarvis.toml", env={}).agents.quality_gate is False
    with pytest.raises(ConfigError):
        load_settings(env={"JARVIS_AGENTS_QUALITY_GATE_AGENTS": "Business Agent!"})


ON = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_SECURITY_CONFIRMATION="deny", JARVIS_CODING_ENABLED="false",
          JARVIS_COMPUTER_ENABLED="false", JARVIS_BUSINESS_ENABLED="true")


def core_for(tmp_path, **extra):
    from jarvis.bootstrap import build_core
    from test_computer_integration import env_for
    return build_core(load_settings(env=env_for(tmp_path, **ON, **extra)))


def test_not_wired_unless_switched_on_and_then_the_business_agent_needs_evidence(tmp_path):
    plain = core_for(tmp_path)
    ok = plain.subsystems["agents"].delegate("Analyse", {"kind": "lead_list"}, agent_id="business", required_capabilities=frozenset({"business.analyze"}))
    assert ok.status is S.SUCCEEDED
    gated = core_for(tmp_path, JARVIS_AGENTS_QUALITY_GATE="true", JARVIS_AGENTS_QUALITY_GATE_AGENTS="business")
    res = gated.subsystems["agents"].delegate("Analyse", {"kind": "lead_list"}, agent_id="business", required_capabilities=frozenset({"business.analyze"}))
    assert res.status is S.BLOCKED and res.error_code == "quality_audit_unavailable"           # typisierter Agent: ohne unabhaengige Audit-Quelle nie angenommen


def test_a_gate_switch_without_agents_or_for_an_unknown_agent_never_silently_gates_nothing(tmp_path):
    none = core_for(tmp_path, JARVIS_AGENTS_QUALITY_GATE="true")
    assert none.subsystems["agents"].orchestrator._quality_gate is None
    unknown = core_for(tmp_path, JARVIS_AGENTS_QUALITY_GATE="true", JARVIS_AGENTS_QUALITY_GATE_AGENTS="gibt-es-nicht")
    assert unknown.subsystems["agents"].status == "disabled"                                  # fail closed: ein Tor fuer einen unbekannten Agenten ist ein Konfigurationsfehler


# ---- Schichtung --------------------------------------------------------------------------------------------------------------------------------------------------
def imports(path):
    t = ast.parse(path.read_text(encoding="utf-8"))
    return {n.module or "" for n in ast.walk(t) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(t) if isinstance(n, ast.Import) for a in n.names}


def test_layering_the_orchestrator_knows_no_quality_module_and_the_gate_only_the_engine():
    assert not [m for m in imports(SRC / "agents" / "orchestrator.py") if "quality" in m]
    assert {m for m in imports(SRC / "quality" / "gate.py") if m.startswith("jarvis")} <= {"jarvis.quality.engine", "jarvis.quality.reports"}
    assert not {m.split(".")[0] for m in imports(SRC / "quality" / "gate.py")} & {"os", "subprocess", "socket", "threading", "pathlib", "sqlite3"}
