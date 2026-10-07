"""Structured coding-agent errors. Messages never contain file contents, secrets or command output."""
from __future__ import annotations

from enum import Enum
from typing import Any

from jarvis.errors import JarvisError


class CodingErrorCode(str, Enum):
    DISABLED = "disabled"
    NOT_STARTED = "not_started"                  # no coding session is running
    ALREADY_STARTED = "already_started"
    SESSION_MISMATCH = "session_mismatch"        # the call names another (older) session
    SESSION_ENDED = "session_ended"              # the session was stopped / failed
    WORKSPACE_DENIED = "workspace_denied"        # not inside a configured workspace root
    WORKSPACE_CHANGED = "workspace_changed"      # the workspace directory vanished or was swapped
    PATH_DENIED = "path_denied"                  # outside the workspace / malformed / forbidden spelling
    PROTECTED_PATH = "protected_path"            # .git internals, key files, secret files
    FILE_NOT_FOUND = "file_not_found"
    FILE_EXISTS = "file_exists"
    FILE_CHANGED = "file_changed"                # the file changed between planning and writing
    FILE_TOO_LARGE = "file_too_large"
    BINARY_FILE = "binary_file"
    SECRET_DETECTED = "secret_detected"
    INVALID_INPUT = "invalid_input"
    COMMAND_NOT_ALLOWED = "command_not_allowed"  # not an allow-listed development command
    RUNNER_UNAVAILABLE = "runner_unavailable"    # the test runner / git is not installed or not runnable safely
    BLOCKED = "blocked"                          # RED: refused by the safety rules
    ACTION_BUDGET_EXCEEDED = "action_budget_exceeded"
    RATE_LIMITED = "rate_limited"
    FAILSAFE = "failsafe"                        # halted by the user
    NOT_AUTHORIZED = "not_authorized"            # no matching approval from the permission engine
    TARGET_CHANGED = "target_changed"            # what was approved is not what would be done any more
    LLM_UNAVAILABLE = "llm_unavailable"
    BACKEND_ERROR = "backend_error"


class CodingError(JarvisError):
    """Controlled failure with a machine-readable `code`; never a crash."""

    def __init__(self, code: CodingErrorCode, message: str, **details: Any) -> None:
        super().__init__(f"[{code.value}] {message}")
        self.code, self.message, self.details = code, message, details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, **({"details": self.details} if self.details else {})}
