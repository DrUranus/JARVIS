"""Plain data of the coding agent. No library types, no behaviour that touches the system."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    ACTIVE = "active"
    HALTED = "halted"
    COMPLETED = "completed"
    FAILED = "failed"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Workspace:
    id: str
    root: str                  # the real (symlink-resolved) directory every operation is confined to
    project_type: str          # python | javascript | typescript | unknown
    created_at: datetime
    is_jarvis: bool = False    # the JARVIS repository itself: stricter rules (the basis for later self-improvement)


@dataclass(frozen=True)
class ProjectInfo:
    root: str
    language: str              # Python | JavaScript | TypeScript | unknown
    framework: str = ""
    test_framework: str = ""
    important_files: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    is_jarvis: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"root": self.root, "language": self.language, "languages": list(self.languages), "framework": self.framework,
                "test_framework": self.test_framework, "important_files": list(self.important_files), "is_jarvis_workspace": self.is_jarvis}


@dataclass(frozen=True)
class FileStat:
    size: int
    is_file: bool
    is_dir: bool
    is_symlink: bool = False
    mtime: float = 0.0


@dataclass(frozen=True)
class DirEntry:
    name: str
    is_file: bool
    is_dir: bool
    is_symlink: bool = False
    size: int = 0


@dataclass(frozen=True)
class SearchHit:
    path: str
    line: int
    text: str = field(repr=False)


@dataclass(frozen=True)
class FileChange:
    """One file touched in a session. Contents are never kept - only hashes and counts."""
    path: str                  # workspace-relative, '/'-separated
    operation: str             # create | modify | delete
    old_hash: str | None
    new_hash: str | None
    added_lines: int = 0
    removed_lines: int = 0

    def summary(self) -> str:
        return f"{self.path}: {self.operation} +{self.added_lines}/-{self.removed_lines}"


@dataclass(frozen=True)
class CommandSpec:
    """A structured command: a list of arguments, never a string for a shell. argv[0] is an absolute program path."""
    argv: tuple[str, ...]
    cwd: str
    timeout: float
    max_output_bytes: int
    env_profile: str = "test"  # test | git


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    stdout: str = field(repr=False, default="")
    stderr: str = field(repr=False, default="")
    timed_out: bool = False
    truncated: bool = False
    duration: float = 0.0
    aborted: bool = False      # stopped by the user's halt while it was running


@dataclass(frozen=True)
class TestResult:
    __test__ = False  # not a pytest test class

    command: tuple[str, ...]
    exit_code: int | None
    passed: bool
    timed_out: bool
    stdout: str = field(repr=False, default="")
    stderr: str = field(repr=False, default="")
    duration: float = 0.0
    truncated: bool = False
    summary: str = ""
    failures: tuple[str, ...] = ()
    aborted: bool = False

    def to_dict(self, command_label: str = "") -> dict[str, Any]:
        return {"command": command_label or " ".join(self.command), "exit_code": self.exit_code, "passed": self.passed,
                "timed_out": self.timed_out, "aborted": self.aborted, "duration": round(self.duration, 2), "summary": self.summary,
                "failures": list(self.failures), "output_truncated": self.truncated, "stdout": self.stdout, "stderr": self.stderr}
