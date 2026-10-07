"""AgentRegistry: the agents that exist. Plain object, no global state: every orchestrator gets its own."""
from __future__ import annotations

import threading

from jarvis.agents.agent import Agent, validate_agent
from jarvis.agents.errors import DuplicateError, StateError, UnknownAgentError
from jarvis.agents.state import AgentStatus


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._lock = threading.RLock()

    def register(self, agent: Agent) -> Agent:
        validate_agent(agent)
        with self._lock:
            if agent.id in self._agents:
                raise DuplicateError(f"agent id {agent.id!r} is already registered")
            self._agents[agent.id] = agent
        return agent

    def unregister(self, agent_id: str) -> Agent:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise UnknownAgentError(f"unknown agent {str(agent_id)[:40]!r}")
            if agent.status is AgentStatus.BUSY:
                raise StateError(f"agent {agent_id!r} is busy and cannot be removed")
            return self._agents.pop(agent_id)

    def get(self, agent_id: str) -> Agent:
        with self._lock:
            try:
                return self._agents[agent_id]
            except (KeyError, TypeError):
                raise UnknownAgentError(f"unknown agent {str(agent_id)[:40]!r}") from None

    def has(self, agent_id: str) -> bool:
        with self._lock:
            try:
                return agent_id in self._agents
            except TypeError:
                return False

    def list(self) -> list[Agent]:
        with self._lock:
            return sorted(self._agents.values(), key=lambda a: a.id)

    def find(self, required: frozenset[str], *, include_unavailable: bool = False) -> list[Agent]:
        """Agents offering every required capability (DISABLED/FAILED ones only if asked), by id."""
        with self._lock:
            return [a for a in sorted(self._agents.values(), key=lambda a: a.id) if required <= a.capabilities
                    and (include_unavailable or a.status in (AgentStatus.AVAILABLE, AgentStatus.BUSY))]

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, agent_id: object) -> bool:
        return self.has(agent_id)  # type: ignore[arg-type]
