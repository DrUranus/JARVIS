"""Structured permission decisions (never a bare boolean)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from jarvis.permissions.levels import PermissionLevel


class DecisionStatus(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    INVALID_REQUEST = "invalid_request"      # malformed request: denied
    POLICY_ERROR = "policy_error"            # broken policy/configuration: denied
    INTERNAL_ERROR = "internal_error"        # unexpected failure inside the engine: denied (fail closed)


class GrantScope(str, Enum):
    AUTOMATIC = "automatic"    # GREEN
    ONCE = "once"              # the user confirmed exactly this call
    SESSION = "session"        # earlier "allow for this session" for this exact action+resource
    PERSISTENT = "persistent"  # explicit allow rule from the configured policy
    ASSERTED = "asserted"      # caller-asserted confirmation (legacy registries only; never in the app)


@dataclass(frozen=True)
class PermissionDecision:
    status: DecisionStatus
    reason: str                            # human readable, secrets redacted
    request_id: str | None = None
    level: PermissionLevel | None = None   # effective level after the engine's own escalation
    matched_rule: str | None = None        # rule id or built-in invariant name that decided
    scope: GrantScope | None = None        # only for ALLOWED
    considered_rules: tuple[str, ...] = ()  # every rule that matched (conflicts are visible here)
    resolved_resource: str | None = None   # normalised resource (real path / host) a tool should use

    @property
    def allowed(self) -> bool:
        return self.status is DecisionStatus.ALLOWED

    @property
    def needs_confirmation(self) -> bool:
        return self.status is DecisionStatus.CONFIRMATION_REQUIRED

    @property
    def denied(self) -> bool:
        return not self.allowed and not self.needs_confirmation

    @property
    def is_error(self) -> bool:
        return self.status in (DecisionStatus.INVALID_REQUEST, DecisionStatus.POLICY_ERROR, DecisionStatus.INTERNAL_ERROR)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "reason": self.reason, "request_id": self.request_id,
                "level": self.level.value if self.level else None, "matched_rule": self.matched_rule,
                "scope": self.scope.value if self.scope else None, "considered_rules": list(self.considered_rules),
                "resolved_resource": self.resolved_resource}
