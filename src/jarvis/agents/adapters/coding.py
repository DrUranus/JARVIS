"""CodingAgent: the `coding` tool as an agent. `halt`/`resume` are not actions of the tool and therefore not available here either."""
from __future__ import annotations

from jarvis.agents import policy as P
from jarvis.agents.adapters.base import ToolSpec, ToolStepAgent

_ACTIONS = {**{a: P.CODING_READ for a in ("status", "start", "stop", "info", "list", "read", "search", "changes", "git")},
            "write": P.CODING_WRITE, "delete": P.CODING_WRITE, "test": P.CODING_TEST, "plan": P.CODING_PLAN}
_PARAMS = frozenset({"action", "workspace", "session", "path", "pattern", "glob", "ignore_case", "content", "old_text", "new_text", "mode",
                     "expected_sha256", "runner", "args", "sub", "goal", "paths", "offset", "limit", "recursive", "include_tests"})


class CodingAgent(ToolStepAgent):
    id = "coding"
    name = "Coding Agent"
    description = "Analyses, changes and tests a project inside one confirmed workspace through the permission-checked coding tool."
    capabilities = frozenset({P.CODING_READ, P.CODING_WRITE, P.CODING_TEST, P.CODING_PLAN})
    tools = {"coding": ToolSpec(_PARAMS, _ACTIONS)}
    interruptible_actions = frozenset({"test"})   # a running test run is stopped through the coding agent's own halt when the task is cancelled
