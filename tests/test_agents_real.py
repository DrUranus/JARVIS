"""Real execution paths (threads + real processes), valid on Windows and POSIX: the orchestrator drives the coding agent against a real project
with real pytest, and cancellation really stops a real running test."""
import sys
import threading
import time

import pytest

from agents_util import WAIT, FakeClock, ManualScheduler, wait_event
from coding_util import ONCE, PYPROJECT, make_rig as coding_rig
from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentTask, TaskStatus
from jarvis.agents.adapters import CodingAgent

S = TaskStatus


def wait_for_file(path, limit=WAIT * 6):
    """Bounded wait for a marker the test process writes when it starts (there is no event for 'a child process is running')."""
    end = time.monotonic() + limit
    gate = threading.Event()
    while time.monotonic() < end:
        if path.exists():
            return True
        gate.wait(0.05)
    return False


def orchestrator(rig, **kw):
    reg = AgentRegistry()
    reg.register(CodingAgent(interrupt=lambda: rig.controller.halt("agent task cancelled")))
    return AgentOrchestrator(reg, tools=rig.registry, scheduler=ManualScheduler(), clock=FakeClock(), **kw), reg


def test_a_real_orchestrated_fix_cycle_with_real_threads_and_real_pytest(tmp_path):
    rig = coding_rig(tmp_path, [ONCE] * 20, real=True, test_timeout=120)
    orch, reg = orchestrator(rig)
    steps = [{"action": "start", "workspace": str(rig.project)}, {"action": "test"},
             {"action": "write", "path": "calc.py", "mode": "replace", "old_text": "return a - b", "new_text": "return a + b"}, {"action": "test"}]
    r = orch.run(AgentTask("fix the failing test", agent_id="coding", input={"steps": steps}), timeout=WAIT * 6)
    assert r.status is S.SUCCEEDED, (r.error, r.output)
    out = r.output["steps"]
    assert out[1]["output"]["passed"] is False and out[3]["output"]["passed"] is True and out[3]["output"]["summary"].startswith("2 passed")
    assert reg.get("coding").status.value == "AVAILABLE" and orch.active_agents == 0
    assert r.started_at <= r.finished_at


def test_cancelling_a_really_running_test_stops_the_process_and_ends_cancelled(tmp_path):
    files = {"pyproject.toml": PYPROJECT, "tests/test_slow.py": "import time\n\n\ndef test_slow():\n    open('started.marker', 'w').close()\n    time.sleep(120)\n"}
    rig = coding_rig(tmp_path, [ONCE] * 4, real=True, files=files, test_timeout=300)
    orch, reg = orchestrator(rig)
    t = AgentTask("run the slow test", agent_id="coding", input={"steps": [{"action": "start", "workspace": str(rig.project)}, {"action": "test"}]}, timeout=600)
    orch.submit(t)
    started_at = time.monotonic()
    orch.start(t.task_id)
    assert wait_for_file(rig.project / "started.marker")          # the real test process is running (it says so itself)
    rep = orch.cancel(t.task_id, wait=WAIT * 3)
    r = orch.get(t.task_id)
    assert rep.accepted and r.status is S.CANCELLED, (rep, r.status, r.error)
    assert time.monotonic() - started_at < 60                      # nowhere near the 120 s the test would have slept
    assert reg.get("coding").status.value == "AVAILABLE" and orch.active_agents == 0 and rig.controller.halted is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process semantics")
def test_windows_halt_kills_the_test_process_it_started(tmp_path):
    files = {"pyproject.toml": PYPROJECT, "tests/test_slow.py": "import time\n\n\ndef test_slow():\n    open('started.marker', 'w').close()\n    time.sleep(120)\n"}
    rig = coding_rig(tmp_path, [ONCE] * 4, real=True, files=files, test_timeout=300)
    orch, _ = orchestrator(rig)
    t = AgentTask("slow", agent_id="coding", input={"steps": [{"action": "start", "workspace": str(rig.project)}, {"action": "test"}]}, timeout=600)
    orch.submit(t)
    orch.start(t.task_id)
    assert wait_for_file(rig.project / "started.marker")
    t0 = time.monotonic()
    orch.cancel(t.task_id, wait=WAIT * 3)
    assert orch.get(t.task_id).status is S.CANCELLED and time.monotonic() - t0 < 30
