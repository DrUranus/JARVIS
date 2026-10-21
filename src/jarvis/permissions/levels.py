"""Permission levels."""
from __future__ import annotations

from enum import Enum


class PermissionLevel(str, Enum):
    GREEN = "green"    # safe; may run automatically
    YELLOW = "yellow"  # meaningful consequences; needs explicit confirmation (or a deliberately configured rule)
    RED = "red"        # dangerous/prohibited; always denied, never overridable by configuration

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {PermissionLevel.GREEN: 0, PermissionLevel.YELLOW: 1, PermissionLevel.RED: 2}


def max_level(*levels: PermissionLevel) -> PermissionLevel:
    """The most restrictive of the given levels."""
    return max(levels, key=lambda lv: lv.rank)


def is_allowed(level: PermissionLevel, confirmed: bool = False) -> bool:
    """Legacy Phase-1 helper: RED is always denied, YELLOW only when confirmed, GREEN always.
    New code goes through PermissionEngine instead."""
    if level is PermissionLevel.RED:
        return False
    if level is PermissionLevel.YELLOW:
        return confirmed
    return True
