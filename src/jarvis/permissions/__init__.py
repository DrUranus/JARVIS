"""Permission levels (Phase 13 will build the full policy engine on this)."""
from __future__ import annotations

from enum import Enum


class PermissionLevel(str, Enum):
    GREEN = "green"    # automatically allowed
    YELLOW = "yellow"  # needs explicit user confirmation
    RED = "red"        # never executed; not overridable via configuration


def is_allowed(level: PermissionLevel, confirmed: bool = False) -> bool:
    """RED is always denied, YELLOW only when confirmed, GREEN always."""
    if level is PermissionLevel.RED:
        return False
    if level is PermissionLevel.YELLOW:
        return confirmed
    return True
