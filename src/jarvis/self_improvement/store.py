"""Proposal storage. The JSON store writes atomically (temp file + rename), keeps at most `max_items` proposals and never overwrites a file it could not
read: an unreadable file is left untouched (copied to *.corrupt) and the store starts empty in memory only until the next successful save."""
from __future__ import annotations

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from jarvis.self_improvement.errors import UnknownProposalError
from jarvis.self_improvement.models import Proposal

log = logging.getLogger("jarvis.self_improvement")


class ProposalStore(ABC):
    @abstractmethod
    def save(self, proposal: Proposal) -> None: ...

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

    def save(self, proposal: Proposal) -> None:
        with self._lock:
            self._items[proposal.proposal_id] = proposal
            while len(self._items) > self._max:
                victim = next((k for k, v in self._items.items() if v.is_terminal), None)
                if victim is None:
                    break
                del self._items[victim]

    def get(self, proposal_id: str) -> Proposal:
        with self._lock:
            try:
                return self._items[proposal_id]
            except KeyError:
                raise UnknownProposalError(f"unknown proposal {proposal_id!r}") from None

    def list(self) -> list[Proposal]:
        with self._lock:
            return sorted(self._items.values(), key=lambda p: p.created_at, reverse=True)


class JsonProposalStore(MemoryProposalStore):
    def __init__(self, path: str | os.PathLike[str], max_items: int = 200) -> None:
        super().__init__(max_items)
        self.path = Path(path)
        self.load_warning = ""
        self._load()

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            self.load_warning = f"proposal file unreadable ({type(exc).__name__})"
            return
        try:
            data = json.loads(raw)
            items = [Proposal.from_dict(d) for d in data["proposals"]]
        except Exception as exc:  # noqa: BLE001 - a damaged file must never crash startup nor be overwritten
            self.load_warning = f"proposal file is damaged ({type(exc).__name__}); it was kept as .corrupt and is not overwritten"
            try:
                self.path.with_suffix(self.path.suffix + ".corrupt").write_text(raw, encoding="utf-8")
            except OSError:
                pass
            self._readonly = True
            return
        for p in items:
            self._items[p.proposal_id] = p

    _readonly = False

    def save(self, proposal: Proposal) -> None:
        with self._lock:
            super().save(proposal)
            if self._readonly:
                return
            payload = json.dumps({"version": 1, "proposals": [p.to_dict() for p in self._items.values()]}, ensure_ascii=False, indent=1)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.path)
