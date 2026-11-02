"""Fehlerbehandlung der Agenten (agent-error-recovery): Klassifikation, begrenzte Wiederholung, nie nach Ablehnung/Notaus/Abbruch,
Ereignis task_update mit Grund, bestehende Replanning-Grenzen unveraendert. Keine Netzwerkzugriffe, keine Wartezeiten."""
from __future__ import annotations

import pytest

from jarvis.agents import AgentResult, AgentTask, TaskStatus
from jarvis.agents.recovery import (MAX_ATTEMPTS, FailureKind, RecoveryRunner, classify)
from jarvis.goals import policy as GP
from jarvis.redaction import SecretDetector
from jarvis.ui_contract.bus import EventLog


def res(status, code, task_id="t1"):
    return AgentResult(task_id, "browser", status, error=code, error_code=code)


class ScriptedOrch:
    """Liefert vorgegebene Ergebnisse; merkt sich jede eingereichte Aufgabe."""
    def __init__(self, results):
        self.results, self.tasks = list(results), []

    def run(self, task, timeout=None):
        self.tasks.append(task)
        r = self.results.pop(0) if self.results else res(TaskStatus.SUCCEEDED, None)
        return AgentResult(task.task_id, r.agent_id, r.status, r.summary, None, r.error, r.error_code)


OK = AgentResult("x", "browser", TaskStatus.SUCCEEDED, "ok")
RETRYABLE = ["timeout", "backend_error", "rate_limited"]
FATAL = ["not_authorized", "permission_denied", "blocked_target", "failsafe", "halted", "cancelled", "budget_exhausted", "tool_access_denied",
         "something_unknown", None]


@pytest.mark.parametrize("code", RETRYABLE)
def test_classify_retryable(code):
    assert classify(TaskStatus.FAILED, code).kind is FailureKind.RETRY


def test_classify_target_changed_needs_replan():
    assert classify(TaskStatus.FAILED, "target_changed").kind is FailureKind.RETRY_REPLAN


@pytest.mark.parametrize("code", FATAL)
def test_classify_fatal_fail_closed(code):
    c = classify(TaskStatus.FAILED, code)
    assert c.kind is FailureKind.FATAL and c.reason


@pytest.mark.parametrize("status", [TaskStatus.CANCELLED, TaskStatus.BLOCKED])
def test_classify_cancel_and_blocked_never_retry(status):
    assert classify(status, "timeout").kind is FailureKind.FATAL


def test_cap_is_three_and_not_raisable():
    assert MAX_ATTEMPTS == 3
    with pytest.raises(ValueError):
        RecoveryRunner(ScriptedOrch([]), max_attempts=4)
    with pytest.raises(ValueError):
        RecoveryRunner(ScriptedOrch([]), max_attempts=0)


@pytest.mark.parametrize("code", RETRYABLE)
def test_each_retryable_code_stops_after_three_attempts(code):
    orch = ScriptedOrch([res(TaskStatus.FAILED, code)] * 10)
    out = RecoveryRunner(orch).run(AgentTask("lies die Seite", task_id="job"))
    assert len(orch.tasks) == 3 and out.attempts == 3 and out.exhausted
    assert out.result.error_code == code and not out.result.succeeded
    assert len({t.task_id for t in orch.tasks}) == 3        # frische Task-IDs je Versuch


def test_success_after_retry():
    orch = ScriptedOrch([res(TaskStatus.FAILED, "rate_limited"), OK])
    out = RecoveryRunner(orch).run(AgentTask("a", task_id="job"))
    assert out.result.succeeded and out.attempts == 2 and not out.exhausted


@pytest.mark.parametrize("code", ["not_authorized", "permission_denied", "blocked_target", "failsafe", "halted", "budget_exhausted"])
def test_fatal_code_never_retried(code):
    orch = ScriptedOrch([res(TaskStatus.FAILED, code)] * 5)
    out = RecoveryRunner(orch).run(AgentTask("a"))
    assert len(orch.tasks) == 1 and out.attempts == 1 and not out.exhausted


def test_cancelled_result_never_retried():
    orch = ScriptedOrch([res(TaskStatus.CANCELLED, "cancelled")] * 5)
    out = RecoveryRunner(orch).run(AgentTask("a"))
    assert out.attempts == 1 and len(orch.tasks) == 1


def test_emergency_stop_before_retry_blocks_it():
    state = {"stop": False}
    orch = ScriptedOrch([res(TaskStatus.FAILED, "timeout")] * 5)
    runner = RecoveryRunner(orch, halted=lambda: state["stop"])
    orig = orch.run

    def run(task, timeout=None):
        r = orig(task, timeout)
        state["stop"] = True                      # Notaus waehrend des Versuchs
        return r
    orch.run = run
    out = runner.run(AgentTask("a"))
    assert len(orch.tasks) == 1 and out.attempts == 1


def test_stop_before_first_attempt_runs_nothing():
    orch = ScriptedOrch([])
    out = RecoveryRunner(orch, halted=lambda: True).run(AgentTask("a"))
    assert orch.tasks == [] and out.attempts == 0 and out.result.error_code == "halted" and out.result.status is TaskStatus.BLOCKED


def test_cancel_request_blocks_retry():
    flag = {"c": False}
    orch = ScriptedOrch([res(TaskStatus.FAILED, "timeout")] * 5)
    orig = orch.run

    def run(task, timeout=None):
        r = orig(task, timeout)
        flag["c"] = True
        return r
    orch.run = run
    out = RecoveryRunner(orch, cancelled=lambda: flag["c"]).run(AgentTask("a"))
    assert len(orch.tasks) == 1 and out.result.error_code in ("timeout", "cancelled")


def test_check_failure_is_fail_closed():
    def boom():
        raise RuntimeError("x")
    orch = ScriptedOrch([res(TaskStatus.FAILED, "timeout")] * 5)
    out = RecoveryRunner(orch, halted=boom).run(AgentTask("a"))
    assert len(orch.tasks) == 0 and out.result.error_code == "halted"


def test_target_changed_retries_only_with_replanned_task():
    orch = ScriptedOrch([res(TaskStatus.FAILED, "target_changed"), OK])
    seen = []

    def replan(task, result, attempt):
        seen.append((result.error_code, attempt))
        return AgentTask("neu geplant", agent_id=task.agent_id)
    out = RecoveryRunner(orch, replan=replan).run(AgentTask("alt", task_id="job"))
    assert out.result.succeeded and seen == [("target_changed", 2)] and orch.tasks[1].objective == "neu geplant"


def test_target_changed_without_replan_falls_back_to_goal_replanning():
    orch = ScriptedOrch([res(TaskStatus.FAILED, "target_changed")] * 3)
    out = RecoveryRunner(orch).run(AgentTask("a"))
    assert len(orch.tasks) == 1 and out.fall_back_to_replanning and not out.exhausted


def test_replan_returning_none_or_raising_stops():
    for rp in (lambda t, r, n: None, lambda t, r, n: 1 / 0):
        orch = ScriptedOrch([res(TaskStatus.FAILED, "target_changed")] * 3)
        out = RecoveryRunner(orch, replan=rp).run(AgentTask("a"))
        assert len(orch.tasks) == 1 and out.fall_back_to_replanning


def test_exhausted_retryable_falls_back_to_replanning():
    out = RecoveryRunner(ScriptedOrch([res(TaskStatus.FAILED, "backend_error")] * 5)).run(AgentTask("a"))
    assert out.exhausted and out.fall_back_to_replanning


def test_fatal_never_falls_back_to_replanning():
    out = RecoveryRunner(ScriptedOrch([res(TaskStatus.FAILED, "not_authorized")])).run(AgentTask("a"))
    assert not out.fall_back_to_replanning


def test_task_update_events_carry_reason_and_validate():
    log = EventLog(None, SecretDetector.from_environment())
    orch = ScriptedOrch([res(TaskStatus.FAILED, "timeout"), res(TaskStatus.FAILED, "rate_limited"), res(TaskStatus.FAILED, "timeout")])
    RecoveryRunner(orch, emit=log.emit).run(AgentTask("a", task_id="job"))
    updates = [e for e in log.events_since(0) if e["type"] == "task_update"]
    assert updates, "expected task_update events"
    assert all(e["data"]["kind"] == "agent_task" and e["data"]["detail"] for e in updates)
    assert any("timeout" in e["data"]["detail"] for e in updates) and any("rate_limited" in e["data"]["detail"] for e in updates)


def test_emit_failure_never_breaks_recovery():
    def bad(_t, _d):
        raise RuntimeError("x")
    orch = ScriptedOrch([res(TaskStatus.FAILED, "timeout"), OK])
    assert RecoveryRunner(orch, emit=bad).run(AgentTask("a")).result.succeeded


def test_existing_goal_replanning_limits_unchanged():
    assert GP.MAX_REPLANS == 2 and GP.MAX_ATTEMPTS_HARD == 5
    assert GP.RETRYABLE_CODES == frozenset({"timeout", "agent_crashed", "executor_failed", "queue_full", "step_failed"})
    assert GP.is_retryable(TaskStatus.FAILED, "timeout") and not GP.is_retryable(TaskStatus.FAILED, "permission_denied")
    assert not GP.is_retryable(TaskStatus.FAILED, "rate_limited")      # das Replanning der Goal Engine wurde nicht erweitert
