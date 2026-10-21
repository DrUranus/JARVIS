"""Local provider: real files, real processes - and nothing else (no network code, no shell).

It trusts the controller for WHAT may happen but still refuses the obviously dangerous: a command must be an argv list
with an absolute program that is not a shell/script host, it never goes through a command interpreter, it runs with a
scrubbed environment, bounded time and bounded output. Writes are atomic (temp file + replace) and hash-guarded.
"""
from __future__ import annotations

import errno
import hashlib
import os
import shutil
import signal
import stat as statmod
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from jarvis.coding.backend import CodingProvider
from jarvis.coding.errors import CodingError, CodingErrorCode as EC
from jarvis.coding.models import CommandResult, CommandSpec, DirEntry, FileStat, TestResult
from jarvis.coding.policy import check_command_shape

_SECRET_ENV = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH", "COOKIE", "SESSION", "PRIVATE")
_DROP_ENV = {"PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DEBUG_TEMPROOT", "NODE_OPTIONS",
             "NODE_PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "BROWSER", "EDITOR", "VISUAL", "PAGER",
             "GIT_DIR", "GIT_WORK_TREE", "GIT_EXTERNAL_DIFF", "GIT_SSH_COMMAND", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_CONFIG_GLOBAL",
             "GIT_CONFIG_SYSTEM", "GIT_CONFIG_PARAMETERS", "COMSPEC_OVERRIDE", "PROMPT_COMMAND", "BASH_ENV", "ENV", "PYTHONINSPECT"}


def scrubbed_env(profile: str) -> dict[str, str]:
    """The parent environment without secrets and without variables that can inject code or options into a tool."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in _DROP_ENV and not k.upper().startswith("GIT_CONFIG_") and not any(w in k.upper() for w in _SECRET_ENV)}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONNOUSERSITE"] = "1"
    env["NO_COLOR"] = "1"
    env["CI"] = "1"
    if profile == "git":
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ASKPASS": "", "LC_ALL": "C.UTF-8" if sys.platform != "win32" else env.get("LC_ALL", "")})
    return env


def _text(data: bytes) -> str:
    """One captured stream as text with '\\n' line endings. A Windows console program writes '\\r\\n' into a pipe; without this every
    line-anchored result check (unittest's 'OK', pytest's 'FAILED ...') would see a trailing '\\r'. Streams are only decoded and
    normalised here - never merged or moved between stdout and stderr."""
    return data.decode("utf-8", "replace").replace("\r\n", "\n")


class _Capture(threading.Thread):
    """Reads one pipe into a bounded buffer; asks for the process to be stopped when it produces too much."""

    def __init__(self, pipe: Any, limit: int, flood: threading.Event) -> None:
        super().__init__(daemon=True)
        self._pipe, self._limit, self._flood = pipe, limit, flood
        self.data = bytearray()
        self.truncated = False

    def run(self) -> None:
        try:
            while chunk := self._pipe.read(8192):
                room = self._limit - len(self.data)
                if room > 0:
                    self.data += chunk[:room]
                if len(chunk) > room:
                    self.truncated = True
                    self._flood.set()
                    return
        except (OSError, ValueError):
            pass


class LocalProvider(CodingProvider):
    name = "local"

    def __init__(self) -> None:
        self._abort = threading.Event()

    def abort_running(self) -> None:
        self._abort.set()

    # -- files ------------------------------------------------------------------------------------------------------------------
    def realpath(self, path: str) -> str:
        return os.path.realpath(path)

    def stat(self, path: str) -> FileStat | None:
        try:
            st = os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            return None
        mode = st.st_mode
        return FileStat(st.st_size, statmod.S_ISREG(mode), statmod.S_ISDIR(mode), statmod.S_ISLNK(mode), st.st_mtime)

    def scandir(self, path: str) -> list[DirEntry]:
        out: list[DirEntry] = []
        with os.scandir(path) as it:
            for e in it:
                try:
                    link = e.is_symlink()
                    out.append(DirEntry(e.name, e.is_file(follow_symlinks=False), e.is_dir(follow_symlinks=False), link,
                                        e.stat(follow_symlinks=False).st_size if not link else 0))
                except OSError:
                    continue
        return sorted(out, key=lambda d: d.name.casefold())

    def read_file(self, path: str, max_bytes: int) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            raise CodingError(EC.FILE_NOT_FOUND, "the file does not exist") from None
        except OSError as exc:
            raise CodingError(EC.BACKEND_ERROR, f"cannot open the file ({errno.errorcode.get(exc.errno or 0, 'OSError')})") from None
        with os.fdopen(fd, "rb") as f:
            if not statmod.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise CodingError(EC.INVALID_INPUT, "not a regular file")
            return f.read(max_bytes)

    @staticmethod
    def _digest(path: str) -> str | None:
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except FileNotFoundError:
            return None

    def write_file(self, path: str, data: bytes, expect_sha256: str | None) -> None:
        parent = os.path.dirname(path)
        if expect_sha256 is None:  # a NEW file: exclusive, never through a symlink
            os.makedirs(parent, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            try:
                fd = os.open(path, flags, 0o644)
            except FileExistsError:
                raise CodingError(EC.FILE_EXISTS, "the file already exists") from None
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return
        if os.path.islink(path):
            raise CodingError(EC.PATH_DENIED, "refusing to write through a symbolic link")
        current = self._digest(path)
        if current is None:
            raise CodingError(EC.FILE_NOT_FOUND, "the file no longer exists")
        if current != expect_sha256:
            raise CodingError(EC.FILE_CHANGED, "the file changed since it was read; nothing was written")
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=".jarvis-write-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            try:
                shutil.copymode(path, tmp)
            except OSError:
                pass
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def delete_file(self, path: str, expect_sha256: str | None) -> None:
        st = self.stat(path)
        if st is None:
            raise CodingError(EC.FILE_NOT_FOUND, "the file does not exist")
        if not st.is_file or st.is_symlink:
            raise CodingError(EC.INVALID_INPUT, "only regular files are deleted (no directories, no links)")
        if expect_sha256 is not None and self._digest(path) != expect_sha256:
            raise CodingError(EC.FILE_CHANGED, "the file changed since it was read; nothing was deleted")
        os.remove(path)

    def find_executable(self, name: str) -> str | None:
        found = shutil.which(name)
        return os.path.abspath(found) if found else None

    # -- processes -----------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _check_spec(spec: CommandSpec) -> None:
        check_command_shape(spec.argv)
        if not os.path.isfile(spec.argv[0]):
            raise CodingError(EC.COMMAND_NOT_ALLOWED, "the program must be an existing file")
        if not os.path.isdir(spec.cwd):
            raise CodingError(EC.INVALID_INPUT, "the working directory does not exist")

    def run_command(self, spec: CommandSpec) -> CommandResult:
        self._check_spec(spec)
        self._abort.clear()
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        started = time.monotonic()
        try:
            proc = subprocess.Popen(list(spec.argv), cwd=spec.cwd, env=scrubbed_env(spec.env_profile), shell=False,  # noqa: S603
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        except OSError as exc:
            raise CodingError(EC.RUNNER_UNAVAILABLE, f"the program could not be started ({errno.errorcode.get(exc.errno or 0, 'OSError')})") from None
        flood = threading.Event()
        out, err = _Capture(proc.stdout, spec.max_output_bytes, flood), _Capture(proc.stderr, spec.max_output_bytes, flood)
        out.start()
        err.start()
        timed_out = aborted = False
        deadline = started + spec.timeout
        while proc.poll() is None:
            if flood.is_set() or self._abort.is_set() or time.monotonic() >= deadline:
                aborted = self._abort.is_set()
                timed_out = not flood.is_set() and not aborted
                self._terminate(proc)
                break
            time.sleep(0.02)
        proc.wait()
        out.join(2)
        err.join(2)
        return CommandResult(None if (timed_out or aborted) else proc.returncode, _text(out.data), _text(err.data), timed_out,
                             out.truncated or err.truncated, time.monotonic() - started, aborted)

    @staticmethod
    def _terminate(proc: "subprocess.Popen[bytes]") -> None:
        """Stop OUR child (and, where the OS lets us, its process group). Nothing else is ever touched."""
        try:
            if sys.platform != "win32":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (OSError, ProcessLookupError):
            try:
                proc.kill()
            except OSError:
                pass

    def run_test(self, spec: CommandSpec) -> TestResult:
        r = self.run_command(spec)
        passed = r.exit_code == 0 and not r.timed_out and not r.truncated and not r.aborted
        return TestResult(spec.argv, r.exit_code, passed, r.timed_out, r.stdout, r.stderr, r.duration, r.truncated, aborted=r.aborted)
