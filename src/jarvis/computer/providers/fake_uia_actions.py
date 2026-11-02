"""Deterministic fake UI-Automation ACTION provider for tests and hardware-free development (backlog step `uia-actions`).

Works on the same trees as `FakeUiaProvider`. Each control gets a small state (value, toggle state, selection, focus) derived from its type; actions change that state
like a well-behaved program would. `misbehave` makes a program that ignores actions, to prove that the controller reports a missing change honestly. Never a production provider.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.uia import ControlType, UiElement
from jarvis.computer.uia_actions import UiAction, UiActionProvider, UiState, UiTarget

_PATTERNS = {ControlType.BUTTON: {UiAction.INVOKE}, ControlType.MENU_ITEM: {UiAction.INVOKE}, ControlType.HYPERLINK: {UiAction.INVOKE},
             ControlType.EDIT: {UiAction.SET_VALUE}, ControlType.DOCUMENT: {UiAction.SET_VALUE}, ControlType.COMBO_BOX: {UiAction.SET_VALUE, UiAction.SELECT},
             ControlType.CHECK_BOX: {UiAction.TOGGLE}, ControlType.RADIO_BUTTON: {UiAction.SELECT}, ControlType.LIST_ITEM: {UiAction.SELECT},
             ControlType.TAB_ITEM: {UiAction.SELECT}}


def _find(root: UiElement, runtime_id: str) -> UiElement | None:
    stack = [root]
    while stack:
        e = stack.pop()
        if e.runtime_id == runtime_id:
            return e
        stack.extend(e.children)
    return None


class FakeUiaActionProvider(UiActionProvider):
    name = "fake-uia-actions"

    def __init__(self, trees: Mapping[int, UiElement] | None = None) -> None:
        from jarvis.computer.providers.fake_uia import FakeUiaProvider
        self._trees = dict(trees) if trees is not None else {h: t for h, t in FakeUiaProvider()._trees.items()}
        self._state: dict[tuple[int, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, int, str, str]] = []      # (operation, window, runtime_id, action)
        self.performed: list[tuple[int, str, str]] = []       # actions that really ran: (window, runtime_id, action)
        self.misbehave = False                                # True: actions are accepted but change nothing
        self.vanish_after: set[str] = set()                   # actions after which the control is gone (e.g. a dialog button)
        self.on_perform: Callable[[], None] | None = None     # hook that runs inside perform (e.g. to trigger the emergency stop)
        self._fault: BaseException | None = None
        self._gone: set[tuple[int, str]] = set()
        self.halted: str | None = None

    def fail_next(self, error: BaseException) -> None:
        self._fault = error

    def halt(self, reason: str = "stopped by user") -> None:
        self.halted = reason

    def resume(self) -> None:
        self.halted = None

    def _control(self, op: str, handle: Any, target: UiTarget, action: str = "") -> tuple[UiElement, dict[str, Any]]:
        if isinstance(handle, bool) or not isinstance(handle, int):
            raise ComputerError(ErrorCode.INVALID_INPUT, "window handle must be an integer")
        self.calls.append((op, handle, target.runtime_id, action))
        if self.halted is not None:
            raise ComputerError(ErrorCode.FAILSAFE, f"UI actions are halted ({self.halted})")
        if self._fault is not None:
            fault, self._fault = self._fault, None
            raise fault
        if handle not in self._trees:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, f"no window with handle {handle}")
        element = None if (handle, target.runtime_id) in self._gone else _find(self._trees[handle], target.runtime_id)
        if element is None:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, "the control no longer exists")
        if (element.name, element.control_type, element.automation_id) != (target.name, target.control_type, target.automation_id):
            raise ComputerError(ErrorCode.TARGET_CHANGED, "the control is not the one that was approved; nothing was done")
        state = self._state.setdefault((handle, target.runtime_id), {
            "value": element.value if element.control_type in (ControlType.EDIT, ControlType.DOCUMENT, ControlType.COMBO_BOX) else None,
            "toggle": "off" if element.control_type is ControlType.CHECK_BOX else None,
            "selected": False if UiAction.SELECT in _PATTERNS.get(element.control_type, ()) else None, "focus": False})
        return element, state

    def read_state(self, window_handle: int, target: UiTarget) -> UiState:
        e, s = self._control("read", window_handle, target)
        return UiState(enabled=e.enabled, visible=e.visible, is_password=e.is_password, patterns=frozenset(_PATTERNS.get(e.control_type, set()) | {UiAction.FOCUS}),
                       value=s["value"], read_only=False if s["value"] is not None else None, toggle_state=s["toggle"], selected=s["selected"], has_focus=s["focus"])

    def perform(self, window_handle: int, target: UiTarget, action: UiAction, value: str | None = None) -> None:
        e, s = self._control("perform", window_handle, target, action.value)
        if e.is_password:
            raise ComputerError(ErrorCode.BLOCKED_TARGET, "password fields are never operated")
        if action is not UiAction.FOCUS and action not in _PATTERNS.get(e.control_type, set()):
            raise ComputerError(ErrorCode.UNSUPPORTED, f"the control does not support {action.value}")
        self.performed.append((window_handle, target.runtime_id, action.value))
        if self.on_perform is not None:
            self.on_perform()
        if action.value in self.vanish_after:
            self._gone.add((window_handle, target.runtime_id))
        if self.misbehave:
            return
        if action is UiAction.SET_VALUE:
            s["value"] = value
        elif action is UiAction.TOGGLE:
            s["toggle"] = "on" if s["toggle"] != "on" else "off"
        elif action is UiAction.SELECT:
            s["selected"] = True
        elif action is UiAction.FOCUS:
            for key, st in self._state.items():
                if key[0] == window_handle:
                    st["focus"] = False
            s["focus"] = True
