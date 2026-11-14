"""V2.1 Integration (Aufgabe 7): fehlender M5-Test "widerspruechliche Ergebnisse zweier Agenten" und die Kombinationen Orchestrator + Plananalyse (M1) + Qualitaet (M7) + Not-Aus-Guard.
Fakes, Events statt Sleeps, kein Netz. Ergaenzt tests/test_v21_coordination.py (unveraendert)."""
from __future__ import annotations

import pytest

from agents_util import WAIT, FakeAgent, FakeClock, InlineExecutor, ManualScheduler, wait_event
from jarvis.agent_budgets import AgentBudgets
from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentTask, TaskStatus
from jarvis.goals.plan_graph import Node, replan
from jarvis.permissions.emergency import EmergencyStop
from jarvis.quality.engine import conflicts, evaluate
from jarvis.tools.base import ToolResult

S = TaskStatus
URL_A, URL_B = "https://a.example/preise", "https://b.example/liste"


def orch_for(agents, *, inline=False, guard=None, **kw):
    reg = AgentRegistry()
    for a in agents:
        reg.register(a)
    return AgentOrchestrator(reg, clock=FakeClock(), scheduler=ManualScheduler(), executor=InlineExecutor() if inline else None, stop_guard=guard, **kw), reg


def guard_of(em):
    return lambda: f"Notaus aktiv ({em.reason})" if em.engaged else None


def figures_of(results):
    return [{"label": r.output["label"], "unit": "EUR", "value": r.output["value"], "source": r.output["source"]} for r in results]


def report_with(figures, shown=False):
    return {"status": "SUCCEEDED", "requirements": [{"id": "r1"}], "coverage": {"r1": ["s1"]}, "statements": [{"id": "s1", "basis": "ESTIMATE"}], "required_fields": {"x": 1},
            "figures": figures, **({"conflicts_shown": [{"label": "innenreinigung", "unit": "EUR"}]} if shown else {})}


# ---- widerspruechliche Ergebnisse ---------------------------------------------------------------------------------------------------------------------
def test_two_agents_that_both_report_success_but_contradict_each_other_are_not_accepted():
    a = FakeAgent("a", output={"label": "innenreinigung", "value": 50.0, "source": URL_A})
    b = FakeAgent("b", output={"label": "innenreinigung", "value": 80.0, "source": URL_B})
    orch, _ = orch_for([a, b], inline=True)
    ra, rb = orch.run(AgentTask("Preis A", agent_id="a", task_id="ta")), orch.run(AgentTask("Preis B", agent_id="b", task_id="tb"))
    assert ra.status is S.SUCCEEDED and rb.status is S.SUCCEEDED                          # beide melden Erfolg ...
    found = conflicts(figures_of([ra, rb]))
    assert [c["label"] for c in found] == ["innenreinigung"] and found[0]["values"] == [50.0, 80.0] and sorted(found[0]["sources"]) == [URL_A, URL_B]
    verdict = evaluate(report_with(figures_of([ra, rb])), file_exists=None)
    assert not verdict.accepted and "consistency" in verdict.failed and verdict.self_reported == "SUCCEEDED"          # ... die Qualitaetspruefung nimmt das Ergebnis nicht an


def test_agreeing_results_within_one_percent_are_no_conflict():
    a = FakeAgent("a", output={"label": "innenreinigung", "value": 50.0, "source": URL_A})
    b = FakeAgent("b", output={"label": "innenreinigung", "value": 50.2, "source": URL_B})
    orch, _ = orch_for([a, b], inline=True)
    rs = [orch.run(AgentTask("x", agent_id="a", task_id="ta")), orch.run(AgentTask("y", agent_id="b", task_id="tb"))]
    assert conflicts(figures_of(rs)) == [] and "consistency" not in evaluate(report_with(figures_of(rs)), file_exists=None).failed


def test_a_failed_agent_contributes_no_figure_and_cannot_create_a_phantom_conflict():
    ok = FakeAgent("a", output={"label": "innenreinigung", "value": 50.0, "source": URL_A})
    bad = FakeAgent("b", behavior="failure")
    orch, _ = orch_for([ok, bad], inline=True)
    rs = [orch.run(AgentTask("x", agent_id="a", task_id="ta")), orch.run(AgentTask("y", agent_id="b", task_id="tb"))]
    assert rs[1].status is S.FAILED and conflicts(figures_of([r for r in rs if r.status is S.SUCCEEDED])) == []


# ---- zehn Agenten + Not-Aus ---------------------------------------------------------------------------------------------------------------------------
def test_stop_with_ten_running_and_ten_queued_agents_starts_nothing_new_and_runs_nothing_twice():
    em = EmergencyStop()
    workers = [FakeAgent(f"w{i}", behavior="wait") for i in range(20)]
    orch, reg = orch_for(workers, guard=guard_of(em), max_concurrent=10, max_queue=50)
    for i in range(20):
        orch.submit(AgentTask("p", agent_id=f"w{i}", task_id=f"p{i}"))
        orch.start(f"p{i}")
    started = workers[:10]                                                                 # gleiche Prioritaet: die Reihenfolge der Einreichung entscheidet, w0..w9 laufen
    for w in started:
        wait_event(w.started)
    assert not any(w.started.is_set() for w in workers[10:]) and orch.active_agents == 10
    em.engage("test", "t")
    for w in started:
        w.release.set()
    assert orch.wait_idle(WAIT)
    ran = [w for w in workers if w.tasks]
    assert len(ran) == 10 and all(len(w.tasks) == 1 for w in ran)
    queued = [orch.get(f"p{i}") for i in range(20) if not workers[i].tasks]
    assert len(queued) == 10 and all(r.status is S.BLOCKED and r.error_code == "emergency_stop" for r in queued)
    assert orch.run(AgentTask("neu", agent_id="w0", task_id="neu"), timeout=WAIT).error_code == "emergency_stop"


def test_no_external_action_is_performed_twice_or_after_the_stop():
    class Outbox:
        sent: list = []
    class Tools:
        def __contains__(self, n):
            return True
        def execute(self, name, **kw):
            Outbox.sent.append((name, kw))
            return ToolResult.ok("gesendet")
    em = EmergencyStop()
    sender = FakeAgent("sender", tool_names=frozenset({"mail"}), tool_calls=[("mail", {"to": "x"})])
    orch, _ = orch_for([sender], inline=True, guard=guard_of(em), tools=Tools())
    t = AgentTask("senden", agent_id="sender", task_id="s1")
    orch.submit(t)
    for _ in range(5):
        orch.start("s1")
    assert Outbox.sent == [("mail", {"to": "x"})]                                          # genau einmal, trotz fuenffachem Start
    em.engage("test", "t")
    res = orch.run(AgentTask("noch einmal", agent_id="sender", task_id="s2"))
    assert res.error_code == "emergency_stop" and len(Outbox.sent) == 1                    # nach dem Halt nichts mehr
    assert em.reset(lambda: True).ok
    assert orch.run(AgentTask("wieder", agent_id="sender", task_id="s3")).status is S.SUCCEEDED and len(Outbox.sent) == 2    # Reset-Semantik unveraendert


# ---- Budget / Absturz -> Neuplanung (M1) --------------------------------------------------------------------------------------------------------------
class _Tools:
    def __contains__(self, n):
        return True

    def execute(self, n, **kw):
        return ToolResult.ok("x")


def plan():
    return [Node("lesen", capability="research.web"), Node("rechnen", ("lesen",), capability="research.web")], {"rechnen": [Node("rechnen2", ("lesen",), capability="research.web")]}


def test_a_crash_may_be_replanned_but_budget_exhaustion_and_emergency_stop_never_are():
    nodes, alts = plan()
    kw = dict(failed="rechnen", done={"lesen"}, alternatives=alts, capabilities={"research.web"}, available_tools=set(), known_info=set())
    crash = FakeAgent("a", behavior="crash")
    orch, _ = orch_for([crash], inline=True)
    r = orch.run(AgentTask("x", agent_id="a", task_id="c1"))
    assert r.status is S.FAILED and r.error_code == "agent_crashed" and replan(nodes, code=r.error_code, **kw).action == "replaced"
    greedy = FakeAgent("g", tool_names=frozenset({"browser"}), tool_calls=[("browser", {})] * 5)
    budgets = AgentBudgets.from_entries(["g;;;2;"], global_timeout=300.0, global_tool_calls=200)
    o2, _ = orch_for([greedy], inline=True, tools=_Tools(), agent_budgets=budgets)
    rb = o2.run(AgentTask("x", agent_id="g", task_id="b1"))
    assert rb.error_code == "agent_budget_exceeded" and replan(nodes, code=rb.error_code, **kw).action == "abort"
    em = EmergencyStop()
    em.engage("t", "t")
    o3, _ = orch_for([FakeAgent("a")], inline=True, guard=guard_of(em))
    rs = o3.run(AgentTask("x", agent_id="a", task_id="e1"))
    assert rs.error_code == "emergency_stop" and replan(nodes, code=rs.error_code, **kw).action == "abort"
