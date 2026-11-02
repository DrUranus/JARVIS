"""Worker process of the UI-Automation ACTION provider (backlog step `uia-actions`).

Runs as `python -m jarvis.computer.providers.uia_act_worker`, started and stopped only by `PywinautoUiaActionProvider`. Like the read-only worker, its MAIN thread owns the
UIA connection. It speaks the same JSON-lines protocol as `uia_worker` and knows exactly two operations: `state` (read one control) and `act` (one pattern call).

What it does NOT do: no coordinates, no mouse, no keyboard events, no window or process control. An action is one call on a UIA control pattern
(Invoke / SetValue / Select / Toggle / SetFocus). Before reading or acting it re-finds the control by its path and checks the fingerprint (name, type, AutomationId); a password
field (or one whose flag cannot be read) is refused and never yields a value. pywinauto is imported lazily inside `PywinautoActor`.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, TextIO

from jarvis.computer.providers.uia_worker import _int

MAX_VALUE = 5000
MAX_REQUEST_BYTES = 64_000      # a request carries a text of up to MAX_VALUE characters, JSON-escaped (up to 6 bytes each)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TOGGLE = {0: "off", 1: "on", 2: "indeterminate"}
_PATTERNS = (("invoke", "Invoke"), ("set_value", "Value"), ("select", "SelectionItem"), ("toggle", "Toggle"))


class Changed(Exception):
    """The control found at the path is not the approved one."""


class Blocked(Exception):
    """A password field (or a flag that cannot be read): never operated, never read."""


class Unsupported(Exception):
    pass


def _norm(text: Any) -> str:
    return _CONTROL.sub(" ", str(text or ""))


def _type_key(text: Any) -> str:
    return re.sub(r"[\s_-]+", "", str(text or "")).lower()


class PywinautoActor:
    """The only code that touches pywinauto for actions (UIA backend, control patterns)."""

    def __init__(self) -> None:
        from pywinauto import uia_defines as defs           # lazy: a missing library is reported by the provider factory
        from pywinauto.uia_element_info import UIAElementInfo
        self._defs, self._info = defs, UIAElementInfo

    def _iface(self, info: Any, name: str) -> Any:
        return self._defs.get_elem_interface(info.element, name)

    def _find(self, handle: int, path: str, name: str, ctype: str, automation_id: str) -> Any:
        parts = path.split(".")
        if parts[0] != "0" or not all(p.isdigit() for p in parts):
            raise LookupError("bad path")
        try:
            info = self._info(handle)
            str(info.name)
        except Exception:      # noqa: BLE001
            raise LookupError("no such window") from None
        for part in parts[1:]:
            try:
                kids = info.children()
                info = kids[int(part)]
            except Exception:      # noqa: BLE001
                raise LookupError("no such control") from None
        try:
            same = (_norm(info.name)[:len(name)] == name and _type_key(info.control_type) == _type_key(ctype)
                    and _norm(info.automation_id)[:len(automation_id)] == automation_id)
        except Exception:      # noqa: BLE001
            same = False
        if not same:
            raise Changed()
        try:
            password = bool(info.element.CurrentIsPassword)
        except Exception:      # noqa: BLE001 - unknown means: treat as protected
            password = True
        if password:
            raise Blocked()
        return info

    def state(self, handle: int, path: str, name: str, ctype: str, automation_id: str) -> dict[str, Any]:
        info = self._find(handle, path, name, ctype, automation_id)
        out: dict[str, Any] = {"enabled": bool(info.enabled), "visible": bool(info.visible), "is_password": False, "patterns": ["focus"], "value": None,
                               "read_only": None, "toggle_state": None, "selected": None, "has_focus": None}
        try:
            out["has_focus"] = bool(info.element.CurrentHasKeyboardFocus)
        except Exception:      # noqa: BLE001
            pass
        for action, pattern in _PATTERNS:
            try:
                iface = self._iface(info, pattern)
            except Exception:      # noqa: BLE001 - pattern not supported
                continue
            out["patterns"].append(action)
            try:
                if action == "set_value":
                    out["value"], out["read_only"] = str(iface.CurrentValue)[:MAX_VALUE], bool(iface.CurrentIsReadOnly)
                elif action == "toggle":
                    out["toggle_state"] = _TOGGLE.get(int(iface.CurrentToggleState))
                elif action == "select":
                    out["selected"] = bool(iface.CurrentIsSelected)
            except Exception:      # noqa: BLE001 - leave unknown
                pass
        return out

    def act(self, handle: int, path: str, name: str, ctype: str, automation_id: str, action: str, value: str | None) -> None:
        info = self._find(handle, path, name, ctype, automation_id)
        if action == "focus":
            info.element.SetFocus()
            return
        pattern = dict((a, p) for a, p in _PATTERNS).get(action)
        if pattern is None:
            raise Unsupported()
        try:
            iface = self._iface(info, pattern)
        except Exception:      # noqa: BLE001
            raise Unsupported() from None
        if action == "invoke":
            iface.Invoke()
        elif action == "toggle":
            iface.Toggle()
        elif action == "select":
            iface.Select()
        else:
            if bool(iface.CurrentIsReadOnly):
                raise Unsupported()
            iface.SetValue(value)


def _answer(actor: Any, request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    handle = _int(request.get("handle"))
    texts = [request.get(k) for k in ("path", "name", "control_type", "automation_id")]
    if op not in ("state", "act") or handle < 0 or not all(isinstance(x, str) and len(x) <= 2000 for x in texts):
        return {"ok": False, "code": "invalid_input", "message": "bad request"}
    action, value = request.get("action"), request.get("value")
    if op == "act" and (action not in ("invoke", "set_value", "select", "toggle", "focus") or not (value is None or (isinstance(value, str) and len(value) <= MAX_VALUE))
                        or (action == "set_value") != (value is not None)):
        return {"ok": False, "code": "invalid_input", "message": "bad request"}
    try:
        if op == "state":
            return {"ok": True, "state": actor.state(handle, *texts)}
        actor.act(handle, *texts, action, value)
        return {"ok": True}
    except LookupError:
        return {"ok": False, "code": "window_not_found", "message": "no such window or control"}
    except Changed:
        return {"ok": False, "code": "target_changed", "message": "the control changed"}
    except Blocked:
        return {"ok": False, "code": "blocked_target", "message": "protected control"}
    except Unsupported:
        return {"ok": False, "code": "unsupported", "message": "pattern not supported"}


def serve(actor: Any, stdin: TextIO, stdout: TextIO) -> None:
    """Protocol loop: one JSON request per line, one JSON answer per line. Errors never carry exception text (it could contain window content)."""
    for line in stdin:
        if len(line) > MAX_REQUEST_BYTES:
            break
        request: Any = None
        try:
            request = json.loads(line)
            answer = _answer(actor, request) if isinstance(request, dict) else {"ok": False, "code": "invalid_input", "message": "bad request"}
        except Exception as exc:      # noqa: BLE001 - never leak the message
            answer = {"ok": False, "code": "backend_error", "message": f"worker failed ({type(exc).__name__})"}
        answer["id"] = request.get("id") if isinstance(request, dict) else None
        stdout.write(json.dumps(answer, ensure_ascii=True) + "\n")
        stdout.flush()


def main() -> int:
    channel, sys.stdout = sys.stdout, sys.stderr      # library output must never corrupt the protocol channel
    try:
        actor = PywinautoActor()
    except Exception as exc:      # noqa: BLE001
        channel.write(json.dumps({"ok": False, "code": "backend_unavailable", "message": f"pywinauto cannot be loaded ({type(exc).__name__})", "id": None}) + "\n")
        channel.flush()
        return 2
    serve(actor, sys.stdin, channel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
