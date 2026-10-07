"""REAL self-repair (Windows and POSIX): real threads, the real orchestrator, the real coding agent on a real project directory with real pytest
runs and real file changes; the permission engine is the real one with scripted confirmations. No network, no external services."""
from __future__ import annotations

import sys
import threading
import time

import pytest

from agents_util import WAIT
from coding_util import ONCE, PYPROJECT, make_rig as coding_rig
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry
from jarvis.agents.adapters import CodingAgent
from jarvis.self_repair import AttemptStatus, RepairEngine, RepairStatus
from repair_util import candidates

S = RepairStatus
FIX = {"path": "calc.py", "mode": "replace", "old_text": "return a - b", "new_text": "return a + b"}
SLOW = {"pyproject.toml": PYPROJECT, "calc.py": "def add(a, b):\n    return a + b\n",
        "tests/test_slow.py": "import time\n\n\ndef test_slow():\n    open('started.marker', 'w').close()\n    time.sleep(120)\n"}
GUARDED = {"pyproject.toml": PYPROJECT, "calc.py": "def add(a, b):\n    return a - b\n",
           "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
           "tests/test_other.py": "from calc import add\n\n\ndef test_other():\n    assert add(5, 3) == 2\n"}      # passes only with the BUG: the fix breaks it


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


def real_engine(rig, made, *, agent=None, max_attempts=3, repair_timeout=300.0, step_timeout=120.0, cancel_grace=10.0):
    reg = AgentRegistry()
    reg.register(agent or CodingAgent(interrupt=lambda: rig.controller.halt("agent task cancelled")))
    orch = AgentOrchestrator(reg, tools=rig.registry, cancel_grace=cancel_grace)               # real threads, real timers
    engine = RepairEngine(orch, AgentPlanner(reg), max_attempts=max_attempts, repair_timeout=repair_timeout, step_timeout=step_timeout,
                          cancel_wait=cancel_grace + 5)
    made.append((engine, orch))
    return engine, orch, reg


def go(engine, rig, objective="Behebe den Fehler in calc.py", cands=None, **ctx):
    context = dict(ctx)
    if cands is not None:
        context["candidates"] = cands
    return engine.run(engine.create(objective, workspace=str(rig.project), context=context).run_id)


def disk(rig):
    return (rig.project / "calc.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_real_1_failing_project_is_repaired_and_proven(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 16, real=True, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    res = go(engine, rig, cands=candidates(FIX))
    assert res.status is S.SUCCEEDED, (res.run.final_summary, res.warnings, [(a.status.value, a.failure_reason) for a in res.attempts])
    assert "return a + b" in disk(rig) and res.changed_files == ("calc.py",)                       # really on disk
    a = res.attempts[0]
    assert a.diagnosis.category.value == "ASSERTION_FAILURE" and a.targeted_test_result.passed and a.regression_result.passed
    assert not res.baseline.passed and res.baseline.failed_tests == ("tests/test_calc.py::test_add",) and a.targeted_test_result.summary.startswith("1 passed")
    assert a.regression_result.summary.startswith("2 passed")
    assert [q.action for q in rig.prompts.requests][:2] == ["start", "test"] and [q.action for q in rig.prompts.requests].count("write") == 1
    assert rig.controller.overview()["session"]["status"] == "completed" and orch.wait_idle(WAIT * 3) and not res.warnings


def test_real_2_repairs_that_do_not_help_end_failed_at_max_attempts(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 24, real=True, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    wrong = [{**FIX, "new_text": "return a - b + 0"}, {**FIX, "old_text": "return a - b + 0", "new_text": "return a - b + 1"},
             {**FIX, "old_text": "return a - b + 1", "new_text": "return a - b + 2"}]
    res = go(engine, rig, cands=candidates(*wrong))
    assert res.status is S.FAILED and res.reason_code == "max_attempts" and res.run.attempt_count == 3
    assert [a.status for a in res.attempts] == [AttemptStatus.FAILED] * 3 and all(a.regression_result is None for a in res.attempts)
    assert "return a - b + 2" in disk(rig) and not res.succeeded                                    # the failure is reported, the half-repaired file is not hidden


def test_real_3_permission_denied_blocks_without_retry(tmp_path, made):
    from jarvis.permissions import ConfirmationChoice
    rig = coding_rig(tmp_path, [ONCE, ONCE, ConfirmationChoice.DENY, ONCE], real=True, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    res = go(engine, rig, cands=candidates(FIX, FIX))
    assert res.status is S.BLOCKED and res.reason_code == "permission_denied" and res.run.attempt_count == 1
    assert "return a - b" in disk(rig) and [q.action for q in rig.prompts.requests].count("write") == 1          # nothing written, asked exactly once


def test_real_4_a_file_outside_the_plan_is_never_accepted(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 16, real=True, test_timeout=120)

    class Sneaky(CodingAgent):
        """A misbehaving agent: besides the planned write it also creates another file."""
        def perform(self, task, ctx):
            steps = task.input.get("steps", [])
            if any(s.get("action") == "write" for s in steps):
                from dataclasses import replace
                extra = {"action": "write", "path": "other.py", "mode": "create", "content": "x = 1\n"}
                task = replace(task, input={"steps": steps[:-1] + [extra, steps[-1]]})
            return super().perform(task, ctx)
    engine, orch, reg = real_engine(rig, made, agent=Sneaky(interrupt=lambda: rig.controller.halt("agent task cancelled")))
    res = go(engine, rig, cands=candidates(FIX))
    assert res.status is S.BLOCKED and res.reason_code == "unexpected_change" and "other.py" in res.run.final_summary
    assert res.attempts[0].status is AttemptStatus.BLOCKED and res.attempts[0].targeted_test_result is None          # never tested, never accepted
    assert not res.succeeded and (rig.project / "other.py").exists()                                                    # honest: nothing was rolled back


def test_real_5_regression_failure_is_failed_not_success(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 16, real=True, files=GUARDED, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    res = go(engine, rig, cands=candidates(FIX, FIX))
    a = res.attempts[0]
    assert res.status is S.FAILED and res.reason_code == "regression_failed" and not res.succeeded
    assert a.targeted_test_result.passed and not a.regression_result.passed and a.regression_result.failed_tests == ("tests/test_other.py::test_other",)
    assert "NOT reported as successful" in res.run.final_summary


def test_real_6_cancellation_stops_the_real_test_process(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 4, real=True, files=SLOW, test_timeout=300)
    engine, orch, reg = real_engine(rig, made)
    run = engine.create("Teste das Projekt", workspace=str(rig.project))
    engine.start(run.run_id)
    assert wait_for_file(rig.project / "started.marker")                                         # the real process says it runs
    t0 = time.monotonic()
    assert engine.cancel(run.run_id).accepted
    res = engine.wait(run.run_id, WAIT * 6)
    assert res.status is S.CANCELLED, (res.status, res.run.final_summary, res.warnings)
    assert time.monotonic() - t0 < 60 and orch.wait_idle(WAIT * 3) and reg.get("coding").status.value == "AVAILABLE"
    assert not any(q.action == "write" for q in rig.prompts.requests)


def test_real_6b_repair_timeout_stops_the_real_test_process(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 4, real=True, files=SLOW, test_timeout=300)
    engine, orch, reg = real_engine(rig, made, repair_timeout=4.0)
    t0 = time.monotonic()
    res = engine.run(engine.create("Teste das Projekt", workspace=str(rig.project)).run_id)
    assert res.status is S.TIMEOUT and time.monotonic() - t0 < 60 and orch.wait_idle(WAIT * 3)


def test_real_7_crlf_sources_are_repaired(tmp_path, made):
    files = {"pyproject.toml": PYPROJECT, "calc.py": "def add(a, b):\r\n    return a - b\r\n",
             "tests/test_calc.py": "from calc import add\r\n\r\n\r\ndef test_add():\r\n    assert add(2, 3) == 5\r\n"}
    rig = coding_rig(tmp_path, [ONCE] * 16, real=True, files=files, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    res = go(engine, rig, cands=candidates(FIX))
    assert res.status is S.SUCCEEDED, (res.run.final_summary, res.warnings)
    assert "return a + b" in disk(rig) and res.attempts[0].targeted_test_result.passed


def test_real_8_secret_files_and_tests_are_refused_before_anything_is_written(tmp_path, made):
    files = {"pyproject.toml": PYPROJECT, ".env": "API_KEY=abcdefghijklmnop\n", "calc.py": "def add(a, b):\n    return a - b\n",
             "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"}
    rig = coding_rig(tmp_path, [ONCE] * 16, real=True, files=files, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    for path in (".env", "tests/test_calc.py", "../escape.py"):
        res = go(engine, rig, cands=candidates({"path": path, "mode": "overwrite", "content": "x = 1\n"}))
        assert res.status is S.BLOCKED, path
    assert (rig.project / ".env").read_text() == "API_KEY=abcdefghijklmnop\n" and not (tmp_path / "escape.py").exists()
    assert not [q for q in rig.prompts.requests if q.action == "write"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths are checked on Windows only")
def test_real_9_windows_paths_and_python_version(tmp_path, made):
    rig = coding_rig(tmp_path, [ONCE] * 16, real=True, test_timeout=120)
    engine, orch, reg = real_engine(rig, made)
    assert "\\" in str(rig.project) and sys.version_info >= (3, 13)
    res = go(engine, rig, cands=candidates({**FIX, "path": "calc.py"}))
    assert res.status is S.SUCCEEDED, res.run.final_summary
    res2 = go(engine, rig, cands=candidates({**FIX, "path": "..\\evil.py"}))
    assert res2.status is S.BLOCKED
