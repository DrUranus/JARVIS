"""Models, state machines, policy, context, diagnosis, planner, evaluator and tester helpers of the self-repair layer."""
from __future__ import annotations

import json

import pytest

from jarvis.self_repair import (AttemptStatus, Diagnosis, DiagnosisEngine, ErrorCategory, InvalidRepairError, PlanBlocked, RepairAttempt, RepairContext,
                                RepairEvaluator, RepairPlan, RepairPlanner, RepairRun, RepairStateError, RepairStatus, TestResult, Verdict, check_context)
from jarvis.self_repair import policy as P
from jarvis.self_repair import tester as T
from jarvis.self_repair.state import ATTEMPT_TERMINAL, ATTEMPT_TRANSITIONS, RUN_TERMINAL, RUN_TRANSITIONS

EDIT = {"path": "calc.py", "mode": "replace", "old_text": "a - b", "new_text": "a + b"}


# ---- RepairRun / state -------------------------------------------------------------------------------------------------------------------------
def test_run_defaults_and_serialisation():
    r = RepairRun("Behebe den Fehler", "/w")
    assert r.status is RepairStatus.PENDING and r.max_attempts == 3 and r.attempt_count == 0 and r.current_phase == "pending"
    assert r.run_id.startswith("r-") and r.started_at is None and r.finished_at is None and r.failure_summary == "" and r.final_summary == ""
    assert RepairRun("x", "/w").run_id != RepairRun("x", "/w").run_id
    json.dumps(r.to_dict())
    assert "Behebe" not in repr(r) and "/w" not in repr(r)


@pytest.mark.parametrize("kw", [{"objective": ""}, {"objective": "x" * 2001}, {"objective": "a\x00"}, {"workspace": ""}, {"workspace": "  "},
                                {"max_attempts": 0}, {"max_attempts": 6}, {"max_attempts": True}, {"attempt_count": 1, "max_attempts": 1 - 0, "run_id": "a b"},
                                {"timeout": 0}, {"timeout": 10 ** 7}, {"status": "TESTING"}, {"attempt_count": 4}])
def test_run_rejects_invalid(kw):
    base = {"objective": "ok", "workspace": "/w"}
    base.update(kw)
    with pytest.raises(InvalidRepairError):
        RepairRun(**base)


def test_run_lifecycle_and_timestamps():
    r = RepairRun("x", "/w").with_status(RepairStatus.TESTING)
    assert r.started_at is not None and r.finished_at is None
    for s in (RepairStatus.DIAGNOSING, RepairStatus.PLANNING, RepairStatus.REPAIRING, RepairStatus.RETESTING, RepairStatus.REGRESSION):
        r = r.with_status(s)
    r = r.with_status(RepairStatus.DIAGNOSING)                       # a failed attempt returns for the next attempt
    r = r.with_status(RepairStatus.FAILED)
    assert r.finished_at is not None and r.is_terminal


@pytest.mark.parametrize("terminal", sorted(RUN_TERMINAL, key=lambda s: s.value))
def test_terminal_run_status_is_final(terminal):
    assert RUN_TRANSITIONS[terminal] == frozenset()
    r = RepairRun("x", "/w")
    object.__setattr__(r, "status", terminal)
    for target in RepairStatus:
        with pytest.raises(RepairStateError):
            r.with_status(target)


def test_no_state_returns_to_pending_and_phases_cannot_be_skipped():
    for old, targets in RUN_TRANSITIONS.items():
        assert RepairStatus.PENDING not in targets
    with pytest.raises(RepairStateError):
        RepairRun("x", "/w").with_status(RepairStatus.REPAIRING)
    with pytest.raises(RepairStateError):
        RepairRun("x", "/w").with_status(RepairStatus.SUCCEEDED)         # success needs at least a test run first
    t = RepairRun("x", "/w").with_status(RepairStatus.TESTING)
    with pytest.raises(RepairStateError):
        t.with_status(RepairStatus.REGRESSION)


def test_attempt_model_and_lifecycle():
    a = RepairAttempt("r-1-a1", "r-1", 1)
    assert a.status is AttemptStatus.PENDING and a.changed_files == () and a.targeted_test_result is None and a.regression_result is None
    a = a.with_status(AttemptStatus.REPAIRING).with_status(AttemptStatus.RETESTING).with_status(AttemptStatus.REGRESSION)
    a = a.with_status(AttemptStatus.FAILED, "regression failed")
    assert a.failure_reason == "regression failed"
    for t in AttemptStatus:
        with pytest.raises(RepairStateError):
            a.with_status(t)
    assert all(ATTEMPT_TRANSITIONS[s] == frozenset() for s in ATTEMPT_TERMINAL)
    for bad in ({"number": 0}, {"number": 6}, {"attempt_id": "a b"}):
        with pytest.raises(InvalidRepairError):
            RepairAttempt(**{"attempt_id": "a1", "run_id": "r1", "number": 1, **bad})


def test_attempt_repr_and_dict_hold_no_secrets():
    secret = "hunter2hunter2"
    a = RepairAttempt("a1", "r1", 1, Diagnosis(ErrorCategory.TEST_FAILURE, f"fails with {secret}", (), (), True, secret), f"fix {secret}", ("calc.py",),
                      None, None, AttemptStatus.PENDING, f"reason {secret}")
    assert secret not in repr(a) and secret not in repr(a.diagnosis)
    assert a.to_dict()["changed_files"] == ["calc.py"]


# ---- TestResult ----------------------------------------------------------------------------------------------------------------------------------
def test_test_result_is_bounded():
    r = TestResult(False, "s" * 5000, 1, tuple(f"t{i}" for i in range(500)), ErrorCategory.UNKNOWN, "o" * 100_000, "e" * 100_000, 1.5)
    assert len(r.summary) <= P.MAX_SUMMARY and len(r.failed_tests) == P.MAX_FAILED_TESTS
    assert len(r.stdout_summary) <= P.MAX_STDOUT and len(r.stderr_summary) <= P.MAX_STDERR
    assert "ooooo" not in repr(r) and "stdout_summary" not in json.dumps(r.to_dict())
    with pytest.raises(InvalidRepairError):
        TestResult("yes")  # type: ignore[arg-type]
    assert TestResult(True, duration=float("nan")).duration == 0.0
    assert TestResult(False, failed_tests=("a", "b")).fingerprint() == TestResult(False, failed_tests=("b", "a")).fingerprint()


# ---- policy: which files may be repair targets ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", [".env", ".env.local", "config/.env", "server.pem", "keys/private.key", "credentials.json", "credentials.py", "secrets.py",
                                  "secrets/app.py", "id_rsa", "id_rsa.pub", ".netrc", "a.p12", "x.kdbx"])
def test_secret_files_are_refused(path):
    assert "secret" in P.refuse_target(path)


@pytest.mark.parametrize("path", ["../x.py", "a/../../x.py", "/etc/passwd", "C:\\Windows\\x.py", "\\\\srv\\share\\x.py", "~/x.py", "", "  ", None, 5, "a\x00.py",
                                  "x" * 400 + ".py", "a/ ./b.py", "calc.py."])
def test_traversal_and_malformed_paths_are_refused(path):
    assert P.refuse_target(path) is not None


@pytest.mark.parametrize("path,word", [(".git/config", "protected"), ("src/jarvis/permissions/engine.py", "protected"), ("security/rules.py", "protected"),
                                       ("pyproject.toml", "manifest"), ("requirements.txt", "dependency"), ("setup.py", "dependency"),
                                       ("package.json", "dependency"), ("tests/test_calc.py", "tests"), ("test_calc.py", "tests"), ("calc_test.py", "tests"),
                                       ("conftest.py", "tests"), ("calc.js", "Python"), ("logo.png", "Python"), ("data.db", "Python"), ("jarvis.toml", "dependency"),
                                       (".venv/lib/x.py", "protected")])
def test_protected_places_manifests_tests_and_non_python_are_refused(path, word):
    assert word.lower() in P.refuse_target(path).lower()


@pytest.mark.parametrize("path", ["calc.py", "src/pkg/mod.py", "a\\b\\mod.py", "./calc.py", "pkg/util_helpers.py"])
def test_ordinary_python_sources_are_acceptable(path):
    assert P.refuse_target(path) is None


def test_norm_path_equates_spellings():
    assert P.norm_path("./Src\\Calc.py") == P.norm_path("src/calc.py")


def test_policy_reserved_key_search():
    assert P.find_reserved({"edits": [{"path": "a", "Confirmed": True}]}) == "Confirmed"
    assert P.find_reserved({"edits": [{"path": "a", "nested": [{"skip_permissions": 1}]}]}) == "skip_permissions"
    assert P.find_reserved({"edits": [{"path": "a"}]}) is None


# ---- RepairPlan ----------------------------------------------------------------------------------------------------------------------------------
def test_repair_plan_validation():
    p = RepairPlan("fix", ("calc.py",), ("tests/test_calc.py::test_add",), reason="because", edits=(EDIT,))
    assert p.allowed_capabilities == {"coding.read", "coding.write", "coding.test"} and p.digest() == RepairPlan("x", ("calc.py",), edits=(dict(EDIT),)).digest()
    assert "fix" not in repr(p) and "a + b" not in repr(p)
    for kw in ({"target_files": ()}, {"target_files": (".env",)}, {"target_files": ("tests/test_a.py",)}, {"target_files": ("../x.py",)},
               {"target_files": ("a.py",), "allowed_capabilities": frozenset({"browser.read"})}, {"target_files": ("a.py",), "allowed_capabilities": frozenset({"coding.plan"})},
               {"objective": " "}, {"target_files": tuple(f"f{i}.py" for i in range(11))}):
        with pytest.raises(InvalidRepairError):
            RepairPlan(**{"objective": "fix", "target_files": ("a.py",), **kw})


# ---- context -------------------------------------------------------------------------------------------------------------------------------------
def test_context_validation():
    c = check_context("/w", "Teste das Projekt", None)
    assert c == RepairContext("/w", (), None, (), False)
    assert check_context("/w", "Behebe den Fehler", None).repair is True and check_context("/w", "Teste", {"candidates": [{"edits": [EDIT]}]}).repair is True
    assert check_context("/w", "Behebe", {"repair": False}).repair is False
    assert check_context("/w", "x", {"tests": "tests/test_a.py", "runner": "pytest"}).tests == ("tests/test_a.py",)
    for bad in ({"password": "x"}, {"confirmed": True}, {"candidates": [{"edits": [{"path": "a.py", "force": True}]}]}, {"runner": "rm -rf"},
                {"runner": "npm test"}, {"tests": ["a"] * 11}, {"tests": [5]}, {"candidates": ["x"]}, {"candidates": [{}] * 6}, {"repair": "yes"},
                {"tests": object()}, {"candidates": [{"edits": [{"path": "a.py", "content": "x" * 200_000}]}]}):
        with pytest.raises(InvalidRepairError):
            check_context("/w", "x", bad)  # type: ignore[arg-type]
    with pytest.raises(InvalidRepairError):
        check_context("/w", "x", "text")  # type: ignore[arg-type]


# ---- diagnosis -----------------------------------------------------------------------------------------------------------------------------------
def tr(text: str, *, failed=("t::a",), timed_out=False, passed=False, stderr=""):
    return TestResult(passed, "", None if timed_out else 1, tuple(failed), ErrorCategory.UNKNOWN, text, stderr, 0.1, timed_out)


@pytest.mark.parametrize("text,category,repairable", [
    ("E   SyntaxError: invalid syntax\ncalc.py:3", ErrorCategory.SYNTAX_ERROR, True),
    ("IndentationError: unexpected indent", ErrorCategory.SYNTAX_ERROR, True),
    ("E   ModuleNotFoundError: No module named 'helpers'", ErrorCategory.IMPORT_ERROR, True),
    ("ImportError: cannot import name 'x' from 'calc'", ErrorCategory.IMPORT_ERROR, True),
    ("E   AssertionError: assert -1 == 5", ErrorCategory.ASSERTION_FAILURE, True),
    ("E   assert add(2, 3) == 5", ErrorCategory.ASSERTION_FAILURE, True),
    ("FileNotFoundError: [Errno 2] No such file or directory: 'data.txt'", ErrorCategory.MISSING_FILE, True),
    ("/usr/bin/python: No module named pytest", ErrorCategory.ENVIRONMENT_ERROR, False),
    ("PermissionError: [Errno 13] Permission denied", ErrorCategory.ENVIRONMENT_ERROR, False),
])
def test_diagnosis_categories(text, category, repairable):
    d = DiagnosisEngine().diagnose(tr(text))
    assert d.category is category and d.repairable is repairable and d.failed_tests == ("t::a",)


def test_diagnosis_timeout_test_failure_unknown_and_pass():
    e = DiagnosisEngine()
    t = e.diagnose(tr("whatever", timed_out=True))
    assert t.category is ErrorCategory.TIMEOUT and not t.repairable
    f = e.diagnose(tr("something odd happened"))
    assert f.category is ErrorCategory.TEST_FAILURE and f.repairable and "no more specific cause" in f.summary
    u = e.diagnose(tr("???", failed=()))
    assert u.category is ErrorCategory.UNKNOWN and not u.repairable
    assert e.diagnose(tr("", passed=True, failed=())).category is ErrorCategory.NONE


def test_diagnosis_syntax_wins_over_a_later_assertion_and_names_files_without_trusting_them():
    d = DiagnosisEngine().diagnose(tr('File "src/calc.py", line 3\nSyntaxError: x\nassert 1 == 2\n/usr/lib/python3/site-packages/pytest/x.py:1: in run'))
    assert d.category is ErrorCategory.SYNTAX_ERROR and d.suspect_files == ("src/calc.py",)


def test_diagnosis_is_pure_and_bounded():
    r = tr("E   AssertionError " + "x" * 100_000)
    d1, d2 = DiagnosisEngine().diagnose(r), DiagnosisEngine().diagnose(r)
    assert d1 == d2 and len(d1.evidence) <= 300 and len(d1.summary) <= 500


# ---- planner -----------------------------------------------------------------------------------------------------------------------------------
def diag(category=ErrorCategory.ASSERTION_FAILURE, repairable=True, failed=("tests/test_calc.py::test_add",)):
    return Diagnosis(category, "d", failed, (), repairable)


def ctx(*cands, tests=()):
    return RepairContext("/w", tuple(tests), None, tuple(cands), True)


def plan(cand, **kw):
    return RepairPlanner().plan(tr("x"), kw.get("diag") or diag(), ctx(cand) if cand is not None else ctx(), kw.get("n", 1))


def test_planner_builds_a_bounded_plan_from_a_supplied_candidate():
    p = plan({"edits": [EDIT], "reason": "operator was wrong"})
    assert p.target_files == ("calc.py",) and p.target_tests == ("tests/test_calc.py::test_add",) and p.reason == "operator was wrong"
    assert p.edits[0]["new_text"] == "a + b" and p.allowed_capabilities == {"coding.read", "coding.write", "coding.test"}


def test_planner_candidate_per_attempt_and_no_invention():
    c = ctx({"edits": [EDIT]}, {"edits": [{**EDIT, "new_text": "b + a"}]})
    pl = RepairPlanner()
    assert pl.plan(tr("x"), diag(), c, 2).edits[0]["new_text"] == "b + a"
    with pytest.raises(PlanBlocked, match="no repair proposal"):
        pl.plan(tr("x"), diag(), c, 3)
    with pytest.raises(PlanBlocked, match="no repair proposal"):
        plan(None)


@pytest.mark.parametrize("category", [ErrorCategory.TIMEOUT, ErrorCategory.ENVIRONMENT_ERROR, ErrorCategory.UNKNOWN])
def test_planner_blocks_what_is_not_understood(category):
    with pytest.raises(PlanBlocked, match="not repaired automatically"):
        plan({"edits": [EDIT]}, diag=diag(category, False))


@pytest.mark.parametrize("cand", [
    {"edits": [{**EDIT, "path": ".env"}]}, {"edits": [{**EDIT, "path": "tests/test_calc.py"}]}, {"edits": [{**EDIT, "path": "../evil.py"}]},
    {"edits": [{**EDIT, "path": "pyproject.toml"}]}, {"edits": [{**EDIT, "path": "src/jarvis/permissions/engine.py"}]}, {"edits": [{**EDIT, "path": "x.sh"}]},
    {"edits": [{**EDIT, "confirmed": True}]}, {"edits": [{**EDIT, "extra": 1}]}, {"edits": []}, {"edits": "x"}, {"edits": [EDIT] * 11},
    {"edits": [EDIT], "force": True}, {"edits": [EDIT], "target_files": ["other.py"]}, {"edits": [EDIT], "target_files": "calc.py"}, {"edits": [5]},
    {"edits": [{"content": "x"}]}])
def test_planner_refuses_unacceptable_proposals(cand):
    with pytest.raises(PlanBlocked):
        plan(cand)


def test_planner_target_files_must_cover_every_edit():
    with pytest.raises(PlanBlocked, match="outside the declared"):
        plan({"edits": [EDIT, {**EDIT, "path": "other.py"}], "target_files": ["calc.py"]})
    p = plan({"edits": [EDIT, {**EDIT, "path": "other.py"}], "target_files": ["calc.py", "other.py"]})
    assert p.target_files == ("calc.py", "other.py")


# ---- evaluator -----------------------------------------------------------------------------------------------------------------------------------
OK, BAD = TestResult(True, "ok"), TestResult(False, "bad", 1, ("t::a",))


def test_golden_rule_needs_everything():
    e = RepairEvaluator()
    assert e.golden(OK, OK, ["calc.py"], ["calc.py"]).verdict is Verdict.SUCCESS
    assert e.golden(BAD, OK, ["calc.py"], ["calc.py"]).verdict is Verdict.FAILED
    assert e.golden(None, OK, [], []).verdict is Verdict.FAILED
    assert e.golden(OK, BAD, ["calc.py"], ["calc.py"]).verdict is Verdict.FAILED
    assert e.golden(OK, None, ["calc.py"], ["calc.py"]).verdict is Verdict.FAILED
    assert e.golden(OK, OK, ["calc.py", "other.py"], ["calc.py"]).verdict is Verdict.BLOCKED
    assert e.golden(BAD, BAD, ["evil.py"], ["calc.py"]).verdict is Verdict.BLOCKED             # a security problem outranks everything
    assert e.golden(OK, OK, ["Calc.PY"], ["./calc.py"]).verdict is Verdict.SUCCESS             # spelling differences are not changes


def test_preexisting_failures_are_counted_not_claimed():
    e = RepairEvaluator()
    base = TestResult(False, "", 1, ("a", "b"))
    reg = TestResult(False, "", 1, ("b", "c"))
    assert e.preexisting(base, reg) == (1, 2) and e.preexisting(None, reg) == (0, 2)


# ---- tester helpers ------------------------------------------------------------------------------------------------------------------------------
def steps(*entries):
    return {"steps": [{"step": i, "tool": "coding", "action": a, "ok": ok, "output": o} for i, (a, ok, o) in enumerate(entries, 1)]}


def test_parse_test_result_and_changes():
    out = steps(("start", True, {}), ("test", True, {"passed": False, "exit_code": 1, "summary": "1 failed", "failures": ["t::a"], "stdout": "E AssertionError",
                                                    "stderr": "", "duration": 0.5, "timed_out": False}),
                ("changes", True, {"changes": ["calc.py: modify +1/-1", "pkg\\x.py: create +3/-0"]}))
    r = T.parse_test_result(out)
    assert r and not r.passed and r.exit_status == 1 and r.failed_tests == ("t::a",) and r.duration == 0.5
    assert T.changed_paths(out) == ("calc.py", "pkg/x.py") and T.change_summaries(out) == ("calc.py: modify +1/-1", "pkg\\x.py: create +3/-0")


def test_parse_test_result_failure_modes():
    assert T.parse_test_result({}) is None and T.parse_test_result(None) is None and T.parse_test_result({"steps": "x"}) is None
    assert T.parse_test_result(steps(("test", False, {"passed": True}))) is None                # the step itself failed: no result
    assert T.parse_test_result(steps(("test", True, "garbage"))) is None
    aborted = T.parse_test_result(steps(("test", True, {"passed": True, "aborted": True})))
    assert aborted and not aborted.passed                                                       # an aborted run is never a pass
    timed = T.parse_test_result(steps(("test", True, {"passed": True, "timed_out": True})))
    assert timed and not timed.passed and timed.timed_out
    assert T.changed_paths(steps(("write", True, {}))) is None


def test_parse_test_result_redacts():
    r = T.parse_test_result(steps(("test", True, {"passed": False, "stdout": "token=abc123456789", "failures": []})), lambda s: s.replace("abc123456789", "[R]"))
    assert r and "abc123456789" not in r.stdout_summary


def test_test_step_builders():
    assert T.test_step(None) == {"action": "test"} and T.test_step("pytest", ["a.py::t", "b.py"]) == {"action": "test", "runner": "pytest", "args": "a.py::t b.py"}
    assert T.start_steps("/w")[0] == {"action": "start", "workspace": "/w"}
