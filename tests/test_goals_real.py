"""REAL execution of the goal engine (valid on Windows and POSIX): real threads, the real orchestrator and timers, the real coding agent on a
real project directory with a real pytest run, real cancellation of a running test process, real timeouts, dependencies and retries.
No external services and no network. The permission engine is the real one with scripted confirmations."""
from __future__ import annotations

import sys
import threading
import time

import pytest

from agents_util import WAIT, FakeAgent, wait_event
from coding_util import ONCE, PYPROJECT, make_rig as coding_rig
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry
from jarvis.agents.adapters import CodingAgent
from jarvis.goals import GoalEngine, GoalPlanner, GoalStatus, StepStatus
from jarvis.goals.fake import StaticPlanner, step

SLOW = {"pyproject.toml": PYPROJECT, "tests/test_slow.py": "import time\n\n\ndef test_slow():\n    open('started.marker', 'w').close()\n    time.sleep(120)\n"}


def wait_for_file(path, limit=WAIT * 6):
    end = time.monotonic() + limit
    gate = threading.Event()
    while time.monotonic() < end:
        if path.exists():
            return True
        gate.wait(0.05)
    return False


@pytest.fixture
def made():
    items = []
    yield items
    for engine, orch in items:
        engine.shutdown(5)
        orch.shutdown(5)


def real_engine(rig, made, *, attempts=2, goal_timeout=300.0, step_timeout=120.0, extra_agents=(), planner=None, cancel_grace=10.0):
    reg = AgentRegistry()
    reg.register(CodingAgent(interrupt=lambda: rig.controller.halt("agent task cancelled")))
    for a in extra_agents:
        reg.register(a)
    orch = AgentOrchestrator(reg, tools=rig.registry, cancel_grace=cancel_grace)         # real threads, real timers
    planner = planner or GoalPlanner(AgentPlanner(reg), max_attempts=attempts, step_timeout=step_timeout)
    engine = GoalEngine(orch, planner, max_attempts=attempts, goal_timeout=goal_timeout, step_timeout=step_timeout, cancel_wait=cancel_grace + 5)
    made.append((engine, orch))
    return engine, orch, reg


def test_real_goal_fixes_a_project_through_real_agents_and_real_pytest(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 12, real=True, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    edits = [{"path": "calc.py", "mode": "replace", "old_text": "return a - b", "new_text": "return a + b"}]
    g = engine.create("Ändere calc.py und prüfe mit den Tests", context={"workspace": str(rig.project), "edits": edits})
    res = engine.run(g.goal_id)
    assert res.status is GoalStatus.SUCCEEDED, (res.summary, [(s.step_id, s.status.value, s.result.summary) for s in res.steps])
    assert [s.step_id for s in res.steps] == ["s1", "s2", "s3", "s4", "s5"] and all(s.status is StepStatus.SUCCEEDED for s in res.steps)
    assert (rig.project / "calc.py").read_text(encoding="utf-8").replace("\r\n", "\n").count("return a + b") == 1          # really on disk
    test_out = res.steps[2].result.output["steps"][0]["output"]
    assert test_out["passed"] is True and test_out["summary"].startswith("2 passed")                                       # a real pytest run
    assert all(s.result.agent_id == "coding" for s in res.steps if s.assigned_agent) and res.steps[0].result.task_id != res.steps[1].result.task_id
    assert rig.controller.overview()["session"]["status"] == "completed" and orch.wait_idle(WAIT * 3) and not res.warnings
    assert [q.action for q in rig.prompts.requests][:3] == ["start", "write", "test"]       # the permission engine asked, in this order


def test_real_dependency_failed_first_step_means_nothing_else_runs(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 6, real=True)
    engine, orch, reg = real_engine(rig, made)
    edits = [{"path": "calc.py", "mode": "replace", "old_text": "return a - b", "new_text": "return a + b"}]
    missing = rig.ws / "does-not-exist"
    res = engine.run(engine.create("Ändere calc.py und prüfe mit den Tests", context={"workspace": str(missing), "edits": edits}).goal_id)
    assert res.status in (GoalStatus.FAILED, GoalStatus.BLOCKED)
    by = {s.step_id: s.status for s in res.steps}
    assert by["s1"] in (StepStatus.FAILED, StepStatus.BLOCKED) and by["s2"] is StepStatus.BLOCKED and by["s3"] is StepStatus.BLOCKED
    assert "return a - b" in (rig.project / "calc.py").read_text(encoding="utf-8")       # the write step never ran
    assert not any(q.action == "write" for q in rig.prompts.requests)


def test_real_retry_after_a_transient_failure_with_real_threads(tmp_path, made):
    flaky = FakeAgent("flaky", {"research.web"}, script=["failure", "failure", "success"], failure_code="step_failed", output={"text": "ok"})
    rig = coding_rig(tmp_path, [], real=True)
    planner = StaticPlanner(lambda goal: [step(goal, "s1", "flaky", attempts=3), step(goal, "ev", None, deps=("s1",))])
    engine, orch, reg = real_engine(rig, made, attempts=3, extra_agents=[flaky], planner=planner)
    res = engine.run(engine.create("lies etwas").goal_id)
    assert res.status is GoalStatus.SUCCEEDED
    r = res.steps[0].result
    assert r.attempts == 3 and [a["status"] for a in r.attempt_log] == ["FAILED", "FAILED", "SUCCEEDED"] and len(flaky.tasks) == 3


def test_real_goal_timeout_stops_a_really_running_test_process(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 4, real=True, files=SLOW, test_timeout=300)
    engine, orch, reg = real_engine(rig, made, attempts=1)
    g = engine.create("Führe die Tests aus", context={"workspace": str(rig.project)}, timeout=4.0)
    t0 = time.monotonic()
    res = engine.run(g.goal_id)
    assert (rig.project / "started.marker").exists()                           # the real test process was running
    assert res.status is GoalStatus.TIMEOUT, (res.summary, res.warnings)
    assert time.monotonic() - t0 < 60                                          # nowhere near the 120 s the test sleeps
    assert orch.wait_idle(WAIT * 3) and not any("not stopped" in w for w in res.warnings)
    assert {s.step_id: s.status for s in res.steps}["s2"] in (StepStatus.TIMEOUT, StepStatus.CANCELLED)


def test_real_step_timeout_through_the_orchestrators_timer(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 4, real=True, files=SLOW, test_timeout=300)
    engine, orch, reg = real_engine(rig, made, attempts=1, step_timeout=4.0)
    res = engine.run(engine.create("Führe die Tests aus", context={"workspace": str(rig.project)}).goal_id)
    by = {s.step_id: s for s in res.steps}
    assert res.status is GoalStatus.FAILED and by["s2"].status is StepStatus.TIMEOUT and by["s2"].result.error_code == "timeout"
    assert orch.wait_idle(WAIT * 3)                                             # the orchestrator stopped the process too (its cancel hook)


def test_real_cancellation_of_a_running_goal_stops_the_real_process(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 4, real=True, files=SLOW, test_timeout=300)
    engine, orch, reg = real_engine(rig, made, attempts=1)
    g = engine.create("Führe die Tests aus", context={"workspace": str(rig.project)})
    engine.start(g.goal_id)
    assert wait_for_file(rig.project / "started.marker")                       # the real test process says it runs
    t0 = time.monotonic()
    assert engine.cancel(g.goal_id).accepted
    res = engine.wait(g.goal_id, WAIT * 6)
    assert res.status is GoalStatus.CANCELLED, (res.status, res.summary, res.warnings)
    assert time.monotonic() - t0 < 60 and orch.wait_idle(WAIT * 3) and reg.get("coding").status.value == "AVAILABLE"
    assert {s.step_id: s.status for s in res.steps}["s2"] is StepStatus.CANCELLED
    assert not any(q.action == "write" for q in rig.prompts.requests)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific path handling is checked on Windows only")
def test_real_goal_on_windows_paths(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 12, real=True, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    edits = [{"path": "calc.py", "mode": "replace", "old_text": "return a - b", "new_text": "return a + b"}]
    res = engine.run(engine.create("Ändere calc.py und prüfe mit den Tests", context={"workspace": str(rig.project), "edits": edits}).goal_id)
    assert res.status is GoalStatus.SUCCEEDED, res.summary
    assert "\\" in str(rig.project)
