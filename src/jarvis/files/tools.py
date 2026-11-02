"""The `files` tool. A ProtectedTool in the ordinary ToolRegistry: every call goes through the one PermissionEngine (request -> decision ->
optional confirmation -> single-use approval -> run). The tool only DESCRIBES a call (the controller's plan: precise path, level, reason, preview)
and, once approved, asks the controller to execute a freshly built plan. There is no `confirmed`/`force`/`recursive` parameter and no delete.

Levels: list | read | organize (plan only, nothing moves) GREEN | create, write, move, copy, mkdir, organize_step YELLOW with preview.
`halt` and `resume` are deliberately NOT actions: only the user (emergency stop) can stop and release the file tools.
"""
from __future__ import annotations

from typing import Any

from jarvis.errors import ToolError
from jarvis.files import resources as res
from jarvis.files.controller import FilesController, Plan
from jarvis.files.errors import FilesError
from jarvis.permissions import ActionSpec, PermissionLevel
from jarvis.tools import ToolParameter, ToolRegistry, ToolResult
from jarvis.tools.base import ProtectedTool

_KEYS = ("path", "destination", "content", "expected_sha256", "offset", "limit", "rules", "plan_id", "step")


class FilesTool(ProtectedTool):
    name = res.TOOL
    description = (
        "Work with files inside the confirmed directories, one step per call. Read: list [path] | read path [offset limit] (bounded; returns sha256). "
        "Change (always asked, with a preview): create path content | write path content expected_sha256 (from `read`) | move path destination | "
        "copy path destination | mkdir path. Tidy up: organize path [rules='.jpg,.png=Bilder;.pdf=Dokumente'] only shows a plan; then "
        "organize_step plan_id step moves ONE file, asked every time. Nothing is ever deleted or overwritten by create/move/copy; links are not "
        "followed; secrets, .env and .git internals are never touched.")
    permission = PermissionLevel.GREEN  # reading is GREEN; every plan raises the level for what it really does
    parameters = (
        ToolParameter("action", "list|read|create|write|move|copy|mkdir|organize|organize_step"),
        ToolParameter("path", "file or directory (relative to the first confirmed root, or absolute inside one)", required=False),
        ToolParameter("destination", "target path (move, copy)", required=False),
        ToolParameter("content", "new file text (create, write)", required=False),
        ToolParameter("expected_sha256", "sha256 of the file as read; the write is refused if it changed (write)", required=False),
        ToolParameter("offset", "first line to return (read)", type="integer", required=False),
        ToolParameter("limit", "maximum lines / entries (read, list)", type="integer", required=False),
        ToolParameter("rules", "organize rules like '.jpg,.png=Bilder;.pdf=Dokumente' (default: common types)", required=False),
        ToolParameter("plan_id", "id returned by organize (organize_step)", required=False),
        ToolParameter("step", "step number from the plan (organize_step)", type="integer", required=False))

    def __init__(self, controller: FilesController) -> None:
        self._c = controller

    def _plan(self, kw: dict[str, Any], phase: str) -> Plan:
        return self._c.plan(kw.get("action"), phase=phase, **{k: kw.get(k) for k in _KEYS})

    def describe_action(self, **kwargs: Any) -> ActionSpec:
        return self._plan(kwargs, "describe").to_spec()  # read-only; invalid input raises FilesError -> the call is denied

    def _perform(self, **kwargs: Any) -> ToolResult:
        try:
            plan = self._plan(kwargs, "perform")  # rebuilt from the CURRENT state and compared with what the user was shown
            return ToolResult.ok(self._c.execute(plan))
        except FilesError as exc:
            return ToolResult(False, exc.to_dict(), str(exc))


def register_files_tools(registry: ToolRegistry, controller: FilesController) -> list[str]:
    engine = registry.permissions
    if not engine.require_protected_tools or engine.trust_caller_confirmation:
        raise ToolError("file tools need a strict permission engine (require_protected_tools, no caller confirmation)")
    registry.register(FilesTool(controller))
    return [res.TOOL]
