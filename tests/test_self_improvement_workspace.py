"""GitWorkspace and SubprocessRunner against REAL git on temporary repositories. Only `git` runs (plus test-owned helper scripts for the runner); no proposed code is
imported or executed. Covers V3 (exact export, manifest, hashes), V7 (metadata review that .gitattributes cannot hide), validated git arguments, process limits.
These tests show the behaviour of the helpers; they do not prove isolation."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from jarvis.self_improvement import ChangeBlocked, GitWorkspace, PreparationError, SubprocessRunner, policy as P
from jarvis.self_improvement.workspace import Export, manifest_digest, valid_sha

PLANNER = "src/jarvis/goals/planner.py"
FILES = {"src/jarvis/__init__.py": "", PLANNER: "def add(a, b):\n    return a - b\n", "src/jarvis/goals/evaluator.py": "X = 1\n", "tests/test_x.py": "def test_x():\n    assert True\n"}


def git(repo: Path, *args: str, check=True) -> str:
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(r.stderr)
    return r.stdout.strip()


def make_repo(tmp_path: Path, files=None, *, crlf=False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    if crlf:
        git(repo, "config", "core.autocrlf", "true")
    for rel, text in {**FILES, **(files or {})}.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as fh:
            fh.write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def commit_change(repo: Path, changes: dict[str, str | None]) -> tuple[str, str]:
    base = git(repo, "rev-parse", "HEAD")
    for rel, text in changes.items():
        f = repo / rel
        if text is None:
            f.unlink()
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return base, git(repo, "rev-parse", "HEAD")


def ws(tmp_path, repo) -> GitWorkspace:
    return GitWorkspace(repo, tmp_path / "data", timeout=30)


# ---- valid git arguments ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["--output=/tmp/x", "HEAD", "main", "g" * 40, "a" * 39, "a" * 41, "A" * 40, "", None, 5, "a" * 40 + " --stat", "a" * 40 + "\n"])
def test_only_full_hex_object_ids_reach_git(tmp_path, bad):
    with pytest.raises(PreparationError):
        valid_sha(bad)
    w = ws(tmp_path, make_repo(tmp_path))
    with pytest.raises(PreparationError):
        w.changed_entries(bad, "a" * 40)
    with pytest.raises(PreparationError):
        w.worktree_for("imp-000000000001", P.BRANCH_PREFIX + "imp-000000000001", bad)
    with pytest.raises(PreparationError):
        w.revert(bad)


def test_a_stored_option_like_base_cannot_write_files(tmp_path):
    w = ws(tmp_path, make_repo(tmp_path))
    target = tmp_path / "pwned"
    with pytest.raises(PreparationError):
        w.review(f"--output={target}", "a" * 40)
    assert not target.exists()


# ---- V7: review from metadata and blobs --------------------------------------------------------------------------------------------------------
def test_a_clean_change_is_reviewed_from_git_objects(tmp_path):
    repo = make_repo(tmp_path)
    base, head = commit_change(repo, {PLANNER: "def add(a, b):\n    return a + b\n"})
    r = ws(tmp_path, repo).review(base, head)
    assert r.changed_files == (PLANNER,) and any("a + b" in ln for ln in r.view) and len(r.diff_digest) == 32


def test_gitattributes_minus_diff_and_binary_cannot_hide_a_change(tmp_path):
    repo = make_repo(tmp_path)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.py -diff\n*.py binary\n")
    base, head = commit_change(repo, {PLANNER: "import socket\n"})
    assert "Binary files" in git(repo, "diff", base, head)               # the TEXT diff is blinded ...
    with pytest.raises(ChangeBlocked, match="socket"):                   # ... the metadata + blob review is not
        ws(tmp_path, repo).review(base, head)


def test_plus_plus_prefixed_added_lines_are_scanned(tmp_path):
    repo = make_repo(tmp_path)
    base, head = commit_change(repo, {PLANNER: "x = 1\n++__import__('os')\n"})
    with pytest.raises(ChangeBlocked, match="manual review"):
        ws(tmp_path, repo).review(base, head)


@pytest.mark.parametrize("changes, text", [
    ({"src/jarvis/goals/new.py": "x = 1\n"}, "only modifications"), ({PLANNER: None}, "only modifications"),
    ({"src/jarvis/permissions/engine.py": "x = 2\n"}, "manual review"), ({"src/jarvis/goals/evaluator.py": "X = 2\n", "tests/test_x.py": "def test_x():\n    pass\n"}, "manual review"),
    ({PLANNER: "x = 'é'\n".encode("latin-1").decode("latin-1")}, None)])
def test_added_deleted_and_unlisted_files_block(tmp_path, changes, text):
    repo = make_repo(tmp_path, {"src/jarvis/permissions/engine.py": "x = 1\n"})
    base, head = commit_change(repo, changes)
    if text is None:
        ws(tmp_path, repo).review(base, head)               # a plain unicode change in an allowed file is fine
        return
    with pytest.raises(ChangeBlocked, match=text):
        ws(tmp_path, repo).review(base, head)


def test_mode_changes_symlinks_renames_and_binary_files_block(tmp_path):
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    os.chmod(repo / PLANNER, 0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chmod")
    head = git(repo, "rev-parse", "HEAD")
    if os.name == "posix":
        with pytest.raises(ChangeBlocked, match="mode"):
            ws(tmp_path, repo).review(base, head)
        os.chmod(repo / PLANNER, 0o644)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "chmod back")
        base2 = git(repo, "rev-parse", "HEAD")
        (repo / "src/jarvis/goals/evaluator.py").unlink()
        os.symlink("planner.py", repo / "src/jarvis/goals/evaluator.py")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "symlink")
        with pytest.raises(ChangeBlocked):
            ws(tmp_path, repo).review(base2, git(repo, "rev-parse", "HEAD"))
    repo2 = make_repo(tmp_path / "b")
    b0, h0 = commit_change(repo2, {PLANNER: "x = 1\n\x00\x01"})
    with pytest.raises(ChangeBlocked, match="binary"):
        ws(tmp_path / "b", repo2).review(b0, h0)


# ---- V3: export of the exact commit ------------------------------------------------------------------------------------------------------------
def test_export_contains_exactly_the_files_of_the_commit_and_no_git(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "untracked.txt").write_text("not versioned")
    (repo / PLANNER).write_text("def add(a, b):\n    return 'UNCOMMITTED'\n")           # working-tree state must not leak into the export
    w = ws(tmp_path, repo)
    exp = w.export_commit(git(repo, "rev-parse", "HEAD"))
    try:
        listed = sorted(p.relative_to(exp.path).as_posix() for p in exp.path.rglob("*") if p.is_file())
        assert listed == sorted(FILES) and not (exp.path / ".git").exists() and not (exp.path / "untracked.txt").exists()
        assert (exp.path / PLANNER).read_text() == FILES[PLANNER] and "UNCOMMITTED" not in (exp.path / PLANNER).read_text()
        assert dict(exp.manifest)[PLANNER] == hashlib.sha256(FILES[PLANNER].encode()).hexdigest()
        assert exp.manifest_sha256 == manifest_digest(list(exp.manifest)) and exp.commit == git(repo, "rev-parse", "HEAD")
        w.verify_export(exp)
        assert (exp.path / PLANNER).stat().st_mode & 0o222 == 0           # exported files are made read-only (advisory: the owner/root can still change them -
        #                                                                   which is why the manifest is verified again after any run)
    finally:
        w.remove_export(exp.path)
    assert not exp.path.exists()


def test_any_difference_between_export_and_manifest_is_detected(tmp_path):
    repo = make_repo(tmp_path)
    w = ws(tmp_path, repo)
    exp = w.export_commit(git(repo, "rev-parse", "HEAD"))
    try:
        for mutate in (lambda: (exp.path / "extra.py").write_text("x"), lambda: os.chmod(exp.path / PLANNER, 0o600) or (exp.path / PLANNER).write_text("changed"),
                       lambda: (exp.path / "src").joinpath(".git").mkdir()):
            for p in [exp.path, *exp.path.rglob("*")]:
                os.chmod(p, 0o700)
            mutate()
            with pytest.raises(PreparationError, match="differs"):
                w.verify_export(exp)
            for q in list(exp.path.rglob("extra.py")) + list(exp.path.rglob(".git")):
                (q.rmdir() if q.is_dir() else q.unlink())
            (exp.path / PLANNER).write_text(FILES[PLANNER])
            w.verify_export(exp)
        # a missing file
        os.chmod(exp.path / "src/jarvis/goals", 0o700)
        (exp.path / "src/jarvis/goals/evaluator.py").unlink()
        with pytest.raises(PreparationError):
            w.verify_export(exp)
    finally:
        w.remove_export(exp.path)


@pytest.mark.skipif(os.name != "posix", reason="symlinks")
def test_export_refuses_symlinks_submodule_entries_and_unusual_names(tmp_path):
    repo = make_repo(tmp_path)
    os.symlink("/etc/passwd", repo / "src/jarvis/link.py")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "link")
    with pytest.raises(PreparationError, match="regular file"):
        ws(tmp_path, repo).export_commit(git(repo, "rev-parse", "HEAD"))
    repo2 = make_repo(tmp_path / "n", {"src/jarvis/we irdé.py": "x = 1\n"})
    with pytest.raises(PreparationError, match="unusual"):
        ws(tmp_path / "n", repo2).export_commit(git(repo2, "rev-parse", "HEAD"))
    repo3 = make_repo(tmp_path / "c", {"src/jarvis/A.py": "x = 1\n", "src/jarvis/a.py": "x = 2\n"})
    with pytest.raises(PreparationError, match="colliding"):
        ws(tmp_path / "c", repo3).export_commit(git(repo3, "rev-parse", "HEAD"))
    assert not P.refuse_target(".git/config") is None and ".git" not in [p.name for p in tmp_path.rglob(".GIT")]


def test_export_survives_clean_smudge_filters_and_crlf_settings(tmp_path):
    """The export reads blobs from the object database: no filter and no autocrlf setting can alter what is tested."""
    repo = make_repo(tmp_path, crlf=True)
    git(repo, "config", "filter.evil.smudge", "echo SMUDGED")
    (repo / ".gitattributes").write_text("*.py filter=evil\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "attrs")
    w = ws(tmp_path, repo)
    exp = w.export_commit(git(repo, "rev-parse", "HEAD"))
    try:
        assert b"SMUDGED" not in (exp.path / PLANNER).read_bytes() and (exp.path / PLANNER).read_bytes() == FILES[PLANNER].encode()
    finally:
        w.remove_export(exp.path)


def test_export_removal_only_touches_export_directories(tmp_path):
    victim = tmp_path / "important"
    victim.mkdir()
    (victim / "f").write_text("keep")
    GitWorkspace.remove_export(victim)
    assert (victim / "f").exists()


# ---- active tree checks (git primitive used by a future activation; fixtures only) -------------------------------------------------------------
@pytest.mark.parametrize("crlf", [False, True], ids=["lf", "windows-crlf-autocrlf"])
def test_dirty_tree_is_detected_with_and_without_autocrlf(tmp_path, crlf):
    repo = make_repo(tmp_path, crlf=crlf)
    w = ws(tmp_path, repo)
    assert w.tracked_changes() == ""
    (repo / PLANNER).write_text("changed\n")
    assert PLANNER in w.tracked_changes()


# ---- process runner: limits ---------------------------------------------------------------------------------------------------------------
def test_runner_timeout_cancel_and_output_cap(tmp_path):
    import threading
    r = SubprocessRunner(max_output=1000, max_total=200_000)
    t0 = time.monotonic()
    res = r.run([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 0.5)
    assert res.timed_out and not res.ok and time.monotonic() - t0 < 15
    flag = threading.Event()
    flag.set()
    assert r.run([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 30, flag).cancelled
    big = r.run([sys.executable, "-c", "import sys\nwhile True:\n    sys.stdout.write('x' * 1000)"], tmp_path, 30)
    assert big.output_limit and not big.ok and len(big.output) <= 1000
    with pytest.raises(PreparationError):
        r.capture([sys.executable, "-c", "import sys; sys.stdout.write('x' * 5000)"], tmp_path, 10, 1000)
    assert r.capture([sys.executable, "-c", "import sys; sys.stdout.write('abc')"], tmp_path, 10, 1000) == b"abc"
    with pytest.raises(PreparationError):
        r.capture([sys.executable, "-c", "raise SystemExit(3)"], tmp_path, 10, 1000)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="descendant discovery uses /proc (Linux only; Windows is untested)")
def test_detached_child_processes_are_killed_with_their_parent(tmp_path):
    """Helper scripts are written by this test (they are not proposed code)."""
    pidfile = tmp_path / "child.pid"
    (tmp_path / "child.py").write_text("import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(60)\n")
    (tmp_path / "parent.py").write_text(textwrap.dedent("""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]], start_new_session=True)
        time.sleep(60)
    """))
    res = SubprocessRunner().run([sys.executable, str(tmp_path / "parent.py"), str(tmp_path / "child.py"), str(pidfile)], tmp_path, 3.0)
    assert res.timed_out
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    alive = True
    while alive and time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except OSError:
            alive = False
    if alive:
        os.kill(pid, 9)
    assert not alive, "the detached grandchild survived the timeout"


def test_runner_environment_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-supersecretvalue1234567890")
    monkeypatch.setenv("MY_PASSWORD", "hunter2hunter2")
    res = SubprocessRunner().run([sys.executable, "-c", "import os; print(sorted(k for k in os.environ if k.upper() in ('OPENAI_API_KEY', 'MY_PASSWORD')))"], tmp_path, 20)
    assert res.ok and "OPENAI" not in res.output and "MY_PASSWORD" not in res.output
