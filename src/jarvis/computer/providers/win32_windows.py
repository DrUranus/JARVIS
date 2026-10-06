"""Window management on the Win32 API through ctypes (standard library only).

`Win32Api` is a thin, separately injectable facade over user32/kernel32/dwmapi, so the provider logic can be unit
tested with a fake facade on any OS. Closing is graceful (WM_CLOSE, like the X button); processes are never killed.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from jarvis.computer.backend import WindowProvider
from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode
from jarvis.computer.models import WindowInfo

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
WM_CLOSE = 0x0010
GA_ROOT = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DWMWA_CLOAKED = 14


class Win32Api:
    """The only place that touches ctypes.windll. Handles are plain ints."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise ComputerUnavailableError("the Win32 window provider only works on Windows")
        import ctypes
        from ctypes import wintypes
        self._ct, self._wt = ctypes, wintypes
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        k = self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        H, I, L, B = wintypes.HWND, wintypes.INT, wintypes.LPARAM, wintypes.BOOL
        self._enum_proc = ctypes.WINFUNCTYPE(B, H, L)
        for fn, args, res in (
            (u.EnumWindows, [self._enum_proc, L], B), (u.IsWindow, [H], B), (u.IsWindowVisible, [H], B),
            (u.IsIconic, [H], B), (u.IsZoomed, [H], B), (u.GetWindowTextLengthW, [H], I),
            (u.GetWindowTextW, [H, wintypes.LPWSTR, I], I), (u.GetClassNameW, [H, wintypes.LPWSTR, I], I),
            (u.GetWindowThreadProcessId, [H, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            (u.GetWindowRect, [H, ctypes.POINTER(wintypes.RECT)], B), (u.GetForegroundWindow, [], H),
            (u.SetForegroundWindow, [H], B), (u.ShowWindow, [H, I], B), (u.PostMessageW, [H, wintypes.UINT, wintypes.WPARAM, L], B),
            (u.WindowFromPoint, [wintypes.POINT], H), (u.GetAncestor, [H, wintypes.UINT], H),
            (k.OpenProcess, [wintypes.DWORD, B, wintypes.DWORD], wintypes.HANDLE), (k.CloseHandle, [wintypes.HANDLE], B),
            (k.QueryFullProcessImageNameW, [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], B),
        ):
            fn.argtypes, fn.restype = args, res
        try:
            self._dwm = ctypes.WinDLL("dwmapi")
            self._dwm.DwmGetWindowAttribute.argtypes = [H, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            self._dwm.DwmGetWindowAttribute.restype = ctypes.c_long
        except OSError:
            self._dwm = None

    def enum_top_level(self) -> list[int]:
        found: list[int] = []

        def cb(hwnd: Any, _lparam: Any) -> bool:
            found.append(int(hwnd or 0))
            return True

        self.user32.EnumWindows(self._enum_proc(cb), 0)
        return found

    def is_window(self, h: int) -> bool:
        return bool(self.user32.IsWindow(h))

    def is_visible(self, h: int) -> bool:
        return bool(self.user32.IsWindowVisible(h))

    def is_iconic(self, h: int) -> bool:
        return bool(self.user32.IsIconic(h))

    def is_zoomed(self, h: int) -> bool:
        return bool(self.user32.IsZoomed(h))

    def is_cloaked(self, h: int) -> bool:  # hidden UWP windows are "visible" but cloaked
        if self._dwm is None:
            return False
        flag = self._wt.DWORD(0)
        ok = self._dwm.DwmGetWindowAttribute(h, DWMWA_CLOAKED, self._ct.byref(flag), self._ct.sizeof(flag)) == 0
        return ok and bool(flag.value)

    def title(self, h: int) -> str:
        n = self.user32.GetWindowTextLengthW(h)
        if n <= 0:
            return ""
        buf = self._ct.create_unicode_buffer(n + 1)
        self.user32.GetWindowTextW(h, buf, n + 1)
        return buf.value

    def class_name(self, h: int) -> str:
        buf = self._ct.create_unicode_buffer(256)
        self.user32.GetClassNameW(h, buf, 256)
        return buf.value

    def pid(self, h: int) -> int:
        pid = self._wt.DWORD(0)
        self.user32.GetWindowThreadProcessId(h, self._ct.byref(pid))
        return int(pid.value)

    def process_name(self, pid: int) -> str:
        proc = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not proc:
            return ""
        try:
            size = self._wt.DWORD(1024)
            buf = self._ct.create_unicode_buffer(1024)
            if self.kernel32.QueryFullProcessImageNameW(proc, 0, buf, self._ct.byref(size)):
                return os.path.basename(buf.value)
            return ""
        finally:
            self.kernel32.CloseHandle(proc)

    def rect(self, h: int) -> tuple[int, int, int, int]:
        r = self._wt.RECT()
        self.user32.GetWindowRect(h, self._ct.byref(r))
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def foreground(self) -> int:
        return int(self.user32.GetForegroundWindow() or 0)

    def window_from_point(self, x: int, y: int) -> int:
        h = self.user32.WindowFromPoint(self._wt.POINT(x, y))
        return int(self.user32.GetAncestor(h, GA_ROOT) or 0) if h else 0

    def show(self, h: int, cmd: int) -> None:
        self.user32.ShowWindow(h, cmd)

    def set_foreground(self, h: int) -> bool:
        return bool(self.user32.SetForegroundWindow(h))

    def post_close(self, h: int) -> bool:
        return bool(self.user32.PostMessageW(h, WM_CLOSE, 0, 0))


class Win32Windows(WindowProvider):
    def __init__(self, api: Any = None) -> None:
        self.api = api if api is not None else Win32Api()

    def _info(self, h: int, foreground: int) -> WindowInfo:
        a = self.api
        pid = a.pid(h)
        left, top, width, height = a.rect(h)
        return WindowInfo(h, a.title(h), a.process_name(pid), pid, a.class_name(h), left, top, width, height,
                          a.is_iconic(h), a.is_zoomed(h), h == foreground)

    def _guard(self, fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except ComputerError:
            raise
        except OSError as exc:
            raise ComputerError(ErrorCode.BACKEND_ERROR, f"Windows API error ({type(exc).__name__})") from None

    def list_windows(self) -> list[WindowInfo]:
        def run() -> list[WindowInfo]:
            fg = self.api.foreground()
            out = []
            for h in self.api.enum_top_level():
                if self.api.is_visible(h) and not self.api.is_cloaked(h) and self.api.title(h).strip():
                    out.append(self._info(h, fg))
            return out
        return self._guard(run)

    def active_window(self) -> WindowInfo | None:
        def run() -> WindowInfo | None:
            h = self.api.foreground()
            return self._info(h, h) if h and self.api.is_window(h) else None
        return self._guard(run)

    def window_at(self, x: int, y: int) -> WindowInfo | None:
        def run() -> WindowInfo | None:
            h = self.api.window_from_point(x, y)
            return self._info(h, self.api.foreground()) if h and self.api.is_window(h) else None
        return self._guard(run)

    def _need(self, handle: int) -> int:
        if not isinstance(handle, int) or not self.api.is_window(handle):
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, f"window {handle} does not exist")
        return handle

    def focus(self, handle: int) -> None:
        def run() -> None:
            h = self._need(handle)
            if self.api.is_iconic(h):
                self.api.show(h, SW_RESTORE)
            self.api.set_foreground(h)
            if self.api.foreground() != h:  # Windows' focus-stealing protection refused: report, do not hack around it
                raise ComputerError(ErrorCode.BACKEND_ERROR, "Windows did not bring the window to the foreground "
                                                             "(focus-stealing protection); click it or use Alt+Tab manually")
        self._guard(run)

    def minimize(self, handle: int) -> None:
        self._guard(lambda: self.api.show(self._need(handle), SW_MINIMIZE))

    def maximize(self, handle: int) -> None:
        self._guard(lambda: self.api.show(self._need(handle), SW_MAXIMIZE))

    def restore(self, handle: int) -> None:
        self._guard(lambda: self.api.show(self._need(handle), SW_RESTORE))

    def close(self, handle: int) -> None:
        def run() -> None:
            if not self.api.post_close(self._need(handle)):
                raise ComputerError(ErrorCode.BACKEND_ERROR, "the window did not accept the close request")
        self._guard(run)
