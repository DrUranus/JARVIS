"""Neutral secret detection/redaction shared by Memory and Permissions (neither depends on the other).

Detection is deliberately conservative (it prefers a false alarm over leaking or persisting a credential):
well-known key formats, "password/token/key = value" statements, credentials in URLs, private keys,
long random-looking tokens, and the exact secret values of the running configuration/environment.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, Mapping

REDACTED = "[REDACTED]"

_ASSIGN_KEYS = (r"api[_\- ]?key|apikey|secret(?:[_\- ]?key)?|passwor[dt]|passwd|pwd|passphrase|kennwort|"
                r"token|access[_\- ]?key|private[_\- ]?key|client[_\- ]?secret|authorization|bearer")

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((name, re.compile(rx, re.IGNORECASE if ci else 0)) for name, rx, ci in (
    ("API key", r"\bsk-[A-Za-z0-9_\-]{16,}", False),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{20,}", False),
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", False),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}", False),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{30,}", False),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}", False),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", False),
    ("credentials in URL", r"://[^/\s:@]+:[^/\s@]+@", False),
    ("credential statement",
     rf"(?:{_ASSIGN_KEYS})\s*(?:=|:|\bis\b|\bist\b|\blautet\b|\bare\b)\s*[\"'`]?[^\s\"'`]{{4,}}", True),
    ("long random token", r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[a-z])(?=[A-Za-z0-9_\-]*[A-Z])[A-Za-z0-9_\-]{32,}\b", False),
))

_ENV_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)
_SENSITIVE_KEY = re.compile(r"pass(?:word|wd)?|pwd|secret|token|api[_\-]?key|auth|credential|private[_\- ]?key|bearer|kennwort",
                            re.IGNORECASE)
MIN_KNOWN_SECRET_LENGTH = 8


class SecretDetector:
    def __init__(self, known_secrets: Iterable[str | None] = ()) -> None:
        self._known: set[str] = set()
        for s in known_secrets:
            self.add_known_secret(s)

    def add_known_secret(self, value: str | None) -> None:
        if value and len(value) >= MIN_KNOWN_SECRET_LENGTH:
            self._known.add(value)

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None, extra: Iterable[str | None] = ()):
        """Treat every value of KEY/SECRET/TOKEN/PASSWORD-named environment variables as secret."""
        env = os.environ if env is None else env
        det = cls(extra)
        for name, value in env.items():
            if _ENV_NAME.search(name):
                det.add_known_secret(value)
        return det

    def find(self, text: str) -> str | None:
        """Description of the first secret found (never the secret itself), else None."""
        if any(k in text for k in self._known):
            return "a configured secret value"
        for label, rx in PATTERNS:
            if rx.search(text):
                return label
        return None

    def redact(self, text: Any) -> str:
        """Return `text` (stringified) with every detected secret replaced by [REDACTED]."""
        out = text if isinstance(text, str) else str(text)
        for k in sorted(self._known, key=len, reverse=True):  # longest first: no partial leftovers
            out = out.replace(k, REDACTED)
        for _, rx in PATTERNS:
            out = rx.sub(REDACTED, out)
        return out

    def redact_mapping(self, data: Mapping[Any, Any]) -> dict[str, str]:
        """Stringify a mapping; values under secret-looking keys are always fully redacted."""
        out: dict[str, str] = {}
        for k, v in data.items():
            key = str(k)
            out[self.redact(key)] = REDACTED if _SENSITIVE_KEY.search(key) else self.redact(v)
        return out
