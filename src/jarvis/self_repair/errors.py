"""Errors of the self-repair layer. Runtime conditions (tests fail, a repair is refused) are states of the run, not exceptions;
these are for programmer errors: malformed models or contexts, illegal status transitions, unknown runs."""
from __future__ import annotations

from jarvis.errors import JarvisError


class RepairError(JarvisError):
    """Base class of the self-repair layer."""


class InvalidRepairError(RepairError):
    """A run, attempt, context or result is malformed."""


class RepairStateError(RepairError):
    """Illegal status transition."""


class UnknownRepairError(RepairError):
    pass


class PlanBlocked(RepairError):
    """The repair planner cannot (or may not) make a plan; the run ends BLOCKED (or FAILED once attempts were already made)."""
