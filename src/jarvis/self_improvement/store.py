"""Proposal storage with integrity protection.

Nothing read from the store is trusted merely because it is in the file. The JSON store signs the whole file with HMAC-SHA256 (key held OUTSIDE the data
directory, see `load_key`) and verifies the signature on EVERY read. A file that fails verification (edited status, forged approval, replaced proposal, wrong key,
older/newer format) makes the store unavailable - reads and writes raise IntegrityError, the file is left untouched (a copy is kept as *.tampered) - instead of
being "repaired". Writes are compare-and-swap per proposal (`rev`), serialised by an OS file lock, so concurrent threads/processes cannot overwrite each other's
changes (ConcurrentUpdateError) and a stale in-memory copy can never silently revert a newer state.

Limits: the HMAC proves that the file was written by someone holding the key; it cannot prevent that holder from writing, and it cannot detect a replay of an
OLDER validly signed file after a restart (within one process a falling sequence number is detected)."""
from __future__ import annotations

import errno
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from jarvis.self_improvement.errors import ConcurrentUpdateError, ImprovementError, IntegrityError, UnknownProposalError
from jarvis.self_improvement.models import Proposal
from jarvis.self_improvement.winsec import WindowsAcl

log = logging.getLogger("jarvis.self_improvement")
FORMAT = 2
MIN_KEY_BYTES = 32


class ProposalStore(ABC):
    @abstractmethod
    def save(self, proposal: Proposal) -> Proposal:
        """Compare-and-swap: succeeds only if the stored revision equals `proposal.rev` (0 = new); returns the stored copy with rev + 1."""

    @abstractmethod
    def get(self, proposal_id: str) -> Proposal: ...

    @abstractmethod
    def list(self) -> list[Proposal]:
        """Newest first."""


class MemoryProposalStore(ProposalStore):
    def __init__(self, max_items: int = 200) -> None:
        self._items: dict[str, Proposal] = {}
        self._max = max_items
        self._lock = threading.RLock()

    def _put(self, proposal: Proposal) -> Proposal:
        cur = self._items.get(proposal.proposal_id)
        if (cur.rev if cur else 0) != proposal.rev or (cur is None and proposal.rev != 0):
            raise ConcurrentUpdateError(f"proposal {proposal.proposal_id} was changed by someone else (expected rev {proposal.rev}, stored {cur.rev if cur else 'none'})")
        stored = replace(proposal, rev=proposal.rev + 1)
        self._items[stored.proposal_id] = stored
        while len(self._items) > self._max:
            victim = next((k for k, v in sorted(self._items.items(), key=lambda kv: kv[1].created_at) if v.is_terminal), None)
            if victim is None:
                break
            del self._items[victim]
        return stored

    def save(self, proposal: Proposal) -> Proposal:
        with self._lock:
            return self._put(proposal)

    def get(self, proposal_id: str) -> Proposal:
        with self._lock:
            try:
                return self._items[proposal_id]
            except KeyError:
                raise UnknownProposalError(f"unknown proposal {proposal_id!r}") from None

    def list(self) -> list[Proposal]:
        with self._lock:
            return sorted(self._items.values(), key=lambda p: p.created_at, reverse=True)


# ---- key handling ------------------------------------------------------------------------------------------------------------------------------
def _default_windows_acl() -> "WindowsAcl":
    """The real Windows ACL helper: fixed absolute system executables, started through the package's one process runner with a scrubbed environment."""
    from jarvis.self_improvement.workspace import SubprocessRunner
    runner = SubprocessRunner(max_output=20_000, max_total=1_000_000)
    cwd = Path(os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows")

    def run(argv):
        res = runner.run(argv, cwd, 180.0)       # cold PowerShell starts can be slow under load; the limit only bounds a hang
        return res.exit_status, res.output
    return WindowsAcl(run)


def _create_key_file(path: Path, acl: "WindowsAcl | None") -> None:
    """Create the key file so that the secret never exists in a file with a broader ACL than intended, and so that no other process can ever see a half-written key:
    1. an EMPTY temp file is created exclusively;  2. (Windows) its inheritance is removed and only the current user, SYSTEM and Administrators get access, and the
    result is verified;  3. only then is the key written;  4. the finished file is published with a hard link, which fails if the key file already exists
    (another process was first - its key is used)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    os.close(fd)
    try:
        if acl is not None:
            try:
                acl.restrict(str(tmp))
            except (OSError, ValueError) as exc:
                raise IntegrityError(f"the new store key file could not be restricted to the current user ({exc}); no key was written") from None
            problems = acl.review(str(tmp))
            if problems:
                raise IntegrityError("the new store key file still has an unacceptable ACL (" + "; ".join(problems[:3]) + "); no key was written")
        with open(tmp, "wb") as fh:
            fh.write((secrets.token_hex(MIN_KEY_BYTES) + "\n").encode("ascii"))
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass
        except OSError as exc:
            raise IntegrityError(f"the store key file could not be published atomically ({type(exc).__name__}); it needs a file system with hard links (NTFS, ext4, ...)") from None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def load_key(env: Mapping[str, str], key_path: str | os.PathLike[str], *, acl: "WindowsAcl | None" = None) -> bytes:
    """The HMAC key: JARVIS_SELF_IMPROVEMENT_STORE_KEY (hex, >= 32 bytes) or a key file that is created (owner-only) on first use. The caller has already
    checked that the file lies outside the data directory and outside every root the coding tools may write to.

    The key file's permissions are checked on every load: POSIX group/other bits, and on Windows the EFFECTIVE ACL (see winsec.py). A file that anybody else could
    read makes this raise IntegrityError (fail closed). An EXISTING file is never modified automatically. `acl` is for tests; on Windows the real helper is used."""
    raw = env.get("JARVIS_SELF_IMPROVEMENT_STORE_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            raise IntegrityError("JARVIS_SELF_IMPROVEMENT_STORE_KEY must be hex") from None
        if len(key) < MIN_KEY_BYTES:
            raise IntegrityError("the store key must be at least 32 bytes")
        return key
    path = Path(key_path).expanduser()
    if acl is None and sys.platform.startswith("win"):
        acl = _default_windows_acl()
    if not path.exists():
        _create_key_file(path, acl)
    try:
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise IntegrityError("the store key file must not be readable by group/others (chmod 600)")
        if acl is not None:
            problems = acl.review(str(path))
            if problems:
                raise IntegrityError("the store key file's ACL is not acceptable: " + "; ".join(problems[:3])
                                     + ". Fix it yourself (for example: icacls <file> /inheritance:r /grant:r \"%USERNAME%:F\" SYSTEM:F Administrators:F) or choose another key_path; "
                                       "an existing key file is never changed automatically.")
        key = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        raise IntegrityError("the store key file is unreadable or malformed") from None
    if len(key) < MIN_KEY_BYTES:
        raise IntegrityError("the store key file holds a too short key")
    return key


# ---- inter-process lock ------------------------------------------------------------------------------------------------------------------------
# What 'somebody else holds the lock' looks like: POSIX flock(LOCK_NB) raises BlockingIOError (EAGAIN/EWOULDBLOCK, on some file systems EACCES); Windows
# msvcrt.locking(LK_NBLCK) raises PermissionError (EACCES, "Locking violation"); the Win32 codes are ACCESS_DENIED 5, SHARING_VIOLATION 32, LOCK_VIOLATION 33.
# Everything else is reported immediately with its real cause instead of being retried until the timeout.
_CONTENTION_ERRNOS = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}


def _is_contention(exc: OSError) -> bool:
    return isinstance(exc, (BlockingIOError, PermissionError)) or exc.errno in _CONTENTION_ERRNOS or getattr(exc, "winerror", None) in (5, 32, 33)


class _FileLock:
    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self._path, self._timeout, self._fh = path, timeout, None

    def __enter__(self) -> "_FileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a+b")
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                if sys.platform.startswith("win"):
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as exc:
                if not _is_contention(exc):                     # EBADF, ENOLCK, EINVAL, ...: a real problem, not 'somebody else holds the lock'
                    self._fh.close()
                    raise ImprovementError(f"the proposal store could not be locked ({type(exc).__name__}: {exc.strerror or exc})") from exc
                if time.monotonic() > deadline:
                    self._fh.close()
                    raise ImprovementError("the proposal store is locked by another process") from None
                time.sleep(0.02)

    def __exit__(self, *exc: object) -> None:
        try:
            if sys.platform.startswith("win"):
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class JsonProposalStore(ProposalStore):
    def __init__(self, path: str | os.PathLike[str], key: bytes, max_items: int = 200) -> None:
        if not isinstance(key, (bytes, bytearray)) or len(key) < MIN_KEY_BYTES:
            raise IntegrityError("a store key of at least 32 bytes is required")
        self.path, self._key, self._max = Path(path), bytes(key), max_items
        self._lock = threading.RLock()
        self._seq_seen = 0
        self.load_warning = ""
        try:
            self._read()
        except IntegrityError as exc:
            self.load_warning = str(exc)

    # ---- reading (always verified) -------------------------------------------------------------------------------------------------------
    def _mac(self, payload: dict) -> str:
        return hmac.new(self._key, _canonical(payload), hashlib.sha256).hexdigest()

    @property
    def _lock_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".lock")

    def _read(self) -> tuple[int, dict[str, Proposal]]:
        """Verified read UNDER the inter-process lock. The file is only ever opened or replaced while that lock is held: on Windows a file that another process has
        open cannot be replaced (no FILE_SHARE_DELETE, os.replace -> PermissionError [WinError 5]), so an unlocked reader made concurrent writers fail. Callers that
        already hold the lock (save) use _read_unlocked - the lock is not re-entrant across handles."""
        if not self.path.exists():                       # nothing to open: no lock (and no directory) needed; a file that appears later is simply not part of this snapshot
            return self._seq_seen, {}
        with _FileLock(self._lock_path):
            return self._read_unlocked()

    def _read_unlocked(self) -> tuple[int, dict[str, Proposal]]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return self._seq_seen, {}
        except OSError as exc:
            raise IntegrityError(f"the proposal file is unreadable ({type(exc).__name__})") from None
        try:
            doc = json.loads(raw.decode("utf-8"))
            mac = doc.pop("mac")
            if doc.get("format") != FORMAT or not isinstance(doc.get("seq"), int) or not isinstance(doc.get("proposals"), list):
                raise ValueError("format")
            if not isinstance(mac, str) or not hmac.compare_digest(mac, self._mac(doc)):
                raise ValueError("mac")
            items = [Proposal.from_dict(d) for d in doc["proposals"]]
        except Exception as exc:  # noqa: BLE001 - every defect is the same outcome: the store is not trusted
            self._quarantine(raw)
            raise IntegrityError(f"the proposal file failed its integrity check ({type(exc).__name__}); it was kept untouched and is not used") from None
        if doc["seq"] < self._seq_seen:
            raise IntegrityError("the proposal file is older than one already seen (rollback)")
        self._seq_seen = doc["seq"]
        return doc["seq"], {p.proposal_id: p for p in items}

    def _quarantine(self, raw: bytes) -> None:
        try:
            self.path.with_suffix(self.path.suffix + ".tampered").write_bytes(raw)
        except OSError:
            pass

    # ---- ProposalStore ---------------------------------------------------------------------------------------------------------------------
    def get(self, proposal_id: str) -> Proposal:
        with self._lock:
            try:
                return self._read()[1][proposal_id]
            except KeyError:
                raise UnknownProposalError(f"unknown proposal {proposal_id!r}") from None

    def list(self) -> list[Proposal]:
        with self._lock:
            return sorted(self._read()[1].values(), key=lambda p: p.created_at, reverse=True)

    def save(self, proposal: Proposal) -> Proposal:
        with self._lock, _FileLock(self._lock_path):
            seq, items = self._read_unlocked()              # verified; raises IntegrityError and writes nothing if the file is not trusted
            cur = items.get(proposal.proposal_id)
            if (cur.rev if cur else 0) != proposal.rev:
                raise ConcurrentUpdateError(f"proposal {proposal.proposal_id} was changed by someone else (expected rev {proposal.rev}, stored {cur.rev if cur else 'none'})")
            stored = replace(proposal, rev=proposal.rev + 1)
            items[stored.proposal_id] = stored
            while len(items) > self._max:
                victim = next((p.proposal_id for p in sorted(items.values(), key=lambda p: p.created_at) if p.is_terminal), None)
                if victim is None:
                    break
                del items[victim]
            doc = {"format": FORMAT, "seq": seq + 1, "proposals": [p.to_dict() for p in items.values()]}
            doc["mac"] = self._mac(doc)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(doc, ensure_ascii=True, indent=1))
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.replace(tmp, self.path)
            except PermissionError as exc:                  # something outside this store (e.g. a virus scanner) holds the file: report it, keep the old file, no retry loop
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise ImprovementError("the proposal file is in use by another program (replace refused); nothing was written") from exc
            self._seq_seen = seq + 1
            return stored
