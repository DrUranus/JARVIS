"""Builds the goal engine (opt-in) on top of the multi-agent layer. Never raises: JARVIS starts without it."""
from __future__ import annotations

import atexit
import logging
from dataclasses import dataclass
from typing import Any

from jarvis.config import Settings
from jarvis.goals.engine import GoalEngine
from jarvis.goals.planner import GoalPlanner

log = logging.getLogger("jarvis.goals")


@dataclass
class GoalsSubsystem:
    status: str                                    # disabled | enabled
    reason: str = ""
    engine: GoalEngine | None = None
    planner: GoalPlanner | None = None

    @property
    def available(self) -> bool:
        return self.engine is not None

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason}
        if self.engine is not None:
            info.update(self.engine.describe())
        return info


def build_goals(settings: Settings, agents: Any) -> GoalsSubsystem:
    cfg = settings.goals
    if not cfg.enabled:
        return GoalsSubsystem("disabled", "the goal engine is off (goals.enabled = false)")
    if agents is None or getattr(agents, "orchestrator", None) is None or getattr(agents, "planner", None) is None:
        return GoalsSubsystem("disabled", "the goal engine needs the multi-agent layer (agents.enabled = true)")
    try:
        planner = GoalPlanner(agents.planner, max_attempts=cfg.max_attempts_per_step, step_timeout=cfg.step_timeout_seconds)
        engine = GoalEngine(agents.orchestrator, planner, max_steps=cfg.max_steps, max_attempts=cfg.max_attempts_per_step,
                            goal_timeout=cfg.goal_timeout_seconds, step_timeout=cfg.step_timeout_seconds, max_active=cfg.max_active_goals,
                            max_history=cfg.max_history)
        atexit.register(engine.shutdown)
    except Exception as exc:  # noqa: BLE001 - whatever happens here, JARVIS still starts
        log.warning("goal engine unavailable: %s", type(exc).__name__)
        return GoalsSubsystem("disabled", f"could not be built ({type(exc).__name__})")
    log.info("goal engine enabled (max %d steps, %d attempts per step)", cfg.max_steps, cfg.max_attempts_per_step)
    return GoalsSubsystem("enabled", "", engine, planner)
