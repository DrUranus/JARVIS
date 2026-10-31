"""Deterministic fake UI-Automation provider for tests and hardware-free development (backlog step `uia-model-fake`).

A fixed tree per window, no randomness, no clock, no Windows, no library. It only reads. The login window deliberately contains a password field that is handed a
value on construction: the model must drop it, which the tests rely on. Never a production provider.
"""
from __future__ import annotations

from typing import Any, Mapping

from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.uia import (UiElement, UiFindResult, UiLimits, UiQuery, UiRect, UiSnapshot, UiTreeProvider, bound_tree, find_in_tree)

NOTEPAD_HANDLE, LOGIN_HANDLE = 1001, 1002
FAKE_SECRET = "hunter2-geheim"          # only here to prove that the model never exposes password values


def _e(rid: str, name: str, ctype: str, *children: UiElement, **kw: Any) -> UiElement:
    return UiElement(runtime_id=rid, name=name, control_type=ctype, children=tuple(children), **kw)


def notepad_tree() -> UiElement:
    """Shaped like the classic Notepad window that the Windows CI test read (docs/uia-compat-results.md)."""
    menu = _e("0.0", "Application", "MenuBar", *(_e(f"0.0.{i}", n, "MenuItem", rect=UiRect(100 + 40 * i, 130, 40, 20)) for i, n in enumerate(("File", "Edit", "Format", "View", "Help"))),
              automation_id="MenuBar", rect=UiRect(100, 130, 768, 20))
    editor = _e("0.1", "Text editor", "Edit", automation_id="15", class_name="Edit", value="", rect=UiRect(100, 150, 750, 440))
    scroll = _e("0.2", "Vertical", "ScrollBar", _e("0.2.0", "Page", "Thumb", rect=UiRect(850, 170, 17, 100)), automation_id="NonClientVerticalScrollBar", rect=UiRect(850, 150, 17, 440))
    status = _e("0.3", "", "StatusBar", _e("0.3.0", "Ln 1, Col 1", "Text"), _e("0.3.1", "100%", "Text"), rect=UiRect(100, 590, 768, 29))
    return _e("0", "Untitled - Notepad", "Window", menu, editor, scroll, status, class_name="Notepad", rect=UiRect(100, 100, 768, 519))


def login_tree() -> UiElement:
    return _e("0", "Sign in - Example", "Window",
              _e("0.0", "User name", "Edit", automation_id="user", value="alice"),
              _e("0.1", "Password", "Edit", automation_id="pass", is_password=True, value=FAKE_SECRET),
              _e("0.2", "Sign in", "Button", automation_id="ok"),
              _e("0.3", "Cancel", "Button", automation_id="cancel"),
              _e("0.4", "Remember me", "CheckBox", enabled=False),
              _e("0.5", "Hidden hint", "Text", visible=False),
              class_name="LoginWindow", rect=UiRect(300, 200, 400, 250))


class FakeUiaProvider(UiTreeProvider):
    name = "fake-uia"

    def __init__(self, trees: Mapping[int, UiElement] | None = None) -> None:
        self._trees = dict(trees) if trees is not None else {NOTEPAD_HANDLE: notepad_tree(), LOGIN_HANDLE: login_tree()}
        self.calls: list[tuple[str, int]] = []
        self._fault: BaseException | None = None

    def fail_next(self, error: BaseException) -> None:
        """The next call raises `error` once."""
        self._fault = error

    def _tree(self, op: str, handle: Any) -> UiElement:
        if isinstance(handle, bool) or not isinstance(handle, int):
            raise ComputerError(ErrorCode.INVALID_INPUT, "window handle must be an integer")
        self.calls.append((op, handle))
        if self._fault is not None:
            fault, self._fault = self._fault, None
            raise fault
        if handle not in self._trees:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, f"no window with handle {handle}")
        return self._trees[handle]

    def describe(self, window_handle: int, limits: UiLimits) -> UiSnapshot:
        tree, nodes, cut = bound_tree(self._tree("describe", window_handle), limits)
        return UiSnapshot(window_handle, tree, nodes, cut, limits)

    def find(self, window_handle: int, query: UiQuery, limits: UiLimits) -> UiFindResult:
        return find_in_tree(self._tree("find", window_handle), query, limits)
