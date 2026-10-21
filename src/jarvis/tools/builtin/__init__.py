"""Minimal built-in tools proving the plug-in mechanism."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.permissions import ActionSpec, PermissionLevel, ResourceType
from jarvis.tools.base import ProtectedTool, Tool, ToolParameter, ToolResult
from jarvis.tools.registry import ToolRegistry


class EchoTool(Tool):
    name = "echo"
    description = "Return the given text unchanged."
    parameters = (ToolParameter("text", "Text to echo"),)
    permission = PermissionLevel.GREEN

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok(str(kwargs["text"]))


class TimeTool(Tool):
    name = "current_time"
    description = "Return the current local date and time (ISO 8601)."
    permission = PermissionLevel.GREEN

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok(datetime.now().astimezone().isoformat(timespec="seconds"))


class PermissionDemoTool(ProtectedTool):
    """Harmless: touches nothing. Exists so the whole confirmation chain (/run permission_demo target=notes.txt)
    can be tried by hand without any real filesystem tool."""
    name = "permission_demo"
    description = "Demo of the permission flow: pretends to modify a file in the workspace (does nothing)."
    parameters = (ToolParameter("target", "Path inside the workspace"),)
    permission = PermissionLevel.YELLOW

    def describe_action(self, **kwargs: Any) -> ActionSpec:
        return ActionSpec(action="write", resource=str(kwargs["target"]), resource_type=ResourceType.PATH,
                          reason="Demonstration der Berechtigungsprüfung (es wird nichts verändert)")

    def _perform(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok(f"demo: would modify {kwargs['target']} (nothing was touched)")


def register_builtin_tools(registry: ToolRegistry, include_demo: bool = False) -> ToolRegistry:
    tools: list[Tool] = [EchoTool(), TimeTool()]
    if include_demo:
        tools.append(PermissionDemoTool())
    for tool in tools:
        registry.register(tool, replace=True)
    return registry
