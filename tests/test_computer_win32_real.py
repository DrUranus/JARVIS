"""Real Windows tests of the Win32 window provider (skipped everywhere else).

They create their own harmless top-level windows with the standard library (tkinter) - no other application is
touched, nothing is typed or clicked, nothing leaves the machine. They need an interactive desktop session; if
Windows will not give a plain test process the foreground at all the foreground tests skip instead of failing.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="real Win32 API")

from jarvis.computer.errors import ComputerError  # noqa: E402


@pytest.fixture(scope="module")
def tk():
    tkinter = pytest.importorskip("tkinter")
    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no interactive desktop")
    root.withdraw()
    yield tkinter, root
    root.destroy()


@pytest.fixture(scope="module")
def api():
    from jarvis.computer.providers.win32_windows import Win32Api
    return Win32Api()


def make_window(tk, title):
    tkinter, root = tk
    w = tkinter.Toplevel(root)
    w.title(title)
    w.geometry("300x120+60+60")
    w.update()
    return w


def hwnd(api, widget):
    widget.update()
    return int(api.user32.GetAncestor(widget.winfo_id(), 2) or widget.winfo_id())


def test_api_facade_basics(api):
    assert api.current_thread_id() > 0
    handles = api.enum_top_level()
    assert handles and all(isinstance(h, int) for h in handles)
    fg = api.foreground()
    if fg:
        assert api.window_thread(fg) > 0 and api.pid(fg) > 0


def test_provider_lists_its_own_window_with_correct_process_info(tk, api):
    from jarvis.computer.providers.win32_windows import Win32Windows
    w = make_window(tk, "JARVIS-win32-test-A")
    try:
        found = [x for x in Win32Windows(api).list_windows() if x.title == "JARVIS-win32-test-A"]
        assert len(found) == 1
        assert found[0].pid == os.getpid() and found[0].process.lower().startswith("python")
        assert found[0].width > 100 and found[0].height > 50
    finally:
        w.destroy()


def test_focus_brings_a_window_to_the_front_even_from_the_background(tk, api):
    from jarvis.computer.providers.win32_windows import Win32Windows
    provider = Win32Windows(api)
    a, b = make_window(tk, "JARVIS-win32-test-A"), make_window(tk, "JARVIS-win32-test-B")
    try:
        ha, hb = hwnd(api, a), hwnd(api, b)
        try:
            provider.focus(ha)
        except ComputerError:
            pytest.skip("this session may not take the foreground at all")
        assert provider.active_window().handle == ha
        provider.focus(hb)  # switch back and forth: the second one is where the foreground lock usually bites
        assert provider.active_window().handle == hb
        provider.focus(ha)
        assert provider.active_window().handle == ha
    finally:
        a.destroy()
        b.destroy()


def test_focus_restores_a_minimized_window_and_unknown_handles_fail_cleanly(tk, api):
    from jarvis.computer.providers.win32_windows import Win32Windows
    provider = Win32Windows(api)
    w = make_window(tk, "JARVIS-win32-test-M")
    try:
        h = hwnd(api, w)
        provider.minimize(h)
        assert api.is_iconic(h)
        try:
            provider.focus(h)
        except ComputerError:
            pytest.skip("this session may not take the foreground at all")
        assert not api.is_iconic(h) and provider.active_window().handle == h
    finally:
        w.destroy()
    with pytest.raises(ComputerError):
        provider.focus(h)  # destroyed: a clean WINDOW_NOT_FOUND, no crash
