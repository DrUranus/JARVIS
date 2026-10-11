"""Structured security/audit log. Replaceable via AuditSink; secrets are redacted centrally before any sink
sees an event. Ordinary conversation is never logged here, only security-relevant events."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from jarvis.redaction import SecretDetector

log = logging.getLogger("jarvis.security")


class AuditEventType(str, Enum):
    PERMISSION_REQUESTED = "permission_requested"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    CONFIRMATION_REQUESTED = "confirmation_requested"
    CONFIRMATION_ACCEPTED = "confirmation_accepted"
    CONFIRMATION_REJECTED = "confirmation_rejected"
    SESSION_GRANT_CREATED = "session_grant_created"
    SESSION_GRANTS_REVOKED = "session_grants_revoked"
    POLICY_LOADED = "policy_loaded"
    POLICY_CHANGED = "policy_changed"
    TOOL_REGISTERED = "tool_registered"
    EXECUTION_RESULT = "execution_result"
    CALLER_CONFIRMATION_IGNORED = "caller_confirmation_ignored"
    SECURITY_ERROR = "security_error"
    IMPROVEMENT = "improvement"     # self-improvement lifecycle event (tool="self_improvement")


@dataclass(frozen=True)
class AuditEvent:
    type: AuditEventType
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    request_id: str | None = None
    tool: str | None = None
    action: str | None = None
    resource: str | None = None
    level: str | None = None
    status: str | None = None
    rule: str | None = None
    scope: str | None = None
    detail: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        return {k: v for k, v in d.items() if v not in (None, "", {})}


class AuditSink(ABC):
    @abstractmethod
    def record(self, event: AuditEvent) -> None:
        """Persist the event. Raise on failure (the AuditLogger decides what a failure means)."""

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        return []


class NullAuditSink(AuditSink):
    def record(self, event: AuditEvent) -> None:
        pass


class MemoryAuditSink(AuditSink):
    """Bounded in-process log (tests, `/audit` without a file)."""

    def __init__(self, max_events: int = 1000) -> None:
        self.events: deque[AuditEvent] = deque(maxlen=max_events)

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        return [e.to_dict() for e in list(self.events)[-n:]]


class LoggingAuditSink(AuditSink):
    def record(self, event: AuditEvent) -> None:
        log.info("audit %s", json.dumps(event.to_dict(), ensure_ascii=False))


class JsonlAuditSink(AuditSink):
    """Append-only JSON Lines file (owner-only permissions where the OS supports it). Created on first event."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(line)

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        except OSError:
            return []
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except ValueError:
                out.append({"type": "unreadable_line"})
        return out


class AuditLogger:
    """Redacts every string of an event, then fans out to the sinks. `record` returns True only if every
    sink accepted the event, so the engine can fail closed when auditing is broken."""

    def __init__(self, sinks: Iterable[AuditSink] = (), redactor: SecretDetector | None = None) -> None:
        self.sinks = list(sinks)
        self._redactor = redactor or SecretDetector()

    def _clean(self, event: AuditEvent) -> AuditEvent:
        r = self._redactor.redact
        data = {k: (r(v) if isinstance(v, str) else v) for k, v in event.__dict__.items() if k != "extra"}
        data["extra"] = self._redactor.redact_mapping(event.extra)
        data["type"] = event.type
        return AuditEvent(**data)

    def record(self, event: AuditEvent) -> bool:
        try:
            clean = self._clean(event)
        except Exception:  # never let a logging problem escape, and never log the unredacted event
            log.exception("audit event could not be sanitised; dropped")
            return False
        ok = True
        for sink in self.sinks:
            try:
                sink.record(clean)
            except Exception as exc:
                ok = False
                log.error("audit sink %s failed: %s", type(sink).__name__, type(exc).__name__)
        return ok

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        for sink in self.sinks:
            events = sink.tail(n)
            if events:
                return events
        return []
