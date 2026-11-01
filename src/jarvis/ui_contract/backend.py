"""The interface a backend offers to a user interface (Control Center, tests, later other clients). The real backend (strand A) and the fake (`fake.py`) implement it;
a transport (strand B) carries it over loopback. The interface is deliberately small: events out, commands in, nothing else."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class UiBackend(ABC):
    @abstractmethod
    def hello(self) -> dict[str, Any]:
        """The hello event (always the first event of a snapshot): contract version, backend name, capabilities, emergency stop state."""

    @abstractmethod
    def snapshot(self) -> list[dict[str, Any]]:
        """The current picture as validated events, hello first, strictly ascending `seq`: hello, latest state, latest activity, latest emergency and, if one is open,
        the pending confirmation request."""

    @abstractmethod
    def events_since(self, seq: int, limit: int = 200) -> list[dict[str, Any]]:
        """Validated events with `seq` greater than the given one, in order, at most `limit` (1..1000). Replay for a client that reconnects."""

    @abstractmethod
    def send(self, command: dict[str, Any]) -> dict[str, Any]:
        """Handle one command and return its `ack` event. A malformed or unknown command is answered with ok=false (code `invalid_command`), never an exception and never ok=true.
        While the emergency stop is engaged only emergency_stop, reset_emergency (a request only) and request_snapshot are served."""

    @abstractmethod
    def detach(self) -> None:
        """The client is gone (window closed, connection lost): every open confirmation closes as `cancelled`, which means DENIED (fail closed); voice stops."""
