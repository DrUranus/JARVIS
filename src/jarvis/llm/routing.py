"""LLM routing policy (docs/LLM_ROUTING.md, step llm-routing-policy).

`route` is a PURE function: (task class, data class, settings) -> chosen provider or a rejection with a reason. No I/O, no clock, no globals.
Rules implemented: local is the default; `secret`/`never` data never reaches the cloud (not even with approval); `personal` data only with an
explicit per-call approval; `vision` only for public data with approval; `speech` never; no silent fallback to the cloud (a rejection instead);
unknown classes fail closed. With routing disabled (default) the single configured provider is returned unchanged.

`LLMRouter` wraps it with the audit event `llm_route` (metadata only). It is wired in `bootstrap.py`; callers must pass the classes themselves --
a model never chooses them. It does not call any provider and does not replace the tool permission path (`ToolRegistry.execute` -> PermissionEngine).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping
from enum import Enum

from jarvis.config import RoutingSettings


class TaskClass(str, Enum):
    CHAT = "chat"
    PLAN = "plan"
    CODE = "code"
    RESEARCH = "research"
    VISION = "vision"
    SPEECH = "speech"


class DataClass(str, Enum):
    PUBLIC = "public"
    PERSONAL = "personal"
    SECRET = "secret"
    NEVER = "never"


class RouteTarget(str, Enum):
    SINGLE = "single"      # routing off: the one configured provider
    LOCAL = "local"
    CLOUD = "cloud"
    NONE = "none"          # rejected


@dataclass(frozen=True)
class RouteDecision:
    allowed: bool
    provider: str          # "" when rejected
    target: RouteTarget
    reason: str


def _deny(reason: str) -> RouteDecision:
    return RouteDecision(False, "", RouteTarget.NONE, reason)


def _coerce(enum_cls, value):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value) if isinstance(value, str) else None
    except ValueError:
        return None


def route(task, data, config: RoutingSettings, *, default_provider: str, approved: bool = False) -> RouteDecision:
    """Choose a provider. `approved` = the caller obtained an explicit one-off approval for THIS call (never a session right)."""
    t, d = _coerce(TaskClass, task), _coerce(DataClass, data)
    if t is None or d is None:
        return _deny("unknown_class")
    if not config.enabled:
        return RouteDecision(True, default_provider, RouteTarget.SINGLE, "routing_disabled")

    def local_or(reason: str) -> RouteDecision:
        # never turns into a cloud call: either the configured local provider, or a rejection
        if config.local_provider:
            return RouteDecision(True, config.local_provider, RouteTarget.LOCAL, reason)
        return _deny("no_local_provider")

    if d in (DataClass.SECRET, DataClass.NEVER):
        return local_or("data_class_never_cloud")
    if t is TaskClass.SPEECH:
        return local_or("speech_never_cloud")
    if not config.cloud_provider:
        return local_or("cloud_not_configured")
    if t.value not in config.cloud_tasks:
        return local_or("task_not_enabled_for_cloud")
    if d is DataClass.PERSONAL and (not approved or t is TaskClass.VISION):
        return local_or("approval_required" if t is not TaskClass.VISION else "vision_personal_never_cloud")
    if t is TaskClass.VISION and not approved:
        return local_or("approval_required")
    return RouteDecision(True, config.cloud_provider, RouteTarget.CLOUD, "cloud_allowed")


class LLMRouter:
    """Audit wrapper around `route`: every decision (also rejections and the disabled case) is handed to `audit` (metadata only; bootstrap turns it
    into an `llm_route` audit event -- this package must not import `jarvis.permissions`). `audit` returns False/raises if nothing could be written:
    then cloud targets are refused (fail closed); local/single ones still run."""

    def __init__(self, config: RoutingSettings, *, default_provider: str, audit: Callable[[Mapping[str, str]], bool]) -> None:
        self._config, self._default, self._audit = config, default_provider, audit

    def decide(self, task, data, *, approved: bool = False, size: int = 0) -> RouteDecision:
        dec = route(task, data, self._config, default_provider=self._default, approved=approved)
        task_s = task.value if isinstance(task, Enum) else str(task)[:20]
        data_s = data.value if isinstance(data, Enum) else str(data)[:20]
        event = {"status": "allowed" if dec.allowed else "denied", "rule": dec.reason, "task": task_s, "data": data_s, "target": dec.target.value,
                 "provider": dec.provider, "approved": str(bool(approved)).lower(), "size": str(max(0, int(size)))}
        try:
            written = bool(self._audit(event))
        except Exception:
            written = False
        if not written and dec.target is RouteTarget.CLOUD:
            return _deny("audit_unavailable")
        return dec
