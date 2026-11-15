"""V2.1 M1 as an optional PRE-RUN check of a goal plan (goals.plan_analysis, OFF by default). Wraps `plan_graph.analyse`; returns None (the plan may run) or a short reason made of
step ids and capability names only - never objectives, inputs or results. It executes nothing and grants nothing; the goal engine stays the only executor."""
from __future__ import annotations

from typing import Any, Callable, Sequence

from jarvis.agents.state import AgentStatus
from jarvis.goals import plan_graph


def make_plan_check(registry: Any, *, max_parallel: int = 3) -> Callable[[Sequence[Any]], str | None]:
    def check(steps: Sequence[Any]) -> str | None:
        caps = {c for a in registry.list() if a.status not in (AgentStatus.DISABLED, AgentStatus.FAILED) for c in a.capabilities}      # read at check time: disabled agents offer nothing
        a = plan_graph.analyse(plan_graph.from_steps(steps), capabilities=caps, available_tools=(), known_info=(), max_parallel=max(1, int(max_parallel)))
        if a.error:
            return f"the plan graph is invalid ({a.error})"
        if a.missing_capabilities:
            detail = "; ".join(f"{sid}: {', '.join(c)}" for sid, c in sorted(a.missing_capabilities.items()))[:300]
            return f"no available agent offers the capability needed by a step ({detail})"
        return None
    return check
