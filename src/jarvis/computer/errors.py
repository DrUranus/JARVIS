"""Structured computer-control errors. Messages never contain typed text, screen content or secrets."""
from __future__ import annotations

from enum import Enum
from typing import Any

from jarvis.errors import ComputerControlError


class ErrorCode(str, Enum):
    DISABLED = "disabled"                        # computer control is off / halted
    BACKEND_UNAVAILABLE = "backend_unavailable"  # library or platform support missing
    NO_DISPLAY = "no_display"
    INVALID_MONITOR = "invalid_monitor"
    INVALID_COORDINATES = "invalid_coordinates"
    INVALID_INPUT = "invalid_input"
    WINDOW_NOT_FOUND = "window_not_found"
    LAUNCH_FAILED = "launch_failed"
    BLOCKED_TARGET = "blocked_target"            # a protected window/application/key combination
    TARGET_CHANGED = "target_changed"            # the screen/window state changed after approval
    NOT_AUTHORIZED = "not_authorized"            # no matching approval from the permission engine
    UNSUPPORTED = "unsupported"
    RATE_LIMITED = "rate_limited"
    FAILSAFE = "failsafe"                        # emergency stop (pointer in a screen corner / halt())
    BACKEND_ERROR = "backend_error"


class ComputerError(ComputerControlError):
    """Controlled failure with a machine-readable `code`; never a crash."""

    def __init__(self, code: ErrorCode, message: str, **details: Any) -> None:
        super().__init__(f"[{code.value}] {message}")
        self.code, self.message, self.details = code, message, details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, **({"details": self.details} if self.details else {})}


class ComputerUnavailableError(ComputerError):
    """The backend cannot be used at all (missing library, no display, wrong platform)."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.BACKEND_UNAVAILABLE, **details: Any) -> None:
        super().__init__(code, message, **details)
