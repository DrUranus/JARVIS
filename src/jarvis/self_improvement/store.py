"""Proposal storage with integrity protection.

Nothing read from the store is trusted merely because it is in the file. The JSON store signs the whole file with HMAC-SHA256 (key held OUTSIDE the data
directory, see `load_key`) and verifies the signature on EVERY read. A file that fails verification (edited status, forged approval, replaced proposal, wrong key,
older/newer format) makes the store unavailable - reads and writes raise IntegrityError, the file is left untouched (a copy is kept as *.tampered) - instead of
being "repaired". Writes are compare-and-swap per proposal (`rev`), serialised by an OS file lock, so concurrent threads/processes cannot overwrite each other's
changes (ConcurrentUpdateError) and a stale in-memory copy can never silently revert a newer state.

Limits: the HMAC proves that the file was written by someone holding the key; it cannot prevent that holder from writing, and it cannot detect a replay of an
OLDER validly signed file after a restart (within one process a falling sequence number is detected)."""
from __future__ import annotations

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
def load_key(env: Mapping[str, str], key_path: str | os.PathLike[str]) -> bytes:
    """The HMAC key: JARVIS_SELF_IMPROVEMENT_STORE_KEY (hex, >= 32 bytes) or a key file that is created (owner-only) on first use. The caller has already
    checked that the file lies outside the data directory and outside every root the coding tools may write to."""
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
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(secrets.token_hex(MIN_KEY_BYTES) + "\n")
    try:
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise IntegrityError("the store key file must not be readable by group/others (chmod 600)")
        key = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        raise IntegrityError("the store key file is unreadable or malformed") from None
    if len(key) < MIN_KEY_BYTES:
        raise IntegrityError("the store key file holds a too short key")
    return key


# ---- inter-process lock ------------------------------------------------------------------------------------------------------------------------
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
            except OSError:
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

    def _read(self) -> tuple[int, dict[str, Proposal]]:
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
        with self._lock, _FileLock(self.path.with_suffix(self.path.suffix + ".lock")):
            seq, items = self._read()                       # verified; raises IntegrityError and writes nothing if the file is not trusted
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
            os.replace(tmp, self.path)
            self._seq_seen = seq + 1
            return stored
