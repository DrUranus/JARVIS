"""Structured browser errors. Messages never contain typed text, page content, cookies or URLs with secrets."""
from __future__ import annotations

from enum import Enum
from typing import Any

from jarvis.errors import JarvisError


class BrowserErrorCode(str, Enum):
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"            # automation library / browser binary missing
    NOT_STARTED = "not_started"            # no browser session is running
    ALREADY_STARTED = "already_started"
    SESSION_MISMATCH = "session_mismatch"  # the call names another (older) session
    PAGE_NOT_FOUND = "page_not_found"      # unknown or closed page
    ELEMENT_NOT_FOUND = "element_not_found"  # unknown / expired element reference, or it vanished
    STALE_ELEMENT = "stale_element"        # the element is not the one that was approved any more
    TARGET_CHANGED = "target_changed"      # page/url/session changed after approval
    BLOCKED_TARGET = "blocked_target"      # RED: forbidden URL, scheme, field, download type...
    LOGIN_REQUIRED = "login_required"      # a login form: the user must act, JARVIS stops
    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    NOT_AUTHORIZED = "not_authorized"      # no matching approval from the permission engine
    RATE_LIMITED = "rate_limited"
    FAILSAFE = "failsafe"                  # emergency stop / action budget exhausted
    DOWNLOAD_FAILED = "download_failed"
    BACKEND_ERROR = "backend_error"


class BrowserError(JarvisError):
    """Controlled failure with a machine-readable `code`; never a crash."""

    def __init__(self, code: BrowserErrorCode, message: str, **details: Any) -> None:
        super().__init__(f"[{code.value}] {message}")
        self.code, self.message, self.details = code, message, details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, **({"details": self.details} if self.details else {})}


class BrowserUnavailableError(BrowserError):
    """The provider cannot be used at all (library or browser not installed)."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(BrowserErrorCode.UNAVAILABLE, message, **details)
