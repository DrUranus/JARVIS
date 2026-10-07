"""Status objects of the three analysis capabilities (research / business / finance) for /research, /business, /finance. They only DESCRIBE: enabled,
registered agent, active tasks, limits, capabilities. They hold no capability of their own and run nothing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jarvis.agents.state import TaskStatus
from jarvis.config import Settings


@dataclass
class AnalysisSubsystem:
    name: str                              # research | business | finance
    status: str                            # enabled | disabled
    reason: str = ""
    agent_id: str = ""
    capabilities: tuple[str, ...] = ()
    limits: dict[str, Any] = field(default_factory=dict)
    agents: Any = None                     # the AgentsSubsystem (duck-typed)

    @property
    def available(self) -> bool:
        return self.status == "enabled"

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"name": self.name, "status": self.status, "reason": self.reason, "agent": self.agent_id, "capabilities": list(self.capabilities),
                                "limits": dict(self.limits), "registered": False, "agent_status": None, "active_tasks": 0}
        reg = getattr(self.agents, "registry", None)
        orch = getattr(self.agents, "orchestrator", None)
        if reg is not None and self.agent_id and reg.has(self.agent_id):
            agent = reg.get(self.agent_id)
            info.update(registered=True, agent_status=agent.status.value, agent_reason=agent.state.reason)
        if orch is not None:
            info["active_tasks"] = sum(1 for r in orch.list() if r.agent_id == self.agent_id and r.status in (TaskStatus.PENDING, TaskStatus.RUNNING))
        return info


def build_analysis_subsystems(settings: Settings, agents: Any) -> dict[str, AnalysisSubsystem]:
    r, b, f = settings.research, settings.business, settings.finance
    layer_on = agents is not None and getattr(agents, "orchestrator", None) is not None
    specs = {
        "research": (r.enabled, "research", ("research.web",), {"max_sources": r.max_sources, "max_actions": r.max_actions, "timeout_seconds": r.timeout_seconds,
                                                                 "max_result_chars": r.max_result_chars, "tool": "browser (permission-checked)"}),
        "business": (b.enabled, "business", ("business.analyze",), {"max_steps": b.max_steps, "timeout_seconds": b.timeout_seconds, "max_result_chars": b.max_result_chars,
                                                                     "tools": "none (analysis and drafts only; sends nothing)"}),
        "finance": (f.enabled, "finance", ("finance.analyze",), {"max_steps": f.max_steps, "timeout_seconds": f.timeout_seconds, "paper_trading_only": f.paper_trading_only,
                                                                  "max_risk_per_trade_pct": f.max_risk_per_trade_pct, "max_position_pct": f.max_position_pct,
                                                                  "max_total_exposure_pct": f.max_total_exposure_pct, "daily_loss_limit_pct": f.daily_loss_limit_pct,
                                                                  "max_leverage": f.max_leverage, "tools": "none (no broker, no orders, no transfers)"}),
    }
    out = {}
    for name, (enabled, agent_id, caps, limits) in specs.items():
        if not enabled:
            out[name] = AnalysisSubsystem(name, "disabled", f"{name} is off ({name}.enabled = false)", agent_id, caps, limits, agents)
        elif not layer_on:
            out[name] = AnalysisSubsystem(name, "disabled", f"{name} needs the multi-agent layer (agents.enabled = true)", agent_id, caps, limits, agents)
        else:
            out[name] = AnalysisSubsystem(name, "enabled", "", agent_id, caps, limits, agents)
    return out
