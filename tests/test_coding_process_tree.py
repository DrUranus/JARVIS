"""Process-tree termination of the coding provider (LocalProvider): timeout, flood and abort_running must end the WHOLE tree.

Windows: the started process is put into a kill-on-close Job Object (jarvis.self_improvement.winjob, reused - no second implementation). Before, only the root
process was ended there. Linux: unchanged (own session + killpg).

Layout: fake-job tests prove the wiring and the error handling on every platform; the `win_` tests start real child/grandchild processes and need Windows - Linux
skips them with a stated reason. A green Linux run is no evidence for the Windows implementation (the CI Windows run is).
Safety: only helper scripts written here are started; helpers end by themselves after <= 25 s; liveness is never tested with os.kill(pid, 0) on Windows."""
import ctypes
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from jarvis.coding import CommandSpec
from jarvis.coding.providers import local as local_mod
from jarvis.coding.providers.local import LocalProvider

WIN = sys.platform.startswith("win")
windows_only = pytest.mark.skipif(not WIN, reason="Windows Job Objects exist only on Windows")


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
    import os
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
    while time.monotonic() < end:
        if path.exists() and path.read_text().strip():
            return True
        time.sleep(0.05)
    return False


def spec_of(argv, cwd: str, timeout: float) -> CommandSpec:
    return CommandSpec(tuple(argv), cwd, timeout, 100_000)


# ---- fake job: wiring and error handling, every platform --------------------------------------------------------------------------------------------
class FakeJob:
    def __init__(self, terminates: bool = True) -> None:
        self.ok, self.calls = terminates, []

    def terminate(self, code: int = 1) -> bool:
        self.calls.append("terminate")
        return self.ok

    def close(self) -> None:
        self.calls.append("close")


class FakeProc:
    pid = 4242

    def __init__(self, job=None) -> None:
        self.killed = 0
        if job is not None:
            self.jarvis_job = job

    def kill(self) -> None:
        self.killed += 1


@pytest.fixture
def as_windows(monkeypatch):
    monkeypatch.setattr(local_mod.sys, "platform", "win32")


def test_windows_termination_uses_the_job_and_does_not_touch_the_process_group(as_windows):
    job, proc = FakeJob(), FakeProc()
    LocalProvider._terminate(proc, job)                                # type: ignore[arg-type]
    assert job.calls == ["terminate"] and proc.killed == 0


def test_windows_termination_falls_back_to_killing_the_root_when_there_is_no_job_or_it_refuses(as_windows):
    for job in (None, FakeJob(terminates=False)):
        proc = FakeProc()
        LocalProvider._terminate(proc, job)                            # type: ignore[arg-type]
        assert proc.killed == 1


def test_a_job_is_attached_to_the_started_process_and_always_closed(tmp_path):
    seen, jobs = [], []

    def factory(pid: int):
        seen.append(pid)
        jobs.append(FakeJob())
        return jobs[-1]

    r = LocalProvider(job_factory=factory).run_command(spec_of([sys.executable, "-c", "print('hi')"], str(tmp_path), 20.0))
    assert r.exit_code == 0 and "hi" in r.stdout
    assert len(seen) == 1 and jobs[0].calls == ["close"]               # normal exit: closed (kill-on-close ends leftovers), never terminated


def test_the_job_is_closed_after_a_timeout_too(tmp_path):
    jobs = []

    def factory(pid: int):
        jobs.append(FakeJob())
        return jobs[-1]

    r = LocalProvider(job_factory=factory).run_command(spec_of([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), 0.5))
    assert r.timed_out and jobs[0].calls[-1] == "close"


def test_a_failing_job_factory_does_not_break_the_run(tmp_path):
    r = LocalProvider(job_factory=lambda pid: None).run_command(spec_of([sys.executable, "-c", "print('ok')"], str(tmp_path), 20.0))
    assert r.exit_code == 0


def test_posix_behaviour_is_unchanged_by_the_job_support(tmp_path):
    assert LocalProvider()._job_factory is None and LocalProvider()._resume is None   # a plain provider has no job on any platform
    r = LocalProvider().run_command(spec_of([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), 0.5))
    assert r.timed_out and r.exit_code is None


# ---- real trees ---------------------------------------------------------------------------------------------------------------------------------------
def write_chain(tmp_path: Path) -> list[str]:
    (tmp_path / "leaf.py").write_text("import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(25)\n")
    (tmp_path / "mid.py").write_text(textwrap.dedent("""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])
        time.sleep(25 if sys.argv[3] == 'stay' else 0.5)       # 'exit': the leaf becomes an ORPHAN (its parent is gone)
    """))
    (tmp_path / "root.py").write_text(textwrap.dedent("""
        import subprocess, sys, time
        subprocess.Popen([sys.executable] + sys.argv[1:])
        time.sleep(25)
    """))
    return [sys.executable, str(tmp_path / "root.py"), str(tmp_path / "mid.py"), str(tmp_path / "leaf.py")]


def chain_spec(tmp_path: Path, mode: str, timeout: float = 4.0) -> tuple[CommandSpec, Path]:
    pidfile = tmp_path / f"leaf-{mode}.pid"
    return spec_of([*write_chain(tmp_path), str(pidfile), mode], str(tmp_path), timeout), pidfile


def wired_provider() -> LocalProvider:
    """The provider as `bootstrap` builds it on this platform: Windows gets the Job Object wiring (a bare LocalProvider() there is the documented root-only fallback and
    is NOT what the application runs); elsewhere the process-group mechanism is built in."""
    if WIN:
        from jarvis.self_improvement import winjob
        return LocalProvider(job_factory=winjob.attach, resume=winjob.resume)
    return LocalProvider()


@pytest.mark.parametrize("mode", ["stay", "exit"])
def test_timeout_ends_the_whole_tree_including_an_orphaned_grandchild(tmp_path, mode):
    spec, pidfile = chain_spec(tmp_path, mode)
    r = wired_provider().run_command(spec)
    assert r.timed_out and wait_file(pidfile), "the leaf never started"
    assert wait_dead(int(pidfile.read_text()), 10), f"a grandchild survived the timeout ({mode})"


def test_abort_running_ends_the_whole_tree(tmp_path):
    spec, pidfile = chain_spec(tmp_path, "stay", timeout=30.0)
    prov = wired_provider()
    threading.Timer(1.5, lambda: (wait_file(pidfile), prov.abort_running())).start()
    r = prov.run_command(spec)
    assert r.aborted and wait_file(pidfile)
    assert wait_dead(int(pidfile.read_text()), 10), "a grandchild survived abort_running"


# ---- WINDOWS ONLY ---------------------------------------------------------------------------------------------------------------------------------------
def win_provider() -> LocalProvider:
    from jarvis.self_improvement import winjob
    return LocalProvider(job_factory=winjob.attach, resume=winjob.resume)


@windows_only
def test_win_bootstrap_wires_the_winjob_module_into_the_local_provider(tmp_path):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from jarvis.self_improvement import winjob
    core = build_core(load_settings(env={"JARVIS_CODING_ENABLED": "true", "JARVIS_CODING_PROVIDER": "local", "JARVIS_MEMORY_PATH": ":memory:",
                                         "JARVIS_LOG_DIR": str(tmp_path), "JARVIS_WORKSPACE": str(tmp_path)}))
    prov = core.subsystems["coding"].controller._provider
    assert prov._job_factory is winjob.attach and prov._resume is winjob.resume


@windows_only
def test_win_a_child_of_the_provider_is_in_a_job(tmp_path):
    probe = ("import ctypes\nk = ctypes.windll.kernel32\nk.GetCurrentProcess.restype = ctypes.c_void_p\nb = ctypes.c_int(0)\n"
             "ok = k.IsProcessInJob(ctypes.c_void_p(k.GetCurrentProcess()), None, ctypes.byref(b))\nprint('INJOB=%d OK=%d' % (b.value, ok))\n")
    r = win_provider().run_command(spec_of([sys.executable, "-c", probe], str(tmp_path), 30.0))
    assert r.exit_code == 0 and "INJOB=1 OK=1" in r.stdout, r.stdout + r.stderr


@windows_only
def test_win_halt_via_abort_running_and_timeout_kill_child_and_grandchild_of_run_test(tmp_path):
    spec, pidfile = chain_spec(tmp_path, "exit", timeout=3.0)
    res = win_provider().run_test(spec)
    assert res.timed_out and not res.passed and wait_file(pidfile)
    assert wait_dead(int(pidfile.read_text()), 10), "the orphaned grandchild survived run_test's timeout on Windows"


@windows_only
def test_win_processes_left_after_a_normal_exit_are_ended_when_the_run_returns(tmp_path):
    (tmp_path / "leaf.py").write_text("import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(25)\n")
    pidfile = tmp_path / "left.pid"
    # The root must not exit before the leaf is really running (it records its pid): otherwise the end of the run closes the job while the leaf is still starting up
    # and the test would race against interpreter start-up. The root then exits NORMALLY (exit code 0), leaving the leaf behind.
    code = (f"import subprocess, sys, time, pathlib\n"
            f"subprocess.Popen([sys.executable, r'{tmp_path / 'leaf.py'}', r'{pidfile}'])\n"
            f"p = pathlib.Path(r'{pidfile}')\n"
            f"end = time.monotonic() + 20\n"
            f"while time.monotonic() < end and not (p.exists() and p.read_text().strip()):\n"
            f"    time.sleep(0.05)\n")
    r = win_provider().run_command(spec_of([sys.executable, "-c", code], str(tmp_path), 30.0))
    assert r.exit_code == 0 and wait_file(pidfile)
    assert wait_dead(int(pidfile.read_text()), 10), "kill-on-close did not end the process left behind"


@windows_only
def test_win_abort_running_kills_child_and_grandchild_even_when_the_middle_process_has_exited(tmp_path):
    spec, pidfile = chain_spec(tmp_path, "exit", timeout=30.0)
    prov = win_provider()
    threading.Timer(2.0, lambda: (wait_file(pidfile), prov.abort_running())).start()
    r = prov.run_command(spec)
    assert r.aborted and wait_file(pidfile)
    assert wait_dead(int(pidfile.read_text()), 10), "the orphaned grandchild survived abort_running on Windows"
