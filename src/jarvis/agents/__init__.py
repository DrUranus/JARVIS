"""Multi-agent architecture v1: an orchestrator that lets the existing agents (browser, coding, computer, research) work on structured
tasks - controlled, bounded and cancellable. Agents act only through ToolRegistry -> PermissionEngine; this layer adds no capability.
The Core does not import this package; `bootstrap` builds it (opt-in)."""
from jarvis.agents.agent import Agent, validate_agent
from jarvis.agents.context import AgentContext, ParentResult, ToolGateway
from jarvis.agents.errors import (AgentError, DuplicateError, InvalidAgentError, InvalidTaskError, StateError, TaskCancelled, ToolAccessError,
                                  UnknownAgentError)
from jarvis.agents.models import AgentTask
from jarvis.agents.orchestrator import AgentOrchestrator, CancelReport
from jarvis.agents.planner import AgentPlanner, Selection
from jarvis.agents.registry import AgentRegistry
from jarvis.agents.result import AgentOutcome, AgentResult
from jarvis.agents.state import AgentState, AgentStatus, TaskStatus

__all__ = ["Agent", "validate_agent", "AgentContext", "ParentResult", "ToolGateway", "AgentError", "DuplicateError", "InvalidAgentError",
           "InvalidTaskError", "StateError", "TaskCancelled", "ToolAccessError", "UnknownAgentError", "AgentTask", "AgentOrchestrator",
           "CancelReport", "AgentPlanner", "Selection", "AgentRegistry", "AgentOutcome", "AgentResult", "AgentState", "AgentStatus", "TaskStatus"]
