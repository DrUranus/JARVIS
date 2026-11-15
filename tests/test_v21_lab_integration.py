"""V2.1 Integration M4/M8: der Bewertungskern des Labs (`jarvis.lab.evaluate`) neben der gesperrten Phase-15-Schicht (`jarvis.self_improvement`).
Erlaubt ist Analyse, Benchmark-Vergleich, Fehlerklassifizierung und Bewertung; nicht erlaubt sind Ausfuehrung, Uebernahme und das Umgehen der Phase-15-Sperren."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from jarvis.config import ConfigError, load_settings
from jarvis.lab import evaluate as lab
from jarvis.self_improvement import policy as P
from jarvis.self_improvement.isolation import ExecutionGuard

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
spec = importlib.util.spec_from_file_location("v21_bench_for_lab", ROOT / "scripts" / "bench" / "v21_bench.py")
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


def no_change():
    same = '<testsuite><testcase classname="a" name="t"/></testsuite>'
    return lab.compare_tests(lab.parse_junit(same), lab.parse_junit(same))


# ---- die Sperrliste des Labs deckt die der Phase-15-Schicht ab (kein Auseinanderlaufen) -----------------------------------------------------------------------
@pytest.mark.parametrize("never", P.NEVER_TARGETS)
def test_every_phase_15_never_target_is_also_protected_in_the_lab(never):
    path = "src/jarvis/" + never + ("x.py" if never.endswith("/") else "")
    a = lab.assess(tests=no_change(), touched_files=[path])
    assert a.verdict == "reject" and "protected_file" in a.reasons, never


def test_files_outside_the_phase_15_allow_list_are_never_an_improvement():
    a = lab.assess(tests=lab.compare_tests(lab.parse_junit('<testsuite><testcase classname="a" name="t"><failure message="x"/></testcase></testsuite>'),
                                           lab.parse_junit('<testsuite><testcase classname="a" name="t"/></testsuite>')), touched_files=["src/jarvis/tools/registry.py"])
    assert a.verdict == "reject" and a.may_apply is False and a.requires_owner_approval is True


def test_an_allowed_target_with_measured_improvement_is_still_only_a_proposal_for_the_owner():
    target = sorted(P.ALLOWED_TARGETS)[0]
    fixed = lab.compare_tests(lab.parse_junit('<testsuite><testcase classname="a" name="t"><failure message="x"/></testcase></testsuite>'),
                              lab.parse_junit('<testsuite><testcase classname="a" name="t"/></testsuite>'))
    a = lab.assess(tests=fixed, touched_files=[target])
    assert a.verdict == "improvement" and a.may_apply is False and a.requires_owner_approval is True
    assert json.loads(json.dumps(a.to_dict()))["may_apply"] is False


# ---- Benchmark-Vergleich auf echten Ausgaben des Benchmarks ---------------------------------------------------------------------------------------------------
def test_two_real_benchmark_outputs_can_be_compared_and_identical_runs_are_no_improvement(tmp_path):
    out1, out2 = tmp_path / "a.json", tmp_path / "b.json"
    assert bench.main(["--runs", "3", "--scale", "0.02", "--out", str(out1)]) == 0 and bench.main(["--runs", "3", "--scale", "0.02", "--out", str(out2)]) == 0
    d1, d2 = json.loads(out1.read_text(encoding="utf-8")), json.loads(out2.read_text(encoding="utf-8"))
    diffs = lab.compare_bench(d1, d1)
    assert set(diffs) == set(bench.CASES) and {d.state for d in diffs.values()} == {"same"}                 # dieselbe Messung mit sich selbst: kein Befund
    a = lab.assess(tests=no_change(), bench=diffs, touched_files=[sorted(P.ALLOWED_TARGETS)[0]])
    assert a.verdict == "no_evidence" and a.may_apply is False
    assert set(lab.compare_bench(d1, d2)) == set(diffs)


def test_failure_classification_groups_by_shape():
    clusters = lab.cluster_failures([("tests/test_a.py::t1", "AssertionError: 5 != 6"), ("tests/test_b.py::t2", "AssertionError: 7 != 8"), ("tests/test_c.py::t3", "KeyError: 'x'")])
    assert sorted(c.count for c in clusters) == [1, 2]


# ---- Phase-15-Sperren bleiben unberuehrt ---------------------------------------------------------------------------------------------------------------------
def test_the_phase_15_execution_lock_is_still_locked_and_the_reserved_keys_are_still_refused():
    assert ExecutionGuard.locked().allowed is False
    for key in ("JARVIS_SELF_IMPROVEMENT_ALLOW_PREPARE", "JARVIS_SELF_IMPROVEMENT_ALLOW_ACTIVATION"):
        with pytest.raises(ConfigError):
            load_settings(env={key: "true"})


def test_the_lab_is_wired_nowhere_and_nothing_imports_it_except_its_tests():
    for path in SRC.rglob("*.py"):
        if "lab" in path.parts and path.parent.name == "lab":
            continue
        text = path.read_text(encoding="utf-8")
        assert "jarvis.lab" not in text, path
