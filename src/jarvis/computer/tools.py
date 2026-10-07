"""Computer-control tools. All are `ProtectedTool`s registered in the ordinary ToolRegistry, so every call goes
through the one PermissionEngine (request -> decision -> optional confirmation -> single-use approval -> run).

A tool only DESCRIBES its call (`describe_action` -> the controller's plan: precise resource URI, level, reason)
and, once approved, performs it (`_perform`) by asking the controller to execute a freshly built plan. There is no
`confirmed`/`force` parameter anywhere; the controller itself refuses to act without a matching approval.

Levels:  screen (observe) GREEN | screen_save, mouse, keyboard, window, app YELLOW (RED for protected targets).
"""
from __future__ import annotations

from typing import Any

from jarvis.computer import resources as res
from jarvis.computer.controller import ComputerController, Plan
from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.errors import ToolError
from jarvis.permissions import ActionSpec, PermissionLevel, ResourceType
from jarvis.tools import ToolParameter, ToolRegistry, ToolResult
from jarvis.tools.base import ProtectedTool


class _ComputerTool(ProtectedTool):
    def __init__(self, controller: ComputerController) -> None:
        self._c = controller

    def _plan(self, **kwargs: Any) -> Plan:
        raise NotImplementedError

    def describe_action(self, **kwargs: Any) -> ActionSpec:
        return self._plan(**kwargs).to_spec()  # read-only; invalid input raises ComputerError -> the call is denied

    def _perform(self, **kwargs: Any) -> ToolResult:
        try:
            plan = self._plan(**kwargs)  # rebuilt from the CURRENT state; execute() compares it with the approval
            return ToolResult.ok(self._c.execute(plan))
        except ComputerError as exc:
            return ToolResult(False, exc.to_dict(), str(exc))


class ScreenTool(_ComputerTool):
    name = "screen"
    description = ("Observe the screen (read-only): action=monitors|screenshot|compare|windows|active_window|cursor|forget. "
                   "Screenshots stay in memory and are never saved or sent anywhere.")
    permission = PermissionLevel.GREEN
    parameters = (ToolParameter("action", "monitors | screenshot | compare | windows | active_window | cursor | forget"),
                  ToolParameter("monitor", "monitor index or 'all' (screenshot)", required=False),
                  ToolParameter("a", "first screenshot id (compare)", required=False),
                  ToolParameter("b", "second screenshot id (compare)", required=False))

    def _plan(self, **kw: Any) -> Plan:
        return self._c.plan_screen(kw.get("action"), monitor=kw.get("monitor"), a=kw.get("a"), b=kw.get("b"))


class ScreenSaveTool(_ComputerTool):
    name = "screen_save"
    description = "Save a stored screenshot as a PNG file inside an allowed directory (explicit, confirmed file write)."
    permission = PermissionLevel.YELLOW
    parameters = (ToolParameter("id", "screenshot id from screen action=screenshot"),
                  ToolParameter("path", "target .png path inside the allowed directories"))

    def describe_action(self, **kw: Any) -> ActionSpec:
        shot = self._c.check_save(kw.get("id"), kw.get("path"))
        return ActionSpec(action="save", resource=kw["path"], resource_type=ResourceType.PATH,
                          reason="Screenshot als PNG-Datei speichern",
                          context={"screenshot": shot.id, "groesse": f"{shot.width}x{shot.height}",
                                   "hinweis": "kann vertrauliche Inhalte zeigen"})

    def _perform(self, **kw: Any) -> ToolResult:
        try:
            return ToolResult.ok(self._c.save_screenshot(kw.get("id")))
        except ComputerError as exc:
            return ToolResult(False, exc.to_dict(), str(exc))


class MouseTool(_ComputerTool):
    name = "mouse"
    description = ("Control the mouse: action=move|click|double_click|right_click|scroll at monitor-relative x,y "
                   "(rejected if outside the screen). Always confirmed.")
    permission = PermissionLevel.YELLOW
    parameters = (ToolParameter("action", "move | click | double_click | right_click | scroll"),
                  ToolParameter("x", "x on the monitor", type="integer"), ToolParameter("y", "y on the monitor", type="integer"),
                  ToolParameter("monitor", "monitor index (default: configured default)", required=False),
                  ToolParameter("amount", "scroll clicks (scroll only; positive = up)", required=False),
                  ToolParameter("window", "window handle: x/y are then relative to that window, which is brought to the front and "
                                          "re-verified before the input (instead of 'monitor')", type="integer", required=False))

    def _plan(self, **kw: Any) -> Plan:
        return self._c.plan_mouse(kw.get("action"), kw.get("x"), kw.get("y"), monitor=kw.get("monitor"), amount=kw.get("amount"),
                                  window=kw.get("window"))


class KeyboardTool(_ComputerTool):
    name = "keyboard"
    description = ("Control the keyboard: action=press (key) | hotkey (keys='ctrl+s') | type (text). Input goes to the active "
                   "window, or to the window given by handle; terminals, shells and security tools are refused. Typed text is never logged.")
    permission = PermissionLevel.YELLOW
    parameters = (ToolParameter("action", "press | hotkey | type"),
                  ToolParameter("key", "key name (press)", required=False),
                  ToolParameter("keys", "combination like 'ctrl+s' (hotkey)", required=False),
                  ToolParameter("text", "text to type (type)", required=False),
                  ToolParameter("window", "window handle: input goes to exactly that window, which is brought to the front and "
                                          "re-verified before every input (default: the active window)", type="integer", required=False))

    def _plan(self, **kw: Any) -> Plan:
        return self._c.plan_keyboard(kw.get("action"), key=kw.get("key"), keys=kw.get("keys"), text=kw.get("text"),
                                     window=kw.get("window"))


class WindowTool(_ComputerTool):
    name = "window"
    description = ("Manage a window by handle (see screen action=windows): action=focus|minimize|maximize|restore|close. "
                   "Closing is graceful (like the X button); shell/system windows and JARVIS itself are never closed.")
    permission = PermissionLevel.YELLOW
    parameters = (ToolParameter("action", "focus | minimize | maximize | restore | close"),
                  ToolParameter("handle", "window handle", type="integer"))

    def _plan(self, **kw: Any) -> Plan:
        return self._c.plan_window(kw.get("action"), kw.get("handle"))


class AppTool(_ComputerTool):
    name = "app"
    description = ("Launch an application by configured alias (computer.apps) with an argument list. Never through a shell; "
                   "terminals, shells, script hosts and system tools are never launched.")
    permission = PermissionLevel.YELLOW
    parameters = (ToolParameter("app", "application alias (or an absolute .exe path if allow_unlisted_apps)"),
                  ToolParameter("args", "list of arguments (a single string is ONE argument)", required=False))

    def _plan(self, **kw: Any) -> Plan:
        return self._c.plan_app(kw.get("app"), kw.get("args"))


TOOL_CLASSES = (ScreenTool, ScreenSaveTool, MouseTool, KeyboardTool, WindowTool, AppTool)


def register_computer_tools(registry: ToolRegistry, controller: ComputerController) -> list[str]:
    """Register all computer tools in the (strict) registry; returns their names. All or nothing: if one
    registration fails, the ones already registered are removed again."""
    engine = registry.permissions
    if not engine.require_protected_tools or engine.trust_caller_confirmation:
        # A lenient (legacy) engine lets callers self-confirm and treats undeclared tools as GREEN: never host these tools.
        raise ToolError("computer tools need a strict permission engine (require_protected_tools, no caller confirmation)")
    names: list[str] = []
    try:
        for cls in TOOL_CLASSES:
            registry.register(cls(controller))
            names.append(cls.name)
    except Exception:
        for name in names:
            registry.unregister(name)
        raise
    assert tuple(names) == res.ALL_TOOLS
    return names
