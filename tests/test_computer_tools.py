"""Computer tools through ToolRegistry + PermissionEngine (real engine, fake backend)."""
import json
import logging
import os
import sys
import threading

import pytest

from computer_util import G, NO, ONCE, R, SESSION, Y, make_rig
from jarvis.computer import ErrorCode
from jarvis.computer.tools import TOOL_CLASSES
from jarvis.permissions import DecisionStatus, GrantScope, Policy, PermissionMode
from jarvis.tools.base import ProtectedTool
from secutil import types


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path, [ONCE] * 30)


# ---- registration ----------------------------------------------------------------------------------------------------------
def test_tools_are_protected_tools_with_truthful_levels(rig):
    levels = {c.name: c.permission for c in TOOL_CLASSES}
    assert levels == {"screen": G, "screen_save": Y, "mouse": Y, "keyboard": Y, "window": Y, "app": Y}
    assert all(issubclass(c, ProtectedTool) for c in TOOL_CLASSES)
    assert rig.registry.names() == ["app", "keyboard", "mouse", "screen", "screen_save", "window"]
    assert len([e for e in rig.sink.events if e.type.value == "tool_registered"]) == 5  # all non-GREEN tools are audited


def test_baseline_rules_are_in_the_engine_policy(rig):
    rules = {r.id: r for r in rig.engine.policy.rules}
    assert rules["computer-baseline-keyboard-confirm"].effect.value == "confirm" and rules["computer-baseline-keyboard-confirm"].tool == "keyboard"
    assert rules["computer-baseline-window-close-confirm"].action == "close"
    assert "policy_changed" in types(rig.sink)


# ---- GREEN: observation ------------------------------------------------------------------------------------------------------
def test_observation_is_green_and_needs_no_confirmation(tmp_path):
    r = make_rig(tmp_path)  # no confirmation answers at all
    logged_before = len(r.sink.events)
    for kw in ({"action": "monitors"}, {"action": "screenshot"}, {"action": "windows"}, {"action": "active_window"},
               {"action": "cursor"}):
        out = r.run("screen", **kw)
        assert out.success and out.permission.scope is GrantScope.AUTOMATIC and out.permission.level is G, kw
    assert r.prompts.requests == [] and len(r.sink.events) == logged_before  # GREEN is neither asked nor logged


def test_screenshot_output_is_metadata_only_and_json_serialisable(rig):
    out = rig.run("screen", action="screenshot", monitor="all").output
    assert set(out) >= {"id", "monitor", "width", "height", "format", "bytes", "sha256", "note"} and out["monitor"] == "all"
    assert json.dumps(out) and "data" not in out
    for tool, kw in (("screen", {"action": "monitors"}), ("screen", {"action": "windows"}), ("screen", {"action": "cursor"})):
        json.dumps(rig.run(tool, **kw).output)


def test_green_actions_can_be_audited_when_configured(tmp_path):
    r2 = make_rig(tmp_path / "v")
    r2.engine._audit_green = True  # what security.audit_green = true does
    r2.run("screen", action="screenshot")
    assert types(r2.sink)[-3:] == ["permission_requested", "permission_granted", "execution_result"]


# ---- YELLOW: confirmation -------------------------------------------------------------------------------------------------------
def test_mouse_click_asks_with_the_facts_and_acts_once(rig):
    out = rig.run("mouse", action="click", x="10", y="12")
    assert out.success and out.output == {"action": "click", "monitor": 0, "x": 10, "y": 12}
    assert out.permission.scope is GrantScope.ONCE and out.permission.level is Y
    c = rig.prompts.requests[0]
    assert (c.tool, c.action, c.level, c.resource) == ("mouse", "click", Y, "screen://monitor/0/10/12")
    assert "Untitled - Notepad" in c.context["ziel"] and c.context["monitor"] == "0 (64x48)"
    assert rig.fb.calls_named("mouse.click") == [("mouse.click", (10, 12, "left", 1))]
    assert types(rig.sink)[-5:] == ["permission_requested", "confirmation_requested", "confirmation_accepted",
                                    "permission_granted", "execution_result"]


def test_declining_means_nothing_happens(tmp_path):
    r = make_rig(tmp_path, [NO, NO, NO, NO])
    h = next(iter(r.fb.windows))
    for tool, kw in (("mouse", dict(action="click", x="1", y="1")), ("keyboard", dict(action="type", text="x")),
                     ("window", dict(action="close", handle=str(h))), ("app", dict(app="notepad"))):
        out = r.run(tool, **kw)
        assert not out.success and "declined" in out.error and out.permission.status is DecisionStatus.DENIED, tool
    assert r.fb.calls == [c for c in r.fb.calls if c[0] in ("screen.monitors", "windows.active", "windows.list", "windows.window_at")]
    assert r.fb.typed == [] and r.fb.launched == [] and h in r.fb.windows


def test_every_acting_tool_is_yellow(rig):
    h = str(next(iter(rig.fb.windows)))
    for tool, kw in (("mouse", dict(action="move", x="1", y="1")), ("mouse", dict(action="scroll", x="1", y="1", amount="2")),
                     ("keyboard", dict(action="press", key="a")), ("window", dict(action="focus", handle=h)),
                     ("window", dict(action="minimize", handle=h)), ("app", dict(app="notepad"))):
        out = rig.run(tool, **kw)
        assert out.success and out.permission.level is Y and out.permission.scope is GrantScope.ONCE, (tool, kw)


def test_cli_style_string_arguments_are_coerced(rig):
    assert rig.run("mouse", action="scroll", x="5", y="6", monitor="1", amount="-2").output["monitor"] == 1
    assert rig.fb.calls_named("mouse.scroll") == [("mouse.scroll", (69, 6, -2))]


def test_extra_unknown_arguments_change_nothing(rig):
    out = rig.run("mouse", action="click", x="3", y="3", force=True, skip_permission=True, confirm="yes")
    assert out.success and out.permission.scope is GrantScope.ONCE and len(rig.prompts.requests) == 1


# ---- sessions: exact and conservative ------------------------------------------------------------------------------------------------
def test_session_permission_for_a_click_covers_only_that_exact_point(tmp_path):
    r = make_rig(tmp_path, [SESSION, ONCE, ONCE])
    assert r.run("mouse", action="click", x="5", y="5").permission.scope is GrantScope.SESSION
    assert r.run("mouse", action="click", x="5", y="5").permission.scope is GrantScope.SESSION  # same point: no prompt
    assert len(r.prompts.requests) == 1
    assert r.run("mouse", action="click", x="6", y="5").permission.scope is GrantScope.ONCE
    assert r.run("mouse", action="double_click", x="5", y="5").permission.scope is GrantScope.ONCE
    assert len(r.prompts.requests) == 3


def test_session_permission_for_an_app_is_bound_to_its_arguments(tmp_path):
    r = make_rig(tmp_path, [SESSION, ONCE])
    assert r.run("app", app="notepad").permission.scope is GrantScope.SESSION
    assert r.run("app", app="notepad").permission.scope is GrantScope.SESSION
    assert r.run("app", app="notepad", args=["secret.txt"]).permission.scope is GrantScope.ONCE  # args change the resource
    assert len(r.prompts.requests) == 2 and r.prompts.requests[1].context["argumente"] == "secret.txt"


def test_keyboard_is_always_asked_and_never_remembered(tmp_path):
    r = make_rig(tmp_path, [SESSION, SESSION, SESSION])
    for text in ("one", "two", "three"):
        out = r.run("keyboard", action="type", text=text)
        assert out.success and out.permission.scope is GrantScope.ONCE  # SESSION answer is downgraded
    assert len(r.prompts.requests) == 3 and not any(q.session_allowed for q in r.prompts.requests)
    assert r.fb.typed == ["one", "two", "three"]


def test_closing_a_window_is_always_asked(tmp_path):
    r = make_rig(tmp_path, [SESSION, SESSION])
    a = r.fb.add_window("A", "a.exe")
    b = r.fb.add_window("B", "b.exe")
    assert r.run("window", action="close", handle=str(a.handle)).success and r.run("window", action="close", handle=str(b.handle)).success
    assert len(r.prompts.requests) == 2 and not any(q.session_allowed for q in r.prompts.requests)


def test_baseline_questions_can_be_switched_off_by_config(tmp_path):
    r = make_rig(tmp_path, [SESSION, ONCE], confirm_keyboard_each_time=False)
    assert r.run("keyboard", action="press", key="a").permission.scope is GrantScope.SESSION
    assert r.run("keyboard", action="press", key="a").permission.scope is GrantScope.SESSION and len(r.prompts.requests) == 1


# ---- RED -------------------------------------------------------------------------------------------------------------------------------------------------
def test_red_actions_are_denied_before_anyone_is_asked(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 20)
    term = r.fb.add_window("Windows PowerShell", "powershell.exe")
    r.fb.add_window("Windows Security", "SecHealthUI.exe", left=40, top=0, width=20, height=20)
    cases = [
        ("keyboard", dict(action="hotkey", keys="win+r")), ("keyboard", dict(action="press", key="win")),
        ("keyboard", dict(action="hotkey", keys="ctrl+alt+delete")), ("keyboard", dict(action="hotkey", keys="ctrl+shift+esc")),
        ("mouse", dict(action="click", x="45", y="5")), ("window", dict(action="close", handle=str(term.handle))),
        ("app", dict(app="cmd")), ("app", dict(app="powershell")), ("app", dict(app="C:\\Windows\\System32\\cmd.exe")),
    ]
    for tool, kw in cases:
        out = r.run(tool, **kw)
        assert not out.success and out.permission.status is DecisionStatus.DENIED and out.permission.matched_rule == "invariant:red", (tool, kw)
        assert out.permission.level is R and "RED actions are never permitted" in out.error
    r.fb.active_handle = term.handle
    out = r.run("keyboard", action="type", text="format c: /y")
    assert out.permission.matched_rule == "invariant:red" and "receives no input" in out.error
    assert r.prompts.requests == [] and r.fb.typed == [] and r.fb.launched == []
    assert r.fb.calls_named("keyboard.") == [] and r.fb.calls_named("windows.close") == [] and r.fb.calls_named("mouse.click") == []


def test_red_denials_are_audited_with_the_resource(tmp_path):
    r = make_rig(tmp_path)
    r.run("app", app="cmd")
    denied = [e for e in r.sink.events if e.type.value == "permission_denied"][-1]
    assert (denied.tool, denied.action, denied.level, denied.rule) == ("app", "launch", "red", "invariant:red")
    assert denied.resource == "app://unlisted/cmd"


def test_a_blocked_alias_is_denied_through_the_engine(tmp_path):
    from computer_util import make_executable
    cmd = make_executable(tmp_path / "bin" / "cmd.exe")
    r = make_rig(tmp_path, [ONCE], apps={"terminal": cmd})
    out = r.run("app", app="terminal")
    assert not out.success and out.permission.matched_rule == "invariant:red" and "never launched" in out.error
    assert r.fb.launched == [] and r.prompts.requests == []


# ---- invalid input: controlled, nothing executed ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("tool,kw,code", [
    ("mouse", dict(action="click", x="9999", y="1"), "invalid_coordinates"), ("mouse", dict(action="click", x="-1", y="1"), "invalid_coordinates"),
    ("mouse", dict(action="click", x="1.5", y="1"), "invalid_input"), ("mouse", dict(action="click", x="a", y="1"), "invalid_input"),
    ("mouse", dict(action="click", x="1", y="1", monitor="9"), "invalid_monitor"), ("mouse", dict(action="bogus", x="1", y="1"), "invalid_input"),
    ("mouse", dict(action="scroll", x="1", y="1", amount="0"), "invalid_input"),
    ("keyboard", dict(action="type", text=""), "invalid_input"), ("keyboard", dict(action="press", key="f13"), "invalid_input"),
    ("keyboard", dict(action="hotkey", keys="s"), "invalid_input"), ("window", dict(action="focus", handle="9999"), "window_not_found"),
    ("window", dict(action="focus", handle="abc"), "invalid_input"), ("app", dict(app=""), "invalid_input"),
    ("screen", dict(action="screenshot", monitor="5"), "invalid_monitor"), ("screen", dict(action="nope"), "invalid_input"),
    ("screen", dict(action="compare", a="x", b="y"), "invalid_input"),
])
def test_invalid_requests_fail_with_a_code_and_touch_nothing(rig, tool, kw, code):
    out = rig.run(tool, **kw)
    assert not out.success and f"[{code}]" in out.error
    assert rig.prompts.requests == [] and rig.fb.calls_named("mouse") == [] and rig.fb.calls_named("keyboard") == []
    assert rig.fb.calls_named("windows.focus") == [] and rig.fb.launched == [] and rig.fb.calls_named("screen.capture") == []


def test_missing_required_parameters(rig):
    assert "missing parameters" in rig.run("mouse", action="click").error
    assert "missing parameters" in rig.run("window", action="focus").error
    assert "missing parameters" in rig.run("app").error


# ---- structured execution errors ---------------------------------------------------------------------------------------------------------------------
def test_backend_failures_come_back_structured(rig):
    from jarvis.computer import ComputerError
    rig.fb.fail_next("mouse.click", ComputerError(ErrorCode.FAILSAFE, "pointer in corner"))
    out = rig.run("mouse", action="click", x="1", y="1")
    assert not out.success and out.output == {"code": "failsafe", "message": "pointer in corner"} and "[failsafe]" in out.error
    rig.fb.fail_next("apps.launch", ComputerError(ErrorCode.LAUNCH_FAILED, "executable not found"))
    out = rig.run("app", app="notepad")
    assert out.output["code"] == "launch_failed"
    rig.fb.fail_next("screen.capture", RuntimeError("driver exploded"))
    out = rig.run("screen", action="screenshot")
    assert not out.success and out.output["code"] == "backend_error" and "driver exploded" not in out.error


def test_halt_surfaces_as_a_structured_error(rig):
    rig.controller.halt("test")
    out = rig.run("mouse", action="click", x="1", y="1")
    assert not out.success and out.output["code"] == "failsafe" and rig.fb.calls_named("mouse.click") == []


def test_rate_limit_is_a_structured_error(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 10, max_actions_per_minute=2)
    assert r.run("mouse", action="move", x="1", y="1").success and r.run("mouse", action="move", x="2", y="1").success
    out = r.run("mouse", action="move", x="3", y="1")
    assert not out.success and out.output["code"] == "rate_limited"


def test_window_closed_after_approval_is_a_structured_error(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    w = r.fb.add_window("Temp", "temp.exe")
    orig = r.prompts.confirm

    def vanish(request):
        choice = orig(request)
        del r.fb.windows[w.handle]  # the user takes a while, the window disappears
        r.fb.z_order.remove(w.handle)
        return choice

    r.prompts.confirm = vanish
    out = r.run("window", action="focus", handle=str(w.handle))
    assert not out.success and out.output["code"] == "window_not_found"


def test_active_window_change_during_confirmation_blocks_typing(tmp_path):
    """The user reads the prompt for Notepad; meanwhile the focus moves to another window: nothing is typed."""
    r = make_rig(tmp_path, [ONCE])
    other = r.fb.add_window("Other", "other.exe")
    orig = r.prompts.confirm

    def switch(request):
        choice = orig(request)
        r.fb.active_handle = other.handle
        return choice

    r.prompts.confirm = switch
    out = r.run("keyboard", action="type", text="private note")
    assert not out.success and out.output["code"] in ("target_changed", "not_authorized") and r.fb.typed == []


# ---- the audit trail never contains typed text -----------------------------------------------------------------------------------------------------------------
def test_audit_records_keyboard_type_but_not_the_text(rig):
    secret = "my-very-private-sentence-4711"
    out = rig.run("keyboard", action="type", text=secret)
    assert out.success and rig.fb.typed == [secret]
    evs = [e for e in rig.sink.events if e.tool == "keyboard"]
    assert {e.action for e in evs} == {"type"} and {e.resource for e in evs} == {"keyboard://text@notepad.exe"}
    assert "execution_result" in {e.type.value for e in evs}
    blob = rig.audit_blob()
    assert secret not in blob and "my-very-private" not in blob and "Untitled" not in blob


def test_the_user_sees_a_preview_at_the_prompt_but_nowhere_else(rig, caplog):
    secret = "dear diary today I wrote this"
    with caplog.at_level(logging.DEBUG, logger="jarvis"):
        out = rig.run("keyboard", action="type", text=secret)
    c = rig.prompts.requests[0]
    assert c.context["vorschau"] == secret and c.context["zeichen"] == str(len(secret))  # informed consent
    assert secret not in rig.audit_blob() and secret not in json.dumps(out.output) and secret not in (out.error or "")
    assert all(secret not in r.getMessage() for r in caplog.records)
    assert secret not in repr(out) and secret not in repr(out.permission) and secret not in str(rig.engine.describe())


def test_preview_can_be_disabled_entirely(tmp_path):
    r = make_rig(tmp_path, [ONCE], show_text_preview=False)
    r.run("keyboard", action="type", text="hide me")
    blob = r.prompt_blob()
    assert "hide me" not in blob and "vorschau" not in blob


def test_secrets_in_the_preview_and_window_titles_are_redacted_at_the_prompt(tmp_path):
    r = make_rig(tmp_path, [ONCE], notepad=False)
    r.fb.add_window("notes api_key=abcd1234efgh5678 - Notepad", "notepad.exe", active=True)
    out = r.run("keyboard", action="type", text="password=hunter22abc")
    assert out.success and r.fb.typed == ["password=hunter22abc"]  # the action itself is the user's business ...
    blob = r.prompt_blob() + r.audit_blob()
    assert "hunter22abc" not in blob and "abcd1234efgh5678" not in blob and "[REDACTED]" in blob  # ... but never displayed/logged


def test_screenshot_bytes_never_reach_logs_or_results(rig, caplog):
    with caplog.at_level(logging.DEBUG, logger="jarvis"):
        out = rig.run("screen", action="screenshot")
        rig.run("mouse", action="click", x="3", y="3")
    shot = rig.controller.screenshots.get(out.output["id"])
    sample = shot.data[:64]
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert sample.hex() not in logs and shot.sha256 not in logs and str(sample) not in logs
    assert shot.data not in json.dumps(out.output).encode() and "data" not in repr(shot) and shot.sha256 not in repr(shot)
    assert any("screenshot captured id=" in r.getMessage() for r in caplog.records)  # metadata IS logged


# ---- saving screenshots (explicit file write) ------------------------------------------------------------------------------------------------------------------
def test_screenshots_are_saved_only_on_explicit_confirmed_request(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    sid = r.run("screen", action="screenshot").output["id"]
    assert list(r.ws.iterdir()) == []  # capturing alone never writes anything
    out = r.run("screen_save", id=sid, path="shots/a.png")
    assert not out.success  # directory does not exist: not created behind the user's back
    (r.ws / "shots").mkdir()
    r.prompts._choices.append(ONCE)
    out = r.run("screen_save", id=sid, path="shots/a.png")
    assert out.success and out.output["path"] == str(r.ws / "shots" / "a.png") and out.output["screenshot"] == sid
    data = (r.ws / "shots" / "a.png").read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and out.output["bytes"] == len(data)
    assert out.permission.level is Y and r.prompts.requests[-1].action == "save" and r.prompts.requests[-1].context["screenshot"] == sid
    if os.name == "posix":
        assert ((r.ws / "shots" / "a.png").stat().st_mode & 0o077) == 0  # owner only


def test_saving_asks_and_a_declined_save_writes_nothing(tmp_path):
    r = make_rig(tmp_path, [NO])
    sid = r.run("screen", action="screenshot").output["id"]
    out = r.run("screen_save", id=sid, path="a.png")
    assert not out.success and not (r.ws / "a.png").exists()


def test_saving_never_overwrites(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE])
    sid = r.run("screen", action="screenshot").output["id"]
    (r.ws / "a.png").write_bytes(b"precious")
    out = r.run("screen_save", id=sid, path="a.png")
    assert not out.success and "already exists" in out.error and (r.ws / "a.png").read_bytes() == b"precious"


@pytest.mark.parametrize("path", ["../escape.png", "/etc/shot.png", "sub/../../x.png", "/tmp/outside.png"])
def test_saving_outside_the_allowed_directory_is_denied_without_asking(tmp_path, path):
    r = make_rig(tmp_path, [ONCE] * 3)
    sid = r.run("screen", action="screenshot").output["id"]
    out = r.run("screen_save", id=sid, path=path)
    assert not out.success and out.permission.matched_rule == "fs:outside_roots" and r.prompts.requests == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_saving_through_a_symlink_that_escapes_is_denied(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    outside = tmp_path / "outside"
    outside.mkdir()
    (r.ws / "link").symlink_to(outside, target_is_directory=True)
    sid = r.run("screen", action="screenshot").output["id"]
    out = r.run("screen_save", id=sid, path="link/x.png")
    assert not out.success and out.permission.matched_rule == "fs:outside_roots" and not (outside / "x.png").exists()


@pytest.mark.parametrize("kw,code", [(dict(id="shot-nope", path="a.png"), "invalid_input"), (dict(id="x", path="a.txt"), "invalid_input"),
                                     (dict(id="x", path="a"), "invalid_input")])
def test_save_input_errors(rig, kw, code):
    assert f"[{code}]" in rig.run("screen_save", **kw).error


def test_a_forgotten_screenshot_cannot_be_saved(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    sid = r.run("screen", action="screenshot").output["id"]
    r.run("screen", action="forget")
    assert "[invalid_input]" in r.run("screen_save", id=sid, path="a.png").error


# ---- policy rules over the resource URIs ---------------------------------------------------------------------------------------------------------------------------
def rule(**kw):
    kw.setdefault("resource_type", "other")
    return kw


def with_rules(r, *rules):
    r.engine.update_policy(Policy.from_rules([*r.engine.policy.rules, *rules]))
    return r


def test_allow_rule_for_one_application_is_a_persistent_permission(tmp_path):
    r = make_rig(tmp_path)
    with_rules(r, rule(id="trust-notepad", effect="allow", tool="app", action="launch", resources=["app://*fakenote.exe"]))
    out = r.run("app", app="notepad")
    assert out.success and out.permission.scope is GrantScope.PERSISTENT and out.permission.matched_rule == "trust-notepad"
    assert r.prompts.requests == []
    # arguments change the resource, so the allow rule does not cover them
    assert not r.run("app", app="notepad", args=["file.txt"]).success and len(r.prompts.requests) == 1


def test_deny_rule_beats_everything(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5)
    with_rules(r, rule(id="no-calc", effect="deny", tool="app", resources=["app://*fakenote.exe*"]),
               rule(id="no-sensitive-window", effect="deny", tool="window", action="close", resources=["window://*/notepad.exe"]))
    out = r.run("app", app="notepad")
    assert not out.success and out.permission.matched_rule == "no-calc" and r.fb.launched == []
    h = next(iter(r.fb.windows))
    assert r.run("window", action="close", handle=str(h)).permission.matched_rule == "no-sensitive-window" and h in r.fb.windows


def test_an_allow_rule_cannot_switch_off_the_keyboard_baseline_question(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE])
    with_rules(r, rule(id="trust-typing", effect="allow", tool="keyboard", action="type", resources=["keyboard://text@notepad.exe"]))
    out = r.run("keyboard", action="type", text="hi")
    assert out.success and out.permission.scope is GrantScope.ONCE and len(r.prompts.requests) == 1  # confirm > allow


def test_keyboard_allow_rule_works_when_the_baseline_is_off(tmp_path):
    r = make_rig(tmp_path, confirm_keyboard_each_time=False)
    with_rules(r, rule(id="trust-typing", effect="allow", tool="keyboard", action="type", resources=["keyboard://text@notepad.exe"]))
    assert r.run("keyboard", action="type", text="hi").permission.matched_rule == "trust-typing"
    r.fb.add_window("Browser", "browser.exe", active=True)  # another target: the rule does not apply
    assert not r.run("keyboard", action="type", text="hi").success and len(r.prompts.requests) == 1


def test_mouse_rules_by_monitor_region_uri(tmp_path):
    r = make_rig(tmp_path)
    with_rules(r, rule(id="monitor1-ok", effect="allow", tool="mouse", action="click", resources=["screen://monitor/1/*"]))
    assert r.run("mouse", action="click", x="3", y="3", monitor="1").permission.matched_rule == "monitor1-ok"
    assert not r.run("mouse", action="click", x="3", y="3", monitor="0").success  # not covered -> asks -> nobody answers


def test_policy_cannot_unlock_red(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3)
    with_rules(r, rule(id="try", effect="allow", tool="app", action="launch", resources=["app://unlisted/*"]),
               rule(id="try2", effect="allow", tool="keyboard", action="hotkey", resources=["keyboard://hotkey/WIN+R@*"]))
    assert r.run("app", app="cmd").permission.matched_rule == "invariant:red"
    assert r.run("keyboard", action="hotkey", keys="win+r").permission.matched_rule == "invariant:red"
    assert r.fb.launched == [] and r.fb.calls_named("keyboard.") == []


def test_lockdown_mode_permits_only_observation(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5)
    r.engine._mode = PermissionMode.LOCKDOWN
    assert r.run("screen", action="screenshot").success
    out = r.run("mouse", action="click", x="1", y="1")
    assert not out.success and out.permission.matched_rule == "invariant:lockdown" and r.prompts.requests == []


def test_callers_cannot_self_confirm_any_tool(tmp_path):
    r = make_rig(tmp_path)  # nobody answers prompts
    h = str(next(iter(r.fb.windows)))
    for tool, kw in (("mouse", dict(action="click", x="1", y="1")), ("keyboard", dict(action="type", text="x")),
                     ("window", dict(action="close", handle=h)), ("app", dict(app="notepad")), ("screen_save", dict(id="x", path="a.png"))):
        out = r.run(tool, confirmed=True, **kw)
        assert not out.success, tool
    assert r.fb.typed == [] and r.fb.launched == [] and r.fb.calls_named("mouse.click") == [] and int(h) in r.fb.windows
    assert types(r.sink).count("caller_confirmation_ignored") >= 3


# ---- concurrency ----------------------------------------------------------------------------------------------------------------------------------------------------
def test_concurrent_tool_calls_are_isolated_and_complete(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 40)
    results, errors = [None] * 12, []

    def work(i):
        try:
            results[i] = r.run("mouse", action="click", x=str(i), y="1")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and all(x.success for x in results)
    assert sorted(c[1][0] for c in r.fb.calls_named("mouse.click")) == list(range(12))
    assert len(r.prompts.requests) == 12
