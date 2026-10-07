"""The Agent interface. An agent receives ONE task and a controlled context and returns a structured outcome.

An agent never holds a controller, a provider, the permission engine, the Core or the memory database. Whatever it does in the
world it does through `ctx.tools` (a ToolGateway: the ordinary ToolRegistry -> PermissionEngine path, limited to the tools the
agent declares in `tool_names`)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from jarvis.agents.context import AgentContext
from jarvis.agents.errors import InvalidAgentError
from jarvis.agents.models import AgentTask
from jarvis.agents.policy import valid_agent_id, valid_capability
from jarvis.agents.result import AgentOutcome
from jarvis.agents.state import AgentState, AgentStatus


class Agent(ABC):
    id: str
    name: str
    description: str
    capabilities: frozenset[str] = frozenset()
    tool_names: frozenset[str] = frozenset()   # the only tools ctx.tools will give this agent
    supports_cancellation: bool = True          # does perform() poll ctx.check_cancelled()/is_cancelled()?

    def __init__(self) -> None:
        self.state = AgentState()

    @property
    def status(self) -> AgentStatus:
        return self.state.status

    @abstractmethod
    def perform(self, task: AgentTask, ctx: AgentContext) -> AgentOutcome:
        """Do the task. Report problems as AgentOutcome.failed/blocked, not by raising (a raised exception is caught by the
        orchestrator, marks the agent FAILED and becomes a FAILED result)."""

    def cancel(self, task_id: str) -> None:
        """Called (from another thread) when the task is cancelled or timed out. Cooperative: stop at the next safe point."""

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description, "capabilities": sorted(self.capabilities),
                "tools": sorted(self.tool_names), "status": self.status.value, "reason": self.state.reason,
                "supports_cancellation": self.supports_cancellation}


def validate_agent(agent: object) -> None:
    """Raise InvalidAgentError unless `agent` can be registered."""
    if not isinstance(agent, Agent):
        raise InvalidAgentError("an agent must be an instance of jarvis.agents.Agent")
    if not valid_agent_id(getattr(agent, "id", None)):
        raise InvalidAgentError("agent id must be a short lower-case identifier (letters, digits, _ -)")
    for attr in ("name", "description"):
        v = getattr(agent, attr, None)
        if not isinstance(v, str) or not v.strip() or len(v) > 300:
            raise InvalidAgentError(f"agent {attr} must be a short text")
    caps = getattr(agent, "capabilities", None)
    if not isinstance(caps, (set, frozenset)) or not caps or not all(valid_capability(c) for c in caps):
        raise InvalidAgentError("agent capabilities must be a non-empty set of names like 'coding.read'")
    tools = getattr(agent, "tool_names", None)
    if not isinstance(tools, (set, frozenset)) or not all(isinstance(t, str) and t for t in tools):
        raise InvalidAgentError("agent tool_names must be a set of tool names")
    if not isinstance(getattr(agent, "state", None), AgentState):
        raise InvalidAgentError("agent.state is missing (call super().__init__())")
