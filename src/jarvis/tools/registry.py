"""Dynamic tool registry. Execution never raises: errors become ToolResult.fail."""
from __future__ import annotations

import logging
from typing import Any

from jarvis.errors import ToolError
from jarvis.permissions import is_allowed
from jarvis.tools.base import Tool, ToolResult

log = logging.getLogger("jarvis.tools")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool, replace: bool = False) -> None:
        name = getattr(tool, "name", None)
        if not name:
            raise ToolError("tool must define a non-empty name")
        if name in self._tools and not replace:
            raise ToolError(f"tool already registered: {name}")
        self._tools[name] = tool

    def unregister(self, name: str) -> None:
        if self._tools.pop(name, None) is None:
            raise ToolError(f"unknown tool: {name}")

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(f"unknown tool: {name}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe_all(self) -> list[dict[str, Any]]:
        return [self._tools[n].describe() for n in self.names()]

    def execute(self, name: str, confirmed: bool = False, **kwargs: Any) -> ToolResult:
        try:
            tool = self.get(name)
        except ToolError as exc:
            return ToolResult.fail(str(exc))
        if not is_allowed(tool.permission, confirmed):
            return ToolResult.fail(f"permission denied for tool {name!r} (level {tool.permission.value})")
        missing = [p.name for p in tool.parameters if p.required and p.name not in kwargs]
        if missing:
            return ToolResult.fail(f"missing parameters for {name!r}: {', '.join(missing)}")
        try:
            return tool.run(**kwargs)
        except Exception as exc:  # tools are untrusted plug-ins; isolate failures
            log.exception("tool %s crashed", name)
            return ToolResult.fail(f"{type(exc).__name__}: {exc}")
