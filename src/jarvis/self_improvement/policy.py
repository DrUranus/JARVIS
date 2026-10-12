"""Limits and rules of the self-improvement layer. These are HEURISTIC FILTERS on what a change may touch; they grant nothing and are NOT a security
boundary: a change that passes them is still untrusted code. Only process isolation (not implemented, see isolation.py) could make running such code safe.

Targets: an explicit ALLOW-LIST of existing source files (everything else - including every path that cannot be classified - is refused). Content: an AST
review of the complete resulting module (static, nothing is imported or executed) plus an allow-list of imports. Both are code, not configuration."""
from __future__ import annotations

import ast
import json
import re
import unicodedata
from collections import Counter
from typing import Any, Mapping, Sequence

from jarvis.self_repair import policy as RP

SOURCE_ROOT = "src/jarvis/"
BRANCH_PREFIX = "jarvis/improve-"
ID_RE = re.compile(r"^imp-[0-9a-f]{12}\Z")
TEST_ID_RE = re.compile(r"^tests/[A-Za-z0-9_./\-]{1,150}\.py(::[A-Za-z0-9_\[\]\-.:]{1,150})?\Z")

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

# ---- allow-list of files a change may touch (exact, canonical, lower-case spelling; anything else is refused) ------------------------------------
# Deliberately small: feature code without a security role. NOT contained: permissions, tool registry/base, coding/browser/computer controllers, core, agents/
# orchestrator, LLM providers, confirmation/approval, process starters, validation of URLs/paths, config, bootstrap, interface, this package.
ALLOWED_TARGETS = frozenset({
    "src/jarvis/goals/planner.py", "src/jarvis/goals/replanner.py", "src/jarvis/goals/evaluator.py",
    "src/jarvis/self_repair/diagnostics.py", "src/jarvis/self_repair/planner.py",
    "src/jarvis/research/analysis.py", "src/jarvis/research/extract.py",
    "src/jarvis/business/calc.py", "src/jarvis/finance/calc.py", "src/jarvis/memory/ranking.py", "src/jarvis/planning/planner.py"})
# Named explicitly although the allow-list already excludes them: a mistake in ALLOWED_TARGETS must not be able to expose these.
NEVER_TARGETS = ("permissions/", "tools/", "coding/", "browser/", "computer/", "core/", "agents/", "llm/", "interface/", "self_improvement/", "voice/",
                 "redaction.py", "config.py", "bootstrap.py", "errors.py", "logging_setup.py")
_SAFE_PATH = re.compile(r"^[a-z0-9_]+(/[a-z0-9_]+)*\.py\Z")
_NEVER_NAME = re.compile(r"(policy|safety|guard|registry|confirmation|audit|validation|urls|workspace|controller|orchestrator|secret|credential|auth)")

# imports a changed module may ADD (top-level module names). Everything else - os, sys, subprocess, socket, asyncio, pathlib, io, builtins, ... - is refused.
ALLOWED_IMPORTS = frozenset({"__future__", "re", "json", "math", "dataclasses", "typing", "enum", "collections", "itertools", "functools", "datetime",
                             "decimal", "fractions", "statistics", "logging", "abc", "textwrap", "string", "heapq", "bisect", "operator", "numbers", "uuid", "hashlib"})
ALLOWED_JARVIS_IMPORTS_DENIED = ("jarvis.permissions", "jarvis.tools", "jarvis.coding", "jarvis.browser", "jarvis.computer", "jarvis.core", "jarvis.llm",
                                 "jarvis.interface", "jarvis.bootstrap", "jarvis.config", "jarvis.self_improvement", "jarvis.voice", "jarvis.redaction")
FORBIDDEN_NAMES = frozenset({"eval", "exec", "compile", "__import__", "open", "input", "breakpoint", "getattr", "setattr", "delattr", "vars", "globals", "locals",
                             "dir", "memoryview", "__builtins__", "builtins", "__loader__", "__spec__", "help", "exit", "quit", "type", "super_import", "classmethod_import"})
FORBIDDEN_ATTRS = frozenset({"system", "popen", "spawn", "spawnl", "spawnv", "execv", "execl", "execve", "fork", "forkpty", "kill", "killpg", "startfile",
                             "environ", "getenv", "putenv", "read_text", "write_text", "read_bytes", "write_bytes", "unlink", "rmdir", "rmtree", "remove", "rename",
                             "replace_file", "chmod", "chown", "connect", "bind", "listen", "urlopen", "request", "send", "sendall", "Popen", "check_output", "check_call"})
ALLOWED_DUNDER_ATTRS = frozenset({"__name__", "__doc__", "__init__", "__post_init__", "__class_getitem__"})
MAX_SOURCE_BYTES = 400_000


def is_allowed_target(path: object) -> bool:
    return refuse_target(path) is None


def refuse_target(path: object) -> str | None:
    """Why a file may NOT be changed (None = acceptable); every refusal says that a manual review is required. See _refuse_target for the rules."""
    why = _refuse_target(path)
    return None if why is None else (why if "manual review" in why else f"{why} (manual review required)")


def _refuse_target(path: object) -> str | None:
    """Why a file may NOT be changed (None = acceptable). The path must be EXACTLY one of ALLOWED_TARGETS: other spellings (case, backslashes, `.`/`..`
    components, 8.3 short names, alternate data streams, Unicode look-alikes) are not an allowed target and are refused."""
    if not isinstance(path, str) or not path or len(path) > 200:
        return "not a plain relative path"
    if any(ord(c) < 32 or ord(c) > 126 for c in path) or "\\" in path or path.startswith(("/", "~")) or ":" in path:
        return "unusual path spelling (control/non-ASCII characters, backslash, drive or stream syntax): not an allowed target"
    parts = path.split("/")
    if any(p in ("", ".", "..") or p.endswith((" ", ".")) or "~" in p for p in parts):
        return "path traversal or short-name spelling: not an allowed target"
    if path != path.casefold() or not _SAFE_PATH.match(path):
        return "non-canonical path spelling (only exact lower-case canonical paths are classified)"
    rel = path[len(SOURCE_ROOT):] if path.startswith(SOURCE_ROOT) else ""
    if not rel or any(rel.startswith(n) or rel == n for n in NEVER_TARGETS) or _NEVER_NAME.search(rel):
        return "security boundary or unclassified area: manual review required"
    if path not in ALLOWED_TARGETS:
        return "not in the allow-list of changeable files: manual review required"
    return None


def is_security_refusal(reason: str | None) -> bool:
    return bool(reason) and "manual review" in reason


# ---- static review of a complete module (AST; nothing is executed or imported) ---------------------------------------------------------------------
def _walk_findings(tree: ast.AST) -> list[str]:
    out: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                top = a.name.split(".")[0]
                if top == "jarvis":
                    if a.name.startswith(ALLOWED_JARVIS_IMPORTS_DENIED):
                        out.append(f"import of security-relevant package {a.name}")
                elif top not in ALLOWED_IMPORTS:
                    out.append(f"import of non-allow-listed module {top}")
        elif isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            top = mod.split(".")[0]
            if n.level:
                out.append("relative import")
            elif top == "jarvis":
                if mod.startswith(ALLOWED_JARVIS_IMPORTS_DENIED) or mod == "jarvis":
                    out.append(f"import from security-relevant package {mod or 'jarvis'}")
            elif top not in ALLOWED_IMPORTS:
                out.append(f"import from non-allow-listed module {top}")
        elif isinstance(n, ast.Name):
            if n.id in FORBIDDEN_NAMES:
                out.append(f"use of forbidden name {n.id}")
            elif n.id.startswith("__") and n.id.endswith("__") and n.id not in ALLOWED_DUNDER_ATTRS | {"__file__", "__all__", "__annotations__"}:
                out.append(f"use of dunder name {n.id}")
        elif isinstance(n, ast.Attribute):
            if n.attr in FORBIDDEN_ATTRS:
                out.append(f"use of forbidden attribute .{n.attr}")
            elif n.attr.startswith("__") and n.attr.endswith("__") and n.attr not in ALLOWED_DUNDER_ATTRS:
                out.append(f"use of dunder attribute .{n.attr}")
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.append("global/nonlocal statement")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and ("\x00" in n.value):
            out.append("NUL character in a string")
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Name) and d.id in FORBIDDEN_NAMES:
                    out.append(f"forbidden decorator {d.id}")
    return out


def static_findings(source: str) -> list[str]:
    """Findings (sorted, with multiplicity) for a complete module. `ast.parse` NFKC-normalises identifiers, so look-alike spellings are seen as the real name;
    comments and the contents of strings cannot hide code. An unparsable module yields a finding (and is therefore refused)."""
    if not isinstance(source, str) or len(source.encode("utf-8", "replace")) > MAX_SOURCE_BYTES:
        return ["module missing or too large"]
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        return [f"module does not parse ({type(exc).__name__})"]
    return sorted(_walk_findings(tree))


def new_findings(old_source: str, new_source: str) -> list[str]:
    """Findings that the change ADDS: the multiset difference new - old (an existing module may already contain a construct; the change must not add more)."""
    old, new = Counter(static_findings(old_source)), Counter(static_findings(new_source))
    return sorted((new - old).elements())


# ---- edits ---------------------------------------------------------------------------------------------------------------------------------------
def validate_edits(edits: Any, max_edits: int) -> tuple[dict[str, str], ...]:
    """Strict check of a list of {"path","old_text","new_text"}. Raises ValueError with a short reason."""
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


def check_targets(edits: Sequence[Mapping[str, str]]) -> str | None:
    for e in edits:
        why = refuse_target(e["path"])
        if why:
            return f"{P_clip(e['path'])}: {why}"
    return None


def P_clip(text: str) -> str:
    return clip(ascii(text), 80)


_BIDI = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\u2028\u2029\u0085]")


def clip(text: Any, limit: int) -> str:
    return RP.clip(text, limit)


def clean_text(text: Any, limit: int) -> str:
    """Plain text for storage: control characters (except newline/tab), bidi/zero-width controls removed, bounded."""
    s = text if isinstance(text, str) else str(text)
    s = _BIDI.sub("", "".join(c for c in s if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127)))
    return clip(s.strip(), limit)


def one_line(text: Any, limit: int = 160) -> str:
    """UNTRUSTED text for a prompt or terminal: a single, quoted, ASCII-escaped line. It cannot start a new line, cannot contain control or bidi
    characters and is always shown inside quotes, so it cannot pose as a status line written by JARVIS."""
    s = text if isinstance(text, str) else str(text)
    s = unicodedata.normalize("NFKC", s)
    s = _BIDI.sub("", s)
    s = " ".join(s.split())
    s = "".join(c for c in s if c.isprintable())
    return json.dumps(clip(s, limit), ensure_ascii=True)
