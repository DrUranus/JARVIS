"""Process-tree termination of SubprocessRunner: what is guaranteed, what is tested where, and what is NOT guaranteed.

* WINDOWS: every started process is put into a kill-on-close Job Object (winjob.py). `taskkill /T` is only the FALLBACK when no job could be created; it follows parent
  process ids and can NOT reach a grandchild whose parent already exited - this is not presented as isolation anywhere.
* LINUX: process group + descendants found beforehand (/proc). A process that calls setsid() after the scan can still escape.
* Neither is a sandbox (files, network and privileges are not restricted - see isolation.py).

Test layout: fake-API tests (platform-neutral, no process involved) prove the ERROR HANDLING; real-process tests prove the behaviour on the platform they run on; the
`win_` tests need Windows and are skipped elsewhere with a stated reason. A green Linux run is no evidence for the Windows implementation.
Safety: only helper scripts written by the tests are started; only processes started by the tests are terminated; helpers end by themselves after <= 25 s; liveness is
NEVER tested with os.kill(pid, 0) - on Windows any signal other than CTRL_C/CTRL_BREAK calls TerminateProcess."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path, PurePath

import pytest

from jarvis.self_improvement import SubprocessRunner
from jarvis.self_improvement import winjob
from jarvis.self_improvement import workspace as ws_mod

WIN = sys.platform.startswith("win")
windows_only = pytest.mark.skipif(not WIN, reason="Windows Job Objects / taskkill exist only on Windows")


# ---- liveness without signalling -----------------------------------------------------------------------------------------------------------------
def alive(pid: int) -> bool:
    if WIN:
        k32 = ctypes.windll.kernel32                                  # type: ignore[attr-defined]
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x00100000, False, pid)                   # SYNCHRONIZE
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102     # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:                                                              # a zombie still answers kill(0); it is dead for our purposes
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def wait_dead(pid: int, seconds: float = 10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end and alive(pid):
        time.sleep(0.1)
    return not alive(pid)


def wait_file(path: Path, seconds: float = 10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not path.exists():
        time.sleep(0.05)
    return path.exists()


# ---- PLATFORM-NEUTRAL: the Job Object helper with a fake Win32 layer ---------------------------------------------------------------------------------
class FakeApi:
    def __init__(self, fail_at: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_at = fail_at

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise OSError(5, f"{name}: access denied (fake)")

    def create_job(self):
        self._step("create_job")
        return 100

    def set_kill_on_close(self, job):
        self._step("set_kill_on_close")

    def open_process(self, pid):
        self._step("open_process")
        return 200

    def assign(self, job, process):
        self._step("assign")

    def terminate(self, job, exit_code):
        self._step("terminate")

    def close(self, handle):
        self.calls.append(f"close:{handle}")
        if self.fail_at == "close":
            raise OSError(6, "invalid handle (fake)")


def test_attach_creates_limits_assigns_and_releases_the_process_handle():
    api = FakeApi()
    job = winjob.attach(4242, api)
    assert job is not None and api.calls == ["create_job", "set_kill_on_close", "open_process", "assign", "close:200"]
    assert job.terminate() is True and api.calls[-1] == "terminate"
    job.close()
    job.close()                                                       # idempotent: the handle is closed once
    assert api.calls.count("close:100") == 1 and job.terminate() is False


@pytest.mark.parametrize("step, closed", [("create_job", []), ("set_kill_on_close", ["close:100"]), ("open_process", ["close:100"]), ("assign", ["close:200", "close:100"])])
def test_attach_failure_at_any_step_returns_none_and_leaks_no_handle(step, closed, caplog):
    api = FakeApi(fail_at=step)
    with caplog.at_level(logging.WARNING, logger="jarvis.self_improvement"):
        assert winjob.attach(4242, api) is None
    assert [c for c in api.calls if c.startswith("close:")] == closed
    assert any("containment unavailable" in r.message for r in caplog.records)


def test_terminate_failure_is_reported_as_false_and_close_failure_does_not_raise(caplog):
    api = FakeApi()
    job = winjob.attach(1, api)
    api.fail_at = "terminate"
    with caplog.at_level(logging.WARNING, logger="jarvis.self_improvement"):
        assert job.terminate() is False
        api.fail_at = "close"
        job.close()                                                   # logged, never raised
    assert any("TerminateJobObject failed" in r.message for r in caplog.records) and any("closing the job handle failed" in r.message for r in caplog.records)


@pytest.mark.skipif(WIN, reason="on Windows the real Win32 layer is used (see the win_ tests)")
def test_without_windows_no_job_can_be_created_and_attach_says_so(caplog):
    with caplog.at_level(logging.WARNING, logger="jarvis.self_improvement"):
        assert winjob.attach(os.getpid()) is None
    assert any("only on Windows" in r.message for r in caplog.records)


def test_struct_layout_matches_the_win32_headers():
    big = ctypes.sizeof(ctypes.c_void_p) == 8
    basic, extended = winjob.structs()
    assert ctypes.sizeof(basic) == (64 if big else 48)
    assert ctypes.sizeof(extended) == (144 if big else 112)
    assert winjob.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x2000 and winjob.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS == 9


# ---- PLATFORM-NEUTRAL: how the runner uses a job / falls back (fake process, patched taskkill) ---------------------------------------------------------
class FakeJob:
    def __init__(self, ok: bool = True) -> None:
        self.ok, self.terminated, self.closed = ok, 0, 0

    def terminate(self, code: int = 1) -> bool:
        self.terminated += 1
        return self.ok

    def close(self) -> None:
        self.closed += 1


class FakeProc:
    pid = 4242

    def __init__(self, job) -> None:
        self.jarvis_job, self.killed = job, 0

    def kill(self) -> None:
        self.killed += 1


@pytest.fixture
def taskkill(monkeypatch):
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_run(argv, **kw):
        calls.append(list(argv))
        return Result
    monkeypatch.setattr(ws_mod.subprocess, "run", fake_run)
    monkeypatch.setenv("SystemRoot", os.path.join("fake", "Windows"))
    return calls, Result


def test_windows_kill_uses_the_job_and_does_not_call_taskkill_when_it_works(taskkill):
    calls, _ = taskkill
    job = FakeJob(ok=True)
    SubprocessRunner._kill_windows(FakeProc(job))
    assert job.terminated == 1 and calls == []


def test_windows_kill_without_a_job_falls_back_to_taskkill_with_an_absolute_path_and_warns(taskkill, caplog):
    calls, _ = taskkill
    proc = FakeProc(None)
    with caplog.at_level(logging.WARNING, logger="jarvis.self_improvement"):
        SubprocessRunner._kill_windows(proc)
    assert calls == [[os.path.join("fake", "Windows", "System32", "taskkill.exe"), "/F", "/T", "/PID", "4242"]]
    assert PurePath(calls[0][0]).name == "taskkill.exe" and calls[0][0] != "taskkill"          # never resolved through PATH / the current directory
    assert proc.killed == 1 and any("no Job Object" in r.message and "grandchildren" in r.message for r in caplog.records)


def test_windows_kill_falls_back_when_the_job_refuses(taskkill):
    calls, _ = taskkill
    job = FakeJob(ok=False)
    proc = FakeProc(job)
    SubprocessRunner._kill_windows(proc)
    assert job.terminated == 1 and len(calls) == 1 and proc.killed == 1


@pytest.mark.parametrize("code, warns", [(0, False), (128, False), (1, True), (5, True)])
def test_a_failing_taskkill_is_logged_and_never_silent(taskkill, caplog, code, warns):
    calls, Result = taskkill
    Result.returncode = code
    with caplog.at_level(logging.WARNING, logger="jarvis.self_improvement"):
        SubprocessRunner._kill_windows(FakeProc(FakeJob(ok=False)))
    assert any("taskkill" in r.message and "failed" in r.message for r in caplog.records) is warns


def test_the_runner_attaches_a_job_to_every_process_and_closes_it_in_every_case(tmp_path):
    jobs: list[FakeJob] = []

    def factory(pid: int):
        jobs.append(FakeJob())
        return jobs[-1]
    r = SubprocessRunner(job_factory=factory)
    assert r.run([sys.executable, "-c", "print(1)"], tmp_path, 20).ok                           # normal exit
    assert r.run([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 0.5).timed_out   # timeout
    assert r.capture([sys.executable, "-c", "print(2)"], tmp_path, 20, 1000).strip() == b"2"    # capture
    assert len(jobs) == 3 and [j.closed for j in jobs] == [1, 1, 1]


def test_a_missing_job_does_not_break_the_runner(tmp_path):
    r = SubprocessRunner(job_factory=lambda pid: None)
    assert r.run([sys.executable, "-c", "print(1)"], tmp_path, 20).ok


# ---- REAL PROCESSES, any platform: does the tree really die? -------------------------------------------------------------------------------------------
def write_chain(tmp_path: Path) -> None:
    (tmp_path / "leaf.py").write_text("import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(25)\n")
    (tmp_path / "mid.py").write_text(textwrap.dedent("""
        import subprocess, sys, time
        # argv: leaf.py pidfile mode ; 'stay' keeps this process (the leaf's parent) running, 'exit' lets it end at once (the leaf becomes an ORPHAN)
        subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])
        time.sleep(25 if sys.argv[3] == 'stay' else 0.5)
    """))
    (tmp_path / "root.py").write_text(textwrap.dedent("""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]])
        time.sleep(25)
    """))


def run_chain(tmp_path: Path, mode: str, timeout: float = 4.0):
    write_chain(tmp_path)
    pidfile = tmp_path / f"leaf-{mode}.pid"
    res = SubprocessRunner().run([sys.executable, str(tmp_path / "root.py"), str(tmp_path / "mid.py"), str(tmp_path / "leaf.py"), str(pidfile), mode], tmp_path, timeout)
    assert wait_file(pidfile), "the leaf never started"
    return res, int(pidfile.read_text())


def test_timeout_ends_the_whole_tree_while_the_parents_are_alive(tmp_path):
    res, leaf = run_chain(tmp_path, "stay")
    assert res.timed_out
    assert wait_dead(leaf, 10), "a grandchild survived the timeout although its parents were alive"


def test_timeout_also_ends_an_orphaned_grandchild(tmp_path):
    """root -> mid -> leaf, mid exits early so the leaf's parent is gone. Linux: the process group still contains the leaf. Windows: only the Job Object can reach it
    (`taskkill /T` follows parent ids and could not) - if this fails on Windows, containment is NOT working there."""
    res, leaf = run_chain(tmp_path, "exit")
    assert res.timed_out
    assert wait_dead(leaf, 10), "the orphaned grandchild survived the timeout"


# ---- WINDOWS ONLY: the real Job Object --------------------------------------------------------------------------------------------------------------
@windows_only
def test_win_the_default_runner_uses_job_objects_and_children_really_are_in_one(tmp_path):
    assert SubprocessRunner()._job_factory is winjob.attach
    probe = ("import ctypes, sys\n"
             "k = ctypes.windll.kernel32\n"
             "k.GetCurrentProcess.restype = ctypes.c_void_p\n"
             "b = ctypes.c_int(0)\n"
             "ok = k.IsProcessInJob(ctypes.c_void_p(k.GetCurrentProcess()), None, ctypes.byref(b))\n"
             "print('INJOB=%d OK=%d' % (b.value, ok))\n")
    res = SubprocessRunner().run([sys.executable, "-c", probe], tmp_path, 30)
    assert res.ok and "INJOB=1 OK=1" in res.output, res.output


@windows_only
def test_win_terminating_the_job_kills_child_and_grandchild_even_after_the_parent_exited(tmp_path):
    (tmp_path / "leaf.py").write_text("import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(25)\n")
    (tmp_path / "root.py").write_text(textwrap.dedent("""
        import subprocess, sys, time, os
        while not os.path.exists(sys.argv[3]):          # handshake: do not start the leaf before the job exists
            time.sleep(0.05)
        subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])
        time.sleep(0.5)                                  # the root exits first: the leaf becomes an orphan
    """))
    go, pidfile = tmp_path / "go", tmp_path / "leaf.pid"
    root = subprocess.Popen([sys.executable, str(tmp_path / "root.py"), str(tmp_path / "leaf.py"), str(pidfile), str(go)])
    job = winjob.attach(root.pid)
    assert job is not None, "a Job Object could not be created/assigned - see the log; containment is unavailable here"
    try:
        go.write_text("go")
        assert wait_file(pidfile)
        leaf = int(pidfile.read_text())
        root.wait(10)
        assert root.poll() is not None and alive(leaf), "precondition: the root has exited, the orphan is still running"
        assert job.terminate() is True
        assert wait_dead(leaf, 10), "TerminateJobObject did not reach the orphaned grandchild"
    finally:
        job.close()
        if root.poll() is None:
            root.kill()


@windows_only
def test_win_closing_the_job_handle_ends_the_tree_kill_on_close(tmp_path):
    (tmp_path / "leaf.py").write_text("import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(25)\n")
    pidfile = tmp_path / "leaf.pid"
    root = subprocess.Popen([sys.executable, "-c", f"import subprocess, sys, time; subprocess.Popen([sys.executable, r'{tmp_path / 'leaf.py'}', r'{pidfile}']); time.sleep(25)"])
    job = winjob.attach(root.pid)
    assert job is not None
    try:
        assert wait_file(pidfile)
        leaf = int(pidfile.read_text())
        time.sleep(0.3)
        job.close()                                                   # no explicit terminate: only the handle is released
        assert wait_dead(root.pid, 10) and wait_dead(leaf, 10), "kill-on-close did not end the tree"
    finally:
        if root.poll() is None:
            root.kill()


@windows_only
def test_win_processes_left_running_after_a_normal_exit_are_ended_when_the_runner_returns(tmp_path):
    """Documented behaviour change of the Job Object: stragglers of a command that exited normally do not outlive SubprocessRunner.run (kill-on-close). On Linux
    they would survive (no equivalent) - that asymmetry is known and not claimed to be isolation."""
    write_chain(tmp_path)
    pidfile = tmp_path / "leaf-straggler.pid"
    (tmp_path / "quick.py").write_text(f"import subprocess, sys; subprocess.Popen([sys.executable, r'{tmp_path / 'leaf.py'}', r'{pidfile}'])\n")
    res = SubprocessRunner().run([sys.executable, str(tmp_path / "quick.py")], tmp_path, 30)
    assert res.ok and not res.timed_out
    assert wait_file(pidfile)
    assert wait_dead(int(pidfile.read_text()), 10), "a straggler survived the runner"


@windows_only
def test_win_taskkill_fallback_still_works_for_a_live_tree(tmp_path):
    """Without a job (simulated by a factory returning None) the fallback ends a tree whose parents are alive. It is NOT expected to catch orphans."""
    write_chain(tmp_path)
    pidfile = tmp_path / "leaf-fb.pid"
    res = SubprocessRunner(job_factory=lambda pid: None).run(
        [sys.executable, str(tmp_path / "root.py"), str(tmp_path / "mid.py"), str(tmp_path / "leaf.py"), str(pidfile), "stay"], tmp_path, 4.0)
    assert res.timed_out and wait_file(pidfile)
    assert wait_dead(int(pidfile.read_text()), 10), "taskkill /T did not end a tree whose parents were alive"
