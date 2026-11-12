"""WP02b: budgets PER AGENT (neutral module: the configuration validates with it, so it imports nothing from the agent layer; the agent layer imports it directly) - time, tool calls per task, tool calls per session, artifact size. Pure data and counters: no I/O, no permissions, no money.

An agent budget can only LOWER what the global limits already allow (`agents.task_timeout_seconds`, `agents.tool_call_limit`, the artifact hard limit): a value above them is refused
when the table is built, and at run time the stricter of the two always wins. Nothing here raises a limit, resets a counter or reads a configuration; the table is immutable and a
new orchestrator is a new session. The session call counter is atomic, so tasks of the same agent running in parallel cannot jointly exceed the total.

Table entry (text, so it fits the configuration): ``agent;max_seconds;max_tool_calls;max_calls_session;max_artifact_chars`` - empty field = no limit of that kind, at least one limit.
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from jarvis.errors import JarvisError

MAX_CALLS_SESSION_HARD = 1_000_000
MAX_ARTIFACT_CHARS_HARD = 100_000     # = agents.policy.MAX_INPUT_BYTES (a test keeps them equal; this module must not import the agent layer: the configuration validates with it)
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,31}$")   # = agents.policy.AGENT_ID_RE (kept equal by a test)
_INT = re.compile(r"^[0-9]{1,9}$")


class BudgetError(JarvisError):
    """The budget table is invalid (or cannot be applied). Raised at start-up / build time - never while a task runs."""


@dataclass(frozen=True)
class AgentBudget:
    max_seconds: float | None = None
    max_tool_calls: int | None = None
    max_calls_session: int | None = None
    max_artifact_chars: int | None = None

    def __post_init__(self) -> None:
        if self.max_seconds is not None and (isinstance(self.max_seconds, bool) or not isinstance(self.max_seconds, (int, float)) or not math.isfinite(self.max_seconds) or self.max_seconds <= 0):
            raise BudgetError("max_seconds must be a positive, finite number")
        for name, value, hard in (("max_tool_calls", self.max_tool_calls, 5000), ("max_calls_session", self.max_calls_session, MAX_CALLS_SESSION_HARD),
                                  ("max_artifact_chars", self.max_artifact_chars, MAX_ARTIFACT_CHARS_HARD)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= hard):
                raise BudgetError(f"{name} must be a whole number between 1 and {hard}")
        if self.max_seconds is None and self.max_tool_calls is None and self.max_calls_session is None and self.max_artifact_chars is None:
            raise BudgetError("an agent budget needs at least one limit")


def _whole(text: str, name: str) -> int | None:
    t = text.strip()
    if not t:
        return None
    if not _INT.match(t):
        raise BudgetError(f"{name} must be a whole number")
    return int(t)


def parse_entry(entry: object, *, global_timeout: float, global_tool_calls: int) -> tuple[str, AgentBudget]:
    if not isinstance(entry, str):
        raise BudgetError("a budget entry must be text 'agent;max_seconds;max_tool_calls;max_calls_session;max_artifact_chars'")
    parts = entry.split(";")
    if len(parts) != 5:
        raise BudgetError("a budget entry needs exactly five fields: agent;max_seconds;max_tool_calls;max_calls_session;max_artifact_chars")
    agent = parts[0].strip()
    if not AGENT_ID_RE.match(agent):
        raise BudgetError("the agent id of a budget entry is not a valid agent id")
    seconds: float | None = None
    if parts[1].strip():
        try:
            seconds = float(parts[1].strip())
        except ValueError:
            raise BudgetError("max_seconds must be a number") from None
    budget = AgentBudget(seconds, _whole(parts[2], "max_tool_calls"), _whole(parts[3], "max_calls_session"), _whole(parts[4], "max_artifact_chars"))
    if budget.max_seconds is not None and budget.max_seconds > global_timeout:
        raise BudgetError(f"max_seconds of {agent!r} is above the global task timeout {global_timeout:g}: a budget can only lower it")
    if budget.max_tool_calls is not None and budget.max_tool_calls > global_tool_calls:
        raise BudgetError(f"max_tool_calls of {agent!r} is above the global tool call limit {global_tool_calls}: a budget can only lower it")
    return agent, budget


class AgentBudgets:
    """Immutable table agent id -> AgentBudget plus the atomic per-session call counters."""

    def __init__(self, by_agent: Mapping[str, AgentBudget] | None = None) -> None:
        self._by_agent = MappingProxyType(dict(by_agent or {}))
        self._lock = threading.Lock()
        self._used: dict[str, int] = {}

    @classmethod
    def from_entries(cls, entries: Iterable[object], *, global_timeout: float, global_tool_calls: int) -> "AgentBudgets":
        table: dict[str, AgentBudget] = {}
        for entry in entries:
            agent, budget = parse_entry(entry, global_timeout=global_timeout, global_tool_calls=global_tool_calls)
            if agent in table:
                raise BudgetError(f"agent {agent!r} has more than one budget entry")
            table[agent] = budget
        return cls(table)

    def get(self, agent_id: str) -> AgentBudget | None:
        return self._by_agent.get(agent_id)

    @property
    def agents(self) -> frozenset[str]:
        return frozenset(self._by_agent)

    def reserve_call(self, agent_id: str, limit: int) -> bool:
        """Books one tool call against the session total of the agent - atomically: of N parallel callers exactly the first `limit` get True."""
        with self._lock:
            used = self._used.get(agent_id, 0)
            if used >= limit:
                return False
            self._used[agent_id] = used + 1
            return True

    def session_calls(self, agent_id: str) -> int:
        with self._lock:
            return self._used.get(agent_id, 0)
