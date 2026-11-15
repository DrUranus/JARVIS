"""V2.1 Aufgabe 2: Der Orchestrator nimmt nach einem aktiven Not-Aus keine neuen Aufgaben an und startet keinen Agenten mehr.

Nur lesender Zugriff auf den Latch (Callback `stop_guard`); der Orchestrator loest den Not-Aus nie aus und hebt ihn nie auf. Deterministisch: Events statt Sleeps,
jede Wartezeit ist nur eine Obergrenze fuer den Fehlerfall."""
import threading

import pytest

from agents_util import WAIT, FakeAgent, make, task, wait_event
from jarvis.agents import TaskStatus
from jarvis.permissions.emergency import EmergencyStop

S = TaskStatus


def guard_of(em: EmergencyStop):
    return lambda: f"Notaus aktiv ({em.reason})" if em.engaged else None


def rig(agent=None, **kw):
    em = EmergencyStop()
    orch, reg, sched = make([agent or FakeAgent("fake")], stop_guard=guard_of(em), **kw)
    return em, orch, reg, sched


# ---- Annahme ------------------------------------------------------------------------------------------------------------------------------------------
def test_submit_after_the_stop_is_blocked_and_the_agent_never_runs():
    em, orch, reg, _ = rig()
    em.engage("test", "t")
    t = task()
    r = orch.submit(t)
    assert r.status is S.BLOCKED and r.error_code == "emergency_stop" and orch.get(t.task_id) is r
    assert orch.start(t.task_id).status is S.BLOCKED and reg.get("fake").tasks == [] and orch.active_agents == 0 and orch.queued == 0


def test_run_and_start_cannot_bypass_the_stop():
    em, orch, reg, _ = rig()
    em.engage("test", "t")
    assert orch.run(task()).status is S.BLOCKED
    assert reg.get("fake").tasks == []


def test_a_task_submitted_before_the_stop_is_not_started_after_it():
    em, orch, reg, _ = rig()
    t = task()
    assert orch.submit(t).status is S.PENDING
    em.engage("test", "t")
    r = orch.start(t.task_id)
    assert r.status is S.BLOCKED and r.error_code == "emergency_stop" and reg.get("fake").tasks == []


def test_the_queue_does_not_drain_into_new_agent_starts_after_the_stop():
    em, orch, reg, _ = rig(FakeAgent("fake", behavior="wait"), inline=False, max_concurrent=1)
    first, second, third = task("a"), task("b"), task("c")
    for t in (first, second, third):
        orch.submit(t)
        orch.start(t.task_id)
    wait_event(reg.get("fake").started)
    em.engage("test", "t")
    reg.get("fake").release.set()                       # the running task ends (it was admitted before the stop); the dispatcher runs again
    assert orch.wait(first.task_id, WAIT).is_terminal and orch.wait_idle(WAIT)
    assert [x.task_id for x in reg.get("fake").tasks] == [first.task_id]
    for t in (second, third):
        r = orch.wait(t.task_id, WAIT)
        assert r.status is S.BLOCKED and r.error_code == "emergency_stop"


def test_every_agent_start_goes_through_the_check_not_only_submit():
    em, orch, reg, _ = rig(FakeAgent("fake", behavior="wait"), inline=False, max_concurrent=1)
    a, b = task("a"), task("b", dependencies=())
    orch.submit(a)
    orch.start(a.task_id)
    wait_event(reg.get("fake").started)
    orch.submit(b)
    orch.start(b.task_id)                               # waits for the slot
    em.engage("x", "t")
    orch.cancel(a.task_id, wait=WAIT)
    assert orch.wait(b.task_id, WAIT).status is S.BLOCKED and len(reg.get("fake").tasks) == 1


# ---- Fehlersicher ---------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("guard", [lambda: (_ for _ in ()).throw(RuntimeError("latch unreadable")), lambda: "stop"])
def test_an_unreadable_or_refusing_guard_fails_closed(guard):
    orch, reg, _ = make([FakeAgent("fake")], stop_guard=guard)
    r = orch.run(task())
    assert r.status is S.BLOCKED and r.error_code == "emergency_stop" and reg.get("fake").tasks == []
    assert "latch unreadable" not in (r.error or "")     # no internals in the message


def test_without_a_guard_nothing_changes():
    orch, reg, _ = make([FakeAgent("fake")])
    assert orch.run(task()).status is S.SUCCEEDED


# ---- Resume / zulaessiger Reset: keine Regression ---------------------------------------------------------------------------------------------------------
def test_an_authorised_reset_admits_new_tasks_again_and_old_blocks_stay_blocked():
    em, orch, reg, _ = rig()
    em.engage("test", "t")
    old = orch.run(task())
    assert old.status is S.BLOCKED
    assert em.reset(lambda: True).ok
    new = orch.run(task())
    assert new.status is S.SUCCEEDED and orch.get(old.task_id).status is S.BLOCKED and len(reg.get("fake").tasks) == 1


def test_a_denied_reset_keeps_the_orchestrator_closed():
    em, orch, reg, _ = rig()
    em.engage("test", "t")
    assert not em.reset(lambda: False).ok
    assert orch.run(task()).status is S.BLOCKED and reg.get("fake").tasks == []


def test_the_orchestrator_never_changes_the_latch():
    em, orch, _, _ = rig()
    orch.run(task())
    em.engage("t", "t")
    orch.run(task())
    orch.shutdown(0.1)
    assert em.engaged and em.reason == "t"


# ---- Parallel -------------------------------------------------------------------------------------------------------------------------------------------------
def test_parallel_submissions_after_the_stop_start_no_agent():
    em, orch, reg, _ = rig(FakeAgent("fake"), inline=False, max_concurrent=8)
    em.engage("test", "t")
    n, go, results = 16, threading.Barrier(16), []

    def worker(i):
        go.wait(WAIT)
        results.append(orch.run(task(f"t{i}"), timeout=WAIT).status)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join(WAIT) for t in threads]
    assert not any(t.is_alive() for t in threads) and results == [S.BLOCKED] * n
    assert reg.get("fake").tasks == [] and orch.active_agents == 0


def test_the_running_tasks_at_the_transition_are_the_only_ones_that_ever_ran():
    """Eight admitted and running tasks, the rest queued; the stop arrives; then 16 threads keep submitting while the running ones finish."""
    em, orch, reg, _ = rig(FakeAgent("fake", behavior="wait"), inline=False, max_concurrent=2)
    queued = [task(f"q{i}") for i in range(6)]
    for t in queued:
        orch.submit(t)
        orch.start(t.task_id)
    wait_event(reg.get("fake").started)
    em.engage("test", "t")
    go, late = threading.Barrier(9), []

    def worker(i):
        go.wait(WAIT)
        late.append(orch.run(task(f"late{i}"), timeout=WAIT).status)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    go.wait(WAIT)
    reg.get("fake").release.set()
    [t.join(WAIT) for t in threads]
    assert not any(t.is_alive() for t in threads) and orch.wait_idle(WAIT)
    assert late == [S.BLOCKED] * 8
    ran = {x.task_id for x in reg.get("fake").tasks}
    assert len(ran) <= 2 and ran <= {t.task_id for t in queued}
    assert all(orch.get(t.task_id).status is S.BLOCKED for t in queued if t.task_id not in ran)


def test_racing_engage_and_submission_never_deadlocks_and_ends_closed():
    for _ in range(10):
        em, orch, reg, _ = rig(FakeAgent("fake"), inline=False, max_concurrent=4)
        go = threading.Barrier(9)

        def worker(i):
            go.wait(WAIT)
            orch.run(task(f"t{i}"), timeout=WAIT)

        def stopper():
            go.wait(WAIT)
            em.engage("race", "t")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)] + [threading.Thread(target=stopper)]
        [t.start() for t in threads]
        [t.join(WAIT) for t in threads]
        assert not any(t.is_alive() for t in threads), "deadlock"
        assert orch.wait_idle(WAIT)
        assert orch.run(task("after")).status is S.BLOCKED
        assert all(r.is_terminal for r in orch.list())


# ---- Verdrahtung: echter Kern, echter Latch (Bootstrap uebergibt nur den lesenden Guard) ------------------------------------------------------------------
def test_build_core_wires_the_guard_so_delegate_is_closed_while_the_stop_is_engaged(tmp_path):
    from jarvis.agents import AgentTask
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from test_computer_integration import env_for
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_BUSINESS_ENABLED="true",
                  JARVIS_SECURITY_CONFIRMATION="deny", JARVIS_CODING_ENABLED="false", JARVIS_COMPUTER_ENABLED="false")
    core = build_core(load_settings(env=env))
    agents = core.subsystems["agents"]
    ok = agents.delegate("Analyse", {"kind": "lead_list"}, agent_id="business", required_capabilities=frozenset({"business.analyze"}))
    assert ok.error_code != "emergency_stop"
    core.permissions.emergency.engage("test", "t")
    closed = agents.delegate("Analyse", {"kind": "lead_list"}, agent_id="business", required_capabilities=frozenset({"business.analyze"}))
    assert closed.status is S.BLOCKED and closed.error_code == "emergency_stop"
    direct = agents.orchestrator.run(AgentTask("Analyse", agent_id="business", input={"kind": "lead_list"}, required_capabilities=frozenset({"business.analyze"})))
    assert direct.status is S.BLOCKED and direct.error_code == "emergency_stop"
    assert core.permissions.reset_emergency_stop is not None                        # reset stays the engine's own, authorised path (not exercised here)
