"""V2.1 Mission 5: Koordination mehrerer Agenten auf dem BESTEHENDEN Orchestrator (keine zweite Architektur): 10 parallele Agenten, Absturz, haengender Aufruf, Budget,
Not-Aus waehrend paralleler Arbeit, Wiederaufnahme nach Prozessabbruch, keine doppelte Ausfuehrung. Plaene kommen aus goals.plan_graph. Fakes, keine Wartezeiten, kein Netzwerk."""
from __future__ import annotations

import threading

import pytest

from agents_util import WAIT, ConcurrencyProbe, FakeAgent, FakeClock, InlineExecutor, ManualScheduler, wait_event
from jarvis.agent_budgets import AgentBudgets
from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentStatus, AgentTask, TaskStatus
from jarvis.goals.plan_graph import Node, analyse, resume
from jarvis.tools.base import ToolResult

S = TaskStatus


def orch_for(agents, *, inline=False, **kw):
    reg = AgentRegistry()
    for a in agents:
        reg.register(a)
    sched = ManualScheduler()
    return AgentOrchestrator(reg, clock=FakeClock(), scheduler=sched, executor=InlineExecutor() if inline else None, **kw), reg, sched


def submit_plan(orch, nodes, agent_of, skip=()):
    """Reicht die Knoten als Aufgaben mit ihren Abhaengigkeiten ein (Reihenfolge aus der Plananalyse); bereits erledigte (`skip`) werden nicht erneut eingereicht."""
    a = analyse(nodes, capabilities={"research.web"}, tools=set(), known_info=set(), max_parallel=orch.max_concurrent, done=skip)
    assert not a.error
    by = {n.id: n for n in nodes}
    ids = [i for w in a.waves for i in w]
    for i in ids:
        orch.submit(AgentTask(f"Schritt {i}", agent_id=agent_of(i), task_id=i, dependencies=tuple(d for d in by[i].deps if d not in skip)))
    for i in ids:
        orch.start(i)
    return ids


def test_ten_agents_work_at_the_same_time_and_the_parallel_limit_is_respected():
    probe = ConcurrencyProbe()
    agents = [FakeAgent(f"a{i}", behavior="wait", probe=probe) for i in range(10)]
    orch, _, _ = orch_for(agents, max_concurrent=10)
    ids = submit_plan(orch, [Node(f"t{i}", capability="research.web") for i in range(10)], lambda i: "a" + i[1:])
    for a in agents:
        wait_event(a.started)
    assert probe.current == 10 and orch.active_agents == 10
    for a in agents:
        a.release.set()
    assert all(orch.wait(i, timeout=WAIT).status is S.SUCCEEDED for i in ids) and probe.peak == 10

    probe2 = ConcurrencyProbe()
    agents2 = [FakeAgent(f"b{i}", behavior="wait", probe=probe2) for i in range(10)]
    orch2, _, _ = orch_for(agents2, max_concurrent=4)
    ids2 = submit_plan(orch2, [Node(f"t{i}", capability="research.web") for i in range(10)], lambda i: "b" + i[1:])
    done = threading.Event()

    def release_all():
        while not done.is_set():
            for a in agents2:
                if a.started.is_set():
                    a.release.set()
            done.wait(0.01)
    t = threading.Thread(target=release_all, daemon=True)
    t.start()
    try:
        assert all(orch2.wait(i, timeout=WAIT).status is S.SUCCEEDED for i in ids2)
    finally:
        done.set()
    assert probe2.peak <= 4 and orch2.peak_running <= 4


def test_one_crashed_agent_does_not_affect_the_others_and_blocks_only_its_dependents():
    agents = [FakeAgent(f"a{i}", behavior="crash" if i == 3 else "success") for i in range(10)]
    orch, reg, _ = orch_for(agents, inline=True, max_concurrent=10)
    nodes = [Node(f"t{i}", capability="research.web") for i in range(10)] + [Node("nach-absturz", ("t3",), capability="research.web"), Node("nach-erfolg", ("t4",), capability="research.web")]
    submit_plan(orch, nodes, lambda i: {"nach-absturz": "a0", "nach-erfolg": "a1"}.get(i, "a" + i[1:]))
    res = {r.task_id: r for r in orch.list()}
    assert res["t3"].status is S.FAILED and res["t3"].error_code == "agent_crashed" and "token=" not in (res["t3"].error or "")
    assert [res[f"t{i}"].status for i in range(10) if i != 3] == [S.SUCCEEDED] * 9
    assert res["nach-absturz"].status is S.BLOCKED and res["nach-absturz"].error_code == "dependency_failed" and res["nach-erfolg"].status is S.SUCCEEDED
    assert reg.get("a3").status is AgentStatus.FAILED and reg.get("a4").status is AgentStatus.AVAILABLE


def test_a_hanging_agent_times_out_keeps_its_slot_and_the_rest_finishes():
    hang = FakeAgent("haenger", behavior="hang", supports_cancellation=False)
    others = [FakeAgent(f"a{i}") for i in range(3)]
    orch, reg, sched = orch_for([hang, *others], max_concurrent=4, default_timeout=30.0, cancel_grace=5.0)
    orch.submit(AgentTask("haengt", agent_id="haenger", task_id="h"))
    orch.start("h")
    wait_event(hang.started)
    for i in range(3):
        assert orch.run(AgentTask("ok", agent_id=f"a{i}", task_id=f"ok{i}"), timeout=WAIT).status is S.SUCCEEDED
    sched.advance(31)
    assert orch.get("h").status is S.FAILED and orch.get("h").error_code == "timeout"
    sched.advance(6)
    assert reg.get("haenger").status is AgentStatus.FAILED                       # reagiert nicht: als FAILED markiert, kein neuer Auftrag an ihn
    blocked = orch.submit(AgentTask("noch einer", agent_id="haenger", task_id="h2"))
    assert blocked.status is S.BLOCKED and blocked.error_code == "agent_failed"
    hang.release.set()


class _Tools:
    def __contains__(self, name):
        return True

    def execute(self, name, **kw):
        return ToolResult.ok("x")


def test_an_exhausted_budget_blocks_only_the_agent_that_used_it_up():
    greedy = FakeAgent("teuer", tool_names=frozenset({"browser"}), tool_calls=[("browser", {})] * 5)
    frugal = FakeAgent("sparsam", tool_names=frozenset({"browser"}), tool_calls=[("browser", {})] * 2)
    budgets = AgentBudgets.from_entries(["teuer;;;3;"], global_timeout=300.0, global_tool_calls=200)
    orch, _, _ = orch_for([greedy, frugal], inline=True, tools=_Tools(), agent_budgets=budgets)
    r1 = orch.run(AgentTask("a", agent_id="teuer", task_id="t1"))
    r2 = orch.run(AgentTask("b", agent_id="sparsam", task_id="t2"))
    r3 = orch.run(AgentTask("c", agent_id="teuer", task_id="t3"))
    assert r1.status is S.BLOCKED and r1.error_code == "agent_budget_exceeded" and r2.status is S.SUCCEEDED and r3.status is S.BLOCKED
    assert budgets.session_calls("teuer") == 3


def test_a_task_never_runs_twice_even_if_it_is_started_again():
    a = FakeAgent("a0")
    orch, _, _ = orch_for([a], inline=True)
    orch.submit(AgentTask("einmal", agent_id="a0", task_id="t"))
    for _ in range(5):
        orch.start("t")
    assert len(a.tasks) == 1 and orch.get("t").status is S.SUCCEEDED
    with pytest.raises(Exception):
        orch.submit(AgentTask("nochmal", agent_id="a0", task_id="t"))            # dieselbe Kennung kann nicht erneut eingereicht werden


def test_resume_after_a_process_abort_runs_only_the_open_steps_and_asks_again_for_side_effects():
    nodes = [Node("lesen", capability="research.web"), Node("rechnen", ("lesen",), capability="research.web"), Node("pruefen", ("rechnen",), capability="research.web"),
             Node("senden", ("pruefen",), capability="research.web", side_effect=True)]
    first = FakeAgent("a0")
    orch1, _, _ = orch_for([first], inline=True)
    for i in ("lesen", "rechnen"):                                                # der erste Prozess schafft zwei Schritte, dann bricht er ab
        orch1.run(AgentTask(i, agent_id="a0", task_id=i))
    done = {r.task_id for r in orch1.list() if r.status is S.SUCCEEDED}
    plan = resume(nodes, done=done, interrupted={"senden"}, capabilities={"research.web"}, tools=set(), known_info=set())
    assert [i for w in plan.analysis.waves for i in w] == ["pruefen", "senden"] and plan.needs_confirmation == ("senden",)
    second = FakeAgent("a0")
    orch2, _, _ = orch_for([second], inline=True)                                 # neuer Prozess, neuer Orchestrator
    confirmed = set()                                                             # der Nutzer hat "senden" (noch) nicht neu bestaetigt
    todo = [n for n in nodes if n.id not in plan.needs_confirmation or n.id in confirmed]
    submit_plan(orch2, todo, lambda i: "a0", skip=done)
    assert [t.task_id for t in second.tasks] == ["pruefen"] and not first.tasks[2:]   # nichts Erledigtes laeuft erneut, der Schritt mit Wirkung wartet


def test_emergency_stop_during_parallel_work_cancels_everything_and_refuses_new_work(tmp_path):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from test_computer_integration import env_for
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_AGENTS_MAX_CONCURRENT="5")))
    sub = core.subsystems["agents"]
    workers = [FakeAgent(f"w{i}", behavior="wait") for i in range(5)]
    for w in workers:
        sub.registry.register(w)
    for i in range(5):
        sub.orchestrator.submit(AgentTask("parallel", agent_id=f"w{i}", task_id=f"p{i}"))
        sub.orchestrator.start(f"p{i}")
    for w in workers:
        wait_event(w.started)
    em = core.permissions.emergency
    em.engage("test", source="test")
    report = em.run_stoppers()
    for i in range(5):
        assert sub.orchestrator.wait(f"p{i}", timeout=WAIT).status is S.CANCELLED
    assert "agents" in {c.name for c in report.components} and em.engaged
    assert core.emergency_stopped
    # BEFUND (dokumentiert, nicht geaendert): der Orchestrator selbst nimmt nach dem Not-Aus noch eine direkt eingereichte Aufgabe an; die Einstiegspunkte (core.handle, Ziele)
    # verweigern neue Arbeit, und JEDER Werkzeugaufruf wird von der PermissionEngine abgelehnt. Ein Agent kann also rechnen, aber nichts in der Welt tun.
    late = FakeAgent("spaet", tool_names=frozenset({"echo"}), tool_calls=[("echo", {"text": "hallo"})])
    sub.registry.register(late)
    sub.orchestrator.run(AgentTask("nach dem Not-Aus", agent_id="spaet", task_id="spaet"), timeout=WAIT)
    assert late.tool_results and all(not r.success for r in late.tool_results)       # kein Werkzeug wird mehr ausgefuehrt
    assert "Notaus" in core.handle("Starte etwas Neues").text or "gestoppt" in core.handle("Starte etwas Neues").text.lower()
    for w in workers:
        w.release.set()
