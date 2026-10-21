"""Fake backend for tests and hardware-free development: records every call, simulates a tiny desktop.

No real mouse, keyboard, display or application is involved. Typed text IS recorded here (so tests can assert
on it) - which is exactly why this class is only ever used in tests/development, never as a production backend.
"""
from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Any, Callable, Sequence

from jarvis.computer.backend import (AppLauncher, ComputerBackend, KeyboardProvider, MouseProvider, ScreenProvider,
                                     WindowProvider)
from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.models import LaunchResult, Monitor, RawFrame, WindowInfo

_BG = (30, 30, 30)


class FakeBackend:
    def __init__(self, monitors: Sequence[Monitor] | None = None, name: str = "fake") -> None:
        self.name = name
        self._monitors = list(monitors) if monitors is not None else [
            Monitor(0, 0, 0, 64, 48, primary=True, name="FAKE-1"), Monitor(1, 64, 0, 32, 24, name="FAKE-2")]
        self.calls: list[tuple[str, tuple]] = []
        self.typed: list[str] = []
        self.cursor = (0, 0)
        self.windows: dict[int, WindowInfo] = {}
        self.z_order: list[int] = []
        self.active_handle: int | None = None
        self.launched: list[tuple[str, tuple[str, ...]]] = []
        self.on_launch: Callable[[str, tuple[str, ...]], None] | None = None
        self.refuse_close: set[int] = set()
        self.focus_denied: set[int] = set()    # focus() raises, like Windows' foreground lock refusing the request
        self.focus_ignored: set[int] = set()   # focus() returns quietly but nothing changes (a provider that cannot tell)
        self.on_type: Callable[[str], None] | None = None  # called after every type_text chunk
        self._faults: dict[str, BaseException] = {}
        self._pid = itertools.count(1000)
        self._handles = itertools.count(100)
        w = max(m.left + m.width for m in self._monitors)
        h = max(m.top + m.height for m in self._monitors)
        self._canvas_w, self._canvas_h = w, h
        self.canvas = bytearray(bytes(_BG) * (w * h))

    # -- test helpers ---------------------------------------------------------------------------------
    def fail_next(self, method: str, error: BaseException) -> None:
        """The next call of e.g. 'mouse.click' raises `error` once."""
        self._faults[method] = error

    def add_window(self, title: str, process: str, *, left: int = 0, top: int = 0, width: int = 40, height: int = 30,
                   class_name: str = "FakeClass", pid: int | None = None, active: bool = False) -> WindowInfo:
        info = WindowInfo(next(self._handles), title, process, pid if pid is not None else next(self._pid), class_name,
                          left, top, width, height)
        self.windows[info.handle] = info
        self.z_order.append(info.handle)
        if active or self.active_handle is None:
            self.active_handle = info.handle
        return info

    def calls_named(self, prefix: str) -> list[tuple[str, tuple]]:
        return [c for c in self.calls if c[0].startswith(prefix)]

    def _hit(self, method: str, *args: Any) -> None:
        self.calls.append((method, args))
        err = self._faults.pop(method, None)
        if err is not None:
            raise err

    def _paint(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self._canvas_w and 0 <= y < self._canvas_h:
            i = (y * self._canvas_w + x) * 3
            self.canvas[i:i + 3] = bytes(color)

    def bundle(self) -> ComputerBackend:
        return ComputerBackend(self.name, _Screen(self), _Mouse(self), _Keyboard(self), _Windows(self), _Apps(self))


class _Screen(ScreenProvider):
    def __init__(self, fb: FakeBackend) -> None:
        self.fb = fb

    def monitors(self) -> list[Monitor]:
        self.fb._hit("screen.monitors")
        return list(self.fb._monitors)

    def capture(self, monitor: Monitor | None) -> RawFrame:
        self.fb._hit("screen.capture", None if monitor is None else monitor.index)
        left, top, w, h = (0, 0, self.fb._canvas_w, self.fb._canvas_h) if monitor is None else \
            (monitor.left, monitor.top, monitor.width, monitor.height)
        stride = self.fb._canvas_w * 3
        rows = [bytes(self.fb.canvas[(top + y) * stride + left * 3:(top + y) * stride + (left + w) * 3]) for y in range(h)]
        return RawFrame(left, top, w, h, b"".join(rows))


class _Mouse(MouseProvider):
    def __init__(self, fb: FakeBackend) -> None:
        self.fb = fb

    def position(self) -> tuple[int, int]:
        return self.fb.cursor

    def move(self, x: int, y: int) -> None:
        self.fb._hit("mouse.move", x, y)
        self.fb.cursor = (x, y)

    def click(self, x: int, y: int, button: str, clicks: int) -> None:
        self.fb._hit("mouse.click", x, y, button, clicks)
        self.fb.cursor = (x, y)
        self.fb._paint(x, y, (255, 255, 255) if button == "left" else (255, 0, 0))

    def scroll(self, x: int, y: int, amount: int) -> None:
        self.fb._hit("mouse.scroll", x, y, amount)
        self.fb.cursor = (x, y)


class _Keyboard(KeyboardProvider):
    def __init__(self, fb: FakeBackend) -> None:
        self.fb = fb

    def press(self, key: str) -> None:
        self.fb._hit("keyboard.press", key)
        self.fb._paint(0, 1, (0, 255, 0))

    def hotkey(self, keys: Sequence[str]) -> None:
        self.fb._hit("keyboard.hotkey", tuple(keys))
        self.fb._paint(1, 1, (0, 255, 0))

    def type_text(self, text: str, interval: float) -> None:
        self.fb._hit("keyboard.type_text", text, interval)
        base = sum(len(t) for t in self.fb.typed)
        self.fb.typed.append(text)
        for i in range(len(text)):
            self.fb._paint((base + i) % self.fb._canvas_w, 0, (0, 0, 255))
        if self.fb.on_type:
            self.fb.on_type(text)


class _Windows(WindowProvider):
    def __init__(self, fb: FakeBackend) -> None:
        self.fb = fb

    def _info(self, h: int) -> WindowInfo:
        w = self.fb.windows[h]
        return replace(w, active=(h == self.fb.active_handle))

    def _need(self, handle: int) -> int:
        if handle not in self.fb.windows:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, f"window {handle} does not exist")
        return handle

    def list_windows(self) -> list[WindowInfo]:
        self.fb._hit("windows.list")
        return [self._info(h) for h in self.fb.z_order if h in self.fb.windows]

    def active_window(self) -> WindowInfo | None:
        self.fb._hit("windows.active")
        h = self.fb.active_handle
        return self._info(h) if h in self.fb.windows else None

    def window_at(self, x: int, y: int) -> WindowInfo | None:
        self.fb._hit("windows.window_at", x, y)
        for h in reversed(self.fb.z_order):
            w = self.fb.windows.get(h)
            if w and not w.minimized and w.left <= x < w.left + w.width and w.top <= y < w.top + w.height:
                return self._info(h)
        return None

    def focus(self, handle: int) -> None:
        self.fb._hit("windows.focus", handle)
        self._need(handle)
        if handle in self.fb.focus_denied:
            raise ComputerError(ErrorCode.BACKEND_ERROR, "Windows did not bring the window to the foreground (foreground lock)")
        if handle in self.fb.focus_ignored:
            return
        self.fb.active_handle = handle
        self.fb.windows[handle] = replace(self.fb.windows[handle], minimized=False)
        self.fb.z_order.remove(handle)
        self.fb.z_order.append(handle)

    def _set(self, method: str, handle: int, **changes: bool) -> None:
        self.fb._hit(method, handle)
        self.fb.windows[self._need(handle)] = replace(self.fb.windows[handle], **changes)

    def minimize(self, handle: int) -> None:
        self._set("windows.minimize", handle, minimized=True, maximized=False)

    def maximize(self, handle: int) -> None:
        self._set("windows.maximize", handle, maximized=True, minimized=False)

    def restore(self, handle: int) -> None:
        self._set("windows.restore", handle, maximized=False, minimized=False)

    def close(self, handle: int) -> None:
        self.fb._hit("windows.close", handle)
        self._need(handle)
        if handle in self.fb.refuse_close:  # e.g. an app asking "save changes?"
            return
        del self.fb.windows[handle]
        self.fb.z_order.remove(handle)
        if self.fb.active_handle == handle:
            self.fb.active_handle = self.fb.z_order[-1] if self.fb.z_order else None


class _Apps(AppLauncher):
    def __init__(self, fb: FakeBackend) -> None:
        self.fb = fb

    def launch(self, executable: str, args: Sequence[str]) -> LaunchResult:
        self.fb._hit("apps.launch", executable, tuple(args))
        self.fb.launched.append((executable, tuple(args)))
        if self.fb.on_launch:
            self.fb.on_launch(executable, tuple(args))
        return LaunchResult(next(self.fb._pid), executable)
