"""A harmless X11 test application (python-xlib only): one window that records the keys it receives, mouse clicks,
hotkeys and close requests into files. Used by the real-GUI test to prove JARVIS' computer control end to end on a
virtual display (Xvfb). It touches nothing but its own files.

usage: x11_app.py <record_file> <ready_file> <title> <x_offset>
"""
import ctypes
import os
import sys


def set_process_name(name: str) -> None:
    try:  # Linux: the 'process' JARVIS sees for this window (python itself is a blocked script host)
        ctypes.CDLL(None).prctl(15, name.encode(), 0, 0, 0)
    except Exception:
        pass


set_process_name("jarvis-xapp")

from Xlib import X, XK, Xatom, display  # noqa: E402
from Xlib.protocol import event as xevent  # noqa: E402


def main() -> None:
    record, ready, title, x_off = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    d = display.Display()
    scr = d.screen()
    win = scr.root.create_window(60 + x_off, 60, 420, 220, 1, scr.root_depth, X.InputOutput, X.CopyFromParent,
                                 background_pixel=scr.white_pixel,
                                 event_mask=X.ExposureMask | X.KeyPressMask | X.ButtonPressMask | X.StructureNotifyMask)
    utf8 = d.intern_atom("UTF8_STRING")
    win.change_property(d.intern_atom("_NET_WM_NAME"), utf8, 8, title.encode())
    win.set_wm_name(title)
    win.set_wm_class("jarvis-xapp", "JarvisXApp")
    win.change_property(d.intern_atom("_NET_WM_PID"), Xatom.CARDINAL, 32, [os.getpid()])
    delete, protocols = d.intern_atom("WM_DELETE_WINDOW"), d.intern_atom("WM_PROTOCOLS")
    win.change_property(protocols, Xatom.ATOM, 32, [delete])
    win.map()
    black = win.create_gc(foreground=scr.black_pixel)
    red = win.create_gc(foreground=scr.default_colormap.alloc_color(65535, 0, 0).pixel)
    d.sync()
    typed, n = [], 0
    with open(ready, "w") as f:
        f.write(str(os.getpid()))
    while True:
        ev = d.next_event()
        if ev.type == X.ClientMessage and ev.client_type == protocols and ev.data[1][0] == delete:
            with open(record + ".closed", "w") as f:
                f.write("closed")
            return
        if ev.type == X.ButtonPress:
            with open(record + ".clicks", "a") as f:
                f.write(f"{ev.detail} {ev.event_x} {ev.event_y}\n")
            win.fill_rectangle(red, ev.event_x - 3, ev.event_y - 3, 7, 7)
            d.sync()
        elif ev.type == X.KeyPress:
            sym = d.keycode_to_keysym(ev.detail, 1 if ev.state & X.ShiftMask else 0)
            char = chr(sym) if 0x20 <= sym <= 0x7E else {0xFF0D: "\n", 0xFF09: "\t"}.get(sym, "")
            if ev.state & X.ControlMask:
                with open(record + ".hotkeys", "a") as f:
                    f.write(f"ctrl+{char}\n")
                continue
            if sym == 0xFF08 and typed:  # BackSpace
                typed.pop()
            elif char:
                typed.append(char)
                win.fill_rectangle(black, 10 + 12 * (n % 30), 10 + 14 * (n // 30), 8, 8)
                n += 1
            with open(record, "w", encoding="utf-8") as f:
                f.write("".join(typed))
            d.sync()


if __name__ == "__main__":
    main()
