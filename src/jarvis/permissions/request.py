"""Structured permission requests. Built by the code that wants to act; judged by the engine."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from jarvis.errors import InvalidRequestError
from jarvis.permissions.levels import PermissionLevel
from jarvis.permissions.resources import ResourceType

_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$")
MAX_RESOURCE, MAX_REASON, MAX_CONTEXT_ITEMS, MAX_CONTEXT_VALUE = 4096, 500, 20, 500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _has_control(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


@dataclass(frozen=True)
class PermissionRequest:
    """What is about to happen. `level` is the *requested* level; the engine may only raise it, never lower it."""
    tool: str                      # e.g. "filesystem", "terminal", "email" (any identifier; the engine knows no tools)
    action: str                    # e.g. "read", "write", "delete", "send"
    level: PermissionLevel
    resource: str | None = None    # path, host, account... the action targets
    resource_type: ResourceType = ResourceType.NONE
    reason: str = ""               # why JARVIS wants to do it (shown to the user)
    context: Mapping[str, str] = field(default_factory=dict)  # small extra facts (shown to the user, audited)
    args_fingerprint: str | None = None  # binds an approval to the exact arguments of the call
    id: str = field(default_factory=_new_id)
    timestamp: datetime = field(default_factory=_utcnow)

    def validate(self) -> None:
        """Raise InvalidRequestError for anything malformed. The engine calls this itself, so requests built
        by hand (bypassing `create`) are checked too."""
        for name, value in (("tool", self.tool), ("action", self.action)):
            if not isinstance(value, str) or not _IDENT.match(value):
                raise InvalidRequestError(f"{name} must be an identifier (letters, digits, _ . : -; max 64)")
        if not isinstance(self.level, PermissionLevel):
            raise InvalidRequestError("level must be a PermissionLevel")
        if not isinstance(self.resource_type, ResourceType):
            raise InvalidRequestError("resource_type must be a ResourceType")
        if self.resource_type is ResourceType.NONE:
            if self.resource is not None:
                raise InvalidRequestError("a resource was given without a resource_type")
        else:
            if not isinstance(self.resource, str) or not self.resource.strip():
                raise InvalidRequestError(f"resource_type {self.resource_type.value!r} requires a resource")
            if len(self.resource) > MAX_RESOURCE or _has_control(self.resource):
                raise InvalidRequestError("resource too long or contains control characters")
        if not isinstance(self.reason, str) or len(self.reason) > MAX_REASON or _has_control(self.reason.replace("\n", " ")):
            raise InvalidRequestError("reason must be a short plain string")
        if not isinstance(self.context, Mapping) or len(self.context) > MAX_CONTEXT_ITEMS:
            raise InvalidRequestError("context must be a small mapping")
        for k, v in self.context.items():
            if not isinstance(k, str) or not isinstance(v, str) or len(k) > 50 or len(v) > MAX_CONTEXT_VALUE:
                raise InvalidRequestError("context keys/values must be short strings")
        if self.args_fingerprint is not None and (not isinstance(self.args_fingerprint, str) or len(self.args_fingerprint) > 128):
            raise InvalidRequestError("invalid args_fingerprint")
        if not isinstance(self.id, str) or not self.id or len(self.id) > 64:
            raise InvalidRequestError("invalid request id")
        if not isinstance(self.timestamp, datetime):
            raise InvalidRequestError("timestamp must be a datetime")

    @classmethod
    def create(cls, **fields: Any) -> "PermissionRequest":
        """Validated construction (raises InvalidRequestError)."""
        try:
            req = cls(**fields)
        except TypeError as exc:
            raise InvalidRequestError(f"malformed permission request: {exc}") from exc
        req.validate()
        return req

    def __repr__(self) -> str:
        """Free-text fields (resource, reason, context) are deliberately left out: they may contain secrets that
        no pattern can recognise, and reprs end up in logs and tracebacks."""
        return (f"PermissionRequest(id={self.id!r}, tool={self.tool!r}, action={self.action!r}, "
                f"level={getattr(self.level, 'value', self.level)!r}, "
                f"resource_type={getattr(self.resource_type, 'value', self.resource_type)!r}, "
                f"has_resource={self.resource is not None})")


@dataclass(frozen=True)
class ActionSpec:
    """What a tool says about one concrete call. The registry turns it into a PermissionRequest; the tool never
    talks to the engine itself, so it cannot skip or shape the decision."""
    action: str = "run"
    resource: str | None = None
    resource_type: ResourceType = ResourceType.NONE
    level: PermissionLevel | None = None  # None = the tool's declared level
    reason: str = ""
    context: Mapping[str, str] = field(default_factory=dict)
