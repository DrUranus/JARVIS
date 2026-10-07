"""Limits and path rules of the self-repair layer. The rules here are a FIRST filter on what a repair plan may name; the real enforcement
stays with the coding controller (workspace confinement, PathGuard) and the permission engine. Nothing here grants anything."""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

from jarvis.agents import policy as AP

RESERVED_KEYS = AP.RESERVED_TOOL_ARGS        # confirmed/force/bypass/skip_permissions ... may appear nowhere in a context or an edit

MAX_ATTEMPTS_DEFAULT = 3
MAX_ATTEMPTS_HARD = 5
MAX_TIMEOUT = 3600.0
MAX_STEP_TIMEOUT = 3600.0
MAX_OBJECTIVE = 2000
MAX_EDITS = 10
MAX_CANDIDATES = 5
MAX_TESTS = 10
MAX_CONTEXT_BYTES = 100_000
MAX_JSON_DEPTH = 8
MAX_FAILED_TESTS = 50
MAX_STDOUT = 3000
MAX_STDERR = 1500
MAX_SUMMARY = 500
CONTEXT_KEYS = frozenset({"tests", "runner", "candidates", "repair"})
EDIT_KEYS = frozenset({"path", "content", "mode", "old_text", "new_text", "expected_sha256"})
RUNNERS = ("pytest", "python -m pytest", "python -m unittest")      # npm test takes no arguments: not usable for targeted tests
FIX_WORDS = re.compile(r"\b(behebe|beheben|repariere|reparieren|korrigiere|fix\w*|repair\w*|heile)\b", re.IGNORECASE)

_SECRET_NAME = re.compile(r"^(\.env.*|.*\.(pem|key|p12|pfx|keystore|jks|kdbx|ppk)|credentials.*|secrets?.*|id_(rsa|dsa|ecdsa|ed25519).*|\.netrc|\.npmrc|\.pypirc|.*\.secret)$")
_PROTECTED_PARTS = frozenset({".git", ".github", ".ssh", ".aws", ".gnupg", "permissions", "security", "node_modules", "__pycache__", ".venv", "venv", ".tox"})
_MANIFEST = re.compile(r"^(pyproject\.toml|setup\.py|setup\.cfg|requirements.*\.txt|pipfile.*|poetry\.lock|package(-lock)?\.json|jarvis.*\.toml|policy.*\.toml)$")
_TEST_NAME = re.compile(r"^(test_.*|.*_test)\.py$|^conftest\.py$")
_TEST_DIRS = frozenset({"tests", "test"})


def split_path(path: object) -> list[str] | None:
    """The components of a relative path, or None when it is not a plain relative path inside the workspace."""
    if not isinstance(path, str) or not path.strip() or len(path) > 300 or "\x00" in path or any(ord(c) < 32 for c in path):
        return None
    p = path.replace("\\", "/")
    if p.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", p) or p.startswith("//"):
        return None
    parts = [c for c in p.split("/") if c not in ("", ".")]
    if not parts or any(c == ".." or c.endswith((" ", ".")) for c in parts):
        return None
    return parts


def norm_path(path: str) -> str:
    parts = split_path(path)
    return "/".join(parts).casefold() if parts else path.replace("\\", "/").casefold()


def refuse_target(path: object) -> str | None:
    """Why a file may NOT be named as repair target (None = acceptable). Secrets, protected places, dependency manifests, tests and
    everything that is not a Python source file are never repaired automatically."""
    parts = split_path(path)
    if parts is None:
        return "not a plain relative path inside the workspace"
    low = [c.casefold() for c in parts]
    name = low[-1]
    if _SECRET_NAME.match(name) or any(_SECRET_NAME.match(c) for c in low):
        return "secret/credential files are never touched"
    if any(c in _PROTECTED_PARTS for c in low):
        return "protected location (git data, security/permission code, environments)"
    if _MANIFEST.match(name):
        return "dependency manifests and configuration are not repaired automatically"
    if _TEST_NAME.match(name) or any(c in _TEST_DIRS for c in low[:-1]):
        return "tests are not changed to make them pass"
    if not name.endswith(".py"):
        return "only existing Python source files are repaired in v1"
    return None


def find_reserved(value: Any, depth: int = 0) -> str | None:
    if depth > MAX_JSON_DEPTH + 2:
        return "nesting"
    if isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in RESERVED_KEYS:
                return k
            hit = find_reserved(v, depth + 1)
            if hit:
                return hit
    elif isinstance(value, (list, tuple)):
        for v in value:
            hit = find_reserved(v, depth + 1)
            if hit:
                return hit
    return None


def check_plain(value: Any, what: str, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"{what} is nested too deeply")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{what} contains a non-finite number")
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            check_plain(v, what, depth + 1)
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"{what} keys must be text")
            check_plain(v, what, depth + 1)
        return
    raise ValueError(f"{what} may only contain plain data (got {type(value).__name__})")


def plain_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: plain_copy(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_copy(v) for v in value]
    return value


def clip(text: Any, limit: int) -> str:
    s = text if isinstance(text, str) else str(text)
    return s if len(s) <= limit else s[: max(0, limit - 1)] + "…"


def tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…" + text[-(limit - 1):]


def json_size(value: Any) -> int:
    try:
        return len(json.dumps(value))
    except (TypeError, ValueError):
        return MAX_CONTEXT_BYTES + 1
