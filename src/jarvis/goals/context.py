"""GoalContext: the ONLY information a goal step gets besides its own objective - what the user passed explicitly, plus the results
of finished steps of this goal. There is no link to the global memory or to other goals."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from jarvis.goals import policy as P
from jarvis.goals.errors import InvalidGoalError
from jarvis.goals.models import GoalStep, GoalStepResult


def check_user_context(ctx: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate what the user explicitly releases for a goal: only known keys, plain data, bounded, no bypass-style keys."""
    if ctx is None:
        return {}
    if not isinstance(ctx, Mapping):
        raise InvalidGoalError("context must be a mapping")
    if len(ctx) > P.MAX_CONTEXT_ITEMS:
        raise InvalidGoalError("too many context entries")
    unknown = sorted(str(k)[:30] for k in ctx if k not in P.CONTEXT_KEYS)
    if unknown:
        raise InvalidGoalError(f"unknown context keys {unknown}; allowed: {sorted(P.CONTEXT_KEYS)}")
    try:
        P.check_plain(ctx, "context")
    except ValueError as exc:
        raise InvalidGoalError(str(exc)) from None
    bad = P.find_reserved(ctx)
    if bad:
        raise InvalidGoalError(f"the context key {bad!r} is not allowed")
    import json
    if len(json.dumps(P.plain_copy(ctx))) > P.MAX_INPUT_BYTES:
        raise InvalidGoalError("the context is too large")
    return P.plain_copy(ctx)


@dataclass(frozen=True)
class GoalContext:
    goal_id: str
    objective: str = field(repr=False)
    current_step: GoalStep | None = None
    previous_step_results: tuple[GoalStepResult, ...] = ()
    explicit_user_context: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def result_of(self, step_id: str) -> GoalStepResult | None:
        return next((r for r in self.previous_step_results if r.step_id == step_id), None)
