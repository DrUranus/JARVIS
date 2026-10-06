"""Temporary permissions and execution grants.

* One-time permission = the decision for exactly one request; it is consumed when the call executes.
* Session permission = an explicit "allow for this session" answer, bound to the exact
  (tool, action, resource, level) and expiring; it never widens to other actions or resources.
* Persistent permission = an explicit allow rule in the configured policy (see policy.py); nothing is learned or
  stored implicitly.
* ExecutionGrant = proof, valid only inside one engine-issued scope, that *this* call with *these* arguments was
  approved. ProtectedTool.run() refuses to run without it.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping

from jarvis.errors import PermissionDeniedError
from jarvis.permissions.levels import PermissionLevel
from jarvis.permissions.resources import ResourceType


@dataclass(frozen=True)
class SessionKey:
    tool: str
    action: str
    resource_type: ResourceType
    resource: str | None   # the normalised resource (real path / host): symlink aliases share one key
    level: PermissionLevel


class SessionGrants:
    """Thread-safe, bounded, expiring store for session permissions."""

    def __init__(self, ttl_seconds: float = 3600.0, clock: Callable[[], float] = time.monotonic,
                 max_grants: int = 100) -> None:
        self._ttl, self._clock, self._max = ttl_seconds, clock, max_grants
        self._grants: dict[SessionKey, float] = {}
        self._lock = threading.RLock()

    def _purge(self) -> None:
        now = self._clock()
        for k in [k for k, exp in self._grants.items() if exp <= now]:
            del self._grants[k]

    def add(self, key: SessionKey) -> bool:
        """False if the store is full (the caller then falls back to a one-time permission)."""
        with self._lock:
            self._purge()
            if key not in self._grants and len(self._grants) >= self._max:
                return False
            self._grants[key] = self._clock() + self._ttl
            return True

    def has(self, key: SessionKey) -> bool:
        with self._lock:
            self._purge()
            return key in self._grants

    def revoke_all(self) -> int:
        with self._lock:
            n = len(self._grants)
            self._grants.clear()
            return n

    def keys(self) -> list[SessionKey]:
        with self._lock:
            self._purge()
            return list(self._grants)


# --- execution grants ---------------------------------------------------------------------------------
_SEAL = object()  # only the engine module-set knows it; accidental construction elsewhere fails
_current: ContextVar["ExecutionGrant | None"] = ContextVar("jarvis_execution_grant", default=None)


@dataclass(frozen=True)
class ExecutionGrant:
    tool: str
    action: str
    fingerprint: str | None
    request_id: str
    resource: str | None = field(default=None, repr=False)  # the approved, normalised resource (real path / host)
    _seal: object = None

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise PermissionDeniedError("execution grants can only be issued by the permission engine")


def args_fingerprint(tool: str, kwargs: Mapping[str, Any]) -> str:
    """Stable digest of one call (tool + arguments). Approvals are bound to it."""
    blob = json.dumps({"tool": tool, "args": dict(kwargs)}, sort_keys=True, default=repr, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def current_grant() -> ExecutionGrant | None:
    return _current.get()


@contextmanager
def _enter_scope(grant: ExecutionGrant) -> Iterator[ExecutionGrant]:
    token = _current.set(grant)
    try:
        yield grant
    finally:
        _current.reset(token)


def verify_execution(tool: str, kwargs: Mapping[str, Any]) -> ExecutionGrant:
    """Called by ProtectedTool.run(): raises unless this exact call was approved by the engine."""
    grant = _current.get()
    if grant is None:
        raise PermissionDeniedError(f"tool {tool!r} must be executed through the permission engine")
    if grant.tool != tool or grant.fingerprint != args_fingerprint(tool, kwargs):
        raise PermissionDeniedError(f"the approval does not cover this call of {tool!r}")
    return grant
