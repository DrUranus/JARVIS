"""The manager and the approval gate. Default behaviour: every code-touching operation is DISABLED (ExecutionDisabled) and no process is started. The remaining tests
exercise the gate/activation logic against an in-memory FakeWorkspace and a fake sandbox that only RECORDS commands - with a test-double attestation, because the
production code can never unlock execution. Nothing here runs proposed code. Tests marked `detection_only` check filters, not isolation."""
from __future__ import annotations

import subprocess
import threading

import pytest

from jarvis.self_improvement import (ApprovalError, ExecutionDisabled, ExecutionGuard, ImprovementError, ImprovementStateError, IsolationAttestation, ProposalStatus as S,
                                     ValidationPipeline, policy as P)
from jarvis.self_improvement.isolation import REQUIRED_PROPERTIES
from jarvis.self_improvement.pipeline import STAGES
from jarvis.self_improvement.workspace import CommandResult
from si_util import FakeSandbox, FakeWorkspace, GOOD, NO, ONCE, PLANNER, PLATFORM, SESSION, TESTS, full_attestation, rig


# ---- default: execution disabled, nothing runs ------------------------------------------------------------------------------------------------
@pytest.fixture
def no_processes(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a process was started")
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr("os.system", boom)


def test_code_operations_are_disabled_and_start_no_process(no_processes):
    r = rig(attested=False)
    p = r.m.propose("Fix add", "add subtracts", suggested_tests=TESTS)
    for call in (lambda: r.m.prepare(p.proposal_id, [GOOD]), lambda: r.m.prepare(p.proposal_id, files=[PLANNER]), lambda: r.m.test(p.proposal_id),
                 lambda: r.m.activate(p.proposal_id), lambda: r.m.rollback(p.proposal_id)):
        with pytest.raises(ExecutionDisabled, match="isolation"):
            call()
    assert r.ws.calls == [] and r.m.get(p.proposal_id).status is S.PROPOSED
    assert r.m.describe()["code_execution"] is False and "sandbox" in r.m.describe()["execution_note"]


def test_the_proposal_workflow_still_works_without_execution(no_processes):
    r = rig(attested=False)
    p = r.m.propose("Fix add", "x")
    assert p.status is S.PROPOSED and r.m.list() and r.m.get(p.proposal_id).history[-1].new is S.PROPOSED
    with pytest.raises(ImprovementStateError):
        r.m.submit_for_approval(p.proposal_id)               # cannot skip PREPARED/TESTED
    with pytest.raises(ApprovalError):
        r.m.approve(p.proposal_id)
    assert r.m.reject(p.proposal_id, "no").status is S.REJECTED
    assert not r.confirm.requests
    assert [e.action for e in r.events()] == ["detected", "proposed", "rejected"]


def test_no_production_path_unlocks_execution():
    assert ExecutionGuard.locked().allowed is False and ExecutionGuard().allowed is False
    assert "no sandbox backend" in ExecutionGuard.locked().reason()
    with pytest.raises(ExecutionDisabled):
        ExecutionGuard.locked().require("x")


@pytest.mark.parametrize("missing", REQUIRED_PROPERTIES)
def test_a_partial_attestation_never_unlocks(missing):
    g = ExecutionGuard(full_attestation(**{missing: False}))
    assert g.allowed is False and missing in g.reason()


def test_an_attestation_for_another_platform_never_unlocks():
    other = "windows" if PLATFORM != "windows" else "linux"
    g = ExecutionGuard(IsolationAttestation("x", other, **{p: True for p in REQUIRED_PROPERTIES}))
    assert g.allowed is False and "another platform" in g.reason()
    assert ExecutionGuard(full_attestation()).allowed is True          # the test double used below


def test_pipeline_without_isolation_runs_only_static_stages_and_never_passes(no_processes):
    r = rig(attested=False)
    ws = r.ws
    wt = ws.create_worktree("imp-000000000001")
    change = ws.apply_and_commit(wt, [GOOD], "m")
    res = ValidationPipeline(ExecutionGuard.locked(), FakeSandbox(), "python").run(change, TESTS, ws.export_commit(change.head_commit))
    assert [s.name for s in res.stages] == list(STAGES)
    by = {s.name: s for s in res.stages}
    assert by["scope"].passed and by["static_review"].passed and "nothing was executed" in by["static_review"].summary
    assert all(not by[n].executed and not by[n].passed and "disabled" in by[n].summary for n in STAGES[2:])
    assert res.passed is False


# ---- gate logic with the test-double attestation (nothing is executed) ----------------------------------------------------------------------
def test_full_lifecycle_requires_two_user_confirmations_with_the_complete_diff():
    r = rig()
    p = r.ready()
    assert p.status is S.READY_FOR_APPROVAL and p.tests_passed and p.tested_manifest and [s.name for s in p.stages] == list(STAGES)
    assert r.ws.active_head == r.ws.base and "a - b" in r.ws.active_files[PLANNER]
    with pytest.raises(ApprovalError):
        r.m.activate(p.proposal_id)                                         # tested and ready, but not approved
    p = r.m.approve(p.proposal_id)
    assert p.status is S.APPROVED and p.approval.diff_digest == p.diff_digest and p.approval.view_digest and r.ws.active_head == r.ws.base
    first = r.confirm.requests[0]
    assert first.action == "approve_change" and not first.session_allowed
    diff = first.context["[JARVIS] Vollstaendiger Diff (ESC-maskiert)"]
    assert "- |     return a - b" in diff and "+ |     return a + b" in diff                      # the complete diff is in the dialog
    assert "Diff-Digest" in first.to_text() and p.diff_digest in first.to_text()
    p = r.m.activate(p.proposal_id)
    assert p.status is S.ACTIVATED and "a + b" in r.ws.active_files[PLANNER]
    second = r.confirm.requests[1]
    assert second.action == "activate_change" and second.context["[JARVIS] Anzeige-Digest"] == first.context["[JARVIS] Anzeige-Digest"]
    assert len(r.confirm.requests) == 2                                                          # a stored approval is not enough: asked again
    r.confirm._choices.append(ONCE)
    p = r.m.rollback(p.proposal_id)
    assert p.status is S.ROLLED_BACK and r.ws.revert_calls == [p.head_commit] and "a - b" in r.ws.active_files[PLANNER]
    assert [t.new for t in p.history] == [S.PROPOSED, S.PREPARED, S.TESTED, S.READY_FOR_APPROVAL, S.APPROVED, S.ACTIVATED, S.ROLLED_BACK]


def test_every_transition_is_audited_with_actor():
    r = rig()
    p = r.m.activate(r.m.approve(r.ready().proposal_id).proposal_id)
    actions = [e.action for e in r.events()]
    for a in ("detected", "proposed", "prepared", "tested", "ready_for_approval", "approve_requested", "approved", "activate_requested", "activated"):
        assert a in actions, actions
    assert all(e.tool == "self_improvement" and e.resource == p.proposal_id for e in r.events()) and r.events("approved")[0].extra["actor"] == "user"


@pytest.mark.parametrize("answers", [(), (NO,), (SESSION,)])
def test_no_explicit_yes_means_no_approval(answers):
    r = rig(answers=answers)
    p = r.ready()
    with pytest.raises(ApprovalError):
        r.m.approve(p.proposal_id)
    assert r.m.get(p.proposal_id).status is S.READY_FOR_APPROVAL and r.events("approve")[0].status == "denied"


def test_activation_needs_its_own_confirmation_even_with_a_stored_approval():
    r = rig(answers=(ONCE, NO))
    p = r.m.approve(r.ready().proposal_id)
    with pytest.raises(ApprovalError, match="not confirmed"):
        r.m.activate(p.proposal_id)
    assert r.m.get(p.proposal_id).status is S.APPROVED and r.ws.active_head == r.ws.base and "fast_forward" not in r.ws.calls


def test_headless_or_missing_gate_or_prompt_failure_cannot_approve():
    r = rig()
    p = r.ready()
    r.m._gate = None
    with pytest.raises(ApprovalError):
        r.m.approve(p.proposal_id)
    r2 = rig()
    q = r2.ready()

    class Boom:
        def confirm(self, request):
            raise EOFError

    from jarvis.permissions.confirmation import ConfirmationProvider
    r2.m._gate._provider = type("B", (Boom, ConfirmationProvider), {})()
    with pytest.raises(ApprovalError):
        r2.m.approve(q.proposal_id)


def test_a_forged_status_without_an_approval_record_cannot_activate():
    r = rig()
    p = r.ready()
    forged = r.store.save(p.moved(S.APPROVED, "user", "forged"))          # a status change without the approval record (what raw editing would amount to)
    with pytest.raises(ApprovalError, match="explicit user approval"):
        r.m.activate(forged.proposal_id)
    assert r.ws.active_head == r.ws.base and not r.confirm.requests


def test_approval_that_does_not_match_the_reviewed_change_is_refused():
    from jarvis.self_improvement.models import Approval, utcnow
    for kw in ({"head_commit": "a" * 40}, {"diff_digest": "b" * 32}, {"view_digest": "c" * 32}):
        r = rig()
        p = r.ready()
        base = dict(at=utcnow(), channel="x", head_commit=p.head_commit, diff_digest=p.diff_digest, view_digest="")
        ok = r.m.approve(p.proposal_id)
        bad = r.store.save(ok.evolve(approval=Approval(**{**base, "view_digest": ok.approval.view_digest, **kw})))
        with pytest.raises(ApprovalError):
            r.m.activate(bad.proposal_id)
        assert r.ws.active_head == r.ws.base


# ---- binding to the exact reviewed and tested content ---------------------------------------------------------------------------------------
def test_branch_tampering_after_review_blocks_approval_and_activation():
    r = rig()
    p = r.ready()
    r.ws.tamper_branch(p.branch)
    with pytest.raises(ApprovalError):
        r.m.approve(p.proposal_id)
    assert not r.confirm.requests                                                # the user is not asked about something that no longer matches
    r2 = rig()
    q = r2.m.approve(r2.ready().proposal_id)
    r2.ws.tamper_branch(q.branch)
    with pytest.raises(ApprovalError):
        r2.m.activate(q.proposal_id)
    assert r2.ws.active_head == r2.ws.base and len(r2.confirm.requests) == 1


def test_content_that_differs_from_the_tested_manifest_blocks():
    r = rig()
    p = r.ready()
    r.store.save(r.store.get(p.proposal_id).evolve(tested_manifest="0" * 64))
    with pytest.raises(ApprovalError, match="differs from the content that was tested"):
        r.m.approve(p.proposal_id)


def test_moved_base_dirty_tree_and_branch_move_block_activation_independently():
    r = rig()
    p = r.m.approve(r.ready().proposal_id)
    r.ws.dirty = True
    from jarvis.self_improvement import PreparationError
    with pytest.raises(PreparationError, match="uncommitted"):
        r.m.activate(p.proposal_id)
    r.ws.dirty = False
    r.ws.move_active()
    r.confirm._choices.append(ONCE)
    with pytest.raises(PreparationError, match="moved"):
        r.m.activate(p.proposal_id)
    assert r.m.get(p.proposal_id).status is S.APPROVED and "a - b" in r.ws.active_files[PLANNER]


def test_unversioned_changes_cannot_make_a_test_pass():
    """Tests/Review run on an EXPORT of the commit (see test_self_improvement_workspace): the pipeline never sees a working directory."""
    r = rig()
    p = r.m.propose("x", "y", suggested_tests=TESTS)
    r.m.prepare(p.proposal_id, [GOOD])
    r.m.test(p.proposal_id)
    argv, export_dir = r.sandbox.calls[0]
    assert str(export_dir) == "/fake-export" and ".git" not in str(export_dir)
    assert all(str(d) == "/fake-export" for _, d in r.sandbox.calls)


def test_a_changed_export_after_the_run_discards_the_result():
    r = rig(verify=False)
    p = r.m.propose("x", "y", suggested_tests=TESTS)
    r.m.prepare(p.proposal_id, [GOOD])
    p = r.m.test(p.proposal_id)
    assert p.status is S.FAILED and not p.tests_passed and "export integrity" in " ".join(s.summary for s in p.stages)


# ---- failures and refusals --------------------------------------------------------------------------------------------------------------------
def test_failing_commands_block_everything_after(no_processes):
    r = rig(sandbox=FakeSandbox(CommandResult(0, "imported", 0.1), CommandResult(1, "1 failed", 0.1)))
    p = r.m.propose("x", "y", suggested_tests=TESTS)
    r.m.prepare(p.proposal_id, [GOOD])
    p = r.m.test(p.proposal_id)
    by = {s.name: s for s in p.stages}
    assert p.status is S.FAILED and by["targeted_tests"].executed and not by["targeted_tests"].passed and not by["regression_tests"].executed
    for call in (r.m.submit_for_approval, r.m.approve):
        with pytest.raises((ImprovementStateError, ApprovalError)):
            call(p.proposal_id)
    assert not r.confirm.requests


def test_exit_status_five_timeouts_cancel_and_missing_tests_are_never_passes():
    for results, why in (([CommandResult(0, "i", 0.1), CommandResult(5, "no tests ran", 0.1)], "targeted"), ([CommandResult(None, "", 5, timed_out=True)], "import"),
                         ([CommandResult(0, "i", 0.1), CommandResult(0, "ok", 0.1), CommandResult(None, "", 5, timed_out=True)], "regression")):
        r = rig(sandbox=FakeSandbox(*results))
        p = r.m.propose("x", "y", suggested_tests=("tests/test_calc.py",))
        r.m.prepare(p.proposal_id, [GOOD])
        p = r.m.test(p.proposal_id)
        assert p.status is S.FAILED and not p.tests_passed, why
    r = rig()
    p = r.m.propose("x", "y", suggested_tests=("tests/test_missing.py",))
    r.m.prepare(p.proposal_id, [GOOD])
    p = r.m.test(p.proposal_id)
    assert p.status is S.FAILED and {s.name: s for s in p.stages}["targeted_tests"].executed is False


@pytest.mark.parametrize("edit", [
    {"path": "src/jarvis/permissions/engine.py", "old_text": "a", "new_text": "b"}, {"path": "src/jarvis/tools/registry.py", "old_text": "a", "new_text": "b"},
    {"path": "src/jarvis/interface/cli.py", "old_text": "a", "new_text": "b"}, {"path": "src/jarvis/Goals/planner.py", "old_text": "a", "new_text": "b"},
    {"path": "../outside.py", "old_text": "a", "new_text": "b"}, {"path": "src/jarvis/goals/planner.py", "old_text": "return a - b", "new_text": "import socket"}])
@pytest.mark.detection_only
def test_forbidden_targets_and_content_are_blocked_for_manual_review(edit):
    r = rig()
    p = r.m.propose("x", "y", suggested_tests=TESTS)
    p = r.m.prepare(p.proposal_id, [edit])
    assert p.status is S.BLOCKED and "manual review" in p.reason and not r.ws.branches and r.sandbox.calls == []
    for call in (r.m.prepare, r.m.test, r.m.approve, r.m.activate):
        with pytest.raises((ImprovementStateError, ApprovalError)):
            call(p.proposal_id)


def test_invalid_edits_and_missing_text_fail_safely():
    r = rig()
    for bad in ([], "nope", [{"path": PLANNER}], [{**GOOD, "confirmed": "yes"}], [{**GOOD, "old_text": "does not occur"}]):
        p = r.m.propose("x", "y", suggested_tests=TESTS)
        assert r.m.prepare(p.proposal_id, bad).status is S.FAILED, bad
    assert r.sandbox.calls == []


# ---- audit failures fail closed -------------------------------------------------------------------------------------------------------------
class Dead:
    def record(self, event):
        return False


class Raises:
    def record(self, event):
        raise OSError("disk full")


@pytest.mark.parametrize("audit", [Dead(), Raises()], ids=["failing-sink", "raising-sink"])
def test_audit_failure_blocks_approve_activate_and_rollback(audit):
    r = rig()
    p = r.ready()
    r.m._audit = audit
    with pytest.raises(ImprovementError, match="audit"):
        r.m.approve(p.proposal_id)
    assert not r.confirm.requests and r.m.get(p.proposal_id).status is S.READY_FOR_APPROVAL
    r2 = rig()
    q = r2.m.approve(r2.ready().proposal_id)
    r2.m._audit = audit
    before = len(r2.confirm.requests)
    with pytest.raises(ImprovementError, match="audit"):
        r2.m.activate(q.proposal_id)
    assert len(r2.confirm.requests) == before and r2.ws.active_head == r2.ws.base
    r3 = rig()
    act = r3.m.activate(r3.m.approve(r3.ready().proposal_id).proposal_id)
    r3.m._audit = audit
    r3.confirm._choices.append(ONCE)
    with pytest.raises(ImprovementError, match="audit"):
        r3.m.rollback(act.proposal_id)
    assert r3.ws.revert_calls == []


def test_no_audit_logger_or_no_sink_refuses_sensitive_actions():
    from jarvis.permissions.audit import AuditLogger
    r = rig()
    ready = r.ready()
    for audit in (None, AuditLogger([])):
        r.m._audit = audit
        with pytest.raises(ImprovementError, match="audit"):
            r.m.approve(ready.proposal_id)
    assert not r.confirm.requests and r.m.get(ready.proposal_id).status is S.READY_FOR_APPROVAL


# ---- concurrency ---------------------------------------------------------------------------------------------------------------------------
def test_concurrent_activations_merge_once():
    for _ in range(15):
        r = rig(answers=(ONCE,) * 6)
        p = r.m.approve(r.ready().proposal_id)
        res = {}

        def act(n):
            try:
                res[n] = r.m.activate(p.proposal_id).status.value
            except ImprovementError as exc:
                res[n] = type(exc).__name__

        ts = [threading.Thread(target=act, args=(i,)) for i in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert list(res.values()).count("ACTIVATED") == 1, res
        assert r.ws.calls.count("fast_forward") == 1 and [e.action for e in r.events()].count("activated") == 1
        assert r.m.get(p.proposal_id).status is S.ACTIVATED


def test_reject_and_activate_race_has_one_winner_and_a_consistent_state():
    for _ in range(15):
        r = rig(answers=(ONCE,) * 4)
        p = r.m.approve(r.ready().proposal_id)
        res = {}

        def do(name, fn):
            try:
                res[name] = fn(p.proposal_id).status.value
            except ImprovementError as exc:
                res[name] = type(exc).__name__

        ts = [threading.Thread(target=do, args=("act", r.m.activate)), threading.Thread(target=do, args=("rej", r.m.reject))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        final = r.m.get(p.proposal_id).status
        merged = r.ws.active_head != r.ws.base
        assert (final is S.ACTIVATED) == merged and final in (S.ACTIVATED, S.REJECTED), (res, final, merged)


def test_a_second_operation_on_a_busy_proposal_is_refused_and_cancel_signals_it():
    r = rig()
    p = r.m.propose("x", "y")
    inside = threading.Event()
    release = threading.Event()
    seen = {}

    def hold():
        with r.m._exclusive(p.proposal_id) as cancel:
            inside.set()
            release.wait(10)
            seen["cancelled"] = cancel.is_set()

    t = threading.Thread(target=hold)
    t.start()
    inside.wait(10)
    with pytest.raises(ImprovementStateError, match="still running"):
        r.m.reject(p.proposal_id)
    assert r.m.cancel(p.proposal_id) is True
    release.set()
    t.join()
    assert seen["cancelled"] and r.m.cancel(p.proposal_id) is False


def test_stale_state_in_the_store_cannot_be_overwritten_by_a_transition():
    from jarvis.self_improvement import ConcurrentUpdateError
    r = rig(attested=False)
    p = r.m.propose("x", "y")
    stale = r.store.get(p.proposal_id)
    r.m.reject(p.proposal_id)
    with pytest.raises(ConcurrentUpdateError):
        r.store.save(stale.moved(S.FAILED, "system"))
    assert r.m.get(p.proposal_id).status is S.REJECTED
    with pytest.raises(ImprovementStateError):
        r.m._commit(p.proposal_id, S.PROPOSED, S.FAILED, "system")           # wrong expectation: refused before any write
