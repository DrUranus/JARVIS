"""Real coding-agent tests: the local provider on a real directory, real pytest/unittest/git processes. Runs on Windows and POSIX.

These create their own small harmless projects below pytest's tmp_path; nothing outside it is touched.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from coding_util import CALC, ONCE, PYPROJECT, TEST_CALC, make_rig
from jarvis.coding import CodingError, CommandSpec, CodingErrorCode as EC
from jarvis.coding.providers.local import LocalProvider, scrubbed_env
from jarvis.coding.workspace import analyze_project, is_jarvis_repo
from jarvis.permissions import DecisionStatus

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def real(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 200, real=True, test_timeout=60)
    r.start()
    return r


def code(out):
    import re
    assert not out.success
    if isinstance(out.output, dict):
        return out.output["code"]
    m = re.search(r"\[([a-z_]+)\]", out.error or "")
    return m.group(1) if m else None


# ---- the whole development cycle ---------------------------------------------------------------------------------------------------------------
def test_fix_a_failing_project_end_to_end(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 40, real=True, test_timeout=120)
    # 1. detect the project
    started = r.start()
    assert started["project"]["language"] == "Python" and started["project"]["test_framework"] == "pytest"
    info = r.ok(action="info")
    assert info["default_runner"] == "python -m pytest" and "pyproject.toml" in info["important_files"]
    # 2. read a file
    src = r.ok(action="read", path="calc.py")
    assert "return a - b" in src["content"] and src["lines"] == 6
    # 3. search
    hits = r.ok(action="search", pattern="def ", glob="*.py")["hits"]
    assert {(h["path"], h["line"]) for h in hits} == {("calc.py", 1), ("calc.py", 5), ("tests/test_calc.py", 4), ("tests/test_calc.py", 8)}
    # 5./6./7. run pytest: it fails (the bug is real) and the failure is recognised
    first = r.ok(action="test")
    assert first["passed"] is False and first["exit_code"] == 1 and first["timed_out"] is False
    assert first["failures"] == ["tests/test_calc.py::test_add"] and "1 failed" in first["summary"] and "1 passed" in first["summary"]
    assert "assert -1 == 5" in first["stdout"] or "-1 == 5" in first["stdout"]
    # 4./8. change the code (hash-guarded, confirmed, summarised)
    out = r.ok(action="write", path="calc.py", mode="replace", old_text="return a - b", new_text="return a + b")
    assert out["added_lines"] == 1 and out["removed_lines"] == 1 and out["old_sha256"] == src["sha256"]
    assert r.file("calc.py").read_text(encoding="utf-8") == CALC.replace("a - b", "a + b")
    # 9. test again
    second = r.ok(action="test")
    # 10. report the successful state
    assert second["passed"] is True and second["exit_code"] == 0 and second["failures"] == [] and "2 passed" in second["summary"]
    report = r.ok(action="changes")
    assert report["changes"] == ["calc.py: modify +1/-1"] and [t["passed"] for t in report["tests"]] == [False, True]
    assert r.ok(action="status")["session"]["tests_run"] == 2 and r.ok(action="stop")["changed_files"] == ["calc.py"]
    # the user was asked for: start, test, write, test - in this order, each with the right level
    assert [q.action for q in r.prompts.requests] == ["start", "test", "write", "test"]
    # and nothing but the one intended file changed (no caches, no bytecode, no stray files)
    assert sorted(p.relative_to(r.project).as_posix() for p in r.project.rglob("*") if p.is_file()) == ["calc.py", "pyproject.toml", "tests/test_calc.py"]


def test_add_a_feature_with_tests_and_run_unittest(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 20, real=True, files={"mod.py": "def double(x):\n    return x * 2\n"})
    r.start()
    r.ok(action="write", path="test_mod.py", mode="create",
         content="import unittest\nfrom mod import double\n\n\nclass T(unittest.TestCase):\n    def test_double(self):\n        self.assertEqual(double(2), 4)\n    def test_neg(self):\n        self.assertEqual(double(-1), -2)\n")
    res = r.ok(action="test", runner="python -m unittest", args=["-v"])
    assert res["passed"] is True and res["summary"] == "OK" and "test_double" in res["stderr"]
    r.ok(action="write", path="mod.py", mode="replace", old_text="x * 2", new_text="x * 3")
    bad = r.ok(action="test", runner="python -m unittest")
    assert bad["passed"] is False and bad["exit_code"] == 1 and bad["summary"] == "FAILED"


def test_unicode_and_line_endings_survive_a_round_trip(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6, real=True, files={"pyproject.toml": PYPROJECT})
    r.start()
    text = "# Größe – Überprüfung ✓\r\nname = 'Käse'\r\n"
    r.ok(action="write", path="u.py", mode="create", content=text)
    assert (r.project / "u.py").read_bytes() == text.encode("utf-8")  # written as given, no newline translation
    r.ok(action="write", path="u.py", mode="replace", old_text="'Käse'\n", new_text="'Brot'\n")  # LF in the request, CRLF in the file
    assert (r.project / "u.py").read_bytes() == "# Größe – Überprüfung ✓\r\nname = 'Brot'\r\n".encode("utf-8")
    assert r.ok(action="read", path="u.py")["content"].splitlines()[0] == "# Größe – Überprüfung ✓"
    assert r.ok(action="search", pattern="Überprüfung")["hits"][0]["line"] == 1


def test_real_writes_are_atomic_hash_guarded_and_leave_no_temp_files(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 8, real=True)
    r.start()
    h = r.ok(action="read", path="calc.py")["sha256"]
    (r.project / "calc.py").write_text("# changed behind our back\n", encoding="utf-8")
    out = r.run(action="write", path="calc.py", mode="overwrite", content="mine\n", expected_sha256=h)
    assert code(out) == "file_changed" and (r.project / "calc.py").read_text(encoding="utf-8") == "# changed behind our back\n"
    r.ok(action="write", path="calc.py", mode="replace", old_text="behind our back", new_text="again")
    assert not [p for p in r.project.iterdir() if p.name.startswith(".jarvis-write-")]


def test_real_delete_removes_exactly_one_file(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6, real=True)
    r.start()
    r.ok(action="delete", path="tests/test_calc.py")
    assert not (r.project / "tests" / "test_calc.py").exists() and (r.project / "tests").is_dir() and (r.project / "calc.py").exists()
    assert code(r.run(action="delete", path="tests")) == "invalid_input" and (r.project / "tests").is_dir()


# ---- process safety (real processes) --------------------------------------------------------------------------------------------------------------------
def test_a_hanging_test_is_stopped_at_the_timeout(tmp_path):
    files = {"pyproject.toml": PYPROJECT, "tests/test_slow.py": "import time\n\n\ndef test_slow():\n    time.sleep(60)\n"}
    r = make_rig(tmp_path, [ONCE] * 4, real=True, files=files, test_timeout=2.0)
    r.start()
    t0 = time.monotonic()
    out = r.ok(action="test")
    assert out["timed_out"] is True and out["passed"] is False and out["exit_code"] is None
    assert time.monotonic() - t0 < 30


def test_a_test_that_floods_its_output_is_cut_off(tmp_path):
    files = {"test_flood.py": "import sys, unittest\n\n\nclass T(unittest.TestCase):\n    def test_flood(self):\n        for _ in range(10**7):\n"
                              "            sys.stderr.write('x' * 1000)\n            sys.stderr.flush()\n"}
    r = make_rig(tmp_path, [ONCE] * 4, real=True, files=files, test_timeout=60, max_output_bytes=5000)
    r.start()
    t0 = time.monotonic()
    out = r.ok(action="test", runner="python -m unittest")
    assert out["output_truncated"] is True and out["passed"] is False and out["timed_out"] is False
    assert len(out["stderr"]) <= 6000 and time.monotonic() - t0 < 40


def test_the_test_process_gets_a_scrubbed_environment_and_no_stdin(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TEST_API_TOKEN", "super-secret-value-123")
    monkeypatch.setenv("MY_PASSWORD", "hunter2hunter2")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k nothing_matches_this")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "evil"))
    body = ("import os, sys\n\n\ndef test_env():\n    seen = {k for k in os.environ if any(w in k.upper() for w in ('TOKEN', 'PASSWORD', 'SECRET'))}\n"
            "    assert not seen, seen\n    assert 'PYTEST_ADDOPTS' not in os.environ and 'PYTHONPATH' not in os.environ\n"
            "    assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1' and os.environ.get('CI') == '1'\n")
    r = make_rig(tmp_path / "x", [ONCE] * 4, real=True, files={"pyproject.toml": PYPROJECT, "tests/test_env.py": body})
    r.start()
    out = r.ok(action="test")
    assert out["passed"] is True, out["stdout"]
    assert "super-secret-value-123" not in str(out) and "hunter2hunter2" not in str(out)
    env = scrubbed_env("git")
    assert "JARVIS_TEST_API_TOKEN" not in env and env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_PAGER"] == "cat"


def test_arguments_reach_the_process_literally_and_shells_are_refused_by_the_provider(tmp_path):
    p = LocalProvider()
    script = "import sys, json; print(json.dumps(sys.argv[1:]))"
    nasty = ["; echo pwned", "&& dir", "$(id)", "`id`", "| more", "> out.txt", "%PATH%", "a b  c", "\"quoted\"", "'single'"]
    res = p.run_command(CommandSpec((sys.executable, "-c", script, *nasty), str(tmp_path), 30, 100_000))
    import json
    assert res.exit_code == 0 and json.loads(res.stdout) == nasty and not (tmp_path / "out.txt").exists()
    for exe in (shutil.which("cmd") or "", shutil.which("powershell") or "", shutil.which("sh") or "", shutil.which("bash") or ""):
        if exe:
            with pytest.raises(CodingError) as e:
                p.run_command(CommandSpec((exe, "-c", "echo hi"), str(tmp_path), 5, 1000))
            assert e.value.code is EC.COMMAND_NOT_ALLOWED
    bat = tmp_path / "x.bat"
    bat.write_text("@echo off\n", encoding="utf-8")
    with pytest.raises(CodingError):
        p.run_command(CommandSpec((str(bat),), str(tmp_path), 5, 1000))
    with pytest.raises(CodingError):
        p.run_command(CommandSpec(("python",), str(tmp_path), 5, 1000))                 # relative program: never a PATH lookup
    with pytest.raises(CodingError):
        p.run_command(CommandSpec((str(tmp_path / "missing.exe"),), str(tmp_path), 5, 1000))
    with pytest.raises(CodingError):
        p.run_command(CommandSpec((sys.executable, "-c", "1"), str(tmp_path / "no-such-dir"), 5, 1000))


def test_provider_limits_time_and_output_on_a_real_process(tmp_path):
    p = LocalProvider()
    t0 = time.monotonic()
    slow = p.run_command(CommandSpec((sys.executable, "-c", "import time; time.sleep(30)"), str(tmp_path), 1.0, 10_000))
    assert slow.timed_out and slow.exit_code is None and time.monotonic() - t0 < 15
    loud = p.run_command(CommandSpec((sys.executable, "-c", "import sys\nwhile True:\n    sys.stderr.write('e' * 4096)\n    sys.stderr.flush()"),
                                     str(tmp_path), 30, 3000))
    assert loud.truncated and len(loud.stderr) <= 3000 and not loud.timed_out
    both = p.run_command(CommandSpec((sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"), str(tmp_path), 30, 10_000))
    assert (both.stdout.strip(), both.stderr.strip(), both.exit_code) == ("out", "err", 3)  # separate streams, exit code, status
    assert both.duration > 0
    stdin = p.run_command(CommandSpec((sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"), str(tmp_path), 30, 1000))
    assert stdin.stdout.strip() == "''" and stdin.exit_code == 0  # a process can never wait for (or read) input
    res = p.run_test(CommandSpec((sys.executable, "-c", "pass"), str(tmp_path), 30, 1000))
    assert res.passed and res.exit_code == 0 and not res.timed_out


# ---- symlinks and links (real) -------------------------------------------------------------------------------------------------------------------------
def _symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symbolic links")


def test_symlinks_cannot_be_used_to_leave_the_workspace(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 20, real=True)
    outside = r.ws.parent / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("needle = 'stolen'\n", encoding="utf-8")
    _symlink(r.project / "dirlink", outside)
    _symlink(r.project / "filelink.py", outside / "secret.py")
    r.start()
    for path in ("dirlink/secret.py", "filelink.py", "dirlink"):
        assert code(r.run(action="read", path=path)) == "path_denied", path
        assert code(r.run(action="write", path=path, mode="replace", old_text="needle", new_text="x")) == "path_denied", path
        assert code(r.run(action="delete", path=path)) == "path_denied", path
    out = r.ok(action="search", pattern="needle")
    assert out["hits"] == [] and out["skipped"]["links"] == 2
    assert {e["path"]: e["type"] for e in r.ok(action="list")["entries"]}["dirlink"] == "link"
    assert (outside / "secret.py").read_text(encoding="utf-8") == "needle = 'stolen'\n"
    assert code(r.run(action="list", path="dirlink")) == "path_denied"


def test_a_link_to_a_secret_file_inside_the_workspace_is_still_secret(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6, real=True, files={"pyproject.toml": PYPROJECT, ".env": "TOKEN=abc\n"})
    _symlink(r.project / "innocent.txt", r.project / ".env")
    r.start()
    out = r.run(action="read", path="innocent.txt")
    assert not out.success and out.permission.level.value == "red"


def test_workspace_replaced_by_a_link_after_start_is_detected(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6, real=True)
    r.start()
    moved = r.ws / "moved-away"
    r.project.rename(moved)
    _symlink(r.project, r.ws.parent)
    assert code(r.run(action="read", path="calc.py")) == "workspace_changed"
    assert r.ok(action="status")["session"]["status"] == "failed"


def test_workspace_removed_after_start(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6, real=True)
    r.start()
    shutil.rmtree(r.project)
    assert code(r.run(action="list")) == "workspace_changed" and r.ok(action="status")["session"]["status"] == "failed"


# ---- git (real) ------------------------------------------------------------------------------------------------------------------------------------------
GIT = shutil.which("git")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True,
                   capture_output=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})


@pytest.mark.skipif(GIT is None, reason="git is not installed")
def test_git_status_diff_and_log_on_a_real_repository(tmp_path):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
    r = make_rig(tmp_path, [ONCE] * 10, real=True, files={"pyproject.toml": PYPROJECT, "calc.py": CALC, ".env": f"TOKEN={secret}\n"})
    _git(r.project, "init", "-q")
    _git(r.project, "add", "-A")
    _git(r.project, "commit", "-q", "-m", "first commit")
    r.start()
    (r.project / "calc.py").write_text(CALC.replace("a - b", "a + b"), encoding="utf-8")
    (r.project / ".env").write_text(f"TOKEN={secret}-changed\n", encoding="utf-8")
    status = r.ok(action="git", sub="status")
    assert status["exit_code"] == 0 and "calc.py" in status["output"]
    diff = r.ok(action="git", sub="diff")
    assert "a + b" in diff["output"] and "TOKEN" not in diff["output"] and secret not in diff["output"]  # .env is excluded from the diff
    log = r.ok(action="git", sub="log")
    assert "first commit" in log["output"]
    for sub in ("commit", "push", "reset", "clean", "checkout"):
        out = r.run(action="git", sub=sub)
        assert not out.success and out.permission.level.value == "red" and out.permission.status is DecisionStatus.DENIED
    assert subprocess.run([GIT, "log", "--oneline"], cwd=r.project, capture_output=True, text=True).stdout.count("\n") == 1  # nothing was committed
    assert code(r.run(action="read", path=".git/config")) == "protected_path" or not r.run(action="read", path=".git/config").success


@pytest.mark.skipif(GIT is None or sys.platform == "win32", reason="needs git and a POSIX shell script")
def test_a_repository_cannot_make_git_run_its_own_programs(tmp_path):
    marker = tmp_path / "pwned"
    hook = tmp_path / "fsmon.sh"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    r = make_rig(tmp_path / "w", [ONCE] * 6, real=True)
    _git(r.project, "init", "-q")
    _git(r.project, "config", "core.fsmonitor", str(hook))
    _git(r.project, "config", "core.pager", f"touch {marker}")
    _git(r.project, "config", "diff.external", str(hook))
    r.start()
    for sub in ("status", "diff", "log"):
        r.ok(action="git", sub=sub)
    assert not marker.exists()


# ---- JARVIS repository itself (read-only analysis) ---------------------------------------------------------------------------------------------------------
def test_the_jarvis_checkout_is_recognised_and_analysed_without_changes():
    p = LocalProvider()
    assert is_jarvis_repo(p, str(REPO))
    info = analyze_project(p, str(REPO))
    assert info.is_jarvis and info.language == "Python" and info.test_framework == "pytest" and "pyproject.toml" in info.important_files


# ---- Windows-specific spellings (real file system semantics) --------------------------------------------------------------------------------------------
win_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")


@win_only
def test_windows_case_insensitive_spellings_resolve_to_the_same_workspace_and_files(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 8, real=True)
    upper = str(r.project).upper()
    r.ok(action="start", workspace=upper)
    assert r.ok(action="status")["session"]["root"].lower() == str(r.project).lower()
    assert r.ok(action="read", path="CALC.PY")["lines"] == 6
    assert r.ok(action="read", path="Tests/TEST_CALC.py")["lines"] > 3
    for spelled in (".ENV", ".Env", "ID_RSA", "Credentials.JSON", ".GIT/config"):
        out = r.run(action="read", path=spelled)
        assert not out.success and out.permission.level.value == "red", spelled


@win_only
@pytest.mark.parametrize("bad", ["C:\\Windows\\win.ini", "c:/windows/win.ini", "\\\\localhost\\c$\\x", "\\\\?\\C:\\x", "..\\..\\x", "CON", "nul.txt", "a.txt:ads",
                                 "calc.py ", "calc.py.", "PROGRA~1\\x", ".\\..\\x"])
def test_windows_paths_that_must_never_work(tmp_path, bad):
    r = make_rig(tmp_path, [ONCE] * 4, real=True)
    r.start()
    out = r.run(action="read", path=bad)
    assert not out.success and code(out) in ("path_denied", "file_not_found", "invalid_input", "protected_path") or out.permission.level.value == "red"
    assert not (r.ws.parent / "x").exists()


def test_the_default_runner_is_this_interpreter_and_never_a_path_lookup(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, real=True)
    r.start()
    r.ok(action="test", args=["-q"])
    # (the fake-provider tests assert the exact argv; here the real run proves it works end to end with this interpreter)
    assert r.ok(action="status")["session"]["tests_run"] == 1


def test_halt_stops_a_running_test_immediately(tmp_path):
    import threading
    files = {"pyproject.toml": PYPROJECT, "tests/test_slow.py": "import time\n\n\ndef test_slow():\n    time.sleep(60)\n"}
    r = make_rig(tmp_path, [ONCE] * 4, real=True, files=files, test_timeout=120.0)
    r.start()
    threading.Timer(1.5, lambda: r.controller.halt("user pressed stop")).start()
    t0 = time.monotonic()
    out = r.ok(action="test")
    assert out["aborted"] is True and out["passed"] is False and out["timed_out"] is False and "halted" in out["note"]
    assert time.monotonic() - t0 < 20
    assert r.ok(action="status")["session"]["status"] == "halted"
    assert code(r.run(action="test")) == "failsafe"
