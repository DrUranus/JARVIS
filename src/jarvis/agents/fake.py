"""FakeAgent for tests and dry runs: configurable behaviour, synchronisation through Events (no sleeps), a shared concurrency probe.
It performs no real action; with `tool_calls` it can exercise the ToolGateway, which still goes through the real ToolRegistry."""
from __future__ import annotations

import threading
from typing import Any

from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentOutcome


class ConcurrencyProbe:
    """Counts how many fake agents are inside perform() at the same moment (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.total = 0

    def enter(self) -> None:
        with self._lock:
            self.current += 1
            self.total += 1
            self.peak = max(self.peak, self.current)

    def leave(self) -> None:
        with self._lock:
            self.current -= 1


class FakeAgent(Agent):
    """behavior: success | failure | blocked | crash | cancelled | wait (blocks until released or cancelled) | hang (blocks until released,
    ignores cancellation)."""

    def __init__(self, agent_id: str = "fake", capabilities: frozenset[str] | set[str] = frozenset({"research.web"}), *,
                 behavior: str = "success", output: Any = None, summary: str = "done", tool_names: frozenset[str] = frozenset(),
                 tool_calls: list[tuple[str, dict[str, Any]]] | None = None, probe: ConcurrencyProbe | None = None,
                 supports_cancellation: bool = True, name: str | None = None) -> None:
        super().__init__()
        self.id = agent_id
        self.name = name or agent_id.title()
        self.description = f"fake agent ({behavior})"
        self.capabilities = frozenset(capabilities)
        self.tool_names = frozenset(tool_names)
        self.supports_cancellation = supports_cancellation
        self.behavior, self.output, self.summary = behavior, output, summary
        self.tool_calls = tool_calls or []
        self.probe = probe
        self.started = threading.Event()      # set when perform() was entered
        self.release = threading.Event()      # set by the test to let `wait`/`hang` finish
        self.cancel_calls: list[str] = []
        self.tasks: list[AgentTask] = []
        self.contexts: list[AgentContext] = []
        self.tool_results: list[Any] = []

    def perform(self, task: AgentTask, ctx: AgentContext) -> AgentOutcome:
        self.tasks.append(task)
        self.contexts.append(ctx)
        if self.probe:
            self.probe.enter()
        self.started.set()
        try:
            for tool, args in self.tool_calls:
                self.tool_results.append(ctx.tools.call(tool, **args) if ctx.tools else None)
            b = self.behavior
            if b == "crash":
                raise RuntimeError("fake agent exploded with token=abc123456789")
            if b == "failure":
                return AgentOutcome.failed("the fake agent failed", code="fake_failure")
            if b == "blocked":
                return AgentOutcome.blocked("the fake agent was blocked", code="fake_blocked")
            if b == "cancelled":
                return AgentOutcome.cancelled()
            if b == "wait":
                self.release.wait()          # woken by the test (release) or by cancel() below; no polling
                ctx.check_cancelled()
            elif b == "hang":
                self.release.wait()
            return AgentOutcome.ok(self.summary, self.output)
        finally:
            if self.probe:
                self.probe.leave()

    def cancel(self, task_id: str) -> None:
        self.cancel_calls.append(task_id)
        if self.behavior == "wait":
            self.release.set()  # a cooperative agent wakes up when it is cancelled
