import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ci_evidence", ROOT / "scripts" / "ci_evidence.py")
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)

PATTERNS = json.loads((ROOT / "scripts" / "ci_skip_baseline.json").read_text(encoding="utf-8"))["platforms"]["linux"]
SHA = "a" * 40
MERGE = "b" * 40


def junit(tmp_path, cases):
    body = "".join(cases)
    path = tmp_path / "j.xml"
    path.write_text(f'<testsuites><testsuite>{body}</testsuite></testsuites>', encoding="utf-8")
    return str(path)


OK = '<testcase classname="t.a" name="ok"/>'
FAIL = '<testcase classname="t.a" name="bad"><failure message="x"/></testcase>'
SKIP_OK = '<testcase classname="t.a" name="s"><skipped message="Windows path semantics"/></testcase>'
SKIP_BAD = '<testcase classname="t.a" name="s2"><skipped message="mystery"/></testcase>'
ENV = {"TEST_OUTCOME": "success", "EVENT_NAME": "push", "GITHUB_RUN_ID": "1"}


def ev(tmp_path, cases, env=None, parent2=None):
    return ci.build_evidence(junit(tmp_path, cases), PATTERNS, {**ENV, **(env or {})}, MERGE, parent2)


def test_success_with_expected_skip(tmp_path):
    e = ev(tmp_path, [OK, SKIP_OK])
    assert e["status"] == "passed" and e["passed"] == 1 and e["skipped"] == 1 and e["expected_skips"] == 1


def test_failed_test_is_failed(tmp_path):
    assert ev(tmp_path, [OK, FAIL])["status"] == "failed"


def test_unexpected_skip_is_not_success(tmp_path):
    e = ev(tmp_path, [OK, SKIP_BAD])
    assert e["status"] == "failed" and e["unexpected_skips"][0]["reason"] == "mystery"


def test_missing_report_is_error(tmp_path):
    e = ci.build_evidence(str(tmp_path / "nope.xml"), PATTERNS, ENV, MERGE, None)
    assert e["status"] == "error"


def test_non_success_outcome_is_error_even_if_report_green(tmp_path):
    assert ev(tmp_path, [OK], {"TEST_OUTCOME": "cancelled"})["status"] == "error"
    assert ev(tmp_path, [OK], {"TEST_OUTCOME": ""})["status"] == "error"


def test_no_passed_tests_is_error(tmp_path):
    assert ev(tmp_path, [SKIP_OK])["status"] == "error"


def test_pull_request_must_test_merge_of_pr_head(tmp_path):
    env = {"EVENT_NAME": "pull_request", "PR_HEAD_SHA": SHA, "PR_NUMBER": "7"}
    assert ev(tmp_path, [OK], env, parent2=SHA)["status"] == "passed"
    assert ev(tmp_path, [OK], env, parent2=SHA)["pr_number"] == 7
    assert ev(tmp_path, [OK], env, parent2="c" * 40)["status"] == "error"
    assert ev(tmp_path, [OK], {**env, "PR_HEAD_SHA": ""}, parent2=SHA)["status"] == "error"


def test_evidence_has_required_fields(tmp_path):
    e = ev(tmp_path, [OK])
    for key in ("tested_commit", "pr_number", "os", "python", "run_id", "job", "status", "passed", "failed", "skipped", "timestamp_utc"):
        assert key in e
