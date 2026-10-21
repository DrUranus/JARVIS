"""Fake coding provider for tests and hardware-free development: an in-memory file system and scripted command results.

No disk, no process. It enforces the same primitive rules as the local provider (exclusive create, hash-guarded replace,
no shells, argv tuples only) so tests cannot pass because the fake was more lenient than reality. File CONTENTS are
kept here (tests assert on them) - which is why this class is never a production provider.
"""
from __future__ import annotations

import hashlib
import os
from typing import Callable

from jarvis.coding.backend import CodingProvider
from jarvis.coding.errors import CodingError, CodingErrorCode as EC
from jarvis.coding.models import CommandResult, CommandSpec, DirEntry, FileStat, TestResult
from jarvis.coding.policy import check_command_shape


class FakeCodingProvider(CodingProvider):
    name = "fake"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.symlinks: dict[str, str] = {}     # link path -> target path
        self.calls: list[tuple[str, tuple]] = []
        self.commands: list[CommandSpec] = []
        self.executables: dict[str, str] = {"git": "/usr/bin/git", "npm": "/usr/bin/npm"}
        self.command_handler: Callable[[CommandSpec], CommandResult] | None = None
        self._faults: dict[str, BaseException] = {}
        self.writes_blocked_by_race: dict[str, bytes] = {}  # path -> content that "someone else" writes just before our write

    # -- helpers for tests -------------------------------------------------------------------------------------------------------
    def put(self, path: str, content: str | bytes) -> None:
        path = os.path.abspath(path)
        self.files[path] = content.encode() if isinstance(content, str) else content
        parent = os.path.dirname(path)
        while parent and parent not in self.dirs:
            self.dirs.add(parent)
            nxt = os.path.dirname(parent)
            if nxt == parent:
                break
            parent = nxt

    def text(self, path: str) -> str:
        return self.files[os.path.abspath(path)].decode()

    def fail_next(self, method: str, error: BaseException) -> None:
        self._faults[method] = error

    def calls_named(self, prefix: str) -> list[tuple[str, tuple]]:
        return [c for c in self.calls if c[0].startswith(prefix)]

    def _hit(self, name: str, *args: object) -> None:
        self.calls.append((name, args))
        fault = self._faults.pop(name, None)
        if fault is not None:
            raise fault

    # -- CodingProvider ------------------------------------------------------------------------------------------------------------
    def realpath(self, path: str) -> str:
        p = os.path.abspath(path)
        for _ in range(20):
            parts = p.split(os.sep)
            for i in range(1, len(parts) + 1):
                prefix = os.sep.join(parts[:i]) or os.sep
                if prefix in self.symlinks:
                    p = os.path.abspath(os.path.join(self.symlinks[prefix], *parts[i:]))
                    break
            else:
                return p
        return p

    def stat(self, path: str) -> FileStat | None:
        self._hit("stat", path)
        p = os.path.abspath(path)
        if p in self.symlinks:
            return FileStat(0, False, False, True)
        real = self.realpath(os.path.dirname(p)) if os.path.dirname(p) != p else p
        p = os.path.join(real, os.path.basename(p))
        if p in self.files:
            return FileStat(len(self.files[p]), True, False)
        if p in self.dirs:
            return FileStat(0, False, True)
        return None

    def scandir(self, path: str) -> list[DirEntry]:
        self._hit("scandir", path)
        base = self.realpath(path)
        out: dict[str, DirEntry] = {}
        for f, data in self.files.items():
            if os.path.dirname(f) == base:
                out[os.path.basename(f)] = DirEntry(os.path.basename(f), True, False, False, len(data))
        for d in self.dirs:
            if os.path.dirname(d) == base and d != base:
                out[os.path.basename(d)] = DirEntry(os.path.basename(d), False, True)
        for link in self.symlinks:
            if os.path.dirname(link) == base:
                out[os.path.basename(link)] = DirEntry(os.path.basename(link), False, False, True)
        return sorted(out.values(), key=lambda e: e.name.casefold())

    def read_file(self, path: str, max_bytes: int) -> bytes:
        self._hit("read_file", path)
        p = self.realpath(path)
        if p not in self.files:
            raise CodingError(EC.FILE_NOT_FOUND, "the file does not exist")
        return self.files[p][:max_bytes]

    def write_file(self, path: str, data: bytes, expect_sha256: str | None) -> None:
        self._hit("write_file", path)
        p = os.path.abspath(path)
        if p in self.symlinks:
            raise CodingError(EC.PATH_DENIED, "refusing to write through a symbolic link")
        if p in self.writes_blocked_by_race:  # simulate another process changing the file right before the write
            self.files[p] = self.writes_blocked_by_race.pop(p)
        if expect_sha256 is None:
            if p in self.files:
                raise CodingError(EC.FILE_EXISTS, "the file already exists")
            self.put(p, data)
            return
        if p not in self.files:
            raise CodingError(EC.FILE_NOT_FOUND, "the file no longer exists")
        if hashlib.sha256(self.files[p]).hexdigest() != expect_sha256:
            raise CodingError(EC.FILE_CHANGED, "the file changed since it was read; nothing was written")
        self.files[p] = data

    def delete_file(self, path: str, expect_sha256: str | None) -> None:
        self._hit("delete_file", path)
        p = os.path.abspath(path)
        if p not in self.files:
            raise CodingError(EC.FILE_NOT_FOUND, "the file does not exist")
        if expect_sha256 is not None and hashlib.sha256(self.files[p]).hexdigest() != expect_sha256:
            raise CodingError(EC.FILE_CHANGED, "the file changed since it was read; nothing was deleted")
        del self.files[p]

    def abort_running(self) -> None:
        self.calls.append(("abort_running", ()))

    def find_executable(self, name: str) -> str | None:
        return self.executables.get(name)

    def run_command(self, spec: CommandSpec) -> CommandResult:
        self._hit("run_command", spec.argv)
        check_command_shape(spec.argv)
        self.commands.append(spec)
        if self.command_handler:
            return self.command_handler(spec)
        return CommandResult(0, "1 passed in 0.01s\n", "", False, False, 0.01)

    def run_test(self, spec: CommandSpec) -> TestResult:
        r = self.run_command(spec)
        return TestResult(spec.argv, r.exit_code, r.exit_code == 0 and not r.timed_out and not r.truncated and not r.aborted, r.timed_out, r.stdout,
                          r.stderr, r.duration, r.truncated, aborted=r.aborted)
