"""V2.1 Mission 4: das Labor BEWERTET nur (vorher/nachher). Es bereitet keinen Code vor, fuehrt nichts aus und gibt nie selbst frei."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jarvis.lab import evaluate as lab

ROOT = Path(__file__).resolve().parents[1]


def junit(cases: dict[str, str]) -> str:
    body = ""
    for name, state in cases.items():
        cls, _, test = name.rpartition("::")
        inner = {"passed": "", "failed": '<failure message="boom">AssertionError: 3 != 4 at 0x7f3a /tmp/x12/y.py:88</failure>', "error": '<error message="E">RuntimeError</error>',
                 "skipped": '<skipped message="why"/>'}[state]
        body += f'<testcase classname="{cls}" name="{test}">{inner}</testcase>'
    return f'<?xml version="1.0"?><testsuites><testsuite>{body}</testsuite></testsuites>'


def run(cases):
    return lab.parse_junit(junit(cases))


def bench(median, lo=None, hi=None, *, n=5, cpus=4, platform="Linux"):
    return {"environment": {"cpus": cpus, "platform": platform, "python": "3.13"}, "runs": n,
            "cases": {"journal": {"n": 200, "median_s": median, "min_s": lo if lo is not None else median * 0.95, "max_s": hi if hi is not None else median * 1.05}}}


BASE = {"t::a": "passed", "t::b": "passed", "t::c": "failed", "t::d": "skipped"}


def test_parse_counts_states_and_refuses_doctype_and_garbage():
    r = run(BASE)
    assert (len(r.passed), len(r.failed), len(r.skipped)) == (2, 1, 1) and "t::c" in r.failed
    with pytest.raises(lab.LabError):
        lab.parse_junit('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><testsuites/>')
    with pytest.raises(lab.LabError):
        lab.parse_junit("kein xml")
    with pytest.raises(lab.LabError):
        lab.parse_junit("<testsuites></testsuites>")  # leerer Lauf ist kein Nachweis


def test_regression_fixed_and_unchanged_are_told_apart():
    d = lab.compare_tests(run(BASE), run({**BASE, "t::a": "failed", "t::c": "passed"}))
    assert d.regressions == ("t::a",) and d.fixed == ("t::c",) and not d.new_skips and not d.removed


def test_a_skipped_or_removed_test_never_counts_as_passed():
    d = lab.compare_tests(run(BASE), run({"t::a": "skipped", "t::c": "failed", "t::d": "skipped"}))
    assert d.new_skips == ("t::a",) and d.removed == ("t::b",)
    v = lab.assess(tests=d)
    assert v.verdict == "reject" and {"new_skip", "removed_test"} <= set(v.reasons)


def test_added_tests_are_listed_and_a_failing_new_test_is_a_regression():
    d = lab.compare_tests(run(BASE), run({**BASE, "t::n1": "passed", "t::n2": "failed"}))
    assert d.added == ("t::n1", "t::n2") and d.regressions == ("t::n2",)


def test_bench_slower_faster_and_within_noise():
    assert lab.compare_bench(bench(1.0), bench(1.6))["journal"].state == "slower"
    assert lab.compare_bench(bench(1.0), bench(0.5))["journal"].state == "faster"
    assert lab.compare_bench(bench(1.0), bench(1.1))["journal"].state == "same"
    # ueberlappende Streuung ist kein Befund, auch wenn der Median stark abweicht
    assert lab.compare_bench(bench(1.0, 0.5, 2.0), bench(1.5, 0.9, 1.9))["journal"].state == "same"


def test_bench_is_incomparable_across_machines_too_few_runs_or_changed_size():
    assert lab.compare_bench(bench(1.0), bench(0.5, cpus=16))["journal"].state == "incomparable"
    assert lab.compare_bench(bench(1.0), bench(0.5, platform="Windows"))["journal"].state == "incomparable"
    assert lab.compare_bench(bench(1.0, n=1), bench(0.5, n=1))["journal"].state == "incomparable"
    other = bench(0.5); other["cases"]["journal"]["n"] = 20
    assert lab.compare_bench(bench(1.0), other)["journal"].state == "incomparable"
    assert lab.compare_bench(bench(1.0), {"environment": {}, "cases": {}})["journal"].state == "missing"


def test_failures_are_clustered_by_shape_not_by_addresses_or_numbers():
    fails = [("t::a", "AssertionError: 3 != 4 at 0x7f3a /tmp/x12/y.py:88"), ("t::b", "AssertionError: 9 != 1 at 0x11bc /tmp/q7/y.py:12"), ("t::c", "PermissionError: [WinError 32] in use")]
    cl = lab.cluster_failures(fails)
    assert [c.count for c in cl] == [2, 1] and cl[0].tests == ("t::a", "t::b")
    assert lab.cluster_failures(run(BASE).failures)[0].count == 1


def test_improvement_needs_evidence_and_nothing_worse():
    same = lab.compare_tests(run(BASE), run(BASE))
    assert lab.assess(tests=same).verdict == "no_evidence"
    fixed = lab.compare_tests(run(BASE), run({**BASE, "t::c": "passed"}))
    assert lab.assess(tests=fixed).verdict == "improvement"
    assert lab.assess(tests=same, bench=lab.compare_bench(bench(1.0), bench(0.5))).verdict == "improvement"
    mixed = lab.assess(tests=fixed, bench=lab.compare_bench(bench(1.0), bench(1.6)))
    assert mixed.verdict == "reject" and "slower" in mixed.reasons
    assert lab.assess(tests=same, bench=lab.compare_bench(bench(1.0), bench(0.5, cpus=16))).verdict == "no_evidence"


@pytest.mark.parametrize("path", ["src/jarvis/permissions/engine.py", "config/jarvis.toml", ".github/workflows/tests.yml", "src/jarvis/ui_contract/bus.py", "src/jarvis/bootstrap.py",
                                  "src\\jarvis\\permissions\\engine.py", "./src/jarvis/permissions/audit.py", "tests/support/protected_manifest.json", ".claude/settings.json", "tests/test_security_engine.py"])
def test_touching_a_protected_file_is_always_rejected(path):
    fixed = lab.compare_tests(run(BASE), run({**BASE, "t::c": "passed"}))
    v = lab.assess(tests=fixed, touched_files=["src/jarvis/business/calc.py", path])
    assert v.verdict == "reject" and "protected_file" in v.reasons and v.protected_touched


def test_deleting_or_weakening_tests_is_rejected_even_with_green_results():
    fixed = lab.compare_tests(run(BASE), run({**BASE, "t::c": "passed"}))
    assert "test_deleted" in lab.assess(tests=fixed, deleted_files=["tests/test_x.py"]).reasons
    assert lab.assess(tests=fixed, touched_files=["../outside.py"]).verdict == "reject"


def test_no_verdict_ever_allows_adoption_without_the_owner():
    fixed = lab.compare_tests(run(BASE), run({**BASE, "t::c": "passed"}))
    for v in (lab.assess(tests=fixed), lab.assess(tests=lab.compare_tests(run(BASE), run(BASE))), lab.assess(tests=fixed, touched_files=["config/jarvis.toml"])):
        assert v.requires_owner_approval is True and v.may_apply is False
        d = v.to_dict()
        assert d["requires_owner_approval"] is True and d["may_apply"] is False
    with pytest.raises(Exception):
        v.may_apply = True  # eingefroren


def test_the_lab_is_pure_no_process_file_network_or_other_layer():
    tree = ast.parse((ROOT / "src" / "jarvis" / "lab" / "evaluate.py").read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "re", "dataclasses", "typing", "xml.etree.ElementTree", "jarvis.errors"}, mods
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "exec", "eval", "compile", "__import__"}  # re.compile ist kein Code-Compiler und bleibt erlaubt
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"system", "Popen", "run", "write_text", "write_bytes", "read_text", "unlink", "rmtree"}
