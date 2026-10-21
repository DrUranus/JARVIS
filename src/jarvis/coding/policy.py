"""What the coding agent may touch and run. Pure functions of names and settings: no file system, no processes.

RED rules here (secret files, `.git` internals, mutating git, executable file types, non-allow-listed commands) have no
configuration switch: settings can only choose among the KNOWN test runners and tighten limits.
"""
from __future__ import annotations

import fnmatch
import posixpath
import re
import sys
import unicodedata
from dataclasses import dataclass

from jarvis.coding.errors import CodingError, CodingErrorCode as EC
from jarvis.config import CODING_TEST_COMMANDS, CodingSettings

SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox", ".nox", "dist", "build", ".mypy_cache",
                       ".pytest_cache", ".ruff_cache", ".idea", ".vscode", ".eggs", "site-packages", ".next", ".cache"})
SECRET_NAMES = frozenset({".env", ".netrc", ".npmrc", ".pypirc", ".git-credentials", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
                          "known_hosts", "authorized_keys", "secrets", "secret", "wallet.dat", "cookies", "login data", "shadow",
                          "htpasswd", ".htpasswd"})
SECRET_PATTERNS = (".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", "*.jks", "*.keystore", "*.ppk", "*.gpg", "*.asc",
                   "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "credentials*", "secrets.*", "secret.*", "*.token", "*.ovpn",
                   "service-account*.json", "*_rsa", "*_ed25519")
SECRET_DIRS = frozenset({".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure"})
EXAMPLE_SUFFIXES = (".example", ".sample", ".template", ".dist")   # `.env.example` documents a layout, it holds no secrets
DEPENDENCY_FILES = frozenset({"pyproject.toml", "setup.py", "setup.cfg", "pipfile", "pipfile.lock", "poetry.lock", "uv.lock", "pdm.lock",
                              "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
                              "requirements.txt"})
BLOCKED_WRITE_EXTENSIONS = frozenset({".exe", ".dll", ".sys", ".msi", ".scr", ".com", ".lnk", ".pif", ".cpl", ".msc", ".reg", ".hta",
                                      ".so", ".dylib", ".apk", ".app", ".dmg", ".pkg", ".jar", ".class", ".pyc", ".pyd", ".bin"})
RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))})
GIT_READ = ("status", "diff", "log")
SHELL_NAMES = frozenset({"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "bash", "bash.exe", "sh", "zsh", "fish",
                         "dash", "ksh", "csh", "tcsh", "wsl", "wsl.exe", "wscript", "wscript.exe", "cscript", "cscript.exe", "mshta",
                         "mshta.exe", "rundll32", "rundll32.exe", "regsvr32", "regsvr32.exe", "env", "start", "sudo", "su", "runas"})
GIT_EXCLUDES = tuple(f":(exclude,glob)**/{p}" for p in (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", "id_rsa*",
                                                         "id_ed25519*", "id_ecdsa*", "credentials*", ".npmrc", ".pypirc", ".netrc"))


def _bad(code: EC, message: str, **details: object) -> CodingError:
    return CodingError(code, message, **details)


@dataclass(frozen=True)
class PathInfo:
    secret: bool = False
    protected: bool = False     # .git internals
    deps: bool = False
    blocked_extension: bool = False


def split_relative(rel: object) -> list[str]:
    """A workspace-relative path as clean components. Rejects every absolute spelling (POSIX, drive, UNC, \\\\?\\ and
    rooted), '..', alternate data streams, device names, control/format characters and trailing dots/spaces - on every
    platform, so the answer never depends on which OS runs the check."""
    if not isinstance(rel, str) or not rel.strip():
        raise _bad(EC.INVALID_INPUT, "path must be a non-empty string")
    if len(rel) > 500 or "\x00" in rel:
        raise _bad(EC.PATH_DENIED, "path too long or contains NUL")
    if any(unicodedata.category(c).startswith("C") for c in rel):
        raise _bad(EC.PATH_DENIED, "path contains control or invisible characters")
    p = rel.replace("\\", "/")
    if p.startswith("/") or p.startswith("~") or re.match(r"^[A-Za-z]:", p):
        raise _bad(EC.PATH_DENIED, "absolute paths are not accepted; use a path relative to the workspace")
    parts: list[str] = []
    for comp in p.split("/"):
        if comp in ("", "."):
            continue
        if comp == "..":
            raise _bad(EC.PATH_DENIED, "'..' is not allowed in a path")
        if ":" in comp:
            raise _bad(EC.PATH_DENIED, "':' is not allowed in a path component (drives, alternate data streams)")
        if comp != comp.rstrip(". ") or comp != comp.strip():
            raise _bad(EC.PATH_DENIED, "path components must not end with a dot or a space")
        if comp.split(".", 1)[0].casefold() in RESERVED:
            raise _bad(EC.PATH_DENIED, "reserved device names are not allowed")
        parts.append(comp)
    if not parts:
        raise _bad(EC.INVALID_INPUT, "path must name something inside the workspace")
    return parts


def classify(parts: list[str]) -> PathInfo:
    low = [c.casefold() for c in parts]
    name = low[-1]
    secret = any(c in SECRET_DIRS for c in low[:-1])
    if not name.endswith(EXAMPLE_SUFFIXES) and (name in SECRET_NAMES or any(fnmatch.fnmatchcase(name, pat) for pat in SECRET_PATTERNS)):
        secret = True
    if name in SECRET_DIRS:
        secret = True
    return PathInfo(secret=secret, protected=".git" in low, deps=name in DEPENDENCY_FILES or fnmatch.fnmatchcase(name, "requirements*.txt"),
                    blocked_extension=posixpath.splitext(name)[1] in BLOCKED_WRITE_EXTENSIONS)


def is_skipped_dir(name: str) -> bool:
    return name.casefold() in SKIP_DIRS or name.casefold() in SECRET_DIRS


# ---- test runners ---------------------------------------------------------------------------------------------------------------
_TB = re.compile(r"^--tb=(auto|long|short|line|native|no)$")
_NUM = re.compile(r"^--(maxfail|durations)=\d{1,4}$")
_EXPR = re.compile(r"^[\w\s().,:\[\]\-*\"'=!+]{1,200}$")
_NODEID = re.compile(r"^[\w.\-/\\ ]+(::[\w\[\]\-.,= +()/]+)*$")
_DOTTED = re.compile(r"^[A-Za-z_][\w.]{0,150}$")
_GLOB = re.compile(r"^[\w*?.\-]{1,100}$")
PYTEST_FLAGS = frozenset({"-q", "-qq", "-v", "-vv", "-x", "--exitfirst", "--lf", "--ff", "-l", "--showlocals", "--strict-markers", "-rf",
                          "-ra", "--no-header", "--co", "--collect-only"})
UNITTEST_FLAGS = frozenset({"-v", "-q", "-f", "-b", "--verbose", "--quiet", "--failfast", "--buffer"})


@dataclass(frozen=True)
class TestCommand:
    __test__ = False

    runner: str             # one of CODING_TEST_COMMANDS
    argv: tuple[str, ...]   # absolute program + validated arguments
    label: str


def _args_list(args: object) -> list[str]:
    if args in (None, ""):
        return []
    items = args.split() if isinstance(args, str) else list(args) if isinstance(args, (list, tuple)) else None
    if items is None or len(items) > 12 or not all(isinstance(a, str) and 0 < len(a) <= 200 for a in items):
        raise _bad(EC.INVALID_INPUT, "args must be a short list of short strings (at most 12)")
    if any(any(ord(c) < 32 or ord(c) == 127 for c in a) for a in items):
        raise _bad(EC.INVALID_INPUT, "arguments must not contain control characters")
    return items


def _relative_selector(value: str) -> str:
    base = value.split("::", 1)[0]
    parts = split_relative(base)  # raises for absolute / '..' / drive / UNC forms
    info = classify(parts)
    if info.secret or info.protected:
        raise _bad(EC.PROTECTED_PATH, "that path is protected")
    return value


def validate_pytest_args(args: list[str]) -> list[str]:
    out: list[str] = []
    it = iter(args)
    for a in it:
        if a in PYTEST_FLAGS or _TB.match(a) or _NUM.match(a):
            out.append(a)
        elif a in ("-k", "-m"):
            v = next(it, None)
            if v is None or not _EXPR.match(v):
                raise _bad(EC.COMMAND_NOT_ALLOWED, f"{a} needs a simple expression")
            out += [a, v]
        elif a.startswith("-"):
            raise _bad(EC.COMMAND_NOT_ALLOWED, f"pytest option {a.split('=')[0]!r} is not allowed (plugins, config files, paths and "
                                               "output redirection are fixed by JARVIS)")
        elif _NODEID.match(a):
            out.append(_relative_selector(a))
        else:
            raise _bad(EC.COMMAND_NOT_ALLOWED, "a test selector must be a workspace-relative path or node id")
    return out


def validate_unittest_args(args: list[str]) -> list[str]:
    out: list[str] = []
    it = iter(args)
    for a in it:
        if a in UNITTEST_FLAGS or a == "discover":
            out.append(a)
        elif a in ("-k", "-p"):
            v = next(it, None)
            if v is None or not _GLOB.match(v):
                raise _bad(EC.COMMAND_NOT_ALLOWED, f"{a} needs a simple pattern")
            out += [a, v]
        elif a in ("-s", "-t"):
            v = next(it, None)
            if v is None:
                raise _bad(EC.COMMAND_NOT_ALLOWED, f"{a} needs a directory")
            split_relative(v)
            out += [a, v]
        elif a.startswith("-"):
            raise _bad(EC.COMMAND_NOT_ALLOWED, f"unittest option {a!r} is not allowed")
        elif _DOTTED.match(a):
            out.append(a)
        else:
            raise _bad(EC.COMMAND_NOT_ALLOWED, "a unittest target must be a dotted module/class/test name")
    return out


class CodingPolicy:
    def __init__(self, test_commands: tuple[str, ...]) -> None:
        self.test_commands = tuple(c for c in test_commands if c in CODING_TEST_COMMANDS)

    def default_runner(self, language: str) -> str:
        order = ("npm test",) if language in ("JavaScript", "TypeScript") else ("python -m pytest", "pytest", "python -m unittest")
        for r in order:
            if r in self.test_commands:
                return r
        if self.test_commands:
            return self.test_commands[0]
        raise _bad(EC.COMMAND_NOT_ALLOWED, "no test runner is enabled (coding.test_commands)")

    def build_test_command(self, runner: object, args: object, root: str, npm_path: str | None) -> TestCommand:
        """The ONLY way a process command is ever made: allow-listed runner + validated arguments, as an argv list.
        `python` always means this interpreter (never a PATH lookup); nothing is ever passed to a shell."""
        name = " ".join(runner.split()) if isinstance(runner, str) else ""
        if name not in CODING_TEST_COMMANDS or name not in self.test_commands:
            raise _bad(EC.COMMAND_NOT_ALLOWED, f"not an allowed test runner; enabled: {list(self.test_commands)}")
        items = _args_list(args)
        if name in ("pytest", "python -m pytest"):
            extra = validate_pytest_args(items)
            argv = (sys.executable, "-m", "pytest", *extra, "--rootdir", root, "-p", "no:cacheprovider", "--color=no", "-rf")
        elif name == "python -m unittest":
            argv = (sys.executable, "-m", "unittest", *validate_unittest_args(items))
        else:  # npm test: no arguments at all
            if items:
                raise _bad(EC.COMMAND_NOT_ALLOWED, "'npm test' takes no arguments in v1")
            if not npm_path:
                raise _bad(EC.RUNNER_UNAVAILABLE, "npm was not found")
            if npm_path.lower().endswith((".cmd", ".bat", ".ps1")):
                raise _bad(EC.RUNNER_UNAVAILABLE, "npm is a .cmd script on this system; scripts are never started through the "
                                                  "command interpreter, so 'npm test' is unavailable here")
            argv = (npm_path, "test")
        return TestCommand(name, argv, " ".join([name, *items]))


def check_command_shape(argv: object) -> None:
    """What every provider enforces about ANY command it is handed (defence in depth; the controller builds them from allow-lists):
    an argv tuple of strings, an absolute program, and that program is no shell, script host or batch/script file."""
    import os
    if not isinstance(argv, tuple) or not argv or not all(isinstance(a, str) and "\x00" not in a for a in argv):
        raise _bad(EC.COMMAND_NOT_ALLOWED, "a command is a tuple of argument strings, never a command line")
    exe = argv[0]
    base = os.path.basename(exe.replace("\\", "/")).casefold()
    if not (os.path.isabs(exe) or exe.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", exe)):
        raise _bad(EC.COMMAND_NOT_ALLOWED, "the program must be an absolute path")
    if base in SHELL_NAMES or base.rsplit(".", 1)[0] in SHELL_NAMES or base.endswith((".bat", ".cmd", ".ps1", ".vbs", ".js", ".wsf", ".com")):
        raise _bad(EC.COMMAND_NOT_ALLOWED, "shells, script hosts and batch files are never started")


def git_command(sub: object, path: str | None, limit: int, git_path: str) -> tuple[str, ...]:
    """argv of a READ-ONLY git query with every program-launching feature switched off. Anything else is refused."""
    if sub not in GIT_READ:
        raise _bad(EC.BLOCKED, f"git {str(sub)[:20]!r} is not run by the coding agent in v1 (only {list(GIT_READ)}; commit, push, "
                               "reset, clean, checkout ... need the user)")
    hooks = "core.hooksPath=NUL" if sys.platform == "win32" else "core.hooksPath=/dev/null"
    base = [git_path, "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", "-c", hooks,
            "-c", "protocol.ext.allow=never", "-c", "core.quotepath=false"]
    if sub == "status":
        base += ["status", "--porcelain=v1", "-b", "--no-renames"]
    elif sub == "diff":
        base += ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--stat", "--patch"]
    else:
        base += ["log", "--no-color", "--no-ext-diff", "-n", str(limit), "--format=%h %ad %an: %s", "--date=short"]
    base += ["--", path if path else ".", *GIT_EXCLUDES]
    return tuple(base)


def baseline_rules(settings: "CodingSettings") -> list:
    """Rules merged into the engine's policy at startup (visible in /permissions). `confirm` = ask every time, never offer a
    session permission; deny > confirm > allow, so a user `allow` rule cannot switch these questions off."""
    from jarvis.coding import resources as res
    from jarvis.permissions import Effect, Rule
    rules = [Rule(id="coding-baseline-special-write-confirm", effect=Effect.CONFIRM, tool=res.TOOL, action="write.*",
                  description="Changes to the JARVIS repository itself and to dependency files are always confirmed, one by one")]
    if settings.confirm_delete_each_time:
        rules.append(Rule(id="coding-baseline-delete-confirm", effect=Effect.CONFIRM, tool=res.TOOL, action="delete*",
                          description="Deleting a file is always confirmed"))
    if settings.confirm_llm_each_time:
        rules.append(Rule(id="coding-baseline-plan-confirm", effect=Effect.CONFIRM, tool=res.TOOL, action="plan",
                          description="Sending project excerpts to an LLM provider is always confirmed"))
    return rules
