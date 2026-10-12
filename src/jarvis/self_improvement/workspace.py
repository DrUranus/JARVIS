"""The only place of this layer that starts processes (git) and touches the filesystem. Commands are fixed argument lists built from VALIDATED values (hex object
ids, ids matching ^imp-[0-9a-f]{12}$) - never a shell, never text taken from a model, a log or a stored proposal. Every call has a timeout, can be cancelled, has
a hard cap on the amount of data written, and runs with a scrubbed environment.

IMPORTANT: this module never runs proposed code. It only runs `git` (object database reads, worktree/branch handling) and builds an EXPORT of a commit: the files
of exactly that commit, taken from the object database (no `.git`, no filters, hashes verified, nothing else in the directory), which is what any future,
properly isolated test run would have to use instead of a mutable working directory. A scrubbed environment and a worktree are NOT a sandbox (see isolation.py).

Preparing a change in a worktree and merging are only reachable through ImprovementManager, which refuses them while the ExecutionGuard is locked (always, today)."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from jarvis.self_improvement import policy as P
from jarvis.self_improvement.errors import ChangeBlocked, PreparationError
from jarvis.self_improvement.isolation import ExecutionGuard
from jarvis.self_improvement.review import RawEntry, ReviewedChange, review_entries

log = logging.getLogger("jarvis.self_improvement")

_ENV_KEEP = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG", "LC_ALL",
             "LOCALAPPDATA", "APPDATA")
_SHA = re.compile(r"^[0-9a-f]{40}\Z")
MAX_EXPORT_FILES = 20_000
MAX_EXPORT_BYTES = 200 * 1024 * 1024


def valid_sha(value: object) -> str:
    """A full SHA-1 object id or PreparationError. Used for EVERY object id that reaches a git argument (also those read from the proposal store)."""
    if not isinstance(value, str) or not _SHA.match(value):
        raise PreparationError("not a valid git object id")
    return value


@dataclass(frozen=True)
class CommandResult:
    exit_status: int | None
    output: str
    duration: float
    timed_out: bool = False
    cancelled: bool = False
    output_limit: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_status == 0 and not (self.timed_out or self.cancelled or self.output_limit)


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], cwd: Path, timeout: float, cancel: threading.Event | None = None,
            env_extra: Mapping[str, str] | None = None) -> CommandResult: ...

    def capture(self, argv: Sequence[str], cwd: Path, timeout: float, max_bytes: int, cancel: threading.Event | None = None) -> bytes: ...


def scrubbed_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Allow-list, not block-list. This removes secrets from the ENVIRONMENT only; it does not stop a process from reading files, the home directory or
    the network. It is not isolation."""
    env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEEP}
    # GIT_CONFIG_NOSYSTEM is deliberately NOT set: it hides the machine's system git config, and Git for Windows keeps `core.autocrlf=true` there - without it a CRLF
    # working tree looks "modified" to `git status` (tracked_changes). It is not needed for safety: hooks and fsmonitor are overridden per command (GitWorkspace._pre),
    # external diff/textconv are switched off, and decisions use object-database reads (cat-file/ls-tree/diff-tree), which no config can turn into code execution.
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    env.update(extra or {})
    return env


def _descendants(pid: int) -> list[int]:
    """All descendants of pid (Linux /proc). Collected BEFORE the group is killed so that children which detached into their own session are found too."""
    kids: dict[int, list[int]] = {}
    try:
        for name in os.listdir("/proc"):
            if name.isdigit():
                try:
                    with open(f"/proc/{name}/stat", "rb") as fh:
                        rest = fh.read().rsplit(b")", 1)[1].split()
                    kids.setdefault(int(rest[1]), []).append(int(name))
                except (OSError, IndexError, ValueError):
                    continue
    except OSError:
        return []
    out, todo = [], [pid]
    while todo:
        for c in kids.get(todo.pop(), []):
            out.append(c)
            todo.append(c)
    return out


class SubprocessRunner:
    """Runs fixed argument lists. Output is capped: more than `max_total` bytes written ends the process (a command cannot fill the disk through its output)."""

    def __init__(self, max_output: int = 200_000, poll: float = 0.1, max_total: int = 5_000_000) -> None:
        self._max, self._poll, self._total = max_output, poll, max_total

    def _spawn(self, argv: Sequence[str], cwd: Path, env_extra: Mapping[str, str] | None, out, err) -> subprocess.Popen:
        kw: dict = {}
        if os.name == "posix":
            kw["start_new_session"] = True
        elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen([str(a) for a in argv], cwd=str(cwd), env=scrubbed_env(env_extra), stdin=subprocess.DEVNULL, stdout=out, stderr=err, shell=False, **kw)
        except (OSError, ValueError) as exc:
            raise PreparationError(f"cannot start {str(argv[0])!r} ({type(exc).__name__})") from None

    def _supervise(self, proc: subprocess.Popen, out, timeout: float, cancel: threading.Event | None, cap: int) -> tuple[bool, bool, bool]:
        started = time.monotonic()
        while True:
            try:
                proc.wait(timeout=self._poll)
                return False, False, False
            except subprocess.TimeoutExpired:
                pass
            why = None
            if cancel is not None and cancel.is_set():
                why = "cancel"
            elif time.monotonic() - started > timeout:
                why = "timeout"
            else:
                try:
                    if os.fstat(out.fileno()).st_size > cap:
                        why = "limit"
                except OSError:
                    pass
            if why:
                self._kill(proc)
                return why == "timeout", why == "cancel", why == "limit"

    def run(self, argv: Sequence[str], cwd: Path, timeout: float, cancel: threading.Event | None = None,
            env_extra: Mapping[str, str] | None = None) -> CommandResult:
        started = time.monotonic()
        with tempfile.TemporaryFile() as out:
            proc = self._spawn(argv, cwd, env_extra, out, subprocess.STDOUT)
            timed_out, cancelled, limit = self._supervise(proc, out, timeout, cancel, self._total)
            size = out.seek(0, os.SEEK_END)
            out.seek(max(0, size - self._max))
            text = out.read().decode("utf-8", "replace")
        stopped = timed_out or cancelled or limit
        return CommandResult(None if stopped else proc.returncode, text, time.monotonic() - started, timed_out, cancelled, limit)

    def capture(self, argv: Sequence[str], cwd: Path, timeout: float, max_bytes: int, cancel: threading.Event | None = None) -> bytes:
        """stdout only, complete (never truncated): more than max_bytes, a timeout, a cancel or a non-zero exit is an error."""
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = self._spawn(argv, cwd, None, out, err)
            timed_out, cancelled, limit = self._supervise(proc, out, timeout, cancel, max_bytes)
            size = out.seek(0, os.SEEK_END)
            limit = limit or size > max_bytes                    # a process that finished between two polls must not slip past the cap
            if timed_out or cancelled or limit or proc.returncode != 0:
                raise PreparationError("git command " + ("timed out" if timed_out else "was cancelled" if cancelled else "exceeded the output limit" if limit else "failed"))
            out.seek(0)
            return out.read()

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        """Kill the process group AND every descendant found beforehand (also detached ones). Not a guarantee: a process that daemonises quickly enough or a
        platform without /proc can escape - one of the reasons proposed code is not run at all."""
        try:
            if os.name == "posix":
                kids = _descendants(proc.pid)
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                for k in kids:
                    try:
                        os.kill(k, signal.SIGKILL)
                    except OSError:
                        pass
            else:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10, check=False)
                proc.kill()
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


@dataclass(frozen=True)
class Worktree:
    proposal_id: str
    path: Path
    branch: str
    base_commit: str


@dataclass(frozen=True)
class Export:
    path: Path
    commit: str
    manifest: tuple[tuple[str, str], ...]       # (path, sha256) sorted
    manifest_sha256: str


def manifest_digest(entries: Sequence[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for path, digest in sorted(entries):
        h.update(path.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
    return h.hexdigest()


def _export_path_ok(path: str) -> bool:
    parts = path.split("/")
    return (bool(path) and len(path) <= 240 and all(p not in ("", ".", "..") and not p.endswith((" ", ".")) and p.casefold() != ".git" and ":" not in p and "\\" not in p
                                                    and all(32 <= ord(c) < 127 for c in p) for p in parts))


class GitWorkspace:
    def __init__(self, repo: str | os.PathLike[str], data_dir: str | os.PathLike[str], runner: CommandRunner | None = None, *, timeout: float = 60.0,
                 max_diff_bytes: int = 100_000, max_file_bytes: int = P.MAX_FILE_BYTES, guard: ExecutionGuard | None = None) -> None:
        # The methods that CHANGE the repository (create_worktree, apply_and_commit, discard, fast_forward, revert) ask this guard themselves, first thing, so that a
        # direct call cannot bypass the manager's lock. Default: locked (fail closed). Read-only methods (review, export_commit, tracked_changes, ...) are not guarded.
        self._guard = guard or ExecutionGuard.locked()
        self._repo = Path(repo).expanduser()
        self._data = Path(data_dir).expanduser()
        self._runner = runner or SubprocessRunner()
        self._timeout = timeout
        self._max_file = max_file_bytes
        self._root: Path | None = None

    # ---- git helpers ---------------------------------------------------------------------------------------------------------------------
    @property
    def worktrees_dir(self) -> Path:
        return self._data / "worktrees"

    def _pre(self, identity: bool = False) -> list[str]:
        hooks = self._data / "_nohooks"
        hooks.mkdir(parents=True, exist_ok=True)
        pre = ["git", "-c", f"core.hooksPath={hooks}", "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false", "-c", "core.safecrlf=false"]
        # core.autocrlf is deliberately NOT overridden: the repository's own setting decides how line endings are compared (Windows checkouts).
        if identity:
            pre += ["-c", "user.name=JARVIS Self-Improvement", "-c", "user.email=jarvis@localhost"]
        return pre

    def _git(self, args: Sequence[str], cwd: Path, cancel: threading.Event | None = None, identity: bool = False) -> CommandResult:
        return self._runner.run([*self._pre(identity), *args], cwd, self._timeout, cancel)

    def _git_bytes(self, args: Sequence[str], cwd: Path, max_bytes: int, cancel: threading.Event | None = None) -> bytes:
        return self._runner.capture([*self._pre(), *args], cwd, self._timeout, max_bytes, cancel)

    def _need(self, r: CommandResult, what: str) -> str:
        if r.cancelled:
            raise PreparationError(f"{what}: cancelled")
        if r.timed_out:
            raise PreparationError(f"{what}: timed out")
        if r.output_limit:
            raise PreparationError(f"{what}: output limit exceeded")
        if not r.ok:
            raise PreparationError(f"{what} failed: {P.clip(r.output.strip().splitlines()[-1] if r.output.strip() else 'no output', 200)}")
        return r.output

    def root(self) -> Path:
        if self._root is None:
            if not self._repo.is_dir():
                raise PreparationError("the configured repository directory does not exist")
            out = self._need(self._git(["rev-parse", "--show-toplevel"], self._repo), "git rev-parse").strip()
            self._root = Path(out).resolve()
            if not (self._root / "src" / "jarvis").is_dir():
                raise PreparationError("the repository has no src/jarvis directory")
        return self._root

    def head(self, cwd: Path | None = None) -> str:
        return valid_sha(self._need(self._git(["rev-parse", "HEAD"], cwd or self.root()), "git rev-parse HEAD").strip())

    def current_branch(self) -> str:
        return self._need(self._git(["symbolic-ref", "--short", "-q", "HEAD"], self.root()), "git symbolic-ref").strip()

    def tracked_changes(self) -> str:
        """Porcelain lines (`XY path`) of modified tracked files; empty = clean. Anything else in the output (git warnings) is not a change."""
        out = self._need(self._git(["status", "--porcelain", "--untracked-files=no"], self.root()), "git status")
        return "\n".join(ln for ln in out.splitlines() if re.match(r"^[ MADRCTU]{2} \S", ln))

    # ---- metadata and objects (the basis of every security decision) ------------------------------------------------------------------------
    def changed_entries(self, base: str, head: str, cancel: threading.Event | None = None) -> list[RawEntry]:
        """Changed files from `git diff-tree --raw`: status, both modes, both blob ids. Not affected by .gitattributes (-diff, binary) or textconv."""
        base, head = valid_sha(base), valid_sha(head)
        raw = self._git_bytes(["diff-tree", "-r", "-z", "--raw", "--no-renames", "--no-abbrev", "--no-ext-diff", base, head], self.root(), 1_000_000, cancel)
        parts = raw.split(b"\0")
        entries: list[RawEntry] = []
        i = 0
        while i < len(parts) and parts[i]:
            meta = parts[i].decode("ascii", "replace")
            m = re.fullmatch(r":(\d{6}) (\d{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) ([A-Z])\d*", meta)
            if not m or i + 1 >= len(parts):
                raise ChangeBlocked("git reported a change that cannot be classified")
            try:
                path = parts[i + 1].decode("utf-8")
            except UnicodeDecodeError:
                raise ChangeBlocked("git reported a file name that is not valid UTF-8") from None
            entries.append(RawEntry(m.group(5), m.group(1), m.group(2), m.group(3), m.group(4), path))
            i += 2
        return entries

    def read_blob(self, sha: str, cancel: threading.Event | None = None) -> bytes:
        return self._git_bytes(["cat-file", "blob", valid_sha(sha)], self.root(), MAX_EXPORT_BYTES, cancel)

    def review(self, base: str, head: str, cancel: threading.Event | None = None) -> ReviewedChange:
        entries = self.changed_entries(base, head, cancel)
        return review_entries(valid_sha(base), valid_sha(head), entries, lambda sha: self.read_blob(sha, cancel))

    # ---- export of an exact commit ---------------------------------------------------------------------------------------------------------
    def export_commit(self, commit: str, cancel: threading.Event | None = None) -> Export:
        """The files of exactly `commit`, from the object database, into a NEW temporary directory: no `.git`, no clean/smudge filters, no working-tree state.
        Refuses symlinks, submodules, unusual names and case collisions; verifies every blob against its object id and the final directory listing against the
        manifest. The caller owns (and must delete) the directory."""
        commit = valid_sha(commit)
        raw = self._git_bytes(["ls-tree", "-r", "-z", "--full-tree", "--long", commit], self.root(), 20_000_000, cancel)
        items = [p for p in raw.split(b"\0") if p]
        if not items or len(items) > MAX_EXPORT_FILES:
            raise PreparationError("the commit has no files or too many files to export")
        dest = Path(tempfile.mkdtemp(prefix="jarvis-export-"))
        try:
            manifest: list[tuple[str, str]] = []
            folded: set[str] = set()
            total = 0
            for item in items:
                m = re.match(rb"^(\d{6}) (\w+) ([0-9a-f]{40})\s+(\d+|-)\t(.+)$", item, re.S)
                if not m or m.group(2) != b"blob" or m.group(1) not in (b"100644", b"100755"):
                    raise PreparationError("the commit contains an entry that is not a regular file (symlink, submodule or unknown type)")
                try:
                    rel = m.group(5).decode("utf-8")
                except UnicodeDecodeError:
                    raise PreparationError("the commit contains a file name that is not valid UTF-8") from None
                if not _export_path_ok(rel):
                    raise PreparationError("the commit contains an unusual file name")
                if rel.casefold() in folded:
                    raise PreparationError("the commit contains file names that differ only in case (collision on case-insensitive file systems)")
                folded.add(rel.casefold())
                data = self.read_blob(m.group(3).decode("ascii"), cancel)
                if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != m.group(3).decode("ascii"):  # noqa: S324
                    raise PreparationError("an exported blob does not match its object id")
                total += len(data)
                if total > MAX_EXPORT_BYTES:
                    raise PreparationError("the export is too large")
                target = dest.joinpath(*rel.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                manifest.append((rel, hashlib.sha256(data).hexdigest()))
            self._harden(dest)
            exp = Export(dest, commit, tuple(sorted(manifest)), manifest_digest(manifest))
            self.verify_export(exp)
            return exp
        except BaseException:
            self.remove_export(dest)
            raise

    @staticmethod
    def _harden(dest: Path) -> None:
        for p in sorted(dest.rglob("*"), key=lambda q: len(q.parts), reverse=True):
            try:
                os.chmod(p, stat.S_IRUSR | (stat.S_IXUSR if p.is_dir() else 0))
            except OSError:
                pass
        try:
            os.chmod(dest, stat.S_IRUSR | stat.S_IXUSR)
        except OSError:
            pass

    @staticmethod
    def verify_export(exp: Export) -> None:
        """Exactly the manifest's files, nothing else (no `.git`, no extra or missing file), every hash equal. Any difference raises."""
        found: dict[str, str] = {}
        dirs: set[str] = set()
        for p in exp.path.rglob("*"):
            if p.is_symlink():
                raise PreparationError("the export contains a symbolic link")
            if p.is_file():
                found[p.relative_to(exp.path).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
            elif p.is_dir():
                dirs.add(p.relative_to(exp.path).as_posix())
            else:
                raise PreparationError("the export contains an unexpected file type")
        expected_dirs = {"/".join(path.split("/")[:i]) for path, _ in exp.manifest for i in range(1, len(path.split("/")))}
        if dirs != expected_dirs or found != dict(exp.manifest) or manifest_digest(list(found.items())) != exp.manifest_sha256:
            raise PreparationError("the export differs from the manifest of the commit")

    @staticmethod
    def remove_export(path: Path) -> None:
        def onerr(func, p, _exc):  # read-only files/dirs on Windows
            try:
                os.chmod(p, stat.S_IRWXU)
                func(p)
            except OSError:
                pass
        if path.name.startswith("jarvis-export-"):
            for p in [path, *path.rglob("*")]:
                try:
                    os.chmod(p, stat.S_IRWXU)
                except OSError:
                    pass
            shutil.rmtree(path, onerror=onerr)

    # ---- preparation (reachable only while the ExecutionGuard allows; never in this version) -------------------------------------------------
    def create_worktree(self, proposal_id: str, cancel: threading.Event | None = None) -> Worktree:
        self._guard.require("creating a worktree")
        if not P.ID_RE.match(proposal_id):
            raise PreparationError("bad proposal id")
        root = self.root()
        base = self.head()
        branch = P.BRANCH_PREFIX + proposal_id
        path = (self.worktrees_dir / proposal_id).resolve()
        if path.exists():
            raise PreparationError("a working copy for this proposal already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._need(self._git(["worktree", "add", "-b", branch, str(path), base], root, cancel), "git worktree add")
        return Worktree(proposal_id, path, branch, base)

    def _safe_file(self, wt: Worktree, rel: str) -> Path:
        why = P.refuse_target(rel)
        if why:
            raise ChangeBlocked(f"{P.clip(ascii(rel), 80)}: {why}")
        cur = wt.path
        for part in rel.split("/"):
            cur = cur / part
            if cur.is_symlink() or getattr(cur, "is_junction", lambda: False)():
                raise ChangeBlocked(f"{rel}: symbolic links and junctions are not followed")
        resolved = cur.resolve()
        root = wt.path.resolve()
        if not resolved.is_relative_to(root) or resolved.relative_to(root).as_posix() != rel:
            raise ChangeBlocked(f"{rel}: the canonical path differs from the requested one (case, short name or link)")
        if not resolved.is_file():
            raise PreparationError(f"{rel}: not an existing file (new files are not created)")
        return resolved

    def read_file(self, wt: Worktree, rel: str) -> str:
        f = self._safe_file(wt, rel)
        if f.stat().st_size > self._max_file:
            raise PreparationError(f"{rel}: file too large")
        try:
            return f.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise PreparationError(f"{rel}: not valid UTF-8 text") from None

    def apply_and_commit(self, wt: Worktree, edits: Sequence[Mapping[str, str]], message: str, cancel: threading.Event | None = None) -> ReviewedChange:
        self._guard.require("applying and committing a change")
        new_content: dict[str, bytes] = {}
        for e in edits:
            if cancel is not None and cancel.is_set():
                raise PreparationError("cancelled")
            rel = e["path"]
            raw = new_content.get(rel)
            if raw is None:
                f = self._safe_file(wt, rel)
                if f.stat().st_size > self._max_file:
                    raise PreparationError(f"{rel}: file too large")
                raw = f.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise PreparationError(f"{rel}: not valid UTF-8 text") from None
            old, new = e["old_text"], e["new_text"]
            if "\r\n" in text and "\r" not in old:
                old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
            if text.count(old) != 1:
                raise PreparationError(f"{rel}: old_text must occur exactly once (found {text.count(old)})")
            new_content[rel] = text.replace(old, new, 1).encode("utf-8")
        for rel, data in new_content.items():
            self._safe_file(wt, rel).write_bytes(data)
        self._need(self._git(["add", "--", *sorted(new_content)], wt.path, cancel), "git add")
        self._need(self._git(["commit", "--no-verify", "--no-gpg-sign", "-q", "-m", message], wt.path, cancel, identity=True), "git commit")
        return self.review(wt.base_commit, self.head(wt.path), cancel)

    def worktree_for(self, proposal_id: str, branch: str, base_commit: str) -> Worktree:
        valid_sha(base_commit)
        wt = Worktree(proposal_id, (self.worktrees_dir / proposal_id).resolve(), branch, base_commit)
        if not P.ID_RE.match(proposal_id) or branch != P.BRANCH_PREFIX + proposal_id or not wt.path.is_dir():
            raise PreparationError("the prepared working copy no longer exists")
        return wt

    def branch_tip(self, branch: str) -> str:
        if not branch.startswith(P.BRANCH_PREFIX) or not P.ID_RE.match(branch[len(P.BRANCH_PREFIX):]):
            raise PreparationError("not an improvement branch")
        return valid_sha(self._need(self._git(["rev-parse", f"refs/heads/{branch}"], self.root()), "git rev-parse branch").strip())

    def discard(self, proposal_id: str, branch: str = "") -> None:
        self._guard.require("discarding a prepared working copy")
        if not P.ID_RE.match(proposal_id):
            return
        path = (self.worktrees_dir / proposal_id).resolve()
        try:
            root = self.root()
            if path.is_dir():
                self._git(["worktree", "remove", "--force", str(path)], root)
                shutil.rmtree(path, ignore_errors=True)
            self._git(["worktree", "prune"], root)
            if branch == P.BRANCH_PREFIX + proposal_id:
                self._git(["branch", "-D", branch], root)
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort and must not mask the real outcome
            log.warning("cleanup of %s failed (%s)", proposal_id, type(exc).__name__)

    # ---- activation / rollback (also locked) -----------------------------------------------------------------------------------------------
    def fast_forward(self, branch: str, expected_base: str, expected_head: str) -> str:
        self._guard.require("merging a change")
        root = self.root()
        expected_base, expected_head = valid_sha(expected_base), valid_sha(expected_head)
        if not self.current_branch():
            raise PreparationError("the active checkout is not on a branch")
        if self.tracked_changes():
            raise PreparationError("the active working tree has uncommitted changes")
        if self.head() != expected_base:
            raise PreparationError("the active branch moved since the change was reviewed; prepare and test it again")
        tip = self.branch_tip(branch)
        if tip != expected_head:
            raise PreparationError("the improvement branch changed after it was approved")
        self._need(self._git(["merge", "--ff-only", "--no-verify", tip], root, identity=True), "git merge --ff-only")
        return self.head()

    def revert(self, commit: str) -> str:
        self._guard.require("reverting a change")
        root = self.root()
        commit = valid_sha(commit)
        if self.tracked_changes():
            raise PreparationError("the active working tree has uncommitted changes")
        r = self._git(["revert", "--no-edit", commit], root, identity=True)
        if not r.ok:
            self._git(["revert", "--abort"], root)
            raise PreparationError("the revert did not apply cleanly and was aborted")
        return self.head()
