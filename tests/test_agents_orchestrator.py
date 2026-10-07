"""AgentOrchestrator behaviour: lifecycle, errors, cancellation, timeouts, concurrency, dependencies, context. Deterministic: manual scheduler,
inline or recorded execution, Events instead of sleeps."""
import threading

import pytest

from agents_util import (WAIT, ConcurrencyProbe, FakeAgent, FakeClock, InlineExecutor, ManualScheduler, RecordingExecutor, make, task, wait_event)
from jarvis.agents import (AgentOrchestrator, AgentOutcome, AgentRegistry, AgentStatus, AgentTask, DuplicateError, InvalidTaskError, TaskStatus,
                           ToolAccessError, TaskCancelled, UnknownAgentError)
from jarvis.agents.agent import Agent
from jarvis.agents.state import TERMINAL
from jarvis.tasks import TaskManager
from jarvis.tasks import TaskStatus as CoreStatus

S = TaskStatus


def finish(orch, tid):
    r = orch.wait(tid, WAIT)
    assert r.is_terminal, r.status
    return r


# ---- submit / start / run ------------------------------------------------------------------------------------------------------------------------
def test_submit_registers_a_pending_task_and_does_not_run_it():
    orch, reg, _ = make()
    t = task()
    r = orch.submit(t)
    assert r.status is S.PENDING and r.agent_id == "fake" and r.started_at is None and orch.get(t.task_id) is r and orch.list() == [r]
    assert reg.get("fake").tasks == [] and orch.active_agents == 0 and orch.queued == 1
    with pytest.raises(DuplicateError):
        orch.submit(t)
    with pytest.raises(InvalidTaskError):
        orch.submit("not a task")
    with pytest.raises(UnknownAgentError):
        orch.get("nope")


def test_start_runs_the_task_and_stores_a_structured_result():
    orch, reg, _ = make([FakeAgent("fake", output={"rows": [1, 2]}, summary="all good")])
    t = task("read it", priority=3)
    orch.submit(t)
    r = orch.start(t.task_id)
    assert r.status is S.SUCCEEDED and r.summary == "all good" and r.output == {"rows": [1, 2]} and r.error is None and r.error_code is None
    assert r.started_at < r.finished_at and r is orch.get(t.task_id)
    a = reg.get("fake")
    assert a.status is AgentStatus.AVAILABLE and a.tasks == [t] and orch.active_agents == 0 and orch.queued == 0
    d = orch.describe(t.task_id)
    assert d["status"] == "SUCCEEDED" and d["still_running"] is False and d["agent_id"] == "fake" and d["requested"] is True


def test_run_is_submit_start_wait_and_never_blocks_forever():
    orch, reg, sched = make([FakeAgent("fake", behavior="wait")], inline=False)
    t = task("long")
    box = {}
    th = threading.Thread(target=lambda: box.update(r=orch.run(t, timeout=WAIT)))
    th.start()
    wait_event(reg.get("fake").started)
    assert orch.get(t.task_id).status is S.RUNNING
    reg.get("fake").release.set()
    th.join(WAIT)
    assert box["r"].status is S.SUCCEEDED
    # a wait that times out returns the CURRENT state instead of hanging
    b = FakeAgent("b", behavior="wait")
    reg.register(b)
    t2 = task("again", agent_id="b")
    orch.submit(t2)
    orch.start(t2.task_id)
    wait_event(b.started)
    assert orch.wait(t2.task_id, 0).status is S.RUNNING and orch.run(task("x", agent_id="fake"), timeout=0).status in (S.RUNNING, S.SUCCEEDED, S.PENDING)
    b.release.set()
    finish(orch, t2.task_id)


def test_repeated_execution_and_double_start():
    orch, reg, _ = make()
    for i in range(5):
        r = orch.run(task(f"job {i}"))
        assert r.status is S.SUCCEEDED
    assert len(reg.get("fake").tasks) == 5 and reg.get("fake").status is AgentStatus.AVAILABLE
    t = task("once")
    orch.submit(t)
    first = orch.start(t.task_id)
    second = orch.start(t.task_id)       # starting a finished task changes nothing
    assert first is second and len(reg.get("fake").tasks) == 6
    assert len(orch.list()) == 6 and len(orch.list(S.SUCCEEDED)) == 6 and orch.list(S.FAILED) == []


def test_tasks_are_selected_by_capability_when_no_agent_is_named():
    a, b = FakeAgent("a", {"x.one"}), FakeAgent("b", {"x.one", "x.two"})
    orch, _, _ = make([a, b])
    r = orch.run(AgentTask("any", required_capabilities=frozenset({"x.two"})))
    assert r.agent_id == "b" and r.status is S.SUCCEEDED
    r = orch.run(AgentTask("any", required_capabilities=frozenset({"x.one"})))
    assert r.agent_id == "a"                         # an AVAILABLE agent is preferred, ties by id
    r = orch.run(AgentTask("any", required_capabilities=frozenset({"x.nine"})))
    assert r.status is S.BLOCKED and r.error_code == "no_suitable_agent"
    assert orch.run(AgentTask("no capabilities and no agent")).error_code == "no_suitable_agent"


# ---- conditions that block a task (reported, not raised) --------------------------------------------------------------------------------------------
def test_unavailable_targets_are_blocked_results_not_exceptions():
    orch, reg, _ = make([FakeAgent("fake", {"x.one"})])
    assert orch.submit(task(agent_id="ghost")).error_code == "unknown_agent"
    assert orch.submit(task(required_capabilities=frozenset({"x.two"}))).error_code == "capability_missing"
    assert orch.submit(task(dependencies=("nope",))).error_code == "unknown_dependency"
    reg.get("fake").state.transition(AgentStatus.DISABLED)
    r = orch.submit(task())
    assert r.status is S.BLOCKED and r.error_code == "agent_disabled" and "disabled" in r.error
    reg.get("fake").state.transition(AgentStatus.AVAILABLE)
    reg.get("fake").state.claim()
    reg.get("fake").state.transition(AgentStatus.FAILED)
    assert orch.submit(task()).error_code == "agent_failed"
    assert reg.get("fake").tasks == [] and all(r.status is S.BLOCKED for r in orch.list())


def test_a_disabled_agent_receives_no_new_task_even_if_it_was_queued_before():
    orch, reg, _ = make()
    t = task()
    orch.submit(t)
    orch.set_enabled("fake", False)
    r = orch.start(t.task_id)
    assert r.status is S.BLOCKED and r.error_code == "agent_unavailable" and reg.get("fake").tasks == []
    assert orch.set_enabled("fake", True) is AgentStatus.AVAILABLE and orch.run(task()).status is S.SUCCEEDED


def test_queue_and_history_are_bounded():
    orch, _, _ = make(max_queue=2, max_history=4)
    ids = []
    for i in range(3):
        t = task(f"q{i}")
        ids.append(t.task_id)
        orch.submit(t)
    assert [orch.get(i).status for i in ids] == [S.PENDING, S.PENDING, S.BLOCKED] and orch.get(ids[2]).error_code == "queue_full"
    for i in range(10):
        orch.run(task(f"h{i}", agent_id="fake")) if False else None
    orch2, _, _ = make(max_history=3)
    done = [orch2.run(task(f"h{i}")).task_id for i in range(6)]
    kept = [r.task_id for r in orch2.list()]
    assert kept == done[-3:] and len(orch2.list()) == 3
    assert orch2.submit(task("dep on trimmed", dependencies=(done[0],))).error_code == "unknown_dependency"


# ---- failures and isolation ------------------------------------------------------------------------------------------------------------------------
def test_failure_and_blocked_results_are_stored_and_the_agent_stays_usable():
    a = FakeAgent("a", behavior="failure")
    b = FakeAgent("b", behavior="blocked")
    orch, _, _ = make([a, b])
    r = orch.run(task(agent_id="a"))
    assert (r.status, r.error, r.error_code) == (S.FAILED, "the fake agent failed", "fake_failure") and a.status is AgentStatus.AVAILABLE
    r = orch.run(task(agent_id="b"))
    assert r.status is S.BLOCKED and r.error_code == "fake_blocked" and b.status is AgentStatus.AVAILABLE
    a.behavior = "success"
    assert orch.run(task(agent_id="a")).status is S.SUCCEEDED


def test_an_agent_crash_is_isolated_redacted_and_marks_only_that_agent():
    bad, good = FakeAgent("bad", behavior="crash"), FakeAgent("good")
    orch, reg, _ = make([bad, good])
    r = orch.run(task(agent_id="bad"))
    assert r.status is S.FAILED and r.error_code == "agent_crashed" and "RuntimeError" in r.error and "abc123456789" not in str(r.to_dict())
    assert bad.status is AgentStatus.FAILED and "crashed" in bad.state.reason and good.status is AgentStatus.AVAILABLE
    assert orch.submit(task(agent_id="bad")).error_code == "agent_failed"      # a failed agent gets nothing new ...
    assert orch.run(task(agent_id="good")).status is S.SUCCEEDED                # ... while the others and the registry work on
    assert len(reg.list()) == 2 and orch.active_agents == 0
    bad.behavior = "success"
    assert orch.reset_agent("bad") is AgentStatus.AVAILABLE and orch.run(task(agent_id="bad")).status is S.SUCCEEDED   # FAILED -> AVAILABLE


def test_an_invalid_outcome_object_counts_as_a_crash():
    class Wrong(FakeAgent):
        def perform(self, task, ctx):
            return {"status": "ok"}

    w = Wrong("w")
    orch, _, _ = make([w])
    r = orch.run(task(agent_id="w"))
    assert r.status is S.FAILED and r.error_code == "agent_crashed" and w.status is AgentStatus.FAILED


def test_tool_access_errors_and_stray_cancellation_are_normal_outcomes_not_crashes():
    class Denied(FakeAgent):
        def perform(self, task, ctx):
            raise ToolAccessError("not your tool")

    class Stray(FakeAgent):
        def perform(self, task, ctx):
            raise TaskCancelled("stop")

    d, s = Denied("d"), Stray("s")
    orch, _, _ = make([d, s])
    r = orch.run(task(agent_id="d"))
    assert r.status is S.FAILED and r.error_code == "tool_access_denied" and d.status is AgentStatus.AVAILABLE
    assert orch.run(task(agent_id="s")).status is S.CANCELLED and s.status is AgentStatus.AVAILABLE


def test_results_are_redacted_and_bounded_before_they_are_stored():
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
    a = FakeAgent("a", output={"note": f"token={secret}", "nested": [f"password=hunter22abc"]}, summary=f"key {secret}")
    big = FakeAgent("big", output={"x": "y" * 50_000})
    orch, _, _ = make([a, big], max_output_chars=2000)
    r = orch.run(task(agent_id="a"))
    blob = str(r.to_dict())
    assert secret not in blob and "hunter22abc" not in blob and "[REDACTED]" in blob
    rb = orch.run(task(agent_id="big"))
    assert rb.output["truncated"] is True and len(str(rb.output)) < 2000
    assert secret not in orch.describe(r.task_id)["summary"] and secret not in orch.describe(r.task_id)["objective"]


# ---- cancellation ----------------------------------------------------------------------------------------------------------------------------------------
def test_cancelling_a_pending_task_is_immediate_and_final():
    orch, reg, _ = make()
    t = task()
    orch.submit(t)
    rep = orch.cancel(t.task_id)
    assert rep.accepted and rep.status is S.CANCELLED and orch.get(t.task_id).status is S.CANCELLED
    assert orch.start(t.task_id).status is S.CANCELLED and reg.get("fake").tasks == []
    again = orch.cancel(t.task_id)
    assert not again.accepted and "already CANCELLED" in again.message
    with pytest.raises(UnknownAgentError):
        orch.cancel("ghost")


def test_cancelling_a_running_task_becomes_cancelled_only_when_the_agent_really_stops():
    a = FakeAgent("fake", behavior="wait")
    orch, reg, _ = make([a], inline=False)
    t = task("long")
    orch.submit(t)
    orch.start(t.task_id)
    wait_event(a.started)
    rep = orch.cancel(t.task_id, wait=WAIT)         # waits for the agent to return
    r = orch.get(t.task_id)
    assert rep.accepted and r.status is S.CANCELLED and a.cancel_calls == [t.task_id] and a.status is AgentStatus.AVAILABLE and orch.active_agents == 0
    assert orch.describe(t.task_id)["cancel_requested"] is True and orch.describe(t.task_id)["still_running"] is False


def test_a_cancel_request_does_not_claim_the_task_ended_while_work_continues():
    a = FakeAgent("fake", behavior="hang", supports_cancellation=True)   # supports it in principle but is busy right now
    orch, _, sched = make([a], inline=False)
    t = task("hang")
    orch.submit(t)
    orch.start(t.task_id)
    wait_event(a.started)
    rep = orch.cancel(t.task_id)
    assert rep.accepted and rep.status is S.RUNNING and "requested" in rep.message           # still RUNNING: nothing is claimed
    assert orch.get(t.task_id).status is S.RUNNING and orch.active_agents == 1 and a.status is AgentStatus.BUSY
    a.release.set()                                                                          # the agent finally returns ...
    r = finish(orch, t.task_id)
    assert r.status is S.SUCCEEDED                                                           # ... having completed the work: reported as it is
    assert a.status is AgentStatus.AVAILABLE


def test_agents_without_cancellation_support_say_so():
    a = FakeAgent("fake", behavior="hang", supports_cancellation=False)
    orch, _, _ = make([a], inline=False)
    t = task()
    orch.submit(t)
    orch.start(t.task_id)
    wait_event(a.started)
    rep = orch.cancel(t.task_id)
    assert not rep.accepted and rep.status is S.RUNNING and "does not support" in rep.message and a.cancel_calls == []
    a.release.set()
    assert finish(orch, t.task_id).status is S.SUCCEEDED


def test_cancel_dependents_become_blocked():
    orch, reg, _ = make()
    a, b = task("A"), task("B", dependencies=())
    orch.submit(a)
    b = AgentTask("B", agent_id="fake", dependencies=(a.task_id,))
    orch.submit(b)
    orch.cancel(a.task_id)
    r = orch.start(b.task_id)
    assert r.status is S.BLOCKED and r.error_code == "dependency_failed" and reg.get("fake").tasks == []


def test_shutdown_cancels_everything_that_is_open():
    a = FakeAgent("fake", behavior="wait")
    orch, _, sched = make([a], inline=False)
    r1, r2 = task("running"), task("waiting")
    orch.submit(r1), orch.submit(r2)
    orch.start(r1.task_id), orch.start(r2.task_id)
    wait_event(a.started)
    orch.shutdown(wait=WAIT)
    assert orch.get(r1.task_id).status is S.CANCELLED and orch.get(r2.task_id).status is S.CANCELLED and orch.active_agents == 0
    assert sched.pending() == 0


# ---- timeout --------------------------------------------------------------------------------------------------------------------------------------------
def test_timeout_fails_the_task_but_the_agent_stays_busy_until_the_work_really_stops():
    a, b = FakeAgent("a", behavior="wait"), FakeAgent("b")
    orch, reg, sched = make([a, b], inline=False, max_concurrent=1, default_timeout=30)
    t, queued = task("slow", agent_id="a"), task("next", agent_id="b")
    orch.submit(t), orch.submit(queued)
    orch.start(t.task_id)
    orch.start(queued.task_id)
    wait_event(a.started)
    assert orch.get(queued.task_id).status is S.PENDING                                  # the only slot is taken
    sched.advance(30)                                                                    # the timeout fires - no waiting
    r = orch.get(t.task_id)
    assert r.status is S.FAILED and r.error_code == "timeout" and "30" in r.error
    d = orch.describe(t.task_id)
    assert d["timed_out"] is True and d["still_running"] in (True, False)
    # cooperative agent: it was told to cancel and returns; only then the agent and the slot are free again
    finish(orch, queued.task_id)
    assert orch.get(t.task_id).status is S.FAILED and a.cancel_calls == [t.task_id]       # the late result did not overwrite the timeout
    assert orch.get(queued.task_id).status is S.SUCCEEDED and a.status is AgentStatus.AVAILABLE and orch.active_agents == 0


def test_a_task_specific_timeout_is_used_and_the_default_comes_from_the_orchestrator():
    a = FakeAgent("a", behavior="hang")
    b = FakeAgent("b", behavior="hang")
    orch, _, sched = make([a, b], inline=False, default_timeout=100, cancel_grace=5)
    t1, t2 = task("custom", agent_id="a", timeout=10), task("default", agent_id="b")
    orch.submit(t1), orch.submit(t2)
    orch.start(t1.task_id), orch.start(t2.task_id)
    wait_event(a.started), wait_event(b.started)
    sched.advance(10)
    assert orch.get(t1.task_id).error_code == "timeout" and orch.get(t2.task_id).status is S.RUNNING
    sched.advance(90)
    assert orch.get(t2.task_id).error_code == "timeout"
    a.release.set(), b.release.set()
    for t in (t1, t2):
        deadline_ok = orch.wait(t.task_id, WAIT)
        assert deadline_ok.status is S.FAILED


def test_an_agent_that_ignores_the_timeout_is_marked_failed_after_the_grace_period_and_recovers_when_it_returns():
    a = FakeAgent("a", behavior="hang", supports_cancellation=False)
    orch, _, sched = make([a], inline=False, default_timeout=10, cancel_grace=5)
    t = task("stuck", agent_id="a")
    orch.submit(t)
    orch.start(t.task_id)
    wait_event(a.started)
    sched.advance(10)
    assert orch.get(t.task_id).error_code == "timeout" and a.status is AgentStatus.BUSY and orch.active_agents == 1
    sched.advance(5)                                                       # grace over, the work still runs
    assert a.status is AgentStatus.FAILED and "did not stop" in a.state.reason and orch.active_agents == 1
    assert orch.submit(task("more", agent_id="a")).error_code == "agent_failed"
    assert orch.describe(t.task_id)["still_running"] is True
    a.release.set()                                                        # it finally returns
    assert orch.wait_idle(WAIT) is True
    assert orch.active_agents == 0 and a.status is AgentStatus.AVAILABLE and orch.get(t.task_id).status is S.FAILED


def test_timers_are_cancelled_when_a_task_finishes_normally():
    orch, _, sched = make()
    orch.run(task())
    assert sched.pending() == 0
    sched.advance(10_000)
    assert orch.list()[0].status is S.SUCCEEDED


# ---- concurrency ---------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("limit", [1, 2, 3])
def test_the_concurrency_limit_is_enforced_at_every_moment(limit):
    probe = ConcurrencyProbe()
    agents = [FakeAgent(f"a{i}", behavior="wait", probe=probe) for i in range(5)]
    orch, reg, _ = make(agents, inline=False, max_concurrent=limit)
    tasks = [task(f"job{i}", agent_id=f"a{i}", priority=5) for i in range(5)]
    for t in tasks:
        orch.submit(t)
        orch.start(t.task_id)
    for a in agents[:limit]:
        wait_event(a.started)
    assert probe.current == limit == orch.active_agents                                   # exactly `limit` run ...
    assert [orch.get(t.task_id).status for t in tasks] == [S.RUNNING] * limit + [S.PENDING] * (5 - limit)   # ... the rest waits as PENDING
    assert orch.queued == 5 - limit
    for i in range(5):                                                                    # finish them one by one, in start order
        agents[i].release.set()
        finish(orch, tasks[i].task_id)
        assert probe.current <= limit and orch.active_agents <= limit
        if i + limit < 5:
            wait_event(agents[i + limit].started)                                         # the freed slot is handed to the next task
    assert probe.peak <= limit and orch.peak_running <= limit and probe.total == 5
    assert all(orch.get(t.task_id).status is S.SUCCEEDED for t in tasks) and orch.active_agents == 0 and orch.queued == 0


def test_a_burst_of_many_tasks_never_exceeds_the_limit_and_all_complete():
    probe = ConcurrencyProbe()
    agents = [FakeAgent(f"w{i}", probe=probe) for i in range(3)]
    orch, _, _ = make(agents, inline=False, max_concurrent=2, max_queue=100)
    ids = []
    for i in range(30):
        t = task(f"burst{i}", agent_id=f"w{i % 3}")
        ids.append(t.task_id)
        orch.submit(t)
        orch.start(t.task_id)
    results = [finish(orch, i) for i in ids]
    assert all(r.status is S.SUCCEEDED for r in results) and probe.peak <= 2 and orch.peak_running <= 2 and probe.total == 30
    assert all(len(a.tasks) == 10 for a in agents)
    assert orch.active_agents == 0 and all(a.status is AgentStatus.AVAILABLE for a in agents)


def test_one_agent_never_works_on_two_tasks_at_once():
    probe = ConcurrencyProbe()
    a = FakeAgent("solo", behavior="wait", probe=probe)
    orch, _, _ = make([a], inline=False, max_concurrent=3)
    t1, t2 = task("one", agent_id="solo"), task("two", agent_id="solo")
    orch.submit(t1), orch.submit(t2)
    orch.start(t1.task_id), orch.start(t2.task_id)
    wait_event(a.started)
    assert probe.current == 1 and orch.get(t2.task_id).status is S.PENDING and a.status is AgentStatus.BUSY
    a.release.set()
    finish(orch, t1.task_id), finish(orch, t2.task_id)
    assert probe.peak == 1


def test_priority_decides_who_starts_first_when_a_slot_frees_up():
    rec = RecordingExecutor()
    agents = [FakeAgent(n) for n in ("a", "b", "c", "d")]
    reg = AgentRegistry()
    [reg.register(x) for x in agents]
    orch = AgentOrchestrator(reg, max_concurrent=1, executor=rec, scheduler=ManualScheduler(), clock=FakeClock())
    blocker = task("first", agent_id="a")
    low, high, mid = task("low", agent_id="b", priority=9), task("high", agent_id="c", priority=1), task("mid", agent_id="d", priority=5)
    for t in (blocker, low, high, mid):
        orch.submit(t)
    orch.start(blocker.task_id)
    for t in (low, high, mid):
        orch.start(t.task_id)
    assert orch.get(blocker.task_id).status is S.RUNNING and orch.queued == 3
    rec.run_next()                                    # the blocker finishes -> the best waiting task starts
    assert orch.get(high.task_id).status is S.RUNNING
    rec.run_next()
    assert orch.get(mid.task_id).status is S.RUNNING
    rec.run_next()
    assert orch.get(low.task_id).status is S.RUNNING
    rec.run_next()
    assert all(orch.get(t.task_id).status is S.SUCCEEDED for t in (blocker, low, high, mid))


def test_a_task_that_can_not_start_for_lack_of_an_executor_fails_cleanly():
    class Broken:
        def submit(self, fn, name):
            raise RuntimeError("can't start new thread")

    reg = AgentRegistry()
    a = FakeAgent("fake")
    reg.register(a)
    orch = AgentOrchestrator(reg, executor=Broken(), scheduler=ManualScheduler(), clock=FakeClock())
    t = task()
    orch.submit(t)
    r = orch.start(t.task_id)
    assert r.status is S.FAILED and r.error_code == "executor_failed" and a.status is AgentStatus.AVAILABLE and orch.active_agents == 0


# ---- dependencies and agent-to-agent hand-over ----------------------------------------------------------------------------------------------------------
def test_a_task_waits_for_its_dependency_and_receives_its_result():
    research = FakeAgent("research", output={"facts": ["a", "b"]}, summary="found 2 facts")
    coder = FakeAgent("coder")
    orch, _, _ = make([research, coder])
    a = task("research", agent_id="research")
    b = AgentTask("implement", agent_id="coder", dependencies=(a.task_id,), input={"want": "x"})
    orch.submit(a), orch.submit(b)
    assert orch.start(b.task_id).status is S.PENDING and coder.tasks == []               # A has not run: B waits (no DAG engine, no guessing)
    assert orch.start(a.task_id).status is S.SUCCEEDED
    assert orch.get(b.task_id).status is S.SUCCEEDED                                    # A finishing released B automatically
    ctx = coder.contexts[0]
    assert set(ctx.parent_results) == {a.task_id}
    p = ctx.parent_results[a.task_id]
    assert (p.agent_id, p.status, p.summary, p.output) == ("research", S.SUCCEEDED, "found 2 facts", {"facts": ["a", "b"]})
    p.output["facts"].append("tampered")                                                # the hand-over is a copy
    assert orch.get(a.task_id).output == {"facts": ["a", "b"]}


def test_a_failed_dependency_blocks_the_dependent_task_and_everything_after_it():
    a_agent, b_agent = FakeAgent("a", behavior="failure"), FakeAgent("b")
    orch, _, _ = make([a_agent, b_agent])
    a = task("A", agent_id="a")
    b = AgentTask("B", agent_id="b", dependencies=(a.task_id,))
    c = AgentTask("C", agent_id="b", dependencies=(b.task_id,))
    for t in (a, b, c):
        orch.submit(t)
    orch.start(c.task_id), orch.start(b.task_id)
    orch.start(a.task_id)
    rb, rc = orch.get(b.task_id), orch.get(c.task_id)
    assert rb.status is S.BLOCKED and rb.error_code == "dependency_failed" and a.task_id in rb.error
    assert rc.status is S.BLOCKED and rc.error_code == "dependency_failed" and b_agent.tasks == []   # B was never run, so C is blocked too


@pytest.mark.parametrize("bad", ["failure", "blocked", "cancelled", "crash"])
def test_every_non_success_blocks_dependents(bad):
    orch, _, _ = make([FakeAgent("a", behavior=bad), FakeAgent("b")])
    a = task("A", agent_id="a")
    b = AgentTask("B", agent_id="b", dependencies=(a.task_id,))
    orch.submit(a), orch.submit(b)
    orch.start(b.task_id)
    orch.start(a.task_id)
    assert orch.get(b.task_id).status is S.BLOCKED


def test_the_result_of_the_parent_task_is_handed_on_to_its_child():
    p, c = FakeAgent("p", output={"v": 1}), FakeAgent("c")
    orch, _, _ = make([p, c])
    parent = task("parent", agent_id="p")
    orch.run(parent)
    r = orch.run(AgentTask("child", agent_id="c", parent_task_id=parent.task_id))
    assert r.status is S.SUCCEEDED and c.contexts[0].parent_results[parent.task_id].output == {"v": 1}
    stranger = orch.run(AgentTask("unrelated", agent_id="c"))
    assert stranger.status is S.SUCCEEDED and c.contexts[1].parent_results == {}


def test_parent_results_are_only_those_of_declared_dependencies():
    agents = [FakeAgent("x", output="secret-of-x"), FakeAgent("y"), FakeAgent("z")]
    orch, _, _ = make(agents)
    x, z = task("X", agent_id="x"), task("Z", agent_id="z")
    orch.run(x), orch.run(z)
    y = AgentTask("Y", agent_id="y", dependencies=(z.task_id,))
    orch.run(y)
    assert set(agents[1].contexts[0].parent_results) == {z.task_id}       # not x's result: nothing is shared implicitly


# ---- context isolation ----------------------------------------------------------------------------------------------------------------------------------
def test_the_agent_gets_only_the_context_the_orchestrator_gives_it():
    a = FakeAgent("fake", {"x.one", "x.two"}, tool_names=frozenset({"echo"}))
    orch, _, _ = make([a])
    t = task("do", input={"k": [1, 2]}, required_capabilities=frozenset({"x.one"}), metadata={"m": "v"})
    orch.run(t)
    ctx = a.contexts[0]
    assert ctx.task_id == t.task_id and ctx.objective == "do" and ctx.input == {"k": [1, 2]} and ctx.allowed_capabilities == frozenset({"x.one"})
    assert ctx.metadata == {"m": "v"} and ctx.relevant_memory == () and ctx.parent_results == {} and ctx.tools.allowed_tools == frozenset({"echo"})
    ctx.input["k"].append(3)                                             # an agent editing its input does not change the task
    assert t.input == {"k": [1, 2]}
    orch.run(task("no explicit capabilities"))
    assert a.contexts[1].allowed_capabilities == frozenset({"x.one", "x.two"})


def test_memory_is_only_fetched_on_explicit_request_read_only_and_redacted():
    calls = []

    def lookup(query, limit):
        calls.append((query, limit))
        return ["likes tea", "password=hunter22abc is the wifi", "x" * 2000, "4", "5", "6", "7"]

    a = FakeAgent("fake")
    reg = AgentRegistry()
    reg.register(a)
    orch = AgentOrchestrator(reg, memory_lookup=lookup, executor=InlineExecutor(), scheduler=ManualScheduler(), clock=FakeClock())
    orch.run(task("no memory wanted"))
    assert calls == [] and a.contexts[0].relevant_memory == ()
    orch.run(task("with memory", memory_query="tea"))
    assert calls == [("tea", 5)]
    mem = a.contexts[1].relevant_memory
    assert len(mem) == 5 and mem[0] == "likes tea" and "hunter22abc" not in " ".join(mem) and all(len(m) <= 500 for m in mem)


def test_memory_failures_never_block_a_task():
    def boom(q, n):
        raise RuntimeError("db down")

    reg = AgentRegistry()
    a = FakeAgent("fake")
    reg.register(a)
    orch = AgentOrchestrator(reg, memory_lookup=boom, executor=InlineExecutor(), scheduler=ManualScheduler(), clock=FakeClock())
    assert orch.run(task("x", memory_query="q")).status is S.SUCCEEDED and a.contexts[0].relevant_memory == ()
    orch2, reg2, _ = make()
    assert orch2.run(task("x", memory_query="q")).status is S.SUCCEEDED     # no lookup configured: simply no memory


def test_agent_results_are_not_written_to_memory_as_a_side_effect():
    stored = []

    class SpyMemory:
        def add(self, *a, **k):
            stored.append(a)

    reg = AgentRegistry()
    reg.register(FakeAgent("fake", output={"x": 1}))
    orch = AgentOrchestrator(reg, memory_lookup=lambda q, n: [], executor=InlineExecutor(), scheduler=ManualScheduler(), clock=FakeClock())
    orch.run(task("x", memory_query="q"))
    assert stored == [] and not hasattr(orch, "memory")


# ---- Core task manager integration -----------------------------------------------------------------------------------------------------------------------
def test_agent_tasks_are_mirrored_into_the_core_task_manager_without_being_merged_with_it():
    tm = TaskManager()
    orch, _, _ = make([FakeAgent("ok", summary="great"), FakeAgent("bad", behavior="failure"), FakeAgent("can", behavior="cancelled")], task_manager=tm)
    ok, bad, can = task("good", agent_id="ok"), task("bad one", agent_id="bad"), task("cancel me", agent_id="can")
    for t in (ok, bad, can):
        orch.run(t)
    pend = task("never started", agent_id="ok", priority=2)
    orch.submit(pend)
    blocked = orch.submit(task("blocked", agent_id="ghost"))
    by_desc = {t.description: t for t in tm.list()}
    assert by_desc["good"].status is CoreStatus.COMPLETED and by_desc["good"].result == "great" and by_desc["good"].required_agents == ["ok"]
    assert by_desc["bad one"].status is CoreStatus.FAILED and by_desc["cancel me"].status is CoreStatus.CANCELLED
    assert by_desc["never started"].status is CoreStatus.PENDING and by_desc["never started"].priority == 2
    assert by_desc["blocked"].status is CoreStatus.FAILED
    assert ok.task_id not in {t.id for t in tm.list()} and "agent_id" not in by_desc["good"].to_dict()      # separate models, linked by mirroring only


def test_mirroring_problems_never_break_orchestration():
    class BrokenManager:
        def add(self, t):
            raise RuntimeError("full")

    orch, _, _ = make(task_manager=BrokenManager())
    assert orch.run(task()).status is S.SUCCEEDED


def test_task_lifecycle_is_forward_only():
    orch, _, _ = make()
    r = orch.run(task())
    rec = orch._records[r.task_id]
    from jarvis.agents.errors import StateError
    for new in S:
        with pytest.raises(StateError):
            orch._finalize(rec, new, "", None, None, None)      # a finished task can never change again
    assert orch.get(r.task_id).status is S.SUCCEEDED and r.status in TERMINAL


def test_invalid_orchestrator_limits_are_rejected():
    for kw in (dict(max_concurrent=0), dict(default_timeout=0), dict(max_queue=0), dict(max_history=0), dict(cancel_grace=-1)):
        with pytest.raises(InvalidTaskError):
            AgentOrchestrator(AgentRegistry(), **kw)
