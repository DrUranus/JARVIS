"""ComputerController against the fake backend. Controller calls run inside engine-issued approvals (`approved`),
exactly like production tool calls; without one every action must be refused."""
import os
import sys
import threading
import time

import pytest

from computer_util import G, ONCE, R, Y, approved, make_executable, make_rig
from jarvis.computer import (ComputerBackend, ComputerController, ComputerError, ErrorCode, Monitor)
from jarvis.computer.providers.fake import FakeBackend
from jarvis.config import ComputerSettings
from jarvis.permissions import PermissionEngine, PermissionRequest, ResourceType, ScriptedConfirmation


def code(fn, *a, **k):
    with pytest.raises(ComputerError) as exc:
        fn(*a, **k)
    return exc.value.code


def go(rig, plan):
    """Execute a plan inside a real approval."""
    with approved(rig.engine, plan):
        return rig.controller.execute(plan)


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path, [ONCE] * 40)


# ---- mouse -------------------------------------------------------------------------------------------------------------------
def test_mouse_actions_reach_the_provider_with_absolute_coordinates(rig):
    c, fb = rig.controller, rig.fb
    assert go(rig, c.plan_mouse("move", 5, 6)) == {"action": "move", "monitor": 0, "x": 5, "y": 6}
    go(rig, c.plan_mouse("click", 10, 11))
    go(rig, c.plan_mouse("double_click", 12, 13))
    go(rig, c.plan_mouse("right_click", 14, 15))
    go(rig, c.plan_mouse("scroll", 20, 21, amount=-3))
    assert fb.calls_named("mouse") == [
        ("mouse.move", (5, 6)), ("mouse.click", (10, 11, "left", 1)), ("mouse.click", (12, 13, "left", 2)),
        ("mouse.click", (14, 15, "right", 1)), ("mouse.scroll", (20, 21, -3))]


def test_second_monitor_coordinates_are_offset_by_its_position(rig):
    go(rig, rig.controller.plan_mouse("click", 5, 7, monitor=1))
    assert rig.fb.calls_named("mouse.click") == [("mouse.click", (69, 7, "left", 1))]  # monitor 1 starts at x=64
    plan = rig.controller.plan_mouse("click", 5, 7, monitor="1")
    assert plan.resource == "screen://monitor/1/5/7"


@pytest.mark.parametrize("x,y,monitor", [(64, 0, None), (0, 48, None), (-1, 0, None), (5000, 5000, None), (32, 0, 1), (0, 24, 1),
                                         (-1, -1, 1)])
def test_out_of_bounds_points_never_reach_the_provider(rig, x, y, monitor):
    assert code(rig.controller.plan_mouse, "click", x, y, monitor=monitor) is ErrorCode.INVALID_COORDINATES
    assert rig.fb.calls_named("mouse") == []


def test_edge_pixels_are_valid(rig):
    for x, y, m in ((0, 0, 0), (63, 47, 0), (0, 0, 1), (31, 23, 1)):
        assert rig.controller.plan_mouse("move", x, y, monitor=m).resource == f"screen://monitor/{m}/{x}/{y}"


@pytest.mark.parametrize("monitor", [2, 7, -1, "all", "x", 1.5])
def test_invalid_monitors_for_mouse(rig, monitor):
    assert code(rig.controller.plan_mouse, "click", 1, 1, monitor=monitor) in (ErrorCode.INVALID_MONITOR, ErrorCode.INVALID_INPUT)


def test_unknown_mouse_action_and_scroll_bounds(rig):
    assert code(rig.controller.plan_mouse, "drag", 1, 1) is ErrorCode.INVALID_INPUT
    for amount in (None, 0, 21, -21, "x"):
        assert code(rig.controller.plan_mouse, "scroll", 1, 1, amount=amount) is ErrorCode.INVALID_INPUT


def test_default_monitor_setting_and_stale_default(tmp_path):
    r = make_rig(tmp_path, default_monitor=1)
    assert r.controller.plan_mouse("move", 1, 1).resource == "screen://monitor/1/1/1"
    r = make_rig(tmp_path / "b", default_monitor=5)  # monitor unplugged: only an UNSPECIFIED monitor falls back to primary
    assert r.controller.plan_mouse("move", 1, 1).resource == "screen://monitor/0/1/1"
    assert code(r.controller.plan_mouse, "move", 1, 1, monitor=5) is ErrorCode.INVALID_MONITOR  # explicit stays an error


def test_mouse_plan_is_yellow_and_describes_the_target(rig):
    p = rig.controller.plan_mouse("click", 10, 10)
    assert p.level is Y and p.tool == "mouse" and p.action == "click" and p.resource == "screen://monitor/0/10/10"
    assert "Notepad" in p.context["ziel"] and p.context["monitor"] == "0 (64x48)"
    assert rig.controller.plan_mouse("scroll", 10, 10, amount=2).context["schritte"] == "2"
    assert p.to_spec().resource_type is ResourceType.OTHER and p.to_spec().level is Y


def test_clicking_a_protected_window_is_red(tmp_path):
    r = make_rig(tmp_path)
    r.fb.add_window("Windows Security", "SecHealthUI.exe", left=40, top=0, width=20, height=20)
    p = r.controller.plan_mouse("click", 45, 5)
    assert p.level is R and p.blocked and "receives no input" in p.reason
    assert r.controller.plan_mouse("click", 5, 5).level is Y  # the Notepad area is fine


def test_mouse_without_window_info_is_still_yellow(tmp_path):
    fb = FakeBackend()
    b = fb.bundle()
    b.windows = None
    c = ComputerController(b, ComputerSettings(enabled=True), sleep=lambda s: None)
    assert c.plan_mouse("click", 1, 1).level is Y and "unbekannt" in c.plan_mouse("click", 1, 1).context["ziel"]


# ---- keyboard ---------------------------------------------------------------------------------------------------------------------
def test_keyboard_actions_and_resources(rig):
    c = rig.controller
    assert go(rig, c.plan_keyboard("press", key="enter")) == {"action": "press", "key": "ENTER"}
    assert go(rig, c.plan_keyboard("hotkey", keys="ctrl+s")) == {"action": "hotkey", "keys": ["CTRL", "S"]}
    assert go(rig, c.plan_keyboard("type", text="Hallo 123")) == {"action": "type", "characters": 9}
    assert rig.fb.calls_named("keyboard") == [("keyboard.press", ("ENTER",)), ("keyboard.hotkey", (("CTRL", "S"),)),
                                              ("keyboard.type_text", ("Hallo 123", 0.02))]
    assert c.plan_keyboard("press", key="a").resource == "keyboard://key/A@notepad.exe"
    assert c.plan_keyboard("hotkey", keys="ctrl+s").resource == "keyboard://hotkey/CTRL+S@notepad.exe"
    assert c.plan_keyboard("type", text="x").resource == "keyboard://text@notepad.exe"


def test_the_typed_text_is_not_part_of_the_resource_or_reason(rig):
    p = rig.controller.plan_keyboard("type", text="hunter22-super-secret")
    assert "hunter22" not in p.resource and "hunter22" not in p.reason and p.context["zeichen"] == "21"
    assert p.context["vorschau"] == "hunter22-super-secret"  # shown to the user at the prompt only


def test_text_preview_is_truncated_and_can_be_switched_off(tmp_path):
    r = make_rig(tmp_path)
    ctx = r.controller.plan_keyboard("type", text="a\nb\t" + "x" * 100).context
    assert ctx["vorschau"].startswith("a⏎b⇥x") and ctx["vorschau"].endswith("…") and len(ctx["vorschau"]) == 41
    r2 = make_rig(tmp_path / "b", show_text_preview=False)
    assert "vorschau" not in r2.controller.plan_keyboard("type", text="secret").context


def test_keyboard_validation_errors_leave_the_provider_untouched(rig):
    c = rig.controller
    for kw in ({"action": "press", "key": "f13"}, {"action": "hotkey", "keys": "s"}, {"action": "hotkey", "keys": "ctrl+ctrl+s"},
               {"action": "type", "text": ""}, {"action": "type", "text": "x" * 501}, {"action": "type", "text": "a\x00b"},
               {"action": "type", "text": None}, {"action": "bogus"}, {"action": "press"}):
        assert code(c.plan_keyboard, **kw) is ErrorCode.INVALID_INPUT, kw
    assert rig.fb.calls_named("keyboard") == []


def test_max_text_length_is_configurable(tmp_path):
    r = make_rig(tmp_path, max_text_length=5)
    assert r.controller.plan_keyboard("type", text="12345") and code(r.controller.plan_keyboard, "type", text="123456") is ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("title,process", [("Windows PowerShell", "powershell.exe"), ("C:\\Windows\\cmd.exe", "cmd.exe"),
                                           ("Task Manager", "Taskmgr.exe"), ("Run", "explorer.exe"), ("x", "WindowsTerminal.exe")])
def test_keyboard_to_a_terminal_or_security_window_is_red(tmp_path, title, process):
    r = make_rig(tmp_path, notepad=False)
    r.fb.add_window(title, process, active=True)
    for plan in (r.controller.plan_keyboard("type", text="format c:"), r.controller.plan_keyboard("press", key="enter"),
                 r.controller.plan_keyboard("hotkey", keys="ctrl+c")):
        assert plan.level is R and plan.blocked and plan.reason
    assert r.fb.calls_named("keyboard") == []


def test_dangerous_keys_and_hotkeys_are_red_even_in_a_harmless_window(rig):
    c = rig.controller
    for kw in ({"action": "press", "key": "win"}, {"action": "hotkey", "keys": "win+r"}, {"action": "hotkey", "keys": "ctrl+alt+delete"},
               {"action": "hotkey", "keys": "ctrl+shift+esc"}, {"action": "hotkey", "keys": "win+x"}):
        assert c.plan_keyboard(**kw).level is R, kw
    assert c.plan_keyboard("hotkey", keys="alt+f4").level is Y


def test_forbidden_keys_are_red_even_without_any_window(tmp_path):
    r = make_rig(tmp_path, notepad=False)  # no window at all
    for kw in ({"action": "hotkey", "keys": "win+r"}, {"action": "press", "key": "win"}, {"action": "hotkey", "keys": "ctrl+alt+delete"}):
        p = r.controller.plan_keyboard(**kw)
        assert p.level is R and p.blocked and p.resource.endswith("@none") and p.context["ziel"] == "unbekannt", kw
    out = r.run("keyboard", action="hotkey", keys="win+r")
    assert not out.success and out.permission.matched_rule == "invariant:red"  # an audited denial, not a 'no window' error
    assert [e for e in r.sink.events if e.type.value == "permission_denied"][-1].action == "hotkey"
    assert r.fb.calls_named("keyboard.") == []


def test_keyboard_needs_a_known_target_window(tmp_path):
    r = make_rig(tmp_path, notepad=False)  # no window at all
    assert code(r.controller.plan_keyboard, "type", text="x") is ErrorCode.WINDOW_NOT_FOUND
    assert code(r.controller.plan_keyboard, "press", key="a") is ErrorCode.WINDOW_NOT_FOUND  # harmless keys still need a target
    assert code(r.controller.plan_keyboard, "hotkey", keys="ctrl+s") is ErrorCode.WINDOW_NOT_FOUND
    fb = FakeBackend()
    b = fb.bundle()
    b.windows = None  # a backend that cannot inspect windows cannot be trusted with keyboard input
    c = ComputerController(b, ComputerSettings(enabled=True))
    assert code(c.plan_keyboard, "type", text="x") is ErrorCode.UNSUPPORTED


def test_typing_is_refused_when_the_active_window_changed_after_planning(rig):
    plan = rig.controller.plan_keyboard("type", text="hello")
    other = rig.fb.add_window("Other", "other.exe")
    rig.fb.active_handle = other.handle
    with approved(rig.engine, plan):
        assert code(rig.controller.execute, plan) is ErrorCode.TARGET_CHANGED
    assert rig.fb.typed == []


def test_typing_is_refused_when_the_target_became_a_terminal(rig):
    plan = rig.controller.plan_keyboard("type", text="rm -rf /")
    term = rig.fb.add_window("Windows PowerShell", "powershell.exe")
    rig.fb.active_handle = term.handle
    with approved(rig.engine, plan):
        assert code(rig.controller.execute, plan) is ErrorCode.BLOCKED_TARGET  # terminal check comes before the handle check
    assert rig.fb.typed == []


# ---- windows -----------------------------------------------------------------------------------------------------------------------
def test_window_operations(rig):
    c, fb = rig.controller, rig.fb
    other = fb.add_window("Calculator", "calc.exe", left=10, top=10)
    hs = go(rig, c.plan_screen("windows"))
    assert [w["process"] for w in hs] == ["notepad.exe", "calc.exe"] and hs[0]["active"] and not hs[1]["active"]
    assert go(rig, c.plan_screen("active_window"))["title"] == "Untitled - Notepad"
    assert go(rig, c.plan_window("focus", other.handle)) == {"action": "focus", "handle": other.handle}
    assert go(rig, c.plan_screen("active_window"))["process"] == "calc.exe"
    go(rig, c.plan_window("minimize", other.handle))
    assert fb.windows[other.handle].minimized
    go(rig, c.plan_window("maximize", other.handle))
    assert fb.windows[other.handle].maximized and not fb.windows[other.handle].minimized
    go(rig, c.plan_window("restore", other.handle))
    assert not fb.windows[other.handle].maximized
    go(rig, c.plan_window("close", other.handle))
    assert other.handle not in fb.windows and [w["process"] for w in go(rig, c.plan_screen("windows"))] == ["notepad.exe"]


def test_window_resource_and_context(rig):
    h = next(iter(rig.fb.windows))
    p = rig.controller.plan_window("close", h)
    assert p.resource == f"window://{h}/notepad.exe" and p.level is Y and "Notepad" in p.context["fenster"]
    assert p.context["handle"] == str(h)


@pytest.mark.parametrize("handle", [99999, 0, -5, "x", None, 1.5])
def test_unavailable_windows(rig, handle):
    assert code(rig.controller.plan_window, "focus", handle) in (ErrorCode.WINDOW_NOT_FOUND, ErrorCode.INVALID_INPUT)


def test_window_closed_between_plan_and_execute_is_a_controlled_error(rig):
    h = next(iter(rig.fb.windows))
    plan = rig.controller.plan_window("focus", h)
    del rig.fb.windows[h]
    rig.fb.z_order.remove(h)
    with approved(rig.engine, plan):
        assert code(rig.controller.execute, plan) is ErrorCode.WINDOW_NOT_FOUND


def test_protected_windows_are_never_closable(tmp_path):
    r = make_rig(tmp_path)
    shell = r.fb.add_window("Program Manager", "explorer.exe", class_name="Progman")
    term = r.fb.add_window("Windows PowerShell", "powershell.exe")
    mine = r.fb.add_window("JARVIS", "WindowsTerminal.exe", pid=4242)
    r.controller._safety = type(r.controller.safety)(own_pids=[4242])
    for w in (shell, term, mine):
        p = r.controller.plan_window("close", w.handle)
        assert p.level is R and p.blocked, w.title
        assert r.controller.plan_window("minimize", w.handle).level is Y  # non-destructive actions stay possible


def test_close_that_the_app_declines_is_not_an_error(rig):
    h = next(iter(rig.fb.windows))
    rig.fb.refuse_close.add(h)  # "save changes?" dialog
    go(rig, rig.controller.plan_window("close", h))
    assert h in rig.fb.windows


def test_unsupported_window_operations_are_structured_errors(tmp_path):
    from jarvis.computer.backend import WindowProvider

    class Minimal(WindowProvider):  # like Xvfb without a window manager
        def list_windows(self):
            from jarvis.computer import WindowInfo
            return [WindowInfo(7, "T", "t.exe")]

        def active_window(self):
            return None

        def focus(self, handle):
            pass

        def close(self, handle):
            pass

    b = FakeBackend().bundle()
    b.windows = Minimal()
    r = make_rig(tmp_path, [ONCE])
    c = ComputerController(b, r.settings, sleep=lambda s: None, own_pids=())
    with approved(r.engine, c.plan_window("minimize", 7)):
        assert code(c.execute, c.plan_window("minimize", 7)) is ErrorCode.UNSUPPORTED
    assert c._window_at(1, 1) is None  # window_at unsupported -> classification simply unavailable


# ---- applications ------------------------------------------------------------------------------------------------------------------
def test_launch_alias_resolves_to_the_real_executable(rig):
    p = rig.controller.plan_app("notepad")
    exe = os.path.realpath(rig.app_path)
    assert p.tool == "app" and p.action == "launch" and p.level is Y and p.resource == "app://" + exe.replace("\\", "/")
    assert p.context["programm"] == exe and p.context["anwendung"] == "notepad"
    assert go(rig, p)["executable"] == exe
    assert rig.fb.launched == [(exe, ())]


def test_aliases_are_case_insensitive(rig):
    assert rig.controller.plan_app("NoTePaD").resource == rig.controller.plan_app("notepad").resource


def test_arguments_are_passed_as_a_list_and_bound_into_the_resource(rig):
    args = ["file one.txt", "--flag=1", "& calc.exe", "$(whoami)", "`id`", "a;b|c>d", "%PATH%"]
    p = rig.controller.plan_app("notepad", args)
    assert "?args=" in p.resource and "whoami" not in p.resource and "calc" not in p.resource
    assert p.context["argumente"].startswith("file one.txt --flag=1 & calc.exe")
    go(rig, p)
    assert rig.fb.launched[0][1] == tuple(args)  # every metacharacter string arrives as ONE literal argument
    assert rig.controller.plan_app("notepad", ["a"]).resource != rig.controller.plan_app("notepad", ["b"]).resource
    assert rig.controller.plan_app("notepad", "x y").resource == rig.controller.plan_app("notepad", ["x y"]).resource


@pytest.mark.parametrize("name", ["cmd", "powershell", "calc", "C:\\Windows\\System32\\cmd.exe", "/bin/sh", "../../bin/sh", "notepad.exe",
                                  "notepad && calc", "notepad; calc", "x" * 100])
def test_unlisted_applications_are_red_and_audited_not_resolved(rig, name):
    p = rig.controller.plan_app(name)
    assert p.level is R and p.blocked and p.resource.startswith("app://unlisted/") and "not an allowed application" in p.reason
    assert rig.fb.launched == []


@pytest.mark.parametrize("bad", ["", "  ", None, 5, "a\x00b", "a\nb", "x" * 300, ["notepad"]])
def test_invalid_application_names(rig, bad):
    assert code(rig.controller.plan_app, bad) is ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("bad", [[1], ["a\x00"], ["x" * 2000], ["a"] * 17, {"a": 1}, 7])
def test_invalid_application_arguments(rig, bad):
    assert code(rig.controller.plan_app, "notepad", bad) is ErrorCode.INVALID_INPUT


def test_alias_pointing_at_a_blocked_program_is_red(tmp_path):
    cmd = make_executable(tmp_path / "bin" / "cmd.exe")
    py = make_executable(tmp_path / "bin" / "python3.13")
    r = make_rig(tmp_path, apps={"terminal": cmd, "snake": py})
    for alias in ("terminal", "snake"):
        p = r.controller.plan_app(alias)
        assert p.level is R and "never launched" in p.reason, alias


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_a_harmless_looking_alias_cannot_hide_a_blocked_target(tmp_path):
    real = make_executable(tmp_path / "bin" / "powershell.exe")
    link = tmp_path / "bin" / "innocent.exe"
    link.symlink_to(real)
    r = make_rig(tmp_path, apps={"innocent": str(link)})
    assert r.controller.plan_app("innocent").level is R  # judged by the resolved target


def test_missing_or_non_executable_targets_are_launch_errors(tmp_path):
    f = tmp_path / "bin" / "plain.exe"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("data")
    f.chmod(0o644)
    r = make_rig(tmp_path, apps={"ghost": str(tmp_path / "bin" / "nothing.exe"), "plain": str(f), "folder": str(tmp_path)})
    for alias in ("ghost", "folder"):
        assert code(r.controller.plan_app, alias) is ErrorCode.LAUNCH_FAILED
    if sys.platform != "win32":
        assert code(r.controller.plan_app, "plain") is ErrorCode.LAUNCH_FAILED  # no execute permission


def test_unlisted_paths_only_when_explicitly_allowed(tmp_path):
    other = make_executable(tmp_path / "other" / "tool.exe")
    r = make_rig(tmp_path)
    assert r.controller.plan_app(other).level is R
    r2 = make_rig(tmp_path / "x", allow_unlisted_apps=True)
    assert r2.controller.plan_app(other).level is Y and r2.controller.plan_app(other).resource.endswith("tool.exe")
    assert r2.controller.plan_app("tool.exe").level is R  # relative names are never resolved
    cmd = make_executable(tmp_path / "other" / "cmd.exe")
    assert r2.controller.plan_app(cmd).level is R  # the hard block list still applies


def test_launch_failure_is_a_structured_error(rig):
    plan = rig.controller.plan_app("notepad")
    rig.fb.fail_next("apps.launch", ComputerError(ErrorCode.LAUNCH_FAILED, "executable not found"))
    with approved(rig.engine, plan):
        assert code(rig.controller.execute, plan) is ErrorCode.LAUNCH_FAILED


def test_default_apps_exist_on_windows_only(tmp_path, monkeypatch):
    r = make_rig(tmp_path)
    assert set(r.controller.effective_apps()) == {"notepad"}
    monkeypatch.setattr(sys, "platform", "win32")
    assert {"notepad", "calculator", "paint"} <= set(r.controller.effective_apps())
    r2 = make_rig(tmp_path / "b", use_default_apps=False)
    assert set(r2.controller.effective_apps()) == {"notepad"}


# ---- screen --------------------------------------------------------------------------------------------------------------------------
def test_monitors_and_cursor(rig):
    mons = go(rig, rig.controller.plan_screen("monitors"))
    assert [(m["index"], m["width"], m["primary"]) for m in mons] == [(0, 64, True), (1, 32, False)]
    rig.fb.cursor = (70, 5)
    assert go(rig, rig.controller.plan_screen("cursor")) == {"monitor": 1, "x": 6, "y": 5}
    rig.fb.cursor = (9999, 9999)
    assert go(rig, rig.controller.plan_screen("cursor"))["monitor"] is None


def test_screenshot_flow_and_storage(rig):
    c = rig.controller
    a = go(rig, c.plan_screen("screenshot"))
    b = go(rig, c.plan_screen("screenshot", monitor=1))
    full = go(rig, c.plan_screen("screenshot", monitor="all"))
    assert (a["width"], a["height"], a["monitor"]) == (64, 48, 0) and (b["width"], b["monitor"]) == (32, 1)
    assert (full["width"], full["height"], full["monitor"]) == (96, 48, "all")
    assert "data" not in a and a["bytes"] == 64 * 48 * 3 and c.screenshots.ids() == [a["id"], b["id"], full["id"]]
    assert c.screenshots.get(a["id"]).data[:3] == bytes((30, 30, 30))


def test_screenshots_are_never_written_to_disk(rig, tmp_path):
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    go(rig, rig.controller.plan_screen("screenshot"))
    assert {p for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("monitor", [2, -1, 99, "x", 1.5])
def test_invalid_screenshot_monitor(rig, monitor):
    assert code(rig.controller.plan_screen, "screenshot", monitor=monitor) in (ErrorCode.INVALID_MONITOR, ErrorCode.INVALID_INPUT)
    assert rig.fb.calls_named("screen.capture") == []


def test_screenshot_size_limit(tmp_path):
    r = make_rig(tmp_path, screenshot_max_pixels=100)
    assert code(r.controller.plan_screen, "screenshot") is ErrorCode.INVALID_INPUT and r.fb.calls_named("screen.capture") == []


def test_store_limit_follows_config(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, screenshot_max_items=2)
    ids = [go(r, r.controller.plan_screen("screenshot"))["id"] for _ in range(3)]
    assert r.controller.screenshots.ids() == ids[1:]


def test_action_observe_verify_flow(rig):
    c = rig.controller
    before = go(rig, c.plan_screen("screenshot"))["id"]
    go(rig, c.plan_mouse("click", 10, 10))
    after = go(rig, c.plan_screen("screenshot"))["id"]
    d = go(rig, c.plan_screen("compare", a=before, b=after))
    assert d["comparable"] and not d["identical"] and d["changed_pixels"] == 1 and d["bbox"] == [10, 10, 10, 10]
    assert go(rig, c.plan_screen("compare", a=before, b=before))["identical"]


def test_compare_needs_stored_screenshots_and_forget_clears(rig):
    assert code(rig.controller.plan_screen, "compare", a="nope", b="nope") is ErrorCode.INVALID_INPUT
    go(rig, rig.controller.plan_screen("screenshot"))
    assert go(rig, rig.controller.plan_screen("forget")) == {"forgotten": 1} and rig.controller.screenshots.ids() == []


def test_unknown_screen_action(rig):
    assert code(rig.controller.plan_screen, "record_video") is ErrorCode.INVALID_INPUT


# ---- failures never crash, never echo ----------------------------------------------------------------------------------------------------
def test_unsupported_capabilities(tmp_path):
    c = ComputerController(ComputerBackend("empty"), ComputerSettings(enabled=True))
    assert c.describe()["capabilities"] == []
    for fn in (lambda: c.plan_screen("monitors").to_spec() and c.plan_screen("screenshot"), lambda: c.plan_mouse("click", 1, 1),
               lambda: c.plan_keyboard("press", key="a"), lambda: c.plan_window("focus", 1), lambda: c.plan_app("notepad")):
        assert code(fn) is ErrorCode.UNSUPPORTED


def test_no_display_is_reported_as_such(rig):
    rig.fb.fail_next("screen.monitors", ComputerError(ErrorCode.NO_DISPLAY, "cannot open the display"))
    assert code(rig.controller.plan_mouse, "click", 1, 1) is ErrorCode.NO_DISPLAY
    rig.fb._monitors = []
    assert code(rig.controller.plan_mouse, "click", 1, 1) is ErrorCode.NO_DISPLAY


def test_unexpected_backend_exceptions_become_structured_errors_without_their_message(rig):
    plan = rig.controller.plan_keyboard("type", text="visible-secret")
    rig.fb.fail_next("keyboard.type_text", RuntimeError("boom while typing visible-secret"))
    with approved(rig.engine, plan):
        with pytest.raises(ComputerError) as exc:
            rig.controller.execute(plan)
    assert exc.value.code is ErrorCode.BACKEND_ERROR and "visible-secret" not in str(exc.value) and "RuntimeError" in str(exc.value)
    rig.fb.fail_next("screen.capture", ValueError("pixels leaked"))
    p = rig.controller.plan_screen("screenshot")
    with approved(rig.engine, p):
        assert code(rig.controller.execute, p) is ErrorCode.BACKEND_ERROR


def test_provider_errors_keep_their_code(rig):
    p = rig.controller.plan_mouse("click", 1, 1)
    rig.fb.fail_next("mouse.click", ComputerError(ErrorCode.FAILSAFE, "pointer in corner"))
    with approved(rig.engine, p):
        assert code(rig.controller.execute, p) is ErrorCode.FAILSAFE


# ---- authorisation enforced by the controller itself --------------------------------------------------------------------------------------------
def test_every_controller_operation_is_refused_without_an_approval(rig):
    c, h = rig.controller, next(iter(rig.fb.windows))
    ops = [c.monitors, c.screenshot, c.windows, c.active_window, c.cursor, lambda: c.mouse_move(1, 1), lambda: c.click(1, 1),
           lambda: c.double_click(1, 1), lambda: c.right_click(1, 1), lambda: c.scroll(2, 1, 1), lambda: c.key_press("a"),
           lambda: c.hotkey("ctrl+s"), lambda: c.type_text("x"), lambda: c.type("x"), lambda: c.focus_window(h),
           lambda: c.minimize_window(h), lambda: c.maximize_window(h), lambda: c.restore_window(h), lambda: c.close_window(h),
           lambda: c.launch_application("notepad"), lambda: c.launch_application("notepad", ["a"]),
           lambda: c.save_screenshot("x")]
    for op in ops:
        assert code(op) is ErrorCode.NOT_AUTHORIZED
    assert code(c.compare, "a", "b") is ErrorCode.INVALID_INPUT  # nothing stored to compare (and no approval either)
    assert rig.fb.calls_named("mouse") == [] and rig.fb.calls_named("keyboard") == [] and rig.fb.calls_named("windows.focus") == []
    assert rig.fb.calls_named("windows.close") == [] and rig.fb.launched == [] and rig.fb.calls_named("screen.capture") == []


def test_an_approval_for_another_operation_does_not_authorise(rig):
    shot_plan = rig.controller.plan_screen("screenshot")
    click_plan = rig.controller.plan_mouse("click", 5, 5)
    with approved(rig.engine, shot_plan):
        assert code(rig.controller.execute, click_plan) is ErrorCode.NOT_AUTHORIZED  # screenshot grant, click plan
    with approved(rig.engine, rig.controller.plan_mouse("click", 5, 5)):
        assert code(rig.controller.execute, rig.controller.plan_mouse("double_click", 5, 5)) is ErrorCode.NOT_AUTHORIZED
        assert code(rig.controller.execute, rig.controller.plan_mouse("click", 6, 5)) is ErrorCode.TARGET_CHANGED
        assert code(rig.controller.execute, rig.controller.plan_mouse("click", 5, 5, monitor=1)) is ErrorCode.TARGET_CHANGED
    assert rig.fb.calls_named("mouse") == []


def test_a_red_plan_is_refused_even_if_an_approval_exists(tmp_path):
    """Defence in depth: simulate an engine that wrongly approved the request."""
    r = make_rig(tmp_path, [ONCE])
    r.fb.add_window("Windows PowerShell", "powershell.exe", active=True)
    plan = r.controller.plan_keyboard("type", text="format c:")
    assert plan.level is R
    req = PermissionRequest(tool=plan.tool, action=plan.action, level=Y, resource=plan.resource, resource_type=ResourceType.OTHER)
    decision = r.engine.authorize(req)  # a (wrong) YELLOW approval for the very same resource
    assert decision.allowed
    with r.engine.execution_scope(req, decision):
        assert code(r.controller.execute, plan) is ErrorCode.BLOCKED_TARGET
    assert r.fb.typed == []


def test_grant_for_the_right_tool_but_foreign_request_is_refused(rig):
    """A GREEN request with the same action string issued for a different tool name cannot drive the controller."""
    plan = rig.controller.plan_screen("monitors")
    req = PermissionRequest(tool="echo", action="monitors", level=G, resource=plan.resource, resource_type=ResourceType.OTHER)
    d = rig.engine.authorize(req)
    with rig.engine.execution_scope(req, d):
        assert code(rig.controller.execute, plan) is ErrorCode.NOT_AUTHORIZED


# ---- emergency stop / rate limit / concurrency -----------------------------------------------------------------------------------------------------
def test_halt_stops_everything_until_resumed(rig):
    c = rig.controller
    c.halt("test")
    assert c.halted == "test" and c.describe()["halted"] == "test"
    for plan in (c.plan_mouse("click", 1, 1), c.plan_screen("monitors")):
        with approved(rig.engine, plan):
            assert code(c.execute, plan) is ErrorCode.FAILSAFE
    assert rig.fb.calls_named("mouse") == []
    c.resume()
    assert go(rig, c.plan_mouse("move", 1, 1))["action"] == "move"


def test_rate_limit_applies_to_input_not_to_observation(tmp_path):
    now = [0.0]
    r = make_rig(tmp_path, [ONCE] * 20, max_actions_per_minute=3)
    r.controller._clock = lambda: now[0]
    for i in range(3):
        go(r, r.controller.plan_mouse("move", i, 0))
    plan = r.controller.plan_mouse("move", 9, 0)
    with approved(r.engine, plan):
        assert code(r.controller.execute, plan) is ErrorCode.RATE_LIMITED
    for _ in range(5):
        go(r, r.controller.plan_screen("monitors"))  # observation is not limited
    now[0] += 61
    assert go(r, r.controller.plan_mouse("move", 9, 0))["x"] == 9


def test_actions_are_serialised(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 20)
    active, peak = [0], [0]
    original = r.fb._hit

    def slow(method, *args):
        if method == "mouse.move":
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.01)
            active[0] -= 1
        return original(method, *args)

    r.fb._hit = slow
    errors = []

    def work(i):
        try:
            go(r, r.controller.plan_mouse("move", i, 0))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and peak[0] == 1 and len(r.fb.calls_named("mouse.move")) == 8


def test_action_delay_is_applied_after_input_only(tmp_path):
    slept = []
    r = make_rig(tmp_path, [ONCE] * 5, action_delay=0.25)
    r.controller._sleep = slept.append
    go(r, r.controller.plan_mouse("move", 1, 1))
    go(r, r.controller.plan_screen("monitors"))
    assert slept == [0.25]


def test_describe_and_alias(rig):
    d = rig.controller.describe()
    assert d["backend"] == "fake" and d["capabilities"] == ["screen", "mouse", "keyboard", "windows", "apps"]
    assert d["apps"] == ["notepad"] and d["limits"]["max_text_length"] == 500 and d["halted"] is None
    assert rig.controller.type == rig.controller.type_text
