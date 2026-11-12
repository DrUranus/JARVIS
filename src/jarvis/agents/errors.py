"""Errors of the multi-agent layer. Runtime conditions are reported in an AgentResult; these are for programmer errors
(invalid models, duplicate ids, illegal state transitions) and for the controlled internal signalling inside an agent."""
from __future__ import annotations

from jarvis.errors import JarvisError


class AgentError(JarvisError):
    """Base class of the multi-agent layer."""


class InvalidAgentError(AgentError):
    """An agent object does not satisfy the Agent interface."""


class InvalidTaskError(AgentError):
    """A task or result is malformed (bad id, bad input, wrong type)."""


class DuplicateError(AgentError):
    """An agent id or a task id is already in use."""


class UnknownAgentError(AgentError):
    pass


class StateError(AgentError):
    """Illegal status transition."""


class TaskCancelled(AgentError):
    """Raised inside an agent when its task was cancelled; the orchestrator turns it into a CANCELLED result."""


class ToolAccessError(AgentError):
    """An agent tried to use a tool it does not own, or tried to pass a bypass argument."""


class AgentBudgetExceeded(ToolAccessError):
    """The agent's own budget (WP02b: tool calls per task or per session) is used up. A ToolAccessError, so agents that already handle that stop the same way; the orchestrator
    turns the task into BLOCKED(agent_budget_exceeded) whatever the agent made of it."""
