"""The inter-process file lock of the proposal store (store._FileLock), tested with REAL processes.

Derived from the candidate tests of the Windows review. The tests are platform-neutral on purpose: the same code runs against flock (POSIX) and msvcrt (Windows), so a
green Linux run says nothing about msvcrt - only the Windows run does. Helper scripts are written by the tests; only processes the tests started are terminated, and
every helper ends by itself after a few seconds."""
from __future__ import annotations

import errno
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from jarvis.self_improvement import ImprovementError
from jarvis.self_improvement import store as store_mod
from jarvis.self_improvement.store import _FileLock, _is_contention

SRC = str(Path(store_mod.__file__).resolve().parents[2])
WIN = sys.platform.startswith("win")


def holder(tmp_path: Path, lock: Path, hold: float) -> subprocess.Popen:
    script = tmp_path / "holder.py"
    script.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {SRC!r})
        from pathlib import Path
        from jarvis.self_improvement.store import _FileLock
        with _FileLock(Path(sys.argv[1])):
            print("LOCKED", flush=True)
            time.sleep(float(sys.argv[2]))
    """))
    p = subprocess.Popen([sys.executable, str(script), str(lock), str(hold)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "LOCKED"
    return p


def test_the_lock_is_exclusive_across_real_processes(tmp_path):
    lock = tmp_path / "x.json.lock"
    p = holder(tmp_path, lock, 2.0)
    t = time.monotonic()
    with _FileLock(lock, timeout=20):
        waited = time.monotonic() - t
    p.wait(20)
    assert waited >= 1.5, waited                         # blocked by the OTHER process until it released


def test_two_stores_in_two_processes_never_hold_the_lock_together(tmp_path):
    """Both processes run a critical section that appends 'in'/'out' markers; the log must strictly alternate (no overlap)."""
    log = tmp_path / "log.txt"
    lock = tmp_path / "x.json.lock"
    script = tmp_path / "worker.py"
    script.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {SRC!r})
        from pathlib import Path
        from jarvis.self_improvement.store import _FileLock
        log, lock, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
        for _ in range(15):
            with _FileLock(lock, timeout=60):
                with open(log, "a") as f:
                    f.write(name + ":in\\n")
                time.sleep(0.01)
                with open(log, "a") as f:
                    f.write(name + ":out\\n")
    """))
    procs = [subprocess.Popen([sys.executable, str(script), str(log), str(lock), n], stderr=subprocess.PIPE, text=True) for n in ("a", "b", "c")]
    errs = [p.communicate(timeout=120)[1] for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0], errs
    lines = log.read_text().split()
    assert len(lines) == 90
    for i in range(0, 90, 2):
        who_in, who_out = lines[i].split(":"), lines[i + 1].split(":")
        assert who_in[1] == "in" and who_out[1] == "out" and who_in[0] == who_out[0], lines[i:i + 2]      # in/out pairs of ONE process never interleave


def test_contention_times_out_with_a_clear_error(tmp_path):
    lock = tmp_path / "x.json.lock"
    p = holder(tmp_path, lock, 4.0)
    try:
        t = time.monotonic()
        with pytest.raises(ImprovementError, match="locked by another process"):
            with _FileLock(lock, timeout=0.5):
                pass
        assert time.monotonic() - t < 3
    finally:
        p.wait(20)


def test_the_lock_is_released_when_the_holder_process_is_killed(tmp_path):
    """Windows releases byte-range locks when a process ends, 'depending on available system resources' (LockFile docs): the wait is generous, a failure here means a
    leaked lock (the store would be unusable until timeout every time)."""
    lock = tmp_path / "x.json.lock"
    p = holder(tmp_path, lock, 30.0)
    p.kill()                                             # our own child: TerminateProcess / SIGKILL - no cleanup code runs in it
    p.wait(10)
    t = time.monotonic()
    with _FileLock(lock, timeout=10):
        pass
    assert time.monotonic() - t < 10


def test_the_lock_is_released_after_an_exception_in_the_critical_section(tmp_path):
    lock = tmp_path / "x.json.lock"
    with pytest.raises(RuntimeError):
        with _FileLock(lock):
            raise RuntimeError("boom")
    with _FileLock(lock, timeout=1):
        pass


def test_the_same_process_can_not_take_the_lock_twice_through_two_handles(tmp_path):
    """Why store._read_unlocked exists: the lock is NOT re-entrant across handles (flock: separate open file descriptions; msvcrt: separate handles)."""
    lock = tmp_path / "x.json.lock"
    with _FileLock(lock):
        with pytest.raises(ImprovementError, match="locked by another process"):
            with _FileLock(lock, timeout=0.3):
                pass


# ---- real errors are not disguised as contention ---------------------------------------------------------------------------------------------------
def winerror(code: int) -> OSError:
    e = OSError(errno.EINVAL, "x")
    e.winerror = code                                    # type: ignore[attr-defined]
    return e


@pytest.mark.parametrize("exc", [BlockingIOError(errno.EAGAIN, "again"), PermissionError(errno.EACCES, "locking violation"), OSError(errno.EACCES, "x"),
                                 OSError(errno.EDEADLK, "x"), winerror(5), winerror(32), winerror(33)],
                         ids=["BlockingIOError", "PermissionError", "EACCES", "EDEADLK", "WinError5", "WinError32", "WinError33"])
def test_contention_errors_are_retried(exc):
    assert _is_contention(exc)


@pytest.mark.parametrize("exc", [OSError(errno.EBADF, "bad descriptor"), OSError(errno.ENOLCK, "no locks available"), OSError(errno.EINVAL, "invalid"), OSError(errno.EIO, "io"),
                                 OSError(errno.ENOSPC, "full"), FileNotFoundError(errno.ENOENT, "gone"), winerror(6)],
                         ids=["EBADF", "ENOLCK", "EINVAL", "EIO", "ENOSPC", "ENOENT", "WinError6-invalid-handle"])
def test_other_errors_are_not_contention(exc):
    assert not _is_contention(exc)


@pytest.mark.parametrize("code", [errno.EBADF, errno.ENOLCK, errno.EINVAL])
def test_a_real_locking_error_is_reported_at_once_with_its_cause(tmp_path, monkeypatch, code):
    """Before the fix every OSError was retried until the timeout and then reported as 'locked by another process', hiding the real problem."""
    def broken(*a, **k):
        raise OSError(code, "simulated non-contention failure")
    if WIN:
        import msvcrt
        monkeypatch.setattr(msvcrt, "locking", broken)
    else:
        import fcntl
        monkeypatch.setattr(fcntl, "flock", broken)
    t = time.monotonic()
    with pytest.raises(ImprovementError, match="could not be locked") as exc:
        with _FileLock(tmp_path / "x.lock", timeout=5):
            pass
    assert time.monotonic() - t < 1.0 and isinstance(exc.value.__cause__, OSError) and exc.value.__cause__.errno == code
    assert "locked by another process" not in str(exc.value)
