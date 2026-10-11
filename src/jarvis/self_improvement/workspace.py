"""The only place of this layer that runs processes and touches files. Commands are fixed argument lists built here from validated values - never a shell,
never text taken from a model or a log. Every call has a timeout, can be cancelled, has bounded output and runs with a scrubbed environment.

GitWorkspace prepares a change in its OWN branch and git worktree (data_dir/worktrees/<id>); the active working tree and branch are never written by
preparation or testing. Activation is a fast-forward merge of exactly the tested commit, rollback a revert commit: history is only ever extended."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import signal
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

log = logging.getLogger("jarvis.self_improvement")

_ENV_KEEP = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG", "LC_ALL",
             "VIRTUAL_ENV", "LOCALAPPDATA", "APPDATA")
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class CommandResult:
    exit_status: int | None
    output: str
    duration: float
    timed_out: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_status == 0 and not self.timed_out and not self.cancelled


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], cwd: Path, timeout: float, cancel: threading.Event | None = None,
            env_extra: Mapping[str, str] | None = None) -> CommandResult: ...


def scrubbed_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Allow-list, not block-list: API keys, tokens and anything else in the environment never reach a spawned process."""
    env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEEP}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    env.update(extra or {})
    return env


class SubprocessRunner:
    def __init__(self, max_output: int = 200_000, poll: float = 0.1) -> None:
        self._max, self._poll = max_output, poll

    def run(self, argv: Sequence[str], cwd: Path, timeout: float, cancel: threading.Event | None = None,
            env_extra: Mapping[str, str] | None = None) -> CommandResult:
        argv = [str(a) for a in argv]
        started = time.monotonic()
        try:
            out = tempfile.TemporaryFile()
        except OSError as exc:
            raise PreparationError(f"no temporary file ({type(exc).__name__})") from None
        with out:
            kw: dict = {}
            if os.name == "posix":
                kw["start_new_session"] = True
            elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                proc = subprocess.Popen(argv, cwd=str(cwd), env=scrubbed_env(env_extra), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                        shell=False, **kw)
            except (OSError, ValueError) as exc:
                raise PreparationError(f"cannot start {argv[0]!r} ({type(exc).__name__})") from None
            timed_out = cancelled = False
            while True:
                try:
                    proc.wait(timeout=self._poll)
                    break
                except subprocess.TimeoutExpired:
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                    elif time.monotonic() - started > timeout:
                        timed_out = True
                    else:
                        continue
                    self._kill(proc)
                    break
            size = out.seek(0, os.SEEK_END)
            out.seek(max(0, size - self._max))
            text = out.read().decode("utf-8", "replace")
        return CommandResult(None if (timed_out or cancelled) else proc.returncode, text, time.monotonic() - started, timed_out, cancelled)

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
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
class PreparedChange:
    worktree: Worktree
    head_commit: str
    changed_files: tuple[str, ...]
    diff: str
    diff_digest: str
    stat: str


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:32]


class GitWorkspace:
    def __init__(self, repo: str | os.PathLike[str], data_dir: str | os.PathLike[str], runner: CommandRunner | None = None, *, timeout: float = 60.0,
                 max_diff_bytes: int = 100_000, max_file_bytes: int = P.MAX_FILE_BYTES) -> None:
        self._repo = Path(repo).expanduser()
        self._data = Path(data_dir).expanduser()
        self._runner = runner or SubprocessRunner()
        self._timeout = timeout
        self._max_diff = min(max_diff_bytes, P.MAX_DIFF_BYTES_HARD)
        self._max_file = max_file_bytes
        self._root: Path | None = None

    # ---- git helpers ---------------------------------------------------------------------------------------------------------------------
    @property
    def worktrees_dir(self) -> Path:
        return self._data / "worktrees"

    def _git(self, args: Sequence[str], cwd: Path, cancel: threading.Event | None = None, identity: bool = False) -> CommandResult:
        hooks = self._data / "_nohooks"
        hooks.mkdir(parents=True, exist_ok=True)
        pre = ["git", "-c", f"core.hooksPath={hooks}", "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false", "-c", "core.safecrlf=false"]
        # core.autocrlf is deliberately NOT overridden: the repository's own setting decides how line endings are compared, otherwise a Windows checkout
        # (autocrlf=true, CRLF in the working tree) would look "modified" to every status check here.
        if identity:
            pre += ["-c", "user.name=JARVIS Self-Improvement", "-c", "user.email=jarvis@localhost"]
        return self._runner.run([*pre, *args], cwd, self._timeout, cancel)

    def _need(self, r: CommandResult, what: str) -> str:
        if r.cancelled:
            raise PreparationError(f"{what}: cancelled")
        if r.timed_out:
            raise PreparationError(f"{what}: timed out")
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
        sha = self._need(self._git(["rev-parse", "HEAD"], cwd or self.root()), "git rev-parse HEAD").strip()
        if not _SHA.match(sha):
            raise PreparationError("unexpected git output")
        return sha

    def current_branch(self) -> str:
        return self._need(self._git(["symbolic-ref", "--short", "-q", "HEAD"], self.root()), "git symbolic-ref").strip()

    def tracked_changes(self) -> str:
        """Porcelain lines (`XY path`) of modified tracked files; empty = clean. Anything else in the output (git warnings) is not a change."""
        out = self._need(self._git(["status", "--porcelain", "--untracked-files=no"], self.root()), "git status")
        return "\n".join(ln for ln in out.splitlines() if re.match(r"^[ MADRCTU]{2} \S", ln))

    # ---- preparation ---------------------------------------------------------------------------------------------------------------------
    def create_worktree(self, proposal_id: str, cancel: threading.Event | None = None) -> Worktree:
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

    def _safe_file(self, wt: Worktree, rel: str, must_exist: bool = True) -> Path:
        why = P.refuse_target(rel)
        if why:
            raise ChangeBlocked(f"{rel}: {why}")
        parts = rel.replace("\\", "/").split("/")
        cur = wt.path
        for part in parts:
            cur = cur / part
            if cur.is_symlink():
                raise ChangeBlocked(f"{rel}: symbolic links are not followed")
        resolved = cur.resolve()
        if not resolved.is_relative_to(wt.path.resolve()):
            raise ChangeBlocked(f"{rel}: outside the working copy")
        if must_exist and not resolved.is_file():
            raise PreparationError(f"{rel}: not an existing file (new files are not created automatically)")
        return resolved

    def read_file(self, wt: Worktree, rel: str) -> str:
        f = self._safe_file(wt, rel)
        if f.stat().st_size > self._max_file:
            raise PreparationError(f"{rel}: file too large")
        try:
            return f.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise PreparationError(f"{rel}: not valid UTF-8 text") from None

    def apply_and_commit(self, wt: Worktree, edits: Sequence[Mapping[str, str]], message: str, cancel: threading.Event | None = None) -> PreparedChange:
        # 1. compute everything in memory first: nothing is written unless every edit applies exactly once
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
        files = sorted(new_content)
        self._need(self._git(["add", "--", *files], wt.path, cancel), "git add")
        self._need(self._git(["commit", "--no-verify", "--no-gpg-sign", "-q", "-m", message], wt.path, cancel, identity=True), "git commit")
        return self.describe_change(wt, cancel)

    def describe_change(self, wt: Worktree, cancel: threading.Event | None = None) -> PreparedChange:
        head = self.head(wt.path)
        rng = f"{wt.base_commit}..{head}"
        names = self._need(self._git(["diff", "--no-ext-diff", "--no-textconv", "--name-status", "--no-renames", rng], wt.path, cancel), "git diff")
        files: list[str] = []
        for line in names.splitlines():
            status, _, path = line.partition("\t")
            if status != "M":
                raise ChangeBlocked(f"{path}: only modifications of existing files are accepted (found status {status})")
            files.append(path)
        if not files:
            raise PreparationError("the change is empty")
        diff = self._need(self._git(["diff", "--no-ext-diff", "--no-textconv", "--no-renames", "-U2", rng], wt.path, cancel), "git diff")
        if len(diff.encode("utf-8", "replace")) > self._max_diff:
            raise PreparationError("the diff exceeds the configured size limit")
        stat = self._need(self._git(["diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--stat", rng], wt.path, cancel), "git diff --stat")
        return PreparedChange(wt, head, tuple(sorted(files)), diff, digest(diff), stat.strip())

    def worktree_for(self, proposal_id: str, branch: str, base_commit: str) -> Worktree:
        wt = Worktree(proposal_id, (self.worktrees_dir / proposal_id).resolve(), branch, base_commit)
        if not wt.path.is_dir() or branch != P.BRANCH_PREFIX + proposal_id:
            raise PreparationError("the prepared working copy no longer exists")
        return wt

    def discard(self, proposal_id: str, branch: str = "") -> None:
        """Remove the isolated working copy and its own branch (only a path/branch derived from a valid proposal id; never anything else)."""
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

    # ---- activation / rollback -----------------------------------------------------------------------------------------------------------
    def fast_forward(self, branch: str, expected_base: str, expected_head: str) -> str:
        """Merge exactly the tested commit into the ACTIVE branch. Refuses unless the active branch is still at the base the change was tested on,
        has no uncommitted changes to tracked files and the branch tip is the approved commit."""
        root = self.root()
        if not branch.startswith(P.BRANCH_PREFIX):
            raise PreparationError("not an improvement branch")
        if not self.current_branch():
            raise PreparationError("the active checkout is not on a branch")
        if self.tracked_changes():
            raise PreparationError("the active working tree has uncommitted changes")
        if self.head() != expected_base:
            raise PreparationError("the active branch moved since the change was tested; prepare and test it again")
        tip = self._need(self._git(["rev-parse", f"refs/heads/{branch}"], root), "git rev-parse branch").strip()
        if tip != expected_head:
            raise PreparationError("the improvement branch changed after it was approved")
        self._need(self._git(["merge", "--ff-only", "--no-verify", tip], root, identity=True), "git merge --ff-only")
        return self.head()

    def revert(self, commit: str) -> str:
        root = self.root()
        if not _SHA.match(commit):
            raise PreparationError("bad commit id")
        if self.tracked_changes():
            raise PreparationError("the active working tree has uncommitted changes")
        r = self._git(["revert", "--no-edit", commit], root, identity=True)
        if not r.ok:
            self._git(["revert", "--abort"], root)
            raise PreparationError("the revert did not apply cleanly and was aborted")
        return self.head()

    def interpreter(self) -> str:
        return sys.executable
