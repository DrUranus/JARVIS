"""Builds the self-repair engine (opt-in) on top of the multi-agent layer. Never raises: JARVIS starts without it."""
from __future__ import annotations

import atexit
import logging
from dataclasses import dataclass
from typing import Any

from jarvis.config import Settings
from jarvis.self_repair.engine import RepairEngine

log = logging.getLogger("jarvis.self_repair")


@dataclass
class SelfRepairSubsystem:
    status: str                                    # disabled | enabled
    reason: str = ""
    engine: RepairEngine | None = None

    @property
    def available(self) -> bool:
        return self.engine is not None

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason}
        if self.engine is not None:
            info.update(self.engine.describe())
        return info


def build_self_repair(settings: Settings, agents: Any, coding: Any = None) -> SelfRepairSubsystem:
    cfg = settings.self_repair
    if not cfg.enabled:
        return SelfRepairSubsystem("disabled", "self-repair is off (self_repair.enabled = false)")
    if agents is None or getattr(agents, "orchestrator", None) is None or getattr(agents, "planner", None) is None:
        return SelfRepairSubsystem("disabled", "self-repair needs the multi-agent layer (agents.enabled = true)")
    if coding is None or not getattr(coding, "available", False):
        return SelfRepairSubsystem("disabled", "self-repair needs the coding agent (coding.enabled = true)")
    try:
        engine = RepairEngine(agents.orchestrator, agents.planner, max_attempts=cfg.max_attempts, repair_timeout=cfg.repair_timeout_seconds,
                              step_timeout=cfg.step_timeout_seconds, max_active=cfg.max_active_repairs, max_history=cfg.max_history)
        atexit.register(engine.shutdown)
    except Exception as exc:  # noqa: BLE001 - whatever happens here, JARVIS still starts
        log.warning("self-repair unavailable: %s", type(exc).__name__)
        return SelfRepairSubsystem("disabled", f"could not be built ({type(exc).__name__})")
    log.info("self-repair enabled (max %d attempts)", cfg.max_attempts)
    return SelfRepairSubsystem("enabled", "", engine)
