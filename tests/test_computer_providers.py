"""Concrete providers against injected fake libraries (no real display, mouse, keyboard or Windows needed),
plus REAL subprocess runs that prove application launching never goes through a shell."""
import os
import subprocess
import sys
import time
import types

import pytest

from jarvis.computer import ComputerError, ErrorCode, Monitor
from jarvis.computer.errors import ComputerUnavailableError
from jarvis.computer.providers import pyautogui_input as pgi
from jarvis.computer.providers.mss_screen import MssScreen
from jarvis.computer.providers.pyautogui_input import PyAutoGuiKeyboard, PyAutoGuiMouse
from jarvis.computer.providers.subprocess_apps import SubprocessLauncher, scrubbed_environment
from jarvis.computer.providers.win32_windows import SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE, Win32Api, Win32Windows
from jarvis.computer.providers.xlib_windows import XlibWindows

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell scripts")


def code(fn, *a, **k):
    with pytest.raises(ComputerError) as exc:
        fn(*a, **k)
    return exc.value.code


# =====================================================================================================================
# mss (screen)
# =====================================================================================================================
class FakeShot:
    def __init__(self, w, h):
        self.width, self.height, self.rgb = w, h, bytes((i % 251 for i in range(w * h * 3)))


def fake_mss(monitors, modern=True, fail_open=False, fail_grab=False):
    mod = types.ModuleType("mss")
    grabbed = []

    class Sct:
        def __init__(self):
            if fail_open:
                raise OSError("Xlib.error.DisplayConnectionError: cannot open display")
            self.monitors = monitors

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def grab(self, area):
            grabbed.append(dict(area))
            if fail_grab:
                raise RuntimeError("grab failed with secret pixels")
            return FakeShot(area["width"], area["height"])

    if modern:
        mod.MSS = Sct
    else:
        mod.mss = Sct  # mss < 10
    mod.grabbed = grabbed
    return mod


ALL = {"left": 0, "top": 0, "width": 3000, "height": 1000}


def test_mss_lists_monitors_primary_first_and_skips_the_virtual_screen(monkeypatch):
    mons = [ALL, {"left": 1920, "top": 0, "width": 1080, "height": 1000, "is_primary": False, "output": "HDMI-1"},
            {"left": 0, "top": 0, "width": 1920, "height": 1000, "is_primary": True, "output": "DP-1"}]
    monkeypatch.setitem(sys.modules, "mss", fake_mss(mons))
    got = MssScreen().monitors()
    assert [(m.index, m.left, m.width, m.primary, m.name) for m in got] == [(0, 0, 1920, True, "DP-1"), (1, 1920, 1080, False, "HDMI-1")]


def test_mss_without_is_primary_uses_the_monitor_at_the_origin(monkeypatch):
    mons = [ALL, {"left": -1280, "top": 0, "width": 1280, "height": 1024}, {"left": 0, "top": 0, "width": 1920, "height": 1080}]
    monkeypatch.setitem(sys.modules, "mss", fake_mss(mons, modern=False))  # also covers the pre-10 `mss.mss` name
    got = MssScreen().monitors()
    assert got[0].left == 0 and got[0].primary and got[1].left == -1280 and not got[1].primary


def test_mss_capture_areas_and_rgb(monkeypatch):
    mod = fake_mss([ALL, {"left": 0, "top": 0, "width": 40, "height": 20}])
    monkeypatch.setitem(sys.modules, "mss", mod)
    s = MssScreen()
    frame = s.capture(Monitor(0, 0, 0, 40, 20, True))
    assert (frame.left, frame.top, frame.width, frame.height) == (0, 0, 40, 20) and len(frame.rgb) == 40 * 20 * 3
    assert mod.grabbed[-1] == {"left": 0, "top": 0, "width": 40, "height": 20}
    full = s.capture(None)
    assert (full.width, full.height) == (3000, 1000) and mod.grabbed[-1] == ALL  # the combined virtual screen


def test_mss_error_mapping(monkeypatch):
    monkeypatch.setitem(sys.modules, "mss", fake_mss([ALL], fail_open=True))
    s = MssScreen()
    with pytest.raises(ComputerUnavailableError) as exc:
        s.monitors()
    assert exc.value.code is ErrorCode.NO_DISPLAY
    monkeypatch.setitem(sys.modules, "mss", fake_mss([ALL, {"left": 0, "top": 0, "width": 4, "height": 4}], fail_grab=True))
    with pytest.raises(ComputerError) as exc:
        MssScreen().capture(Monitor(0, 0, 0, 4, 4, True))
    assert exc.value.code is ErrorCode.BACKEND_ERROR and "secret pixels" not in str(exc.value)
    monkeypatch.setitem(sys.modules, "mss", fake_mss([ALL]))  # only the virtual screen -> no real monitors
    assert code(MssScreen().monitors) is ErrorCode.NO_DISPLAY


def test_mss_missing_or_broken_library_is_unavailable_not_a_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "mss", None)  # `import mss` -> ImportError
    with pytest.raises(ComputerUnavailableError, match="pip install"):
        MssScreen()


# =====================================================================================================================
# pyautogui (mouse + keyboard)
# =====================================================================================================================
class FailSafe(Exception):
    pass


def fake_pyautogui():
    m = types.ModuleType("pyautogui")
    m.PAUSE, m.FAILSAFE, m.FailSafeException, m.calls, m.raise_next = 0.1, False, FailSafe, [], None

    def rec(name):
        def f(*a, **k):
            m.calls.append((name, a, k))
            if m.raise_next:
                err, m.raise_next = m.raise_next, None
                raise err
        return f

    for n in ("moveTo", "click", "scroll", "press", "hotkey", "write", "keyUp"):
        setattr(m, n, rec(n))
    m.position = lambda: types.SimpleNamespace(x=11, y=22)
    return m


@pytest.fixture
def pg(monkeypatch):
    mod = fake_pyautogui()
    monkeypatch.setitem(sys.modules, "pyautogui", mod)
    monkeypatch.setattr(pgi, "_module", None)
    return mod


def test_pyautogui_is_configured_for_safety_and_cached(pg):
    PyAutoGuiMouse()
    assert pg.PAUSE == 0 and pg.FAILSAFE is True  # fail-safe (corner = emergency stop) stays ON
    assert pgi.load_pyautogui() is pg


def test_pyautogui_mouse_mapping(pg):
    m = PyAutoGuiMouse()
    assert m.position() == (11, 22)
    m.move(5, 6)
    m.click(7, 8, "right", 2)
    m.scroll(9, 10, -3)
    assert pg.calls == [("moveTo", (5, 6), {"duration": 0}),
                        ("click", (), {"x": 7, "y": 8, "button": "right", "clicks": 2, "interval": 0.05}),
                        ("scroll", (-3,), {"x": 9, "y": 10})]


def test_pyautogui_keyboard_mapping(pg):
    k = PyAutoGuiKeyboard()
    k.press("ENTER")
    k.press("PAGEUP")
    k.hotkey(("CTRL", "SHIFT", "S"))
    k.type_text("Hi!\n\tx", 0.01)
    assert pg.calls == [("press", ("enter",), {}), ("press", ("pageup",), {}), ("hotkey", ("ctrl", "shift", "s"), {}),
                        ("write", ("Hi!\n\tx",), {"interval": 0.01})]


@pytest.mark.parametrize("text", ["héllo", "日本語", "emoji 🚀", "a\x00b", "a\x1bb"])
def test_pyautogui_refuses_characters_it_cannot_type_instead_of_dropping_them(pg, text):
    assert code(PyAutoGuiKeyboard().type_text, text, 0) is ErrorCode.UNSUPPORTED
    assert pg.calls == []


def test_pyautogui_failsafe_and_errors_never_echo_messages(pg):
    k, m = PyAutoGuiKeyboard(), PyAutoGuiMouse()
    pg.raise_next = FailSafe("corner")
    assert code(m.click, 1, 1, "left", 1) is ErrorCode.FAILSAFE
    pg.raise_next = RuntimeError("could not type 'hunter22'")
    with pytest.raises(ComputerError) as exc:
        k.type_text("hunter22", 0)
    assert exc.value.code is ErrorCode.BACKEND_ERROR and "hunter22" not in str(exc.value) and "RuntimeError" in str(exc.value)


class _Boom:
    """meta-path finder making `import pyautogui` fail the way it does on a bare Linux box."""

    def __init__(self, exc):
        self.exc = exc

    def find_spec(self, name, path=None, target=None):
        if name == "pyautogui":
            raise self.exc
        return None


@pytest.mark.parametrize("exc,expected,text", [
    (ImportError("nope"), ErrorCode.BACKEND_UNAVAILABLE, "pip install"),
    (SystemExit("You must install tkinter on Linux to use MouseInfo"), ErrorCode.BACKEND_UNAVAILABLE, "python3-tk"),
    (KeyError("DISPLAY"), ErrorCode.NO_DISPLAY, "display"),
    (RuntimeError("weird"), ErrorCode.BACKEND_UNAVAILABLE, "RuntimeError"),
])
def test_pyautogui_import_hazards_are_contained(monkeypatch, exc, expected, text):
    monkeypatch.delitem(sys.modules, "pyautogui", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Boom(exc), *sys.meta_path])
    monkeypatch.setattr(pgi, "_module", None)
    with pytest.raises(ComputerUnavailableError) as exc_info:  # SystemExit must NOT escape and kill JARVIS
        PyAutoGuiMouse()
    assert exc_info.value.code is expected and text in str(exc_info.value)


# =====================================================================================================================
# Win32 windows (logic against a fake API facade; the real facade is Windows-only)
# =====================================================================================================================
class FakeWin32Api:
    def __init__(self):
        self.w = {}
        self.procs = {}
        self.fg = 0
        self.shown, self.closed = [], []
        self.allow_foreground, self.close_ok, self.boom = True, True, False
        self.attached = []

    def add(self, h, title="T", cls="Cls", pid=10, visible=True, cloaked=False, iconic=False, zoomed=False, rect=(1, 2, 30, 40), proc="app.exe"):
        self.w[h] = dict(title=title, cls=cls, pid=pid, visible=visible, cloaked=cloaked, iconic=iconic, zoomed=zoomed, rect=rect)
        self.procs[pid] = proc

    def _chk(self):
        if self.boom:
            raise OSError("win32 exploded")

    def enum_top_level(self):
        self._chk()
        return list(self.w)

    def is_window(self, h):
        return h in self.w

    is_visible = lambda self, h: self.w[h]["visible"]  # noqa: E731
    is_cloaked = lambda self, h: self.w[h]["cloaked"]  # noqa: E731
    is_iconic = lambda self, h: self.w[h]["iconic"]  # noqa: E731
    is_zoomed = lambda self, h: self.w[h]["zoomed"]  # noqa: E731
    title = lambda self, h: self.w[h]["title"]  # noqa: E731
    class_name = lambda self, h: self.w[h]["cls"]  # noqa: E731
    pid = lambda self, h: self.w[h]["pid"]  # noqa: E731
    process_name = lambda self, pid: self.procs.get(pid, "")  # noqa: E731
    rect = lambda self, h: self.w[h]["rect"]  # noqa: E731

    def foreground(self):
        return self.fg

    def window_from_point(self, x, y):
        return self.fg

    def show(self, h, cmd):
        self.shown.append((h, cmd))
        if cmd == SW_RESTORE:
            self.w[h]["iconic"] = False

    def set_foreground(self, h):
        if self.allow_foreground and (not self.lock or self._attached_now):
            self.fg = h
        return self.allow_foreground

    # foreground-lock simulation: a plain SetForegroundWindow fails when `lock` is on; joining the foreground thread's
    # input queue (AttachThreadInput) lets it through - exactly like the real OS rule
    lock = False
    attached: list = []
    attach_ok = True

    def current_thread_id(self):
        return 1

    def window_thread(self, h):
        return 2 if h == self.fg else 3

    def attach_thread_input(self, me, other, attach):
        self.attached.append((me, other, attach))
        self._attached_now = attach and self.attach_ok
        return self.attach_ok

    _attached_now = False

    def bring_to_top(self, h):
        return True

    def post_close(self, h):
        self.closed.append(h)
        return self.close_ok


@pytest.fixture
def api():
    a = FakeWin32Api()
    a.add(1, "Notepad", "Notepad", 10, proc="notepad.exe")
    a.add(2, "Hidden", pid=20, visible=False)
    a.add(3, "Ghost UWP", pid=21, cloaked=True)
    a.add(4, "", "NoTitle", pid=22)
    a.add(5, "Calc", "CalcFrame", 11, iconic=True, proc="calc.exe")
    a.fg = 1
    return a


def test_win32_lists_only_real_visible_windows(api):
    got = Win32Windows(api).list_windows()
    assert [(w.handle, w.title, w.process, w.pid, w.class_name) for w in got] == [(1, "Notepad", "notepad.exe", 10, "Notepad"),
                                                                                 (5, "Calc", "calc.exe", 11, "CalcFrame")]
    assert got[0].active and not got[1].active and got[1].minimized and (got[0].left, got[0].width) == (1, 30)


def test_win32_active_and_window_at(api):
    w = Win32Windows(api)
    assert w.active_window().title == "Notepad"
    api.fg = 0
    assert w.active_window() is None and w.window_at(5, 5) is None
    api.fg = 5
    assert w.window_at(5, 5).handle == 5


def test_win32_focus_restores_minimized_windows_and_verifies(api):
    w = Win32Windows(api)
    w.focus(5)
    assert api.shown == [(5, SW_RESTORE)] and api.fg == 5
    api.allow_foreground = False  # focus-stealing protection
    with pytest.raises(ComputerError) as exc:
        w.focus(1)
    assert exc.value.code is ErrorCode.BACKEND_ERROR and "focus-stealing" in str(exc.value)


def test_win32_show_commands_and_close_is_graceful(api):
    w = Win32Windows(api)
    w.minimize(1)
    w.maximize(1)
    w.restore(1)
    assert api.shown == [(1, SW_MINIMIZE), (1, SW_MAXIMIZE), (1, SW_RESTORE)]
    w.close(1)
    assert api.closed == [1]  # WM_CLOSE only: nothing in this provider can terminate a process
    api.close_ok = False
    assert code(w.close, 1) is ErrorCode.BACKEND_ERROR


@pytest.mark.parametrize("handle", [999, 0, -1, "1", None])
def test_win32_unknown_handles(api, handle):
    w = Win32Windows(api)
    for op in (w.focus, w.minimize, w.maximize, w.restore, w.close):
        assert code(op, handle) is ErrorCode.WINDOW_NOT_FOUND
    assert api.closed == [] and api.shown == []


def test_win32_api_errors_are_structured(api):
    api.boom = True
    assert code(Win32Windows(api).list_windows) is ErrorCode.BACKEND_ERROR


def test_win32_real_api_only_exists_on_windows():
    if sys.platform != "win32":
        with pytest.raises(ComputerUnavailableError, match="only works on Windows"):
            Win32Api()
        with pytest.raises(ComputerUnavailableError):
            Win32Windows()


# =====================================================================================================================
# X11 windows (development backend): clean failure without a display
# =====================================================================================================================
def test_xlib_without_a_display_is_unavailable_not_a_crash(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(ComputerUnavailableError) as exc:
        XlibWindows()
    assert exc.value.code in (ErrorCode.NO_DISPLAY, ErrorCode.BACKEND_UNAVAILABLE)


# =====================================================================================================================
# application launcher: argument list, never a shell
# =====================================================================================================================
RECORDER = """#!/bin/sh
out="$1"; shift
: > "$out"
for a in "$@"; do printf '%s\\n' "$a" >> "$out"; done
env > "$out.env"
"""


def wait_for(path, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(path) and os.path.exists(str(path) + ".env"):
            time.sleep(0.05)
            return
        time.sleep(0.02)
    raise AssertionError(f"{path} never appeared")


@posix_only
def test_arguments_with_shell_metacharacters_arrive_literally(tmp_path, monkeypatch):
    from computer_util import make_executable
    exe = make_executable(tmp_path / "rec.exe", RECORDER)
    out = tmp_path / "out.txt"
    monkeypatch.chdir(tmp_path)
    nasty = ["a b", "; touch PWNED1", "$(touch PWNED2)", "`touch PWNED3`", "| touch PWNED4", "&& touch PWNED5", "> PWNED6",
             "*", "~", "$HOME", "%PATH%", "--flag=1"]
    res = SubprocessLauncher().launch(exe, [str(out), *nasty])
    assert isinstance(res.pid, int) and res.pid > 0 and res.executable == exe
    wait_for(out)
    assert out.read_text(encoding="utf-8").splitlines() == nasty  # every string is exactly ONE argument, nothing was interpreted
    assert not [p.name for p in tmp_path.iterdir() if p.name.startswith("PWNED")]


@posix_only
def test_launched_programs_do_not_inherit_secret_environment_variables(tmp_path, monkeypatch):
    from computer_util import make_executable
    exe = make_executable(tmp_path / "rec.exe", RECORDER)
    out = tmp_path / "o.txt"
    for k, v in {"MY_SERVICE_API_KEY": "topsecret-111", "SOME_TOKEN": "topsecret-222", "DB_PASSWORD": "topsecret-333",
                 "CLIENT_SECRET": "topsecret-444", "HARMLESS_SETTING": "visible-ok"}.items():
        monkeypatch.setenv(k, v)
    SubprocessLauncher().launch(exe, [str(out)])
    wait_for(out)
    env = (tmp_path / "o.txt.env").read_text(encoding="utf-8")
    assert "topsecret" not in env and "API_KEY" not in env and "SOME_TOKEN" not in env and "DB_PASSWORD" not in env
    assert "HARMLESS_SETTING=visible-ok" in env and "PATH=" in env


def test_scrubbed_environment_function():
    env = scrubbed_environment({"OPENAI_API_KEY": "x", "ANTHROPIC_API_KEY": "y", "GITHUB_TOKEN": "z", "PGPASSWORD": "p",
                                "PATH": "/bin", "HOME": "/h", "AWS_SECRET_ACCESS_KEY": "s", "SystemRoot": "C:\\Windows"})
    assert env == {"PATH": "/bin", "HOME": "/h", "SystemRoot": "C:\\Windows"}


def test_popen_is_called_with_a_list_without_a_shell(tmp_path, monkeypatch):
    seen = {}

    class FakePopen:
        pid = 4321

        def __init__(self, argv, **kw):
            seen["argv"], seen["kw"] = argv, kw

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    res = SubprocessLauncher().launch("/opt/app/tool", ["one two", "three; rm -rf /"])
    kw = seen["kw"]
    assert seen["argv"] == ["/opt/app/tool", "one two", "three; rm -rf /"] and isinstance(seen["argv"], list)
    assert kw["shell"] is False and kw["stdin"] == subprocess.DEVNULL and kw["stdout"] == subprocess.DEVNULL
    assert kw["close_fds"] is True and "API_KEY" not in " ".join(kw["env"])
    assert (kw.get("start_new_session") is True) or "creationflags" in kw  # detached from JARVIS
    assert res.pid == 4321


@pytest.mark.parametrize("raised,message", [(FileNotFoundError("/x"), "not found"), (PermissionError("/x"), "permission denied"),
                                            (OSError("Exec format error /secret/path"), "OSError")])
def test_launch_failures_are_structured(monkeypatch, raised, message):
    def boom(*a, **k):
        raise raised

    monkeypatch.setattr(subprocess, "Popen", boom)
    with pytest.raises(ComputerError) as exc:
        SubprocessLauncher().launch("/opt/app/tool", [])
    assert exc.value.code is ErrorCode.LAUNCH_FAILED and message in str(exc.value) and "/secret/path" not in str(exc.value)


@posix_only
def test_real_launch_failures(tmp_path):
    f = tmp_path / "plain.exe"
    f.write_text("not a program")
    f.chmod(0o644)
    assert code(SubprocessLauncher().launch, str(f), []) is ErrorCode.LAUNCH_FAILED
    assert code(SubprocessLauncher().launch, str(tmp_path / "missing.exe"), []) is ErrorCode.LAUNCH_FAILED


@posix_only
def test_finished_programs_are_reaped_not_left_as_zombies(tmp_path):
    from computer_util import make_executable
    exe = make_executable(tmp_path / "quick.exe", "#!/bin/sh\nexit 0\n")
    launcher = SubprocessLauncher()
    first = launcher.launch(exe, []).pid
    for _ in range(100):  # wait until it has exited
        try:
            os.kill(first, 0)
            time.sleep(0.02)
        except OSError:
            break
        if launcher._children and launcher._children[0].poll() is not None:
            break
    launcher.launch(exe, [])  # the next launch reaps finished children
    assert all(p.pid != first for p in launcher._children)
    for p in launcher._children:
        p.wait(timeout=5)


def test_tracking_of_launched_children_is_bounded(monkeypatch):
    class Alive:
        pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: Alive())
    launcher = SubprocessLauncher()
    for _ in range(SubprocessLauncher.MAX_TRACKED + 20):
        launcher.launch("/x", [])
    assert len(launcher._children) == SubprocessLauncher.MAX_TRACKED


def test_an_aborted_hotkey_releases_its_modifiers(pg):
    """pyautogui.hotkey does not clean up when it fails halfway; a stuck CTRL would turn the next typing into shortcuts."""
    pg.raise_next = FailSafe("corner")
    with pytest.raises(ComputerError) as exc:
        PyAutoGuiKeyboard().hotkey(("CTRL", "SHIFT", "S"))
    assert exc.value.code is ErrorCode.FAILSAFE
    assert [c for c in pg.calls if c[0] == "keyUp"] == [("keyUp", ("s",), {}), ("keyUp", ("shift",), {}), ("keyUp", ("ctrl",), {})]
    pg.calls.clear()
    PyAutoGuiKeyboard().hotkey(("CTRL", "S"))  # a successful combination triggers no extra releases
    assert [c[0] for c in pg.calls] == ["hotkey"]


# ---- foreground lock (Windows) --------------------------------------------------------------------------------------------------------
def test_win32_focus_gets_through_the_foreground_lock_by_joining_the_input_queue(api):
    api.lock = True
    w = Win32Windows(api, sleep=lambda s: None)
    w.focus(5)
    assert api.fg == 5
    assert api.attached == [(1, 2, True), (1, 2, False)]  # attached to the old foreground thread, and detached again


def test_win32_focus_fails_loudly_when_the_lock_cannot_be_overcome(api):
    api.lock, api.attach_ok = True, False
    w = Win32Windows(api, sleep=lambda s: None)
    with pytest.raises(ComputerError) as exc:
        w.focus(5)
    assert exc.value.code is ErrorCode.BACKEND_ERROR and "foreground lock" in str(exc.value) and api.fg == 1
    assert all(a[2] is True for a in api.attached)  # nothing was attached that needed detaching


def test_win32_focus_never_leaves_threads_attached_even_if_the_call_raises(api):
    api.lock = True

    def boom(h):
        raise OSError("boom")

    api.bring_to_top = boom
    with pytest.raises(ComputerError):
        Win32Windows(api, sleep=lambda s: None).focus(5)
    assert api.attached == [(1, 2, True), (1, 2, False)]


def test_win32_provider_injects_no_input_events_to_win_the_focus(api):
    """The focus workaround only uses focus/queue calls: no keyboard/mouse event API exists on the facade."""
    import inspect
    from jarvis.computer.providers import win32_windows as mod
    src = inspect.getsource(mod)
    for forbidden in ("keybd_event", "SendInput", "mouse_event", "SetWindowsHookEx", "WriteProcessMemory",
                      "CreateRemoteThread", "TerminateProcess"):
        assert forbidden not in src
