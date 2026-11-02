"""Structured file-tool errors. Messages never contain file contents or secrets."""
from __future__ import annotations

from typing import Any

from jarvis.errors import JarvisError


class FilesError(JarvisError):
    """Controlled failure with a machine-readable `code` (e.g. outside_roots, symlink_rejected, protected_path, file_changed, file_exists,
    no_delete, failsafe, action_budget_exceeded, rate_limited, not_authorized, invalid_input); never a crash."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"[{code}] {message}")
        self.code, self.message, self.details = code, message, details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **({"details": self.details} if self.details else {})}
