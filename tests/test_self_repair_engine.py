"""RepairEngine with the scripted FakeCodingAgent: every path of the run, deterministic."""
from __future__ import annotations

import json
import logging
import threading

import pytest

from repair_util import EDIT, FAIL, FAIL_OUT, FakeCodingAgent, candidates, failing, rig, test_run, wait_event
from jarvis.agents import AgentPlanner
from jarvis.redaction import SecretDetector
from jarvis.self_repair import (AttemptStatus, ErrorCategory, InvalidRepairError, RepairError, RepairPlanner, RepairStateError, RepairStatus,
                                UnknownRepairError)

GOOD = test_run(True, summary="2 passed")
S = RepairStatus


@pytest.fixture
def engines():
    made = []

    def build(*a, **kw):
        out = rig(*a, **kw)
        made.append(out)
        return out

    yield build
    for engine, orch, agent, _ in made:
        agent.release.set()
        engine.shutdown(1.0)
        orch.shutdown(0.5)


def repair(engine, objective="Behebe den Fehler in calc.py", cands=None, **ctx):
    context = dict(ctx)
    if cands is not None:
        context["candidates"] = cands
    return engine.run(engine.create(objective, workspace="/w", context=context or None).run_id)


# ---- success path ----------------------------------------------------------------------------------------------------------------------------
def test_repair_succeeds_only_after_targeted_and_regression_pass(engines):
    agent = FakeCodingAgent([failing(), GOOD, GOOD])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert res.status is S.SUCCEEDED and res.reason_code == "repaired" and res.run.attempt_count == 1 and res.changed_files == ("calc.py",)
    assert agent.actions == ["start", "info", "test", "write", "changes", "test", "test", "stop"]          # order: baseline, repair, targeted, regression
    a = res.attempts[0]
    assert a.status is AttemptStatus.SUCCEEDED and a.diagnosis.category is ErrorCategory.ASSERTION_FAILURE
    assert a.targeted_test_result.passed and a.regression_result.passed and a.changed_files == ("calc.py",) and not agent.session
    assert res.baseline is not None and not res.baseline.passed and res.run.finished_at >= res.run.started_at
    w = agent.written[0]
    assert w["action"] == "write" and w["path"] == "calc.py" and "confirmed" not in w                  # a plain tool step, nothing extra


def test_targeted_retest_runs_the_failed_tests_only_and_regression_the_whole_suite(engines):
    agent = FakeCodingAgent([failing(), GOOD, GOOD])
    engine, *_ = engines(agent)
    repair(engine, cands=candidates(EDIT), runner="pytest")
    tests = [s for t in agent.tasks for s in t.input["steps"] if s["action"] == "test"]
    assert tests[0] == {"action": "test", "runner": "pytest"} and tests[1] == {"action": "test", "runner": "pytest", "args": FAIL[0]}
    assert tests[2] == {"action": "test", "runner": "pytest"}


def test_nothing_to_repair_when_tests_already_pass(engines):
    agent = FakeCodingAgent([GOOD])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert res.status is S.SUCCEEDED and res.reason_code == "tests_pass" and not agent.written and res.attempts == () and "nothing was changed" in res.run.final_summary


def test_self_test_only_reports_the_result(engines):
    agent = FakeCodingAgent([GOOD])
    engine, *_ = engines(agent)
    assert repair(engine, "Teste das aktuelle Projekt").status is S.SUCCEEDED
    agent = FakeCodingAgent([failing()])
    engine, *_ = engines(agent)
    res = repair(engine, "Teste das aktuelle Projekt")
    assert res.status is S.FAILED and res.reason_code == "tests_fail" and not agent.written and res.baseline.failed_tests == FAIL and not agent.session


# ---- blocked: nothing understood / not allowed ------------------------------------------------------------------------------------------------------
def test_no_proposal_means_blocked_not_an_invented_repair(engines):
    agent = FakeCodingAgent([failing()])
    engine, *_ = engines(agent)
    res = repair(engine)
    assert res.status is S.BLOCKED and res.reason_code == "no_plan" and not agent.written and "no repair proposal" in res.run.final_summary and not agent.session


@pytest.mark.parametrize("path", [".env", "tests/test_calc.py", "pyproject.toml", "../outside.py", "secrets.py", "id_rsa", "server.pem",
                                  "src/jarvis/permissions/engine.py", "calc.sh"])
def test_forbidden_targets_block_the_run_before_any_write(engines, path):
    agent = FakeCodingAgent([failing()])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates({**EDIT, "path": path}))
    assert res.status is S.BLOCKED and not agent.written and "write" not in agent.actions


@pytest.mark.parametrize("cat,out,flag", [(ErrorCategory.TIMEOUT, "", "timeout"), (ErrorCategory.ENVIRONMENT_ERROR, "No module named pytest", None),
                                          (ErrorCategory.UNKNOWN, "", None)])
def test_unrepairable_diagnoses_block(engines, cat, out, flag):
    bad = test_run(False, () if cat is ErrorCategory.UNKNOWN else FAIL, out, timed_out=bool(flag))
    agent = FakeCodingAgent([bad])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert res.status is S.BLOCKED and not agent.written and res.baseline.error_category is cat


def test_jarvis_own_repository_is_not_a_repair_target(engines):
    agent = FakeCodingAgent([failing()], jarvis_repo=True)
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert res.status is S.BLOCKED and res.reason_code == "jarvis_repo" and not agent.written


def test_permission_denied_for_the_repair_blocks_without_retry(engines):
    agent = FakeCodingAgent([failing()], script=["ok", "denied"])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT, EDIT))
    assert res.status is S.BLOCKED and res.reason_code == "permission_denied" and not agent.written
    assert [t.metadata["phase"] for t in agent.tasks] == ["baseline", "repair", "cleanup"] and res.attempts[0].status is AttemptStatus.BLOCKED
    assert res.run.attempt_count == 1                                                  # no second attempt, no retry of the refused step


def test_permission_denied_for_the_test_blocks(engines):
    agent = FakeCodingAgent([], script=["denied"])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert res.status is S.BLOCKED and res.reason_code == "permission_denied" and len(agent.tasks) == 1 and res.attempts == ()


# ---- failure paths --------------------------------------------------------------------------------------------------------------------------------
def test_failed_repairs_stop_at_max_attempts(engines):
    agent = FakeCodingAgent([failing()] * 4)
    engine, *_ = engines(agent)
    cands = candidates(*[{**EDIT, "new_text": f"a + b + {i}"} for i in range(5)])
    res = repair(engine, cands=cands)
    assert res.status is S.FAILED and res.reason_code == "max_attempts" and res.run.attempt_count == 3 and len(agent.written) == 3
    assert [a.status for a in res.attempts] == [AttemptStatus.FAILED] * 3 and all(not a.targeted_test_result.passed for a in res.attempts)
    assert all(a.regression_result is None for a in res.attempts)                       # a failed targeted test never reaches the regression run
    assert agent.actions.count("test") == 4 and "3 attempt" in res.run.final_summary


def test_attempt_limit_is_hard(engines):
    engine, *_ = engines(FakeCodingAgent([failing()] * 8), max_attempts=5)
    run = engine.create("Behebe", workspace="/w", max_attempts=50, context={"candidates": candidates(*[{**EDIT, "new_text": str(i)} for i in range(5)])})
    assert run.max_attempts == 5
    assert engine.run(run.run_id).run.attempt_count == 5
    with pytest.raises(InvalidRepairError):
        rig(max_attempts=6)
    with pytest.raises(InvalidRepairError):
        rig(max_attempts=0)
    with pytest.raises(InvalidRepairError):
        rig(repair_timeout=10 ** 6)
    with pytest.raises(InvalidRepairError):
        rig(repair_timeout=0)
    with pytest.raises(InvalidRepairError):
        engine.create("x", workspace="/w", timeout=10 ** 6)


def test_per_run_limits_cannot_exceed_the_engine_limits(engines):
    engine, *_ = engines(FakeCodingAgent([failing()] * 4), max_attempts=2)
    assert engine.create("Behebe", workspace="/w", max_attempts=5).max_attempts == 2


def test_regression_failure_is_failed_never_succeeded(engines):
    reg = test_run(False, ("tests/test_calc.py::test_add", "tests/test_other.py::test_x"), "E AssertionError")
    agent = FakeCodingAgent([failing(), GOOD, reg])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT, EDIT))
    assert res.status is S.FAILED and res.reason_code == "regression_failed" and "NOT reported as successful" in res.run.final_summary
    assert "1 of 2 failing test(s) already failed before the repair" in res.run.final_summary
    a = res.attempts[0]
    assert a.targeted_test_result.passed and not a.regression_result.passed and a.status is AttemptStatus.FAILED and len(res.attempts) == 1


def test_unexpected_file_change_blocks_and_nothing_is_accepted(engines):
    agent = FakeCodingAgent([failing(), GOOD, GOOD], extra_change="other.py")
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert res.status is S.BLOCKED and res.reason_code == "unexpected_change" and "other.py" in res.run.final_summary and "not rolled back" in res.run.final_summary
    assert res.attempts[0].status is AttemptStatus.BLOCKED and agent.actions.count("test") == 1             # no re-test of an unacceptable change
    assert "other.py" in res.attempts[0].changed_files


def test_a_repair_that_changes_nothing_stops(engines):
    agent = FakeCodingAgent([failing()], noop_write=True)
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT, {**EDIT, "new_text": "x"}))
    assert res.status is S.FAILED and res.reason_code == "no_change" and res.run.attempt_count == 1 and agent.actions.count("test") == 1


def test_the_same_repair_is_not_applied_twice(engines):
    agent = FakeCodingAgent([failing()] * 3)
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT, EDIT, EDIT))
    assert res.status is S.FAILED and res.reason_code == "repeated_plan" and len(agent.written) == 1 and res.run.attempt_count == 2


def test_running_out_of_candidates_after_attempts_is_failed_not_blocked(engines):
    agent = FakeCodingAgent([failing()] * 3)
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert res.status is S.FAILED and res.reason_code == "exhausted" and "after 1 attempt" in res.run.final_summary


def test_an_edit_that_does_not_apply_uses_up_an_attempt_and_the_next_candidate_gets_its_turn(engines):
    agent = FakeCodingAgent([failing(), GOOD, GOOD], script=["ok", "permanent", "ok"])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates({**EDIT, "old_text": "nope"}, EDIT))
    assert res.status is S.SUCCEEDED and res.run.attempt_count == 2 and [a.status for a in res.attempts] == [AttemptStatus.FAILED, AttemptStatus.SUCCEEDED]


def test_a_failure_that_follows_the_second_candidate_still_never_reports_success(engines):
    agent = FakeCodingAgent([failing(), failing(), GOOD, test_run(False, FAIL, FAIL_OUT)])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT, {**EDIT, "new_text": "b + a"}))
    assert res.status is S.FAILED and [a.status for a in res.attempts] == [AttemptStatus.FAILED, AttemptStatus.FAILED]


# ---- transient / permanent / crash -----------------------------------------------------------------------------------------------------------------
def test_transient_failure_of_a_test_task_is_retried_once_visibly(engines):
    agent = FakeCodingAgent([GOOD], script=["failure"])
    engine, *_ = engines(agent)
    res = repair(engine, "Teste das Projekt")
    assert res.status is S.SUCCEEDED and len(agent.tasks) == 3 and any("transient" in w for w in res.warnings)       # baseline x2 + cleanup


def test_permanent_failure_is_not_retried(engines):
    agent = FakeCodingAgent([], script=["permanent"])
    engine, *_ = engines(agent)
    res = repair(engine, "Teste das Projekt")
    assert res.status is S.FAILED and res.reason_code == "invalid_input" and len(agent.tasks) == 1


def test_repair_writes_are_never_retried_automatically(engines):
    agent = FakeCodingAgent([failing()], script=["ok", "failure"])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert len([t for t in agent.tasks if t.metadata["phase"] == "repair"]) == 1 and res.status is S.FAILED


def test_agent_crash_ends_the_run_with_a_clear_status(engines):
    agent = FakeCodingAgent([], script=["crash"])
    engine, *_ = engines(agent)
    res = repair(engine, "Teste das Projekt")
    assert res.status in (S.FAILED, S.BLOCKED) and res.run.is_terminal and "abc123456789" not in json.dumps(res.to_dict())


def test_unexpected_exception_in_the_planner_ends_failed(engines):
    class Boom(RepairPlanner):
        def plan(self, *a, **k):
            raise ZeroDivisionError("boom")
    engine, *_ = engines(FakeCodingAgent([failing()]), repair_planner=Boom())
    res = repair(engine, cands=candidates(EDIT))
    assert res.status is S.FAILED and res.reason_code == "internal_error" and "ZeroDivisionError" in res.run.final_summary


def test_agent_returning_an_invalid_status_is_a_failure(engines):
    engine, orch, agent, _ = engines(FakeCodingAgent([GOOD]))

    class Lying:
        def __init__(self, o):
            self._o = o

        def __getattr__(self, n):
            return getattr(self._o, n)

        def wait_any(self, *a, **k):
            from dataclasses import replace
            return [replace(r, status="SUCCEEDED") for r in self._o.wait_any(*a, **k)]
    engine._orch = Lying(orch)
    res = repair(engine, "Teste das Projekt")
    assert res.status is S.FAILED and res.reason_code == "invalid_status"


def test_no_suitable_agent_blocks(engines):
    engine, orch, agent, _ = engines(FakeCodingAgent([GOOD]))
    orch.set_enabled("coding", False)
    res = repair(engine, "Teste das Projekt")
    assert res.status is S.BLOCKED and res.reason_code == "no_agent" and not agent.tasks


# ---- cancel / timeout --------------------------------------------------------------------------------------------------------------------------------
def test_cancel_before_start(engines):
    agent = FakeCodingAgent([GOOD])
    engine, *_ = engines(agent)
    run = engine.create("Teste", workspace="/w")
    rep = engine.cancel(run.run_id)
    assert rep.accepted and engine.get(run.run_id).status is S.CANCELLED and engine.run(run.run_id).status is S.CANCELLED and not agent.tasks


def test_cancel_of_a_finished_run_changes_nothing(engines):
    engine, *_ = engines(FakeCodingAgent([GOOD]))
    res = repair(engine, "Teste das Projekt")
    rep = engine.cancel(res.run.run_id)
    assert not rep.accepted and rep.status is S.SUCCEEDED and engine.get(res.run.run_id).status is S.SUCCEEDED


def test_cancel_while_the_agent_is_working(engines):
    agent = FakeCodingAgent([failing()], script=["ok", "cancel"])
    engine, *_ = engines(agent, inline=False)
    run = engine.create("Behebe", workspace="/w", context={"candidates": candidates(EDIT)})
    engine.start(run.run_id)
    wait_event(agent.started)
    # wait until the repair task (second call) is the one running
    import time
    end = time.monotonic() + 10
    gate = threading.Event()
    while len(agent.tasks) < 2 and time.monotonic() < end:
        gate.wait(0.01)
    assert engine.cancel(run.run_id).accepted
    res = engine.wait(run.run_id, 10)
    assert res.status is S.CANCELLED and agent.cancel_calls and not agent.written and res.attempts[0].status is AttemptStatus.CANCELLED
    assert any("left open" in w for w in res.warnings)                                # honest: the session was not closed after a cancel


def test_cancel_during_the_baseline_run(engines):
    agent = FakeCodingAgent([], script=["cancel"])
    engine, *_ = engines(agent, inline=False)
    run = engine.create("Teste", workspace="/w")
    engine.start(run.run_id)
    wait_event(agent.started)
    engine.cancel(run.run_id)
    assert engine.wait(run.run_id, 10).status is S.CANCELLED


def test_unresponsive_agent_is_reported_not_claimed_stopped(engines):
    agent = FakeCodingAgent([], script=["hang"])
    engine, *_ = engines(agent, inline=False)
    run = engine.create("Teste", workspace="/w")
    engine.start(run.run_id)
    wait_event(agent.started)
    engine.cancel(run.run_id)
    res = engine.wait(run.run_id, 10)
    assert res.status is S.CANCELLED and any("not stopped" in w for w in res.warnings) and agent.cancel_calls


def test_repair_timeout_ends_the_run(engines):
    agent = FakeCodingAgent([], script=["cancel"])
    engine, *_ = engines(agent, inline=False, repair_timeout=0.3)
    res = engine.run(engine.create("Teste", workspace="/w").run_id)
    assert res.status is S.TIMEOUT and res.reason_code == "timeout" and agent.cancel_calls


def test_timeout_is_checked_between_phases():
    from goals_util import MonoClock
    clock = MonoClock()
    agent = FakeCodingAgent([failing()])

    class Slow(FakeCodingAgent):
        def perform(self, task, ctx):
            clock.t += 10_000
            return super().perform(task, ctx)
    slow = Slow([failing()])
    engine, orch, slow, _ = rig(slow, clock=clock)
    res = engine.run(engine.create("Behebe", workspace="/w", context={"candidates": candidates(EDIT)}).run_id)
    assert res.status is S.TIMEOUT and not slow.written


# ---- engine mechanics ---------------------------------------------------------------------------------------------------------------------------------
def test_a_run_never_runs_twice_and_unknown_ids_fail(engines):
    agent = FakeCodingAgent([GOOD])
    engine, *_ = engines(agent)
    run = engine.create("Teste", workspace="/w")
    engine.run(run.run_id)
    again = engine.run(run.run_id)
    assert again.status is S.SUCCEEDED and sum(1 for t in agent.tasks if t.metadata["phase"] == "baseline") == 1
    for call in (engine.get, engine.run, engine.cancel, engine.attempts, engine.result, engine.start):
        with pytest.raises(UnknownRepairError):
            call("r-nope")


def test_active_run_limit_and_double_start(engines):
    agent = FakeCodingAgent([], script=["cancel"])
    engine, *_ = engines(agent, inline=False, max_active=1)
    a, b = engine.create("Teste", workspace="/w"), engine.create("Teste", workspace="/w")
    engine.start(a.run_id)
    wait_event(agent.started)
    with pytest.raises(RepairStateError):
        engine.run(a.run_id)
    with pytest.raises(RepairError, match="at most 1"):
        engine.start(b.run_id)
    assert engine.get(b.run_id).status is S.PENDING


def test_history_is_trimmed(engines):
    engine, *_ = engines(FakeCodingAgent([GOOD] * 6), max_history=3)
    ids = [engine.create(f"Teste {i}", workspace="/w").run_id for i in range(3)]
    for i in ids:
        engine.run(i)
    engine.create("Teste neu", workspace="/w")
    assert len(engine.list()) <= 4 and engine.list(status=S.PENDING, limit=1)


def test_workspace_is_mandatory_and_context_is_checked(engines):
    engine, *_ = engines()
    for kw in ({"workspace": ""}, {"workspace": "x" * 2000}, {"workspace": "/w", "context": {"confirmed": True}}, {"workspace": "/w", "context": {"foo": 1}}):
        with pytest.raises(InvalidRepairError):
            engine.create("Teste", **kw)
    with pytest.raises(TypeError):
        engine.create("Teste")  # type: ignore[call-arg]


def test_secrets_never_reach_results_or_logs(engines, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "hunter2hunter2"
    agent = FakeCodingAgent([test_run(False, FAIL, f"E AssertionError password={secret}\n{secret}"), GOOD, GOOD])
    engine, *_ = engines(agent, detector=SecretDetector([secret]))
    res = repair(engine, f"Behebe Fehler GEHEIMES-ZIEL {secret}", cands=candidates(EDIT))
    blob = json.dumps(res.to_dict()) + repr(res) + "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in blob and "GEHEIMES-ZIEL" not in "\n".join(r.getMessage() for r in caplog.records)
    assert res.baseline.stdout_summary.count(secret) == 0


def test_results_hold_no_unbounded_logs(engines):
    agent = FakeCodingAgent([test_run(False, FAIL, "E AssertionError " + "x" * 500_000), GOOD, GOOD])
    engine, *_ = engines(agent)
    res = repair(engine, cands=candidates(EDIT))
    assert len(res.baseline.stdout_summary) <= 3000 and len(json.dumps(res.to_dict())) < 20_000


def test_the_golden_rule_is_what_decides(engines):
    # targeted passes, regression passes, but a second file was touched -> never a success
    agent = FakeCodingAgent([failing(), GOOD, GOOD], extra_change="b.py")
    engine, *_ = engines(agent)
    assert repair(engine, cands=candidates(EDIT)).status is not S.SUCCEEDED


def test_state_machine_is_followed_end_to_end(engines):
    seen = []
    engine, orch, agent, _ = engines(FakeCodingAgent([failing(), GOOD, GOOD]))
    orig = engine._set

    def spy(rec, status, phase):
        seen.append(status)
        return orig(rec, status, phase)
    engine._set = spy
    repair(engine, cands=candidates(EDIT))
    assert seen == [S.TESTING, S.DIAGNOSING, S.PLANNING, S.REPAIRING, S.RETESTING, S.REGRESSION]
