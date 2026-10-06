"""Secret detection for memory. Memory never stores API keys, passwords, tokens or similar.

The detection logic lives in the neutral `jarvis.redaction` module (shared with the permission system);
this subclass only adds the memory-specific rejection error.
"""
from __future__ import annotations

from jarvis.errors import SecretRejectedError
from jarvis.redaction import MIN_KNOWN_SECRET_LENGTH, PATTERNS, SecretDetector

__all__ = ["SecretGuard", "PATTERNS", "MIN_KNOWN_SECRET_LENGTH"]


class SecretGuard(SecretDetector):
    def check(self, *texts: str | None) -> None:
        for text in texts:
            if text and (kind := self.find(text)):
                raise SecretRejectedError(
                    f"refusing to store content that looks like a secret ({kind}); "
                    "memories must never contain passwords, API keys or tokens")
