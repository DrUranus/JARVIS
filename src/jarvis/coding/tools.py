"""The coding tool. A ProtectedTool in the ordinary ToolRegistry: every call goes through the one PermissionEngine
(request -> decision -> optional confirmation -> single-use approval -> run). The tool only DESCRIBES a call (the controller's
plan: precise resource, level, reason, change summary) and, once approved, asks the controller to execute a freshly built
plan. There is no `confirmed`/`force` parameter, and no way to pass a command line.

Levels: status/info/list/read/search/changes/git(read-only)/stop GREEN | start, write, delete, test, plan YELLOW |
secret files, .git internals, mutating git, executable file types, paths outside the workspace RED.
`halt` and `resume` are deliberately NOT actions: only the user (CLI) can stop and release the agent.
"""
from __future__ import annotations

from typing import Any

from jarvis.coding import resources as res
from jarvis.coding.controller import CodingController, Plan
from jarvis.coding.errors import CodingError
from jarvis.errors import ToolError
from jarvis.permissions import ActionSpec, PermissionLevel
from jarvis.tools import ToolParameter, ToolRegistry, ToolResult
from jarvis.tools.base import ProtectedTool

_KEYS = ("session", "workspace", "path", "pattern", "glob", "ignore_case", "content", "old_text", "new_text", "mode", "expected_sha256",
         "runner", "args", "sub", "goal", "paths", "offset", "limit", "recursive", "include_tests")


class CodingTool(ProtectedTool):
    name = res.TOOL
    description = (
        "Work on a software project inside one confirmed workspace, one verifiable step per call. Session: start workspace=<dir> | status | stop. "
        "Read: info | list [path] | read path | search pattern [glob] | changes | git sub=status|diff|log. "
        "Change: write path mode=create|overwrite|replace (content | old_text+new_text, expected_sha256 from `read`) | delete path. "
        "Verify: test [runner=pytest|python -m pytest|python -m unittest|npm test] [args=...]. Plan: plan goal=... paths=a.py,b.py. "
        "No shell, no arbitrary commands; secrets, .env and .git internals are never read or written; commit/push are not available.")
    permission = PermissionLevel.GREEN  # reading is GREEN; every plan raises the level for what it really does
    parameters = (
        ToolParameter("action", "start|status|stop|info|list|read|search|changes|git|write|delete|test|plan"),
        ToolParameter("workspace", "directory to work in (start)", required=False),
        ToolParameter("session", "session id (optional safety check)", required=False),
        ToolParameter("path", "path relative to the workspace", required=False),
        ToolParameter("pattern", "text to search for (search)", required=False),
        ToolParameter("glob", "file name filter such as *.py (search)", required=False),
        ToolParameter("ignore_case", "true|false (search)", type="boolean", required=False),
        ToolParameter("content", "new file text (write mode=create|overwrite)", required=False),
        ToolParameter("old_text", "text to replace; must occur exactly once (write mode=replace)", required=False),
        ToolParameter("new_text", "replacement text (write mode=replace)", required=False),
        ToolParameter("mode", "create|overwrite|replace (write)", required=False),
        ToolParameter("expected_sha256", "sha256 of the file as read; the write is refused if it changed", required=False),
        ToolParameter("runner", "pytest | python -m pytest | python -m unittest | npm test (test)", required=False),
        ToolParameter("args", "extra test arguments from a small allow-list, e.g. -x -q tests/test_a.py", required=False),
        ToolParameter("sub", "status|diff|log (git; read-only)", required=False),
        ToolParameter("goal", "what to achieve (plan)", required=False),
        ToolParameter("paths", "comma separated files to include (plan)", required=False),
        ToolParameter("offset", "first line to return (read)", type="integer", required=False),
        ToolParameter("limit", "maximum lines / entries", type="integer", required=False),
        ToolParameter("recursive", "true|false (list)", type="boolean", required=False),
        ToolParameter("include_tests", "include the last test result (plan)", type="boolean", required=False))

    def __init__(self, controller: CodingController) -> None:
        self._c = controller

    def _plan(self, kw: dict[str, Any], phase: str) -> Plan:
        return self._c.plan(kw.get("action"), phase=phase, **{k: kw.get(k) for k in _KEYS})

    def describe_action(self, **kwargs: Any) -> ActionSpec:
        return self._plan(kwargs, "describe").to_spec()  # read-only; invalid input raises CodingError -> the call is denied

    def _perform(self, **kwargs: Any) -> ToolResult:
        try:
            plan = self._plan(kwargs, "perform")  # rebuilt from the CURRENT state and compared with what the user was shown
            return ToolResult.ok(self._c.execute(plan))
        except CodingError as exc:
            return ToolResult(False, exc.to_dict(), str(exc))


def register_coding_tools(registry: ToolRegistry, controller: CodingController) -> list[str]:
    engine = registry.permissions
    if not engine.require_protected_tools or engine.trust_caller_confirmation:
        raise ToolError("coding tools need a strict permission engine (require_protected_tools, no caller confirmation)")
    registry.register(CodingTool(controller))
    return [res.TOOL]
