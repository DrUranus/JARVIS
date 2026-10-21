"""Resource URIs: what the permission engine (and the user, and policy rules) see for each action.

    screen://monitor/0                     screenshot of monitor 0        screen://all   whole virtual desktop
    screen://monitor/0/120/340             mouse point (monitor-relative)
    keyboard://key/ENTER@notepad.exe       key press, in the active window's process
    keyboard://hotkey/CTRL+S@notepad.exe   key combination
    keyboard://text@notepad.exe            typing (the text itself is NEVER part of a resource)
    window://66012/notepad.exe             window handle + process
    app://C:/Windows/System32/notepad.exe  resolved executable (+ ?args=<digest> when arguments are given)

Engine globs (policy rules, resource_type "other") work on these strings, e.g. "keyboard://*@notepad.exe".
"""
from __future__ import annotations

import hashlib
import re
from typing import Sequence

TOOL_SCREEN, TOOL_SCREEN_SAVE, TOOL_MOUSE = "screen", "screen_save", "mouse"
TOOL_KEYBOARD, TOOL_WINDOW, TOOL_APP = "keyboard", "window", "app"
ALL_TOOLS = (TOOL_SCREEN, TOOL_SCREEN_SAVE, TOOL_MOUSE, TOOL_KEYBOARD, TOOL_WINDOW, TOOL_APP)

_UNSAFE = re.compile(r"[^\w.\- ()+]")


def _clean(text: str, limit: int = 80) -> str:
    """OS-provided names (process, window class) made safe for use inside a resource string."""
    return _UNSAFE.sub("_", text.strip())[:limit] or "unknown"


def screen_resource(monitor: int | None) -> str:
    return "screen://all" if monitor is None else f"screen://monitor/{monitor}"


def screen_info_resource(kind: str) -> str:
    return f"screen://{kind}"           # windows | active-window | cursor | screenshots


def mouse_resource(monitor: int, x: int, y: int) -> str:
    return f"screen://monitor/{monitor}/{x}/{y}"


def key_resource(key: str, target: str) -> str:
    return f"keyboard://key/{key}@{_clean(target)}"


def hotkey_resource(keys: Sequence[str], target: str) -> str:
    return f"keyboard://hotkey/{'+'.join(keys)}@{_clean(target)}"


def text_resource(target: str) -> str:
    return f"keyboard://text@{_clean(target)}"


def window_resource(handle: int, process: str) -> str:
    return f"window://{handle}/{_clean(process)}"


def app_resource(executable: str, args: Sequence[str] = ()) -> str:
    uri = "app://" + executable.replace("\\", "/")
    if args:  # a session permission for "notepad" must not silently cover "notepad <any file>"
        uri += "?args=" + hashlib.sha256("\x1f".join(args).encode()).hexdigest()[:8]
    return uri
