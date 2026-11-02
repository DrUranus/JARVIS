"""Model of UI-Automation ACTIONS by pattern and the provider interface for them (backlog step `uia-actions`).

Actions go through UIA control patterns, never through coordinates: Invoke (press), Value (set a text), SelectionItem (select), Toggle (switch), focus.
This module holds only data, pure functions and the abstract interface: no library, no Windows code, no tool. Whoever calls a provider decides about permissions
(the `ComputerController`, after the `PermissionEngine`).

Properties the model enforces itself:
- A password field never carries a value (`UiState` drops it on construction); its `repr` never shows a value.
- `judge` compares the state read BEFORE and AFTER an action with the expected change and says honestly whether it happened (True), did not happen (False) or
  cannot be checked (None). A set text is never echoed: only whether it matches.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.uia import ControlType, HARD_MAX_TEXT

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_VALUE_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")      # a text value may keep newline and tab (validate_text allows them)
TOGGLE_STATES = ("off", "on", "indeterminate")


class UiAction(str, Enum):
    INVOKE = "invoke"          # InvokePattern: press a button, activate a menu item or link
    SET_VALUE = "set_value"    # ValuePattern: set the text of a field
    SELECT = "select"          # SelectionItemPattern: select a list entry, radio button or tab
    TOGGLE = "toggle"          # TogglePattern: switch a check box
    FOCUS = "focus"            # keyboard focus on the control (no input)

    @classmethod
    def parse(cls, raw: Any) -> "UiAction":
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, str):
            for a in cls:
                if a.value == raw.strip().casefold():
                    return a
        raise ComputerError(ErrorCode.INVALID_INPUT, f"unknown ui action; use one of {[a.value for a in cls]}")


PATTERN_OF = {UiAction.INVOKE: "Invoke", UiAction.SET_VALUE: "Value", UiAction.SELECT: "SelectionItem", UiAction.TOGGLE: "Toggle", UiAction.FOCUS: "Focus"}
VALUE_CONTROLS = frozenset({ControlType.EDIT, ControlType.DOCUMENT, ControlType.COMBO_BOX})      # set_value only on text-like controls


@dataclass(frozen=True)
class UiTarget:
    """The control an action is meant for, as found by a read just before: its path (`runtime_id` of the snapshot) plus a fingerprint the provider must re-check."""
    runtime_id: str
    name: str
    control_type: ControlType
    automation_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_id, str) or not re.fullmatch(r"\d+(\.\d+){0,20}", self.runtime_id):
            raise ComputerError(ErrorCode.INVALID_INPUT, "runtime_id must be a path of numbers like 0.2.1")
        for n in ("name", "automation_id"):
            if not isinstance(getattr(self, n), str):
                raise ComputerError(ErrorCode.INVALID_INPUT, f"{n} must be text")
            object.__setattr__(self, n, _CONTROL.sub(" ", getattr(self, n))[:HARD_MAX_TEXT])
        if not isinstance(self.control_type, ControlType):
            object.__setattr__(self, "control_type", ControlType.from_name(self.control_type))


@dataclass(frozen=True)
class UiState:
    """What a provider reports about ONE control right now (never a live handle)."""
    enabled: bool = True
    visible: bool = True
    is_password: bool = False
    patterns: frozenset = frozenset()                    # the UiActions the control supports
    value: str | None = field(default=None, repr=False)  # never in repr; always None for password fields
    read_only: bool | None = None
    toggle_state: str | None = None                      # off | on | indeterminate
    selected: bool | None = None
    has_focus: bool | None = None

    def __post_init__(self) -> None:
        for n in ("enabled", "visible", "is_password"):
            if not isinstance(getattr(self, n), bool):
                raise ComputerError(ErrorCode.INVALID_INPUT, f"{n} must be true or false")
        object.__setattr__(self, "patterns", frozenset(UiAction.parse(p) for p in self.patterns))
        if self.value is not None:
            object.__setattr__(self, "value", None if self.is_password else _VALUE_CONTROL.sub(" ", str(self.value))[:HARD_MAX_TEXT])
        if self.toggle_state is not None and self.toggle_state not in TOGGLE_STATES:
            raise ComputerError(ErrorCode.INVALID_INPUT, "toggle_state must be off, on or indeterminate")

    def info(self) -> dict[str, Any]:
        """The state without its text value (the value is compared, never shown)."""
        out: dict[str, Any] = {"enabled": self.enabled, "visible": self.visible, "patterns": sorted(p.value for p in self.patterns)}
        for key in ("read_only", "toggle_state", "selected", "has_focus"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        return out


def judge(action: UiAction, before: UiState, after: UiState | None, value: str | None = None) -> dict[str, Any]:
    """Was the expected change reached? Returns {verified: True|False|None, expected, observed}. Pure; never contains the text that was set."""
    if action is UiAction.INVOKE:
        return {"verified": None, "expected": "kein pruefbarer Zielzustand (Invoke loest nur aus)",
                "observed": "Element nach der Aktion nicht mehr vorhanden" if after is None else "Element vorhanden"}
    if after is None:
        return {"verified": False, "expected": _expected(action), "observed": "Element nach der Aktion nicht mehr lesbar"}
    if action is UiAction.SET_VALUE:
        if after.value is None:
            return {"verified": False, "expected": _expected(action), "observed": "Wert nach der Aktion nicht lesbar"}
        ok = after.value == value
        return {"verified": ok, "expected": _expected(action), "observed": "Wert stimmt" if ok else f"Wert weicht ab (gelesen: {len(after.value)} Zeichen)"}
    if action is UiAction.TOGGLE:
        ok = after.toggle_state is not None and after.toggle_state != before.toggle_state
        return {"verified": ok, "expected": _expected(action), "observed": f"Zustand {before.toggle_state} -> {after.toggle_state}"}
    if action is UiAction.SELECT:
        return {"verified": after.selected is True, "expected": _expected(action), "observed": f"ausgewaehlt: {after.selected}"}
    return {"verified": after.has_focus is True, "expected": _expected(action), "observed": f"Fokus: {after.has_focus}"}


def _expected(action: UiAction) -> str:
    return {UiAction.SET_VALUE: "Wert entspricht dem gesetzten Text", UiAction.TOGGLE: "Schaltzustand hat sich geaendert", UiAction.SELECT: "Element ist ausgewaehlt",
            UiAction.FOCUS: "Element hat den Tastaturfokus", UiAction.INVOKE: "keine Pruefung"}[action]


class UiActionProvider(ABC):
    """Acts on ONE control of a window through a UIA pattern. Contract for every implementation:
    - `read_state` only reads; `perform` does exactly the one pattern call and nothing else (no coordinates, no keyboard, no mouse, no process control).
    - Both re-check the fingerprint of `target` against the live control and raise ComputerError(TARGET_CHANGED) if it differs, WINDOW_NOT_FOUND for an unknown window
      and ELEMENT_GONE-like WINDOW_NOT_FOUND for a vanished control.
    - A password field is refused by `perform` (BLOCKED_TARGET) whatever the caller says, and `read_state` never returns its value.
    - Hands out plain data only. Whoever calls it decides about permissions (the controller, after the permission engine)."""
    name: str = "ui-action-provider"

    @abstractmethod
    def read_state(self, window_handle: int, target: UiTarget) -> UiState: ...

    @abstractmethod
    def perform(self, window_handle: int, target: UiTarget, action: UiAction, value: str | None = None) -> None: ...
