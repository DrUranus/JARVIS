"""Execution of proposed code is DISABLED in this version, and there is no switch that enables it.

A git worktree is not a sandbox. A process that runs proposed code (importing a changed module, running pytest on it) has the privileges of the JARVIS user:
it can read the home directory, credentials and every other file the user can read, write anywhere (including `.git/hooks` of the main repository, which a
worktree's `.git` file points to), open network connections and start detached child processes that survive a timeout. A scrubbed environment only hides
environment variables; a regex or AST review of the code is a filter, not a proof. So proposed code is neither imported nor executed - not before, not during
and not after an approval.

What a future sandbox would have to PROVE before `ExecutionGuard` may allow anything (every property, on every supported platform, by a test that runs there):
  - a separate unprivileged user or equivalent isolation (container, namespace, AppContainer / job object with restricted token)
  - no access to host credentials, the home directory or any file outside its own read-only copy of the exported commit
  - no network (unless explicitly and narrowly granted)
  - no connection to the main repository or its hooks (the copy has no `.git`)
  - bounded CPU time, memory, wall-clock time, output and number of processes
  - reliable termination of ALL descendant processes, including detached ones
  - platform-specific tests for Linux and Windows
No such backend exists. `ExecutionGuard` therefore never unlocks in production code: the factory does not pass an attestation, configuration cannot supply one and
the settings reject `allow_prepare`, `allow_activation` and `repo_path`."""
from __future__ import annotations

import sys
from dataclasses import dataclass, fields

from jarvis.self_improvement.errors import ImprovementError

REQUIRED_PROPERTIES = ("unprivileged_user", "no_host_credentials", "no_network", "no_main_repository", "resource_limits", "kills_all_descendants", "platform_tests_passed")


class ExecutionDisabled(ImprovementError):
    """Running, testing, preparing or activating proposed code is switched off because effective isolation is not proven."""


@dataclass(frozen=True)
class IsolationAttestation:
    """A claim that a sandbox backend has all required properties on `platform`. Only a backend that ships WITH its own passing platform tests may create
    one; nothing in this package does."""
    backend: str
    platform: str
    unprivileged_user: bool = False
    no_host_credentials: bool = False
    no_network: bool = False
    no_main_repository: bool = False
    resource_limits: bool = False
    kills_all_descendants: bool = False
    platform_tests_passed: bool = False

    def missing(self) -> list[str]:
        return [f.name for f in fields(self) if f.name in REQUIRED_PROPERTIES and getattr(self, f.name) is not True]


class ExecutionGuard:
    """Default and only production state: locked."""

    def __init__(self, attestation: IsolationAttestation | None = None) -> None:
        self._att = attestation

    @classmethod
    def locked(cls) -> "ExecutionGuard":
        return cls(None)

    @property
    def allowed(self) -> bool:
        a = self._att
        if a is None or a.missing():
            return False
        current = "windows" if sys.platform.startswith("win") else "linux" if sys.platform.startswith("linux") else sys.platform
        return a.platform == current

    def reason(self) -> str:
        if self._att is None:
            return "no sandbox backend exists; a worktree is not a sandbox"
        miss = self._att.missing()
        return f"isolation not proven (missing: {', '.join(miss)})" if miss else "attestation is for another platform"

    def require(self, what: str) -> None:
        if not self.allowed:
            raise ExecutionDisabled(f"{what} is disabled: proposed code is never prepared, imported, tested or activated without proven isolation ({self.reason()})")
