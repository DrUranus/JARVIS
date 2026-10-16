"""Windows Job Object containment for the processes SubprocessRunner starts.

`taskkill /T` follows PARENT process ids, so a grandchild whose parent has already exited is out of its reach. A Job Object does not have that gap: every process
the job contains - and every process those start - belongs to it, and closing the job terminates all of them (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE), even if our own
termination call fails or JARVIS itself dies.

Honest limits (not hidden):
* A Job Object is containment, not a sandbox: it does not restrict files, network or privileges (see isolation.py).
* The runner starts the process SUSPENDED (CREATE_SUSPENDED), assigns it to the job and only then resumes it (`resume`), so no child can exist before the assignment.
  What stays open: if JARVIS itself dies between the start and the assignment, a suspended process remains (it is in no job yet); and a process started WITHOUT the
  suspended start (a caller that injects only a job factory) still has the old window between Popen and the assignment.
* Assignment can fail (for example when JARVIS itself runs inside a job that forbids nesting or breakaway). Then `attach` returns None, a warning is logged and the
  runner falls back to `taskkill /T`, which is NOT a guarantee for orphaned grandchildren.
* Nothing here could be executed where it was written (Linux). The Win32 layer is exercised only by the Windows tests; the error handling around it is tested with a
  fake API on every platform.
"""
from __future__ import annotations

import functools
import logging
import sys
from typing import Protocol

log = logging.getLogger("jarvis.self_improvement")

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
PROCESS_SUSPEND_RESUME = 0x0800
CREATE_SUSPENDED = 0x00000004          # CreateProcess flag: the primary thread starts suspended, nothing of the program has run yet


@functools.lru_cache(maxsize=1)
def structs() -> "tuple[type, type]":
    """(JOBOBJECT_BASIC_LIMIT_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION) as ctypes structures. Built on first use: ctypes is imported lazily, never at module level
    (an architecture rule of this code base; the layout uses fixed-width fields so that its size can be checked on any 64-bit platform)."""
    import ctypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                   "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BasicLimits(ctypes.Structure):                      # DWORD = uint32, SIZE_T / ULONG_PTR = size_t, LARGE_INTEGER = int64
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    return BasicLimits, ExtendedLimits


class JobApi(Protocol):
    """The Win32 calls we need. The real implementation is Win32Api; tests pass a fake."""

    def create_job(self) -> int: ...
    def set_kill_on_close(self, job: int) -> None: ...
    def open_process(self, pid: int) -> int: ...
    def assign(self, job: int, process: int) -> None: ...
    def terminate(self, job: int, exit_code: int) -> None: ...
    def close(self, handle: int) -> None: ...
    def resume(self, pid: int) -> None: ...


class Win32Api:
    def __init__(self) -> None:
        if not sys.platform.startswith("win"):
            raise OSError("Job Objects exist only on Windows")
        import ctypes
        self._ct = ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)          # type: ignore[attr-defined]
        H, U32, BOOL = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
        k.CreateJobObjectW.argtypes, k.CreateJobObjectW.restype = [ctypes.c_void_p, ctypes.c_wchar_p], H
        k.SetInformationJobObject.argtypes, k.SetInformationJobObject.restype = [H, ctypes.c_int, ctypes.c_void_p, U32], BOOL
        k.OpenProcess.argtypes, k.OpenProcess.restype = [U32, BOOL, U32], H
        k.AssignProcessToJobObject.argtypes, k.AssignProcessToJobObject.restype = [H, H], BOOL
        k.TerminateJobObject.argtypes, k.TerminateJobObject.restype = [H, ctypes.c_uint], BOOL
        k.CloseHandle.argtypes, k.CloseHandle.restype = [H], BOOL
        self._k = k

    def _fail(self) -> OSError:
        return self._ct.WinError(self._ct.get_last_error())         # type: ignore[attr-defined]

    def create_job(self) -> int:
        h = self._k.CreateJobObjectW(None, None)
        if not h:
            raise self._fail()
        return h

    def set_kill_on_close(self, job: int) -> None:
        info = structs()[1]()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._k.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, self._ct.byref(info), self._ct.sizeof(info)):
            raise self._fail()

    def open_process(self, pid: int) -> int:
        h = self._k.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not h:
            raise self._fail()
        return h

    def assign(self, job: int, process: int) -> None:
        if not self._k.AssignProcessToJobObject(job, process):
            raise self._fail()

    def terminate(self, job: int, exit_code: int) -> None:
        if not self._k.TerminateJobObject(job, exit_code):
            raise self._fail()

    def close(self, handle: int) -> None:
        self._k.CloseHandle(handle)

    def resume(self, pid: int) -> None:
        """Resume a process that was started with CREATE_SUSPENDED. NtResumeProcess (ntdll) is looked up only here, so a missing export can not affect the job calls."""
        h = self._k.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not h:
            raise self._fail()
        try:
            try:
                fn = self._ct.WinDLL("ntdll").NtResumeProcess            # type: ignore[attr-defined]
            except (OSError, AttributeError) as exc:
                raise OSError(f"NtResumeProcess is not available ({exc})") from None
            fn.argtypes, fn.restype = [self._ct.c_void_p], self._ct.c_long
            status = fn(h)
            if status < 0:                                               # NTSTATUS: negative = error
                raise OSError(f"NtResumeProcess failed (NTSTATUS 0x{status & 0xFFFFFFFF:08X})")
        finally:
            self._k.CloseHandle(h)


class JobObject:
    """A job that contains one started process and everything it starts. `close()` ends the whole tree (kill-on-close)."""

    def __init__(self, api: JobApi, handle: int) -> None:
        self._api, self._handle = api, handle

    def terminate(self, exit_code: int = 1) -> bool:
        """Terminate every process in the job. False when the OS refused (the caller then falls back and closes the job, which kills the tree as well)."""
        if self._handle is None:
            return False
        try:
            self._api.terminate(self._handle, exit_code)
            return True
        except OSError as exc:
            log.warning("TerminateJobObject failed (%s)", exc)
            return False

    def close(self) -> None:
        """Release the handle. With kill-on-close this also terminates anything still running in the job. Safe to call twice."""
        h, self._handle = self._handle, None
        if h is not None:
            try:
                self._api.close(h)
            except OSError as exc:
                log.warning("closing the job handle failed (%s)", exc)


def attach(pid: int, api: JobApi | None = None) -> JobObject | None:
    """Put the process `pid` into a new kill-on-close job. Returns None (and logs why) when that is not possible; the caller must then treat containment as
    ABSENT. Never raises."""
    try:
        api = api or Win32Api()
    except OSError as exc:
        log.warning("process containment unavailable: %s", exc)
        return None
    try:
        job = api.create_job()
    except OSError as exc:
        log.warning("process containment unavailable: CreateJobObject failed (%s)", exc)
        return None
    try:
        api.set_kill_on_close(job)
        proc = api.open_process(pid)
        try:
            api.assign(job, proc)
        finally:
            api.close(proc)
    except OSError as exc:
        log.warning("process containment unavailable: %s", exc)
        try:
            api.close(job)
        except OSError:
            pass
        return None
    return JobObject(api, job)


def resume(pid: int, api: JobApi | None = None) -> None:
    """Let a process that was started suspended run. Raises OSError when that is not possible - the caller must then end the process (it would stay frozen)."""
    (api or Win32Api()).resume(pid)
