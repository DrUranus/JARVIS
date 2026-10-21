"""Plan validation: a plan is checked completely BEFORE the first step starts. An invalid plan raises InvalidPlanError and nothing runs."""
from __future__ import annotations

import json
from typing import Callable, Sequence

from jarvis.goals import policy as P
from jarvis.goals.errors import InvalidPlanError
from jarvis.goals.models import Goal, GoalStep
from jarvis.goals.state import StepStatus


def longest_chain(steps: Sequence[GoalStep]) -> int:
    """Number of steps on the longest dependency chain. Raises InvalidPlanError for a cycle (or an unknown dependency)."""
    by_id = {s.step_id: s for s in steps}
    state: dict[str, int] = {}     # 1 = visiting, 2 = done (value = depth in `depth`)
    depth: dict[str, int] = {}
    for root in steps:
        if state.get(root.step_id) == 2:
            continue
        stack: list[tuple[str, int]] = [(root.step_id, 0)]
        while stack:
            sid, idx = stack.pop()
            deps = by_id[sid].dependencies
            if idx == 0:
                if state.get(sid) == 1:
                    raise InvalidPlanError("the plan contains a dependency cycle")
                state[sid] = 1
            if idx < len(deps):
                stack.append((sid, idx + 1))
                d = deps[idx]
                if d not in by_id:
                    raise InvalidPlanError(f"step {sid!r} depends on the unknown step {d[:30]!r}")
                if state.get(d) == 1:
                    raise InvalidPlanError("the plan contains a dependency cycle")
                if state.get(d) != 2:
                    stack.append((d, 0))
            else:
                depth[sid] = 1 + max((depth[d] for d in deps), default=0)
                state[sid] = 2
    return max(depth.values(), default=0)


def validate_plan(goal: Goal, steps: Sequence[GoalStep], *, max_steps: int, max_depth: int = P.MAX_DEPTH_HARD,
                  max_attempts: int = P.MAX_ATTEMPTS_HARD, max_step_timeout: float = P.MAX_STEP_TIMEOUT,
                  agent_exists: Callable[[str], bool] | None = None) -> tuple[GoalStep, ...]:
    """Return the plan as a tuple if (and only if) it is sound."""
    if not isinstance(steps, (list, tuple)) or not steps:
        raise InvalidPlanError("the plan has no steps")
    limit = min(max_steps, P.MAX_STEPS_HARD)
    if len(steps) > limit:
        raise InvalidPlanError(f"the plan has {len(steps)} steps; at most {limit} are allowed")
    seen: set[str] = set()
    for s in steps:
        if not isinstance(s, GoalStep):
            raise InvalidPlanError("a plan consists of GoalStep objects only")
        if s.goal_id != goal.goal_id:
            raise InvalidPlanError("a step belongs to another goal")
        if s.step_id in seen:
            raise InvalidPlanError(f"duplicate step id {s.step_id!r}")
        seen.add(s.step_id)
        if s.status is not StepStatus.PENDING or s.result is not None or s.attempts != 0:
            raise InvalidPlanError(f"step {s.step_id!r} must start PENDING without a result")
        if s.max_attempts > min(max_attempts, P.MAX_ATTEMPTS_HARD):
            raise InvalidPlanError(f"step {s.step_id!r} allows more attempts than the limit ({max_attempts})")
        if s.timeout is not None and s.timeout > max_step_timeout:
            raise InvalidPlanError(f"step {s.step_id!r} has a timeout above the limit ({max_step_timeout:g} s)")
        bad = P.find_reserved(s.input)
        if bad:
            raise InvalidPlanError(f"step {s.step_id!r} contains the forbidden key {bad!r}")
        for cap in s.required_capabilities:
            if not P.valid_capability(cap) or cap not in P.KNOWN_CAPABILITIES:
                raise InvalidPlanError(f"step {s.step_id!r} needs the unknown capability {str(cap)[:40]!r}")
        try:
            if len(json.dumps(s.input)) > P.MAX_INPUT_BYTES:
                raise InvalidPlanError(f"the input of step {s.step_id!r} is too large")
        except (TypeError, ValueError):
            raise InvalidPlanError(f"the input of step {s.step_id!r} is not plain data") from None
        if s.is_evaluation:
            if s.required_capabilities or not s.dependencies:
                raise InvalidPlanError(f"evaluation step {s.step_id!r} must depend on other steps and needs no capability")
            continue
        if s.assigned_agent is None:
            raise InvalidPlanError(f"step {s.step_id!r} has no agent")
        if agent_exists is not None and not agent_exists(s.assigned_agent):
            raise InvalidPlanError(f"step {s.step_id!r} names the unknown agent {s.assigned_agent[:30]!r}")
        if not s.required_capabilities:
            raise InvalidPlanError(f"step {s.step_id!r} names no capability")
        steps_in = s.input.get("steps")
        url = s.input.get("url")
        if steps_in is not None:
            if not isinstance(steps_in, list) or not steps_in or not all(isinstance(x, dict) for x in steps_in):
                raise InvalidPlanError(f"step {s.step_id!r}: input.steps must be a list of tool steps")
        elif s.input.get("kind") is not None:
            if s.input["kind"] not in P.ANALYSIS_KINDS:
                raise InvalidPlanError(f"step {s.step_id!r}: unknown analysis kind {str(s.input['kind'])[:30]!r}")
        elif not P.valid_url(url):
            raise InvalidPlanError(f"step {s.step_id!r}: the input needs 'steps', an analysis 'kind' or a valid http(s) 'url'")
        clean = s.input.get("cleanup")
        if clean is not None and (not isinstance(clean, str) or clean not in {x.step_id for x in steps} or clean == s.step_id):
            raise InvalidPlanError(f"step {s.step_id!r}: cleanup must name another step of the plan")
    if longest_chain(steps) > min(max_depth, P.MAX_DEPTH_HARD):
        raise InvalidPlanError(f"the dependency chain is longer than {max_depth}")
    return tuple(steps)
