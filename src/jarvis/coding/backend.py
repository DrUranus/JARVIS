"""Provider interface of the coding agent. A provider performs exactly the primitive operation it is asked to, on
absolute paths the controller already validated. It decides nothing about permissions, workspaces or secrets: that is
the controller's job (after the permission engine). It never accepts a command *string*."""
from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.coding.models import CommandResult, CommandSpec, DirEntry, FileStat, TestResult


class CodingProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def realpath(self, path: str) -> str:
        """The path with every symlink resolved (works for paths that do not exist yet)."""

    @abstractmethod
    def stat(self, path: str) -> FileStat | None:
        """Information about the path itself (symlinks are NOT followed); None if it does not exist."""

    @abstractmethod
    def scandir(self, path: str) -> list[DirEntry]: ...

    @abstractmethod
    def read_file(self, path: str, max_bytes: int) -> bytes:
        """At most `max_bytes` bytes of a regular file."""

    @abstractmethod
    def write_file(self, path: str, data: bytes, expect_sha256: str | None) -> None:
        """expect_sha256 None: create a NEW file (fails if it exists; parent directories are created).
        expect_sha256 set: replace the file atomically ONLY if its current content has that hash (else FILE_CHANGED)."""

    @abstractmethod
    def delete_file(self, path: str, expect_sha256: str | None) -> None:
        """Delete one regular file (never a directory); if a hash is given, only if the content still matches."""

    @abstractmethod
    def find_executable(self, name: str) -> str | None:
        """Absolute path of a program found on PATH, or None."""

    @abstractmethod
    def run_command(self, spec: CommandSpec) -> CommandResult:
        """Run one structured command without a shell: bounded time, bounded output, scrubbed environment."""

    @abstractmethod
    def run_test(self, spec: CommandSpec) -> TestResult:
        """run_command, reported as a TestResult."""

    def abort_running(self) -> None:
        """Stop a command that is running right now (called by the controller's halt). Providers without processes do nothing."""
