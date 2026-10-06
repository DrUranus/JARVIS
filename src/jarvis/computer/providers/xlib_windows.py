"""Window management on X11 through python-xlib. Development / verification backend (Linux); the target
platform is Windows. Works without a window manager (Xvfb): minimize/maximize then report `unsupported`."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from jarvis.computer.backend import WindowProvider
from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode
from jarvis.computer.models import WindowInfo


def _load_xlib() -> tuple[Any, Any, Any]:
    try:
        from Xlib import X, display, error
    except ImportError:
        raise ComputerUnavailableError("python-xlib is not installed (pip install 'jarvis-ai[computer]')") from None
    except Exception as exc:
        raise ComputerUnavailableError(f"python-xlib could not be loaded ({type(exc).__name__})") from None
    return X, display, error


class XlibWindows(WindowProvider):
    def __init__(self) -> None:
        self._X, self._display, self._error = _load_xlib()
        with self._open():  # fail early and cleanly when no X server is reachable
            pass

    @contextmanager
    def _open(self) -> Iterator[Any]:
        try:
            d = self._display.Display()
        except Exception as exc:
            raise ComputerUnavailableError(f"cannot connect to the X server ({type(exc).__name__})", ErrorCode.NO_DISPLAY) from None
        try:
            yield d
        except self._error.XError as exc:
            raise ComputerError(ErrorCode.BACKEND_ERROR, f"X11 error ({type(exc).__name__})") from None
        finally:
            d.close()

    # -- properties ----------------------------------------------------------------------------------------------
    def _name(self, d: Any, win: Any) -> str:
        for atom, ptype in (("_NET_WM_NAME", "UTF8_STRING"), ("WM_NAME", 0)):
            try:
                prop = win.get_full_property(d.intern_atom(atom), d.intern_atom(ptype) if ptype else 0)
            except self._error.XError:
                continue
            if prop and prop.value:
                v = prop.value
                return (v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)).strip()
        return ""

    def _pid(self, d: Any, win: Any) -> int:
        try:
            prop = win.get_full_property(d.intern_atom("_NET_WM_PID"), 0)
            return int(prop.value[0]) if prop and len(prop.value) else 0
        except self._error.XError:
            return 0

    @staticmethod
    def _process(pid: int) -> str:
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def _is_viewable(self, win: Any) -> bool:
        try:
            return win.get_attributes().map_state == self._X.IsViewable
        except self._error.XError:
            return False

    def _client(self, d: Any, top: Any) -> Any | None:
        """The named client window of a top-level window (a reparenting WM wraps clients in frames)."""
        if self._name(d, top):
            return top
        try:
            for child in top.query_tree().children:
                if self._name(d, child):
                    return child
        except self._error.XError:
            pass
        return None

    def _info(self, d: Any, win: Any, active_id: int | None) -> WindowInfo:
        pid = self._pid(d, win)
        wm_class = ""
        try:
            cls = win.get_wm_class()
            wm_class = cls[1] if cls else ""
        except self._error.XError:
            pass
        try:
            g = win.get_geometry()
            rect = (g.x, g.y, g.width, g.height)
        except self._error.XError:
            rect = (0, 0, 0, 0)
        return WindowInfo(win.id, self._name(d, win), self._process(pid), pid, wm_class, *rect,
                          active=(active_id is not None and win.id == active_id))

    def _active_id(self, d: Any) -> int | None:
        root = d.screen().root
        focus = d.get_input_focus().focus
        win = focus if hasattr(focus, "query_tree") else None
        if win is None or win.id == root.id:  # PointerRoot / None: the window under the pointer
            win = root.query_pointer().child
            if not win:
                return None
        while True:  # climb to the top-level window
            tree = win.query_tree()
            if tree.parent is None or tree.parent.id == root.id:
                break
            win = tree.parent
        client = self._client(d, win)
        return client.id if client else None

    # -- WindowProvider ---------------------------------------------------------------------------------------------
    def list_windows(self) -> list[WindowInfo]:
        with self._open() as d:
            active = self._active_id(d)
            out = []
            for top in d.screen().root.query_tree().children:
                if not self._is_viewable(top):
                    continue
                client = self._client(d, top)
                if client is not None:
                    out.append(self._info(d, client, active))
            return out

    def active_window(self) -> WindowInfo | None:
        with self._open() as d:
            aid = self._active_id(d)
            if aid is None:
                return None
            return self._info(d, d.create_resource_object("window", aid), aid)

    def window_at(self, x: int, y: int) -> WindowInfo | None:
        with self._open() as d:
            active = self._active_id(d)
            for top in reversed(d.screen().root.query_tree().children):  # last child = topmost
                if not self._is_viewable(top):
                    continue
                g = top.get_geometry()
                if g.x <= x < g.x + g.width and g.y <= y < g.y + g.height:
                    client = self._client(d, top)
                    if client is not None:
                        return self._info(d, client, active)
            return None

    def _window(self, d: Any, handle: int) -> Any:
        if not isinstance(handle, int) or handle <= 0:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, f"window {handle} does not exist")
        win = d.create_resource_object("window", handle)
        try:
            win.get_attributes()
        except self._error.XError:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, f"window {handle} does not exist") from None
        return win

    def focus(self, handle: int) -> None:
        with self._open() as d:
            win = self._window(d, handle)
            win.configure(stack_mode=self._X.Above)
            win.set_input_focus(self._X.RevertToParent, self._X.CurrentTime)
            d.sync()

    def close(self, handle: int) -> None:
        from Xlib import protocol  # noqa: PLC0415 - lazy, same optional dependency
        with self._open() as d:
            win = self._window(d, handle)
            delete, protocols = d.intern_atom("WM_DELETE_WINDOW"), d.intern_atom("WM_PROTOCOLS")
            supported = win.get_full_property(protocols, 0)
            if not supported or delete not in list(supported.value):
                raise ComputerError(ErrorCode.UNSUPPORTED, "the window does not support a graceful close request")
            event = protocol.event.ClientMessage(window=win, client_type=protocols, data=(32, [delete, self._X.CurrentTime, 0, 0, 0]))
            win.send_event(event, event_mask=0)
            d.sync()
