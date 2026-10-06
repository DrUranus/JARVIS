"""Minimal built-in tools proving the plug-in mechanism."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.tools.base import Tool, ToolParameter, ToolResult
from jarvis.tools.registry import ToolRegistry


class EchoTool(Tool):
    name = "echo"
    description = "Return the given text unchanged."
    parameters = (ToolParameter("text", "Text to echo"),)

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok(str(kwargs["text"]))


class TimeTool(Tool):
    name = "current_time"
    description = "Return the current local date and time (ISO 8601)."

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok(datetime.now().astimezone().isoformat(timespec="seconds"))


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    for tool in (EchoTool(), TimeTool()):
        registry.register(tool, replace=True)
    return registry
