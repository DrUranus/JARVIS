"""Pure building blocks: validation, resources, safety classification, screenshots, PNG, diff, verification."""
import struct
import zlib
from datetime import datetime, timezone

import pytest

from jarvis.computer import (ComputerError, ComputerSafety, ErrorCode, Monitor, RawFrame, Screenshot, ScreenshotStore,
                            WindowInfo, encode_png, frame_diff, verify_change)
from jarvis.computer import resources as res
from jarvis.computer import validation as val
from jarvis.computer.errors import ComputerUnavailableError
from jarvis.computer.safety import BLOCKED_STEMS, stem_of
from jarvis.permissions import PermissionLevel

G, Y, R = PermissionLevel.GREEN, PermissionLevel.YELLOW, PermissionLevel.RED
MON = Monitor(0, 0, 0, 100, 50, True)
MON2 = Monitor(1, 100, 0, 40, 30)


def code(fn, *a, **k):
    with pytest.raises(ComputerError) as exc:
        fn(*a, **k)
    return exc.value.code


# ---- errors --------------------------------------------------------------------------------------------------------
def test_error_is_structured():
    e = ComputerError(ErrorCode.INVALID_COORDINATES, "bad point", monitor=0)
    assert str(e) == "[invalid_coordinates] bad point" and e.code is ErrorCode.INVALID_COORDINATES
    assert e.to_dict() == {"code": "invalid_coordinates", "message": "bad point", "details": {"monitor": 0}}
    assert ComputerError(ErrorCode.UNSUPPORTED, "x").to_dict() == {"code": "unsupported", "message": "x"}
    u = ComputerUnavailableError("no lib")
    assert u.code is ErrorCode.BACKEND_UNAVAILABLE and isinstance(u, ComputerError)
    from jarvis.errors import JarvisError
    assert isinstance(e, JarvisError)


# ---- coordinates / monitors ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("x,y", [(0, 0), (99, 49), (50, 25), ("7", "8")])
def test_points_inside_the_monitor(x, y):
    assert val.validate_point(x, y, MON) == (int(x), int(y))


@pytest.mark.parametrize("x,y", [(-1, 0), (0, -1), (100, 0), (0, 50), (100, 50), (10_000, 5), (-5000, -5000), (99, 50)])
def test_points_outside_are_rejected_never_clamped(x, y):
    assert code(val.validate_point, x, y, MON) is ErrorCode.INVALID_COORDINATES


@pytest.mark.parametrize("bad", [1.5, "1.5", None, True, False, [1], "abc", "", " ", float("nan"), float("inf"), "1e3", "０"])
def test_non_integer_coordinates_are_invalid_input(bad):
    assert code(val.validate_point, bad, 1, MON) is ErrorCode.INVALID_INPUT
    assert code(val.validate_point, 1, bad, MON) is ErrorCode.INVALID_INPUT


def test_error_message_names_the_bounds():
    with pytest.raises(ComputerError) as exc:
        val.validate_point(500, 5, MON)
    assert "x 0..99" in exc.value.message and "y 0..49" in exc.value.message and exc.value.details["width"] == 100


def test_monitor_validation():
    assert val.validate_monitor(1, [MON, MON2]) is MON2 and val.validate_monitor("0", [MON, MON2]) is MON
    for bad in (2, -1, 99):
        assert code(val.validate_monitor, bad, [MON, MON2]) is ErrorCode.INVALID_MONITOR
    assert code(val.validate_monitor, None, [MON]) is ErrorCode.INVALID_INPUT
    assert code(val.validate_monitor, 0, []) is ErrorCode.NO_DISPLAY
    assert val.as_int(" 12 ", "n") == 12 and val.as_int(-3, "n") == -3


def test_scroll_amount():
    assert val.validate_scroll(3, 20) == 3 and val.validate_scroll("-5", 20) == -5
    for bad in (0, 21, -21, "x", 1.5, None):
        assert code(val.validate_scroll, bad, 20) in (ErrorCode.INVALID_INPUT,)


# ---- keys / hotkeys -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,key", [("a", "A"), ("Enter", "ENTER"), ("return", "ENTER"), ("esc", "ESC"), ("Escape", "ESC"),
                                     ("del", "DELETE"), ("pgup", "PAGEUP"), ("control", "CTRL"), ("f5", "F5"), (" ", "SPACE"),
                                     ("7", "7"), ("/", "/"), ("cmd", "WIN"), ("LWIN", "WIN"), ("  tab  ", "TAB"), ("enter\n", "ENTER")])
def test_key_names_are_normalised(raw, key):
    assert val.normalize_key(raw) == key


@pytest.mark.parametrize("bad", ["", "  ", "f13", "super_mega", "ctrl+s", "é", "\x00", None, 5, ["a"], "a" * 50])
def test_unknown_keys_are_rejected(bad):
    assert code(val.normalize_key, bad) is ErrorCode.INVALID_INPUT


def test_hotkeys():
    assert val.parse_hotkey("ctrl+s", 4) == ("CTRL", "S")
    assert val.parse_hotkey("Shift+Ctrl+z", 4) == ("CTRL", "SHIFT", "Z")  # modifiers first, canonical order
    assert val.parse_hotkey(["alt", "f4"], 4) == ("ALT", "F4")
    assert val.parse_hotkey("ctrl+alt+shift+t", 4) == ("CTRL", "ALT", "SHIFT", "T")


@pytest.mark.parametrize("bad", ["s", "ctrl", "ctrl+", "+s", "ctrl++s", "ctrl+ctrl+s", "ctrl+shift", "a+b", "ctrl+a+b",
                                 "ctrl+alt+shift+win+t", "", None, 5, {"ctrl": "s"}, "ctrl+f13"])
def test_invalid_hotkeys(bad):
    assert code(val.parse_hotkey, bad, 4) is ErrorCode.INVALID_INPUT


# ---- text ---------------------------------------------------------------------------------------------------------------------
def test_text_validation():
    assert val.validate_text("Hallo Welt äöü 🚀", 100) == "Hallo Welt äöü 🚀"
    assert val.validate_text("a\nb\tc", 100) == "a\nb\tc"
    for bad in ("", None, 5, "x" * 101, "a\x00b", "a\x1bb", "a\x7fb", "a\rb"):
        assert code(val.validate_text, bad, 100) is ErrorCode.INVALID_INPUT


def test_text_is_never_echoed_in_errors():
    for bad in ("secret-pass\x00word", "hunter22" * 50):
        with pytest.raises(ComputerError) as exc:
            val.validate_text(bad, 20)
        assert "hunter22" not in str(exc.value) and "secret-pass" not in str(exc.value)


# ---- application arguments ------------------------------------------------------------------------------------------------------
def test_app_args():
    assert val.validate_app_args(None) == () and val.validate_app_args([]) == () and val.validate_app_args("") == ()
    assert val.validate_app_args(["a", "b c", "--flag=1"]) == ("a", "b c", "--flag=1")
    assert val.validate_app_args("one two; rm -rf /") == ("one two; rm -rf /",)  # ONE argument, never split or parsed
    assert val.validate_app_args(("x",)) == ("x",)
    for bad in ([1], [None], 5, {"a": 1}, ["a\x00b"], ["a\nb"], ["x" * 1001], ["a"] * 17):
        assert code(val.validate_app_args, bad) is ErrorCode.INVALID_INPUT


# ---- resources ----------------------------------------------------------------------------------------------------------------
def test_resource_uris():
    assert res.screen_resource(0) == "screen://monitor/0" and res.screen_resource(None) == "screen://all"
    assert res.mouse_resource(1, 20, 30) == "screen://monitor/1/20/30"
    assert res.key_resource("ENTER", "notepad.exe") == "keyboard://key/ENTER@notepad.exe"
    assert res.hotkey_resource(("CTRL", "S"), "notepad.exe") == "keyboard://hotkey/CTRL+S@notepad.exe"
    assert res.text_resource("notepad.exe") == "keyboard://text@notepad.exe"
    assert res.window_resource(66012, "notepad.exe") == "window://66012/notepad.exe"
    assert res.app_resource(r"C:\Windows\System32\notepad.exe") == "app://C:/Windows/System32/notepad.exe"
    assert res.screen_info_resource("windows") == "screen://windows"


def test_app_resource_binds_arguments_by_digest_not_content():
    base = res.app_resource("/bin/x")
    a, b = res.app_resource("/bin/x", ["secret.txt"]), res.app_resource("/bin/x", ["other.txt"])
    assert base == "app:///bin/x" and a != b != base and a.startswith(base + "?args=") and "secret" not in a
    assert res.app_resource("/bin/x", ["secret.txt"]) == a  # deterministic


def test_resources_sanitise_os_provided_names():
    r = res.key_resource("A", "evil\nname/../\x00x")
    assert "\n" not in r and "\x00" not in r and "/../" not in r.split("@", 1)[1]
    assert res.window_resource(1, "") == "window://1/unknown"


# ---- safety classification --------------------------------------------------------------------------------------------------------
def win(title="Doc - Notepad", process="notepad.exe", cls="Notepad", pid=500):
    return WindowInfo(1, title, process, pid, cls, 0, 0, 10, 10)


@pytest.mark.parametrize("path", [r"C:\Windows\System32\cmd.exe", "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
                                  "pwsh.exe", "/usr/bin/bash", "/bin/sh", r"C:\Python313\python.exe", "/usr/bin/python3.13",
                                  "pythonw.exe", "wscript.exe", "mshta.exe", "rundll32.exe", "regedit.exe", "taskmgr.exe",
                                  "wt.exe", "msiexec.exe", "certutil.exe", "curl.exe", "ssh.exe", "schtasks.exe", "net.exe",
                                  "CMD.EXE", "WindowsTerminal.exe", "node.exe", "SecHealthUI.exe", "MpCmdRun.exe", "sudo",
                                  "xterm", "reg.exe", "diskpart.exe", "shutdown.exe", "taskkill.exe", "wsl.exe"])
def test_dangerous_executables_are_red(path):
    v = ComputerSafety().executable_verdict(path)
    assert v.level is R and v.blocked and v.reason


@pytest.mark.parametrize("path", [r"C:\Windows\System32\notepad.exe", "calc.exe", "mspaint.exe", "/usr/bin/gedit", "fakenote.exe",
                                  "firefox.exe", r"C:\Program Files\App\app.exe"])
def test_ordinary_executables_are_not_blocked(path):
    assert not ComputerSafety().executable_verdict(path).blocked


def test_config_can_only_add_to_the_blocklists():
    safe = ComputerSafety(extra_processes=["secret-tool.exe"], extra_titles=["Bank Login"])
    assert safe.executable_verdict("C:/x/secret-tool.exe").blocked
    assert safe.window_blocked_reason(win("My Bank Login - Browser", "browser.exe"))
    assert safe.executable_verdict("cmd.exe").blocked  # built-ins stay, whatever is configured
    assert ComputerSafety(extra_processes=[], extra_titles=[]).executable_verdict("cmd.exe").blocked
    assert "cmd" in BLOCKED_STEMS and stem_of("C:\\a\\CMD.EXE") == "cmd" and stem_of("/usr/bin/python3.13") == "python3.13"


@pytest.mark.parametrize("w", [win("C:\\Windows\\System32\\cmd.exe", "cmd.exe", "ConsoleWindowClass"),
                               win("Windows PowerShell", "powershell.exe"), win("Administrator: Command Prompt", "cmd.exe"),
                               win("Task Manager", "Taskmgr.exe"), win("Registry Editor", "regedit.exe"),
                               win("Windows Security", "SecHealthUI.exe"), win("User Account Control", "consent.exe"),
                               win("Run", "explorer.exe"), win("Start", "StartMenuExperienceHost.exe"),
                               win("Ubuntu", "WindowsTerminal.exe", "CASCADIA_HOSTING_WINDOW_CLASS"),
                               win("anything", "x.exe", "ConsoleWindowClass"), win("Windows Defender Firewall", "mmc.exe"),
                               win("notes about POWERSHELL scripts", "notepad.exe")])  # titles are matched conservatively
def test_terminals_shells_and_security_windows_receive_no_input(w):
    assert ComputerSafety().window_blocked_reason(w)
    assert ComputerSafety().window_input_verdict(w).level is R


def test_ordinary_and_missing_windows_are_not_blocked():
    s = ComputerSafety()
    assert s.window_blocked_reason(win()) is None and s.window_blocked_reason(None) is None
    assert s.window_input_verdict(win("Report.docx - Word", "winword.exe")).level is Y


def test_close_protection():
    s = ComputerSafety(own_pids=[4242])
    assert s.window_close_verdict(win(pid=4242)).level is R and "own window" in s.window_close_verdict(win(pid=4242)).reason
    assert s.window_close_verdict(win("Program Manager", "explorer.exe", "Progman")).blocked
    assert s.window_close_verdict(win("", "explorer.exe", "Shell_TrayWnd")).blocked
    assert s.window_close_verdict(win("x", "winlogon.exe")).blocked and s.window_close_verdict(win("x", "dwm.exe")).blocked
    assert s.window_close_verdict(win("Windows PowerShell", "powershell.exe")).blocked
    assert not s.window_close_verdict(win()).blocked


@pytest.mark.parametrize("keys", [("WIN", "R"), ("WIN", "X"), ("WIN", "D"), ("CTRL", "ALT", "DELETE"), ("CTRL", "SHIFT", "ESC"),
                                  ("CTRL", "ESC"), ("ALT", "ESC"), ("SHIFT", "WIN", "S"), ("CTRL", "WIN", "D")])
def test_dangerous_hotkeys_are_red(keys):
    v = ComputerSafety().hotkey_verdict(keys)
    assert v.level is R and v.reason


@pytest.mark.parametrize("keys", [("CTRL", "S"), ("CTRL", "C"), ("ALT", "F4"), ("ALT", "TAB"), ("CTRL", "SHIFT", "T"), ("SHIFT", "F10")])
def test_ordinary_hotkeys_are_not_blocked(keys):
    assert ComputerSafety().hotkey_verdict(keys).level is Y


def test_windows_key_alone_is_red():
    s = ComputerSafety()
    assert s.key_verdict("WIN").blocked and not s.key_verdict("ENTER").blocked


# ---- screenshots ------------------------------------------------------------------------------------------------------------------
def shot(w=4, h=3, fill=(10, 20, 30), monitor=0, paint=()):
    data = bytearray(bytes(fill) * (w * h))
    for x, y, c in paint:
        data[(y * w + x) * 3:(y * w + x) * 3 + 3] = bytes(c)
    return Screenshot.from_frame(RawFrame(0, 0, w, h, bytes(data)), monitor)


def test_screenshot_info_never_contains_pixels():
    s = shot()
    info = s.info()
    assert info["bytes"] == 36 and info["width"] == 4 and info["id"].startswith("shot-") and len(info["sha256"]) == 16
    assert "data" not in info and s.data not in str(info).encode()
    assert "data" not in repr(s) and "\\x0a" not in repr(s) and s.sha256 not in repr(s)
    assert shot(monitor=None).info()["monitor"] == "all"
    assert isinstance(s.captured_at, datetime) and s.captured_at.tzinfo is timezone.utc


def test_store_is_bounded_and_ordered():
    store = ScreenshotStore(max_items=2)
    a, b, c = (store.add(shot(fill=(i, i, i))) for i in (1, 2, 3))
    assert store.ids() == [b.id, c.id] and store.latest() is c
    assert code(store.get, a.id) is ErrorCode.INVALID_INPUT
    assert store.get(b.id) is b and store.clear() == 2 and store.ids() == [] and store.latest() is None


def test_store_respects_a_byte_budget_but_keeps_the_newest():
    store = ScreenshotStore(max_items=10, max_bytes=100)
    big = [store.add(shot(w=6, h=4, fill=(i, 0, 0))) for i in range(5)]  # 72 bytes each
    assert store.ids() == [big[-1].id]


def test_png_encoding_is_a_valid_png():
    s = shot(4, 3, paint=[(1, 1, (255, 0, 0))])
    png = encode_png(4, 3, s.data)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    pos, chunks, idat = 8, [], b""
    while pos < len(png):
        n = struct.unpack(">I", png[pos:pos + 4])[0]
        kind, body = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + n]
        assert struct.unpack(">I", png[pos + 8 + n:pos + 12 + n])[0] == zlib.crc32(kind + body) & 0xFFFFFFFF
        chunks.append(kind)
        idat += body if kind == b"IDAT" else b""
        pos += 12 + n
    assert chunks == [b"IHDR", b"IDAT", b"IEND"]
    assert struct.unpack(">IIBBBBB", png[16:29]) == (4, 3, 8, 2, 0, 0, 0)
    raw = zlib.decompress(idat)
    assert len(raw) == 3 * (1 + 12) and raw[0] == 0 and raw[13 + 1 + 3:13 + 1 + 6] == b"\xff\x00\x00"  # pixel (1,1) is red


def test_png_rejects_inconsistent_data():
    assert code(encode_png, 2, 2, b"\x00" * 5) is ErrorCode.INVALID_INPUT
    assert code(encode_png, 0, 2, b"") is ErrorCode.INVALID_INPUT


def test_frame_diff():
    a = shot()
    assert frame_diff(a, shot()).identical and frame_diff(a, shot()).changed_ratio == 0.0
    d = frame_diff(a, shot(paint=[(1, 1, (255, 255, 255)), (3, 2, (0, 0, 0))]))
    assert d.comparable and not d.identical and d.changed_pixels == 2 and d.changed_ratio == pytest.approx(2 / 12)
    assert d.bbox == (1, 1, 3, 2)
    assert frame_diff(a, shot(w=5, h=3)).comparable is False
    assert d.info()["bbox"] == [1, 1, 3, 2] and frame_diff(a, shot()).info()["bbox"] is None


def test_verify_change():
    before, after = shot(), shot(paint=[(0, 0, (9, 9, 9))])
    assert verify_change(before, after).ok and verify_change(before, before).ok is False
    assert verify_change(before, before, expect_change=False).ok and not verify_change(before, after, expect_change=False).ok
    assert verify_change(before, after, min_changed_ratio=0.5).ok is False  # change too small to count
    assert verify_change(before, shot(w=9, h=9)).ok  # size change counts as a change


def test_monitor_contains():
    assert MON.contains(0, 0) and MON.contains(99, 49) and not MON.contains(100, 0) and not MON.contains(-1, 5)
