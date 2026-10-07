"""Builds the multi-agent subsystem and hands it to the composition root. Never raises: JARVIS starts without it.

The adapters are registered for every known tool; an agent whose tool is not present (its subsystem is off) is registered DISABLED with
the reason, so /agents shows the whole picture and nothing can be sent to it.
"""
from __future__ import annotations

import atexit
import logging
from dataclasses import dataclass
from typing import Any, Callable

from jarvis.agents.adapters import BrowserAgent, CodingAgent, ComputerAgent, ResearchAgent
from jarvis.agents.agent import Agent
from jarvis.agents.errors import AgentError
from jarvis.agents.models import AgentTask
from jarvis.agents.orchestrator import AgentOrchestrator
from jarvis.agents.planner import AgentPlanner, Selection
from jarvis.agents.registry import AgentRegistry
from jarvis.agents.result import AgentResult
from jarvis.agents.state import AgentStatus, TaskStatus
from jarvis.config import Settings
from jarvis.memory import MemoryStore
from jarvis.tasks import TaskManager
from jarvis.tools import ToolRegistry

log = logging.getLogger("jarvis.agents")


@dataclass
class AgentsSubsystem:
    status: str                                    # disabled | enabled
    reason: str = ""
    orchestrator: AgentOrchestrator | None = None
    planner: AgentPlanner | None = None
    registry: AgentRegistry | None = None

    @property
    def available(self) -> bool:
        return self.orchestrator is not None

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason}
        if self.orchestrator is not None and self.registry is not None:
            info.update(agents=[a.describe() for a in self.registry.list()], active=self.orchestrator.active_agents,
                        queued=self.orchestrator.queued, max_concurrent=self.orchestrator.max_concurrent)
        return info

    def select(self, objective: str, required: frozenset[str] = frozenset()) -> Selection:
        if self.planner is None:
            return Selection(None, reason="the multi-agent layer is off")
        return self.planner.select(objective, required)

    def delegate(self, objective: str, input: dict[str, Any] | None = None, *, agent_id: str | None = None,
                 required_capabilities: frozenset[str] = frozenset(), **task_kw: Any) -> AgentResult:
        """Core entry point: pick an agent (explicit, or by the planner) and run ONE task. Returns an AgentResult (never raises for runtime
        conditions). The agent acts only through the permission-checked tools."""
        if self.orchestrator is None:
            raise AgentError("the multi-agent layer is off (agents.enabled = false)")
        caps = frozenset(required_capabilities)
        if agent_id is None:
            sel = self.select(objective, caps)
            if not sel.found:
                return AgentResult("-", None, TaskStatus.BLOCKED, sel.reason, None, sel.reason, "no_suitable_agent")
            agent_id, caps = sel.agent_id, caps | sel.capabilities
        return self.orchestrator.run(AgentTask(objective, agent_id=agent_id, input=input or {}, required_capabilities=caps, **task_kw))


def _interrupt_of(core_subsystems: dict[str, Any], name: str) -> Callable[[], Any] | None:
    sub = core_subsystems.get(name)
    return (lambda: sub.halt("agent task cancelled")) if sub is not None and getattr(sub, "available", False) and hasattr(sub, "halt") else None


def build_agents(settings: Settings, tools: ToolRegistry, memory: MemoryStore | None, task_manager: TaskManager,
                 subsystems: dict[str, Any]) -> AgentsSubsystem:
    cfg = settings.agents
    if not cfg.enabled:
        return AgentsSubsystem("disabled", "multi-agent orchestration is off (agents.enabled = false)")
    try:
        registry = AgentRegistry()
        lookup = None
        if memory is not None and getattr(memory, "enabled", False):
            lookup = lambda q, n: [e.content for e in memory.search(q, limit=n)]  # noqa: E731 - read-only, explicit query only
        orch = AgentOrchestrator(registry, tools=tools, max_concurrent=cfg.max_concurrent, default_timeout=cfg.task_timeout_seconds,
                                 max_queue=cfg.max_queue, max_history=cfg.max_history, cancel_grace=cfg.cancel_grace_seconds,
                                 tool_call_limit=cfg.tool_call_limit, max_output_chars=cfg.max_output_chars, task_manager=task_manager,
                                 memory_lookup=lookup)
        agents: list[Agent] = [ResearchAgent(), BrowserAgent(), CodingAgent(interrupt=_interrupt_of(subsystems, "coding")), ComputerAgent()]
        for agent in agents:
            registry.register(agent)
            missing = sorted(t for t in agent.tool_names if t not in tools)
            if missing:
                agent.state.transition(AgentStatus.DISABLED, f"tool {', '.join(missing)} is not available (subsystem off)")
        atexit.register(orch.shutdown)
    except Exception as exc:  # noqa: BLE001 - whatever happens here, JARVIS still starts
        log.warning("multi-agent layer unavailable: %s", type(exc).__name__)
        return AgentsSubsystem("disabled", f"could not be built ({type(exc).__name__})")
    log.info("multi-agent layer enabled (%d agents, max %d concurrent)", len(registry), cfg.max_concurrent)
    return AgentsSubsystem("enabled", "", orch, AgentPlanner(registry), registry)
