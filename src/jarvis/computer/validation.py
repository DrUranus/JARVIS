"""Pure input validation: coordinates, monitors, keys, hotkeys, text, scroll amounts, application arguments.
Error messages describe the problem, never echo typed text."""
from __future__ import annotations

import re
from typing import Any, Sequence

from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.models import Monitor

MAX_ARGS, MAX_ARG_LENGTH = 16, 1000

_MODIFIERS = ("CTRL", "ALT", "SHIFT", "WIN")
_NAMED = ("ENTER", "TAB", "ESC", "SPACE", "BACKSPACE", "DELETE", "INSERT", "HOME", "END", "PAGEUP", "PAGEDOWN",
          "UP", "DOWN", "LEFT", "RIGHT")
_FUNCTION = tuple(f"F{i}" for i in range(1, 13))
_PUNCT = tuple("-=[];',./\\`")
KEYS: frozenset[str] = frozenset(
    (*_MODIFIERS, *_NAMED, *_FUNCTION, *_PUNCT, *"ABCDEFGHIJKLMNOPQRSTUVWXYZ", *"0123456789"))
_ALIASES = {"RETURN": "ENTER", "ESCAPE": "ESC", "DEL": "DELETE", "INS": "INSERT", "PGUP": "PAGEUP", "PGDN": "PAGEDOWN",
            "PAGE_UP": "PAGEUP", "PAGE_DOWN": "PAGEDOWN", "CONTROL": "CTRL", "CMD": "WIN", "META": "WIN",
            "SUPER": "WIN", "WINDOWS": "WIN", "LWIN": "WIN", "RWIN": "WIN", "OPTION": "ALT", " ": "SPACE"}
MODIFIERS = frozenset(_MODIFIERS)


def _bad(code: ErrorCode, message: str, **details: Any) -> ComputerError:
    return ComputerError(code, message, **details)


def as_int(value: Any, name: str) -> int:
    """Accept ints and decimal strings (CLI arguments). Reject bools, floats, anything else."""
    if isinstance(value, bool):
        raise _bad(ErrorCode.INVALID_INPUT, f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,9}", value.strip()):  # ASCII digits only: \d accepts e.g. full-width ０
        return int(value.strip())
    raise _bad(ErrorCode.INVALID_INPUT, f"{name} must be an integer")


def validate_monitor(index: Any, monitors: Sequence[Monitor]) -> Monitor:
    idx = as_int(index, "monitor")
    if not monitors:
        raise _bad(ErrorCode.NO_DISPLAY, "no monitors available")
    if not 0 <= idx < len(monitors):
        raise _bad(ErrorCode.INVALID_MONITOR, f"monitor {idx} does not exist (available: 0..{len(monitors) - 1})",
                   available=len(monitors))
    return monitors[idx]


def validate_point(x: Any, y: Any, monitor: Monitor) -> tuple[int, int]:
    """Monitor-relative point; must lie on the monitor. Never clamped: a bad point is an error."""
    xi, yi = as_int(x, "x"), as_int(y, "y")
    if not monitor.contains(xi, yi):
        raise _bad(ErrorCode.INVALID_COORDINATES,
                   f"({xi}, {yi}) is outside monitor {monitor.index} (x 0..{monitor.width - 1}, y 0..{monitor.height - 1})",
                   monitor=monitor.index, width=monitor.width, height=monitor.height)
    return xi, yi


def validate_scroll(amount: Any, max_scroll: int) -> int:
    n = as_int(amount, "amount")
    if n == 0 or abs(n) > max_scroll:
        raise _bad(ErrorCode.INVALID_INPUT, f"scroll amount must be non-zero and at most {max_scroll} clicks")
    return n


def normalize_key(name: Any) -> str:
    if not isinstance(name, str):
        raise _bad(ErrorCode.INVALID_INPUT, "key must be a string")
    stripped = " " if name == " " else name.strip()
    if not stripped:
        raise _bad(ErrorCode.INVALID_INPUT, "key must not be empty")
    key = _ALIASES.get(stripped.upper(), stripped.upper())
    if key not in KEYS:
        raise _bad(ErrorCode.INVALID_INPUT, f"unsupported key {key[:20]!r}; use letters, digits, F1-F12, arrows, "
                                            "ENTER, TAB, ESC, SPACE, BACKSPACE, DELETE, HOME, END, PAGEUP/DOWN, CTRL, ALT, SHIFT")
    return key


def parse_hotkey(keys: Any, max_keys: int) -> tuple[str, ...]:
    """'ctrl+shift+s' or ['ctrl', 's'] -> ('CTRL', 'SHIFT', 'S') with modifiers first. 2..max_keys keys,
    at least one modifier and exactly one non-modifier key."""
    if isinstance(keys, str):
        parts = [p for p in keys.split("+")]
        if any(not p.strip() for p in parts):
            raise _bad(ErrorCode.INVALID_INPUT, "hotkey has an empty part (use e.g. 'ctrl+s')")
    elif isinstance(keys, (list, tuple)):
        parts = list(keys)
    else:
        raise _bad(ErrorCode.INVALID_INPUT, "hotkey must be like 'ctrl+s' or a list of keys")
    norm = [normalize_key(p) for p in parts]
    if not 2 <= len(norm) <= max_keys:
        raise _bad(ErrorCode.INVALID_INPUT, f"a hotkey needs 2..{max_keys} keys")
    if len(set(norm)) != len(norm):
        raise _bad(ErrorCode.INVALID_INPUT, "hotkey contains a key twice")
    mods = [k for k in norm if k in MODIFIERS]
    others = [k for k in norm if k not in MODIFIERS]
    if not mods or len(others) != 1:
        raise _bad(ErrorCode.INVALID_INPUT, "a hotkey needs at least one modifier (CTRL/ALT/SHIFT) and exactly one other key")
    order = {m: i for i, m in enumerate(_MODIFIERS)}
    return (*sorted(mods, key=order.__getitem__), *others)


def validate_text(text: Any, max_length: int) -> str:
    if not isinstance(text, str) or not text:
        raise _bad(ErrorCode.INVALID_INPUT, "text must be a non-empty string")
    if len(text) > max_length:
        raise _bad(ErrorCode.INVALID_INPUT, f"text too long ({len(text)} > {max_length} characters)")
    if any((ord(c) < 32 and c not in "\n\t") or ord(c) == 127 for c in text):
        raise _bad(ErrorCode.INVALID_INPUT, "text contains control characters (only newline and tab are allowed)")
    return text


def validate_app_args(args: Any) -> tuple[str, ...]:
    """A list of plain strings. A bare string is ONE argument (never split, never shell-parsed)."""
    if args is None:
        return ()
    if isinstance(args, str):
        args = [args] if args else []
    if not isinstance(args, (list, tuple)) or not all(isinstance(a, str) for a in args):
        raise _bad(ErrorCode.INVALID_INPUT, "args must be a list of strings")
    if len(args) > MAX_ARGS:
        raise _bad(ErrorCode.INVALID_INPUT, f"too many arguments (max {MAX_ARGS})")
    for a in args:
        if len(a) > MAX_ARG_LENGTH or any(ord(c) < 32 or ord(c) == 127 for c in a):
            raise _bad(ErrorCode.INVALID_INPUT, "argument too long or contains control characters")
    return tuple(args)
