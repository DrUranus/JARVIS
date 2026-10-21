"""Errors of the goal layer. Runtime conditions (a step failed, a goal timed out) are states of the goal, not exceptions; these are for
programmer errors: malformed models, illegal status transitions, invalid plans, unknown goals."""
from __future__ import annotations

from jarvis.errors import JarvisError


class GoalError(JarvisError):
    """Base class of the goal layer."""


class InvalidGoalError(GoalError):
    """A goal, step or result is malformed."""


class InvalidPlanError(GoalError):
    """A plan failed validation; nothing of it was executed."""


class PlanningError(GoalError):
    """The planner cannot (or may not) make a plan for this objective. `blocked` tells the engine to end the goal BLOCKED."""


class GoalStateError(GoalError):
    """Illegal status transition."""


class UnknownGoalError(GoalError):
    pass
