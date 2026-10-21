"""What an agent gets to see: AgentContext (explicit data) and ToolGateway (the one door to the outside world).

The gateway is NOT a second permission system. It only (a) limits an agent to the tools it declared, (b) refuses the legacy
bypass arguments, (c) bounds the number of calls and stops them when the task is cancelled. Every call it forwards is an
ordinary ToolRegistry.execute: the PermissionEngine decides, asks the user, audits."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

from jarvis.agents.errors import TaskCancelled, ToolAccessError
from jarvis.agents.policy import RESERVED_TOOL_ARGS
from jarvis.agents.state import TaskStatus
from jarvis.tools import ToolRegistry, ToolResult


class ToolGateway:
    def __init__(self, registry: ToolRegistry | None, allowed: frozenset[str], cancel: threading.Event, max_calls: int = 200) -> None:
        self._registry = registry
        self._allowed = frozenset(allowed)
        self._cancel = cancel
        self._max = max_calls
        self._calls = 0

    @property
    def allowed_tools(self) -> frozenset[str]:
        return self._allowed

    def available(self, tool: str) -> bool:
        """Is the tool both declared for this agent and present in the registry (i.e. is its subsystem enabled)?"""
        return self._registry is not None and tool in self._allowed and tool in self._registry

    def call(self, tool: str, **kwargs: Any) -> ToolResult:
        if self._cancel.is_set():
            raise TaskCancelled("the task was cancelled")
        if tool not in self._allowed:
            raise ToolAccessError(f"this agent may not use the tool {str(tool)[:40]!r}")
        bad = RESERVED_TOOL_ARGS & set(kwargs)
        if bad:
            raise ToolAccessError(f"arguments {sorted(bad)} are not accepted: permissions cannot be pre-confirmed or bypassed")
        if self._registry is None or tool not in self._registry:
            return ToolResult.fail(f"tool {tool!r} is not available (its subsystem is not enabled)")
        if self._calls >= self._max:
            raise ToolAccessError(f"this task used its budget of {self._max} tool calls")
        self._calls += 1
        return self._registry.execute(tool, **kwargs)

    @property
    def calls(self) -> int:
        return self._calls


@dataclass(frozen=True)
class ParentResult:
    """A finished task whose result was handed on: structured data only."""
    task_id: str
    agent_id: str | None
    status: TaskStatus
    summary: str
    output: Any


@dataclass(frozen=True)
class AgentContext:
    task_id: str
    objective: str
    input: Mapping[str, Any]
    allowed_capabilities: frozenset[str]            # the task's required capabilities (the agent may do no more than these)
    relevant_memory: tuple[str, ...] = ()           # only what the orchestrator was explicitly asked to fetch (memory_query)
    parent_results: Mapping[str, ParentResult] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)
    tools: ToolGateway | None = field(default=None, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise TaskCancelled("the task was cancelled")

    def __repr__(self) -> str:  # objective, input and memory can contain anything
        return f"AgentContext(task_id={self.task_id!r}, capabilities={sorted(self.allowed_capabilities)})"
