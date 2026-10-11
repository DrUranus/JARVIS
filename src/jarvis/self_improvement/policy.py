"""Limits and rules of the self-improvement layer. This is a FIRST filter on what a change may touch; it grants nothing and it is
not an authority on permissions. The rules are code, not configuration: no setting and no model reply can relax them.

A change may only replace text inside EXISTING Python source files below src/jarvis/. Security boundaries (permissions, policies, secrets handling,
the approval mechanism itself, configuration and wiring) can never be changed by this layer: such a change is BLOCKED and needs a manual review."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from jarvis.self_repair import policy as RP

SOURCE_ROOT = "src/jarvis/"
BRANCH_PREFIX = "jarvis/improve-"
ID_RE = re.compile(r"^imp-[0-9a-f]{12}$")
TEST_ID_RE = re.compile(r"^tests/[A-Za-z0-9_./\-]{1,150}\.py(::[A-Za-z0-9_\[\]\-.:]{1,150})?$")

MAX_TITLE = 160
MAX_TEXT = 1200
MAX_EVIDENCE = 8
MAX_LIST = 10
MAX_FILES = 10
MAX_TESTS = 10
MAX_EDITS_HARD = 10
MAX_EDIT_TEXT = 20_000
MAX_FILE_BYTES = 400_000
MAX_DIFF_BYTES_HARD = 500_000
MAX_REPLY_CHARS = 30_000
MAX_HISTORY = 60
MAX_OUTPUT = 4000
EDIT_KEYS = frozenset({"path", "old_text", "new_text"})

_PROTECTED_DIRS = frozenset({"permissions", "self_improvement"})
_PROTECTED_FILES = frozenset({"redaction.py", "config.py", "bootstrap.py", "logging_setup.py", "errors.py"})
_PROTECTED_NAME = re.compile(r"^(policy.*\.py|safety\.py|guard.*\.py|registry\.py|confirmation.*\.py|audit.*\.py)$")

# Added code that reaches outside the sandbox of a normal source change or that names the security machinery. Matching lines are not "wrong" in
# general - they are simply never accepted automatically.
_FORBIDDEN_ADDED = tuple((label, re.compile(rx)) for label, rx in (
    ("process execution", r"\b(subprocess|os\.system|os\.popen|os\.exec\w*|os\.spawn\w*|pty|multiprocessing)\b"),
    ("dynamic code execution", r"\b(eval|exec|compile|__import__)\s*\(|\bimportlib\b|\bctypes\b|\bpickle\b|\bmarshal\b|\brunpy\b"),
    ("network access", r"\b(socket|urllib|http\.client|ftplib|smtplib|requests|httpx)\b"),
    ("destructive file operation", r"\b(shutil\.rmtree|os\.remove|os\.unlink|os\.rmdir|os\.chmod|os\.chown|Path\([^)]*\)\.(unlink|rmdir))\b"),
    ("security machinery", r"\b(PermissionEngine|ConfirmationProvider|ConfirmationChoice|set_confirmation_provider|trust_caller_confirmation|audit_strict|"
                          r"require_protected_tools|ProtectedTool|PathGuard|SecretDetector|SecretGuard|RESERVED_TOOL_ARGS|session_grant|allowed_roots|denied_paths)\b"),
    ("the improvement layer itself", r"\bjarvis\.self_improvement\b|\bself_improvement\b|ApprovalGate|ImprovementManager"),
))


def refuse_target(path: object) -> str | None:
    """Why a file may NOT be changed (None = acceptable)."""
    parts = RP.split_path(path)
    if parts is None:
        return "not a plain relative path inside the repository"
    rel = "/".join(parts)
    low = [c.casefold() for c in parts]
    if not rel.casefold().startswith(SOURCE_ROOT) or len(parts) < 3:
        return "only existing source files below src/jarvis/ may be changed"
    if low[-1] in _PROTECTED_FILES or _PROTECTED_NAME.match(low[-1]) or any(c in _PROTECTED_DIRS for c in low[:-1]):
        return "security boundary (permissions, policies, secrets, configuration, wiring, approval): manual review required"
    if any(RP._SECRET_NAME.match(c) for c in low):
        return "secret/credential files are never touched (manual review required)"
    if any(c in RP._PROTECTED_PARTS for c in low):
        return "protected location (git data, environments, security code): manual review required"
    if not low[-1].endswith(".py"):
        return "only Python source files may be changed"
    return None


def is_security_refusal(reason: str | None) -> bool:
    return bool(reason) and "manual review" in reason


def scan_added(text: str) -> str | None:
    """Why added code is not accepted automatically (None = nothing found). `text` is code or the '+' lines of a diff."""
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        for label, rx in _FORBIDDEN_ADDED:
            if rx.search(code):
                return f"added code touches {label}: manual review required"
    return None


def validate_edits(edits: Any, max_edits: int) -> tuple[dict[str, str], ...]:
    """Strict check of a list of {"path","old_text","new_text"}. Raises ValueError with a short reason; the caller maps it to BLOCKED or FAILED."""
    if not isinstance(edits, Sequence) or isinstance(edits, (str, bytes)) or not edits:
        raise ValueError("edits must be a non-empty list")
    if len(edits) > min(max_edits, MAX_EDITS_HARD):
        raise ValueError(f"at most {min(max_edits, MAX_EDITS_HARD)} edits")
    out: list[dict[str, str]] = []
    for e in edits:
        if not isinstance(e, Mapping) or set(e) != EDIT_KEYS:
            raise ValueError("each edit needs exactly the keys path, old_text, new_text")
        hit = RP.find_reserved(e)
        if hit:
            raise ValueError(f"reserved key {hit!r}")
        if not all(isinstance(e[k], str) for k in EDIT_KEYS):
            raise ValueError("edit values must be text")
        if not e["old_text"] or len(e["old_text"]) > MAX_EDIT_TEXT or len(e["new_text"]) > MAX_EDIT_TEXT or e["old_text"] == e["new_text"]:
            raise ValueError("old_text must be non-empty, differ from new_text and stay within the size limit")
        if "\x00" in e["old_text"] + e["new_text"]:
            raise ValueError("binary content")
        out.append({"path": e["path"], "old_text": e["old_text"], "new_text": e["new_text"]})
    return tuple(out)


def check_edits_allowed(edits: Sequence[Mapping[str, str]]) -> str | None:
    """None when every edit may be prepared automatically, else the reason it needs a manual review."""
    for e in edits:
        why = refuse_target(e["path"])
        if why:
            return f"{e['path']}: {why}"
        why = scan_added(e["new_text"])
        if why:
            return f"{e['path']}: {why}"
    return None


def clip(text: Any, limit: int) -> str:
    return RP.clip(text, limit)


def clean_text(text: Any, limit: int) -> str:
    """Plain, single-purpose text: no control characters except newline/tab, bounded."""
    s = text if isinstance(text, str) else str(text)
    s = "".join(c for c in s if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))
    return clip(s.strip(), limit)
