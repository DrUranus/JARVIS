"""V2 Vorbereitung: das Merge-Simulationsskript berichtet Konflikte, ohne irgendetwas im pruefenden Checkout zu veraendern."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("simulate_pr_merge_under_test", ROOT / "scripts" / "v2" / "simulate_pr_merge.py")
sim = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sim
spec.loader.exec_module(sim)


def g(cwd, *a):
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path, conflict=True):
    r = tmp_path / "r"
    r.mkdir()
    g(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("eins\n")
    (r / "tests" / "support").mkdir(parents=True)
    (r / "tests/support/protected_manifest.json").write_text(json.dumps({"files": {"a.txt": "0" * 64}}))
    g(r, "add", "-A")
    g(r, "commit", "-q", "-m", "base")
    g(r, "checkout", "-q", "-b", "side")
    (r / "a.txt").write_text("zwei\n" if conflict else "eins\n")
    (r / "b.txt").write_text("neu\n")
    g(r, "add", "-A")
    g(r, "commit", "-q", "-m", "side")
    g(r, "checkout", "-q", "main")
    (r / "a.txt").write_text("drei\n")
    g(r, "commit", "-q", "-am", "main change")
    return r


def snapshot(r):
    return (g(r, "rev-parse", "HEAD"), g(r, "branch", "--format=%(refname:short) %(objectname)"), g(r, "status", "--porcelain"), g(r, "worktree", "list").count("\n"), (r / "a.txt").read_text())


def test_a_conflict_is_reported_with_the_protected_file_and_nothing_changes(tmp_path):
    r = repo(tmp_path)
    before = snapshot(r)
    rep = sim.simulate(r, "side")
    assert rep["ok"] and rep["clean"] is False and rep["conflicts"] == ["a.txt"] and rep["protected_conflicts"] == ["a.txt"]
    assert snapshot(r) == before                                   # kein Branch bewegt, kein Index/Arbeitsverzeichnis veraendert, kein Worktree uebrig


def test_a_clean_merge_is_reported_clean_and_leaves_no_trace(tmp_path):
    r = repo(tmp_path, conflict=False)
    (r / "a.txt").write_text("eins\n")
    g(r, "commit", "-q", "-am", "back")
    before = snapshot(r)
    rep = sim.simulate(r, "side")
    assert rep["ok"] and rep["clean"] is True and rep["conflicts"] == [] and snapshot(r) == before


def test_unknown_references_are_refused_without_side_effects(tmp_path):
    r = repo(tmp_path)
    before = snapshot(r)
    assert sim.simulate(r, "gibt-es-nicht")["ok"] is False and sim.simulate(r, "side", base="auch-nicht")["ok"] is False
    assert snapshot(r) == before


def test_the_script_has_no_network_push_or_destructive_branch_commands():
    text = (ROOT / "scripts" / "v2" / "simulate_pr_merge.py").read_text(encoding="utf-8")
    for bad in ('"push"', '"fetch"', '"pull"', '"checkout"', '"reset"', '"branch"', '"commit"', '"rebase"', "--force-with-lease", "http"):
        assert bad not in text, bad
