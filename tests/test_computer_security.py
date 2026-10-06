"""Adversarial tests: every attempt to move the mouse, type, launch or close WITHOUT (or beyond) a PermissionEngine
approval must fail, and nothing sensitive may leak. Plus static scans of the source tree."""
import ast
import dataclasses
import inspect
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from computer_util import G, NO, ONCE, R, Y, approved, make_executable, make_rig
from jarvis.computer import (ComputerBackend, ComputerController, ComputerError, ComputerSafety, ErrorCode, Monitor, Plan)
from jarvis.computer.factory import ComputerSubsystem
from jarvis.computer.providers.fake import FakeBackend
from jarvis.computer.providers.subprocess_apps import SubprocessLauncher
from jarvis.computer.tools import TOOL_CLASSES
from jarvis.config import ComputerSettings
from jarvis.errors import PermissionDeniedError
from jarvis.permissions import (ExecutionGrant, PermissionRequest, ResourceType, ScriptedConfirmation, args_fingerprint)
from secutil import types

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
COMP = SRC / "computer"


def code(fn, *a, **k):
    with pytest.raises(ComputerError) as exc:
        fn(*a, **k)
    return exc.value.code


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path, [ONCE] * 30)


def silent(rig):
    """True if the fake backend saw nothing that acts on the PC."""
    acting = ("mouse.", "keyboard.", "windows.focus", "windows.close", "windows.minimize", "windows.maximize", "windows.restore", "apps.")
    return not any(c[0].startswith(acting) for c in rig.fb.calls) and not rig.fb.launched and not rig.fb.typed


# =====================================================================================================================
# 1. direct calls cannot skip the permission layer
# =====================================================================================================================
TOOL_CALLS = {"screen": dict(action="monitors"), "screen_save": dict(id="x", path="a.png"), "mouse": dict(action="click", x="1", y="1"),
              "keyboard": dict(action="type", text="x"), "window": dict(action="close", handle="100"), "app": dict(app="notepad")}


@pytest.mark.parametrize("cls", TOOL_CLASSES, ids=lambda c: c.name)
def test_tool_run_without_the_engine_is_refused(rig, cls):
    tool = cls(rig.controller)
    with pytest.raises(PermissionDeniedError, match="permission engine"):
        tool.run(**TOOL_CALLS[cls.name])
    assert silent(rig) and rig.fb.calls_named("screen.capture") == []


@pytest.mark.parametrize("cls", TOOL_CLASSES, ids=lambda c: c.name)
def test_computer_tools_cannot_define_their_own_run(cls):
    assert cls.run is __import__("jarvis.tools.base", fromlist=["ProtectedTool"]).ProtectedTool.run
    with pytest.raises(TypeError, match="_perform"):
        type("Evil", (cls,), {"run": lambda self, **kw: None})


def test_controller_refuses_every_operation_without_an_approval(rig):
    c, h = rig.controller, next(iter(rig.fb.windows))
    for op in (lambda: c.click(1, 1), lambda: c.mouse_move(1, 1), lambda: c.right_click(1, 1), lambda: c.double_click(1, 1),
               lambda: c.scroll(1, 1, 1), lambda: c.type_text("x"), lambda: c.type("x"), lambda: c.key_press("a"),
               lambda: c.hotkey("ctrl+s"), lambda: c.focus_window(h), lambda: c.close_window(h), lambda: c.minimize_window(h),
               lambda: c.launch_application("notepad"), c.screenshot, c.windows, c.monitors):
        assert code(op) is ErrorCode.NOT_AUTHORIZED
    assert silent(rig) and rig.fb.calls_named("screen.capture") == []


def test_there_is_no_confirmed_style_shortcut_anywhere():
    banned = {"confirmed", "confirm", "force", "unsafe", "skip", "skip_permission", "bypass", "no_confirm", "yes", "sudo", "admin",
              "shell", "command", "cmd", "raw", "eval", "exec", "override", "trusted"}
    for cls in TOOL_CLASSES:
        assert not ({p.name for p in cls.parameters} & banned), cls.name
    for owner in (ComputerController, ComputerSubsystem):
        for name, fn in inspect.getmembers(owner, inspect.isfunction):
            if not name.startswith("_") or name == "__init__":
                assert not (set(inspect.signature(fn).parameters) & banned), f"{owner.__name__}.{name}"


def test_extra_arguments_such_as_confirmed_do_not_reach_the_controller_or_change_the_outcome(tmp_path):
    r = make_rig(tmp_path)  # nobody answers prompts
    for tool, kw in TOOL_CALLS.items():
        if tool == "screen":
            continue
        out = r.run(tool, confirmed=True, confirm=True, force=True, skip_permission=True, **kw)
        assert not out.success, tool
    assert silent(r) and types(r.sink).count("caller_confirmation_ignored") >= 4  # (screen_save fails earlier: unknown screenshot id)


# =====================================================================================================================
# 2. approvals are worth exactly what they were issued for
# =====================================================================================================================
def test_an_approval_for_one_click_cannot_carry_out_another(rig):
    """The classic: approve (1,1), then swap in the plan for (5,5) with the approved resource string."""
    approved_plan = rig.controller.plan_mouse("click", 1, 1)
    evil_plan = rig.controller.plan_mouse("click", 5, 5)
    forged = dataclasses.replace(evil_plan, resource=approved_plan.resource)  # fields of the approved one, action of the evil one
    with approved(rig.engine, approved_plan):
        assert code(rig.controller.execute, forged) is ErrorCode.NOT_AUTHORIZED
        assert code(rig.controller.execute, evil_plan) is ErrorCode.TARGET_CHANGED
    assert rig.fb.calls_named("mouse.click") == []


def test_plans_cannot_be_downgraded_or_rewritten_after_creation(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5)
    r.fb.add_window("Windows PowerShell", "powershell.exe", active=True)
    red = r.controller.plan_keyboard("type", text="format c: /y")
    assert red.level is R
    for forged in (dataclasses.replace(red, level=Y), dataclasses.replace(red, reason="harmless"),
                   dataclasses.replace(red, level=Y, resource=red.resource.replace("powershell.exe", "notepad.exe")),
                   dataclasses.replace(red, action="press"), dataclasses.replace(red, tool="screen")):
        req = PermissionRequest(tool=forged.tool, action=forged.action, level=Y, resource=forged.resource, resource_type=ResourceType.OTHER)
        d = r.engine.authorize(req)
        with r.engine.execution_scope(req, d):
            assert code(r.controller.execute, forged) is ErrorCode.NOT_AUTHORIZED
    assert r.fb.typed == []


def test_hand_built_plans_are_refused_even_with_a_matching_approval(rig):
    real = rig.controller.plan_mouse("click", 2, 2)
    hand_built = Plan(real.tool, real.action, real.resource, real.level, "x", {}, lambda: rig.fb.typed.append("pwned"))
    with approved(rig.engine, real):
        assert code(rig.controller.execute, hand_built) is ErrorCode.NOT_AUTHORIZED
        assert code(rig.controller.execute, "not a plan") is ErrorCode.NOT_AUTHORIZED  # type: ignore[arg-type]
        assert code(rig.controller.execute, None) is ErrorCode.NOT_AUTHORIZED  # type: ignore[arg-type]
    assert rig.fb.typed == []


def test_one_plans_action_cannot_be_run_under_anothers_signature(rig):
    a, b = rig.controller.plan_mouse("click", 1, 1), rig.controller.plan_mouse("click", 5, 5)
    mixed = Plan(a.tool, a.action, a.resource, a.level, a.reason, dict(a.context), b._run, a._sig)  # a's fields+signature, b's action
    with approved(rig.engine, a):
        assert code(rig.controller.execute, mixed) is ErrorCode.NOT_AUTHORIZED
    assert rig.fb.calls_named("mouse.click") == []


def test_a_plan_from_another_controller_is_refused(tmp_path):
    r1, r2 = make_rig(tmp_path / "a", [ONCE]), make_rig(tmp_path / "b", [ONCE])
    foreign = r1.controller.plan_mouse("click", 1, 1)
    with approved(r2.engine, r2.controller.plan_mouse("click", 1, 1)):
        assert code(r2.controller.execute, foreign) is ErrorCode.NOT_AUTHORIZED
    assert r1.fb.calls_named("mouse.click") == [] and r2.fb.calls_named("mouse.click") == []


def test_forged_grants_and_decisions_do_not_open_the_controller(rig):
    with pytest.raises(PermissionDeniedError):
        ExecutionGrant("mouse", "click", None, "id", "screen://monitor/0/1/1")  # no engine seal
    with pytest.raises(PermissionDeniedError):
        ExecutionGrant("mouse", "click", None, "id", "screen://monitor/0/1/1", _seal=object())
    plan = rig.controller.plan_mouse("click", 1, 1)
    req = PermissionRequest(tool="mouse", action="click", level=Y, resource=plan.resource, resource_type=ResourceType.OTHER)
    from jarvis.permissions import DecisionStatus, GrantScope, PermissionDecision
    forged = PermissionDecision(DecisionStatus.ALLOWED, "trust me", req.id, Y, scope=GrantScope.ONCE)
    with pytest.raises(PermissionDeniedError):
        with rig.engine.execution_scope(req, forged):  # no approval was issued for this request
            pass
    assert code(rig.controller.execute, plan) is ErrorCode.NOT_AUTHORIZED


def test_an_approval_is_gone_once_its_scope_closes(rig):
    plan = rig.controller.plan_mouse("click", 1, 1)
    with approved(rig.engine, plan):
        rig.controller.execute(plan)
    assert code(rig.controller.execute, plan) is ErrorCode.NOT_AUTHORIZED  # no replay after the scope
    assert len(rig.fb.calls_named("mouse.click")) == 1


def test_an_approval_is_not_visible_to_other_threads(rig):
    plan = rig.controller.plan_mouse("click", 1, 1)
    outcome = []
    with approved(rig.engine, plan):
        t = threading.Thread(target=lambda: outcome.append(code(rig.controller.execute, plan)))
        t.start()
        t.join()
    assert outcome == [ErrorCode.NOT_AUTHORIZED] and rig.fb.calls_named("mouse.click") == []


def test_a_tool_approval_cannot_be_reused_with_other_arguments(rig):
    tool = TOOL_CLASSES[2](rig.controller)  # mouse
    kw_a, kw_b = dict(action="click", x="1", y="1"), dict(action="click", x="9", y="9")
    req = PermissionRequest(tool="mouse", action="click", level=Y, resource="screen://monitor/0/1/1", resource_type=ResourceType.OTHER,
                            args_fingerprint=args_fingerprint("mouse", kw_a))
    d = rig.engine.authorize(req)
    with rig.engine.execution_scope(req, d):
        with pytest.raises(PermissionDeniedError, match="does not cover"):
            tool.run(**kw_b)
        assert tool.run(**kw_a).success
    assert rig.fb.calls_named("mouse.click") == [("mouse.click", (1, 1, "left", 1))]


def test_a_request_modified_after_approval_gets_no_scope(rig):
    plan = rig.controller.plan_keyboard("type", text="hello")
    req = PermissionRequest(tool=plan.tool, action=plan.action, level=Y, resource=plan.resource, resource_type=ResourceType.OTHER)
    d = rig.engine.authorize(req)
    for changed in (dataclasses.replace(req, resource="keyboard://text@cmd.exe"), dataclasses.replace(req, action="press"),
                    dataclasses.replace(req, tool="mouse"), dataclasses.replace(req, level=G)):
        rig.engine._approve(req, d, plan.resource)  # re-arm the same legitimate approval
        with pytest.raises(PermissionDeniedError):
            with rig.engine.execution_scope(changed, d):
                pass


def test_screen_state_changing_after_approval_is_caught(tmp_path):
    """Resolution changes while the user reads the prompt: the click is re-validated and refused, nothing clicks."""
    r = make_rig(tmp_path, [ONCE])
    orig = r.prompts.confirm

    def shrink(request):
        choice = orig(request)
        r.fb._monitors = [Monitor(0, 0, 0, 8, 8, True)]
        return choice

    r.prompts.confirm = shrink
    out = r.run("mouse", action="click", x="50", y="40")
    assert not out.success and out.output["code"] == "invalid_coordinates" and r.fb.calls_named("mouse.click") == []


# =====================================================================================================================
# 3. fail closed
# =====================================================================================================================
def test_an_engine_failure_means_nothing_happens(rig, monkeypatch):
    monkeypatch.setattr(rig.engine, "_evaluate", lambda r: (_ for _ in ()).throw(RuntimeError("boom")))
    for tool in ("screen", "mouse", "keyboard", "window", "app"):
        out = rig.run(tool, **TOOL_CALLS[tool])
        assert not out.success and out.permission.status.value == "internal_error", tool
    assert silent(rig) and rig.fb.calls_named("screen.capture") == []


def test_an_unwritable_audit_log_blocks_consequential_actions(tmp_path):
    from jarvis.permissions.audit import AuditSink

    class Broken(AuditSink):
        def record(self, event):
            raise OSError("disk full")

    r = make_rig(tmp_path, [ONCE] * 3)
    r.engine.audit.sinks.append(Broken())
    out = r.run("mouse", action="click", x="1", y="1")
    assert not out.success and out.permission.status.value == "internal_error" and r.fb.calls_named("mouse.click") == []
    assert r.run("screen", action="monitors").success  # GREEN observation keeps working


def test_a_crashing_describe_never_reaches_the_controller_or_provider(rig, monkeypatch):
    monkeypatch.setattr(rig.controller, "plan_mouse", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    out = rig.run("mouse", action="click", x="1", y="1")
    assert not out.success and "invalid permission request" in out.error and silent(rig)


# =====================================================================================================================
# 4. coordinates can never escape the screen
# =====================================================================================================================
def test_every_point_around_every_monitor_is_judged_correctly(rig):
    monitors = {m.index: m for m in rig.fb._monitors}
    for idx, m in monitors.items():
        for x in range(-3, m.width + 3):
            for y in range(-3, m.height + 3):
                inside = 0 <= x < m.width and 0 <= y < m.height
                try:
                    plan = rig.controller.plan_mouse("move", x, y, monitor=idx)
                except ComputerError as exc:
                    assert not inside and exc.code is ErrorCode.INVALID_COORDINATES, (idx, x, y)
                else:
                    assert inside and plan.resource == f"screen://monitor/{idx}/{x}/{y}", (idx, x, y)


@pytest.mark.parametrize("x", [10 ** 9, -10 ** 9, 10 ** 18, 2 ** 63, -2 ** 63, 2 ** 31, -2 ** 31, 65536, 4294967296])
def test_huge_coordinates_are_rejected(rig, x):
    assert code(rig.controller.plan_mouse, "click", x, 1) is ErrorCode.INVALID_COORDINATES
    assert code(rig.controller.plan_mouse, "click", 1, x) is ErrorCode.INVALID_COORDINATES


@pytest.mark.parametrize("bad", ["9" * 12, "1e3", "0x10", "1_0", "١", "１", " ", "\x00", "1\n2", float("nan"), float("inf"), True, None])
def test_exotic_numbers_are_invalid_input(rig, bad):
    assert code(rig.controller.plan_mouse, "click", bad, 1) in (ErrorCode.INVALID_INPUT, ErrorCode.INVALID_COORDINATES)


def test_provider_always_receives_a_point_inside_the_chosen_monitor(tmp_path):
    fb = FakeBackend([Monitor(0, 0, 0, 20, 10, True), Monitor(1, -15, -4, 12, 9), Monitor(2, 20, 5, 7, 7)])
    r = make_rig(tmp_path, [ONCE] * 300)
    r.controller._backend = fb.bundle()
    for idx in (0, 1, 2):
        m = fb._monitors[idx]
        for x, y in ((0, 0), (m.width - 1, m.height - 1), (m.width // 2, 0)):
            with approved(r.engine, r.controller.plan_mouse("click", x, y, monitor=idx)):
                r.controller.click(x, y, monitor=idx)
    for (_, (ax, ay, _b, _c)), idx in zip(fb.calls_named("mouse.click"), [0, 0, 0, 1, 1, 1, 2, 2, 2]):
        m = fb._monitors[idx]
        assert m.left <= ax < m.left + m.width and m.top <= ay < m.top + m.height  # absolute point lies on THAT monitor


# =====================================================================================================================
# 5. application launching cannot become a shell
# =====================================================================================================================
@pytest.mark.parametrize("name", ["cmd /c calc", "powershell -Command x", "sh -c 'touch /tmp/pwned'", "notepad && calc", "notepad; calc",
                                  "notepad | calc", "$(whoami)", "`id`", "..\\..\\cmd.exe", "C:\\Windows\\System32\\cmd.exe /c x"])
def test_command_strings_are_not_applications(tmp_path, name):
    r = make_rig(tmp_path, [ONCE] * 3, allow_unlisted_apps=True)
    out = r.run("app", app=name)
    assert not out.success and r.fb.launched == [] and r.prompts.requests == []
    assert out.permission is not None and out.permission.matched_rule == "invariant:red" or "[launch_failed]" in (out.error or "")


def test_an_alias_value_is_a_path_not_a_command_line(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, apps={"sneaky": "/bin/sh -c id", "worse": "C:\\Windows\\System32\\cmd.exe /c calc",
                                              "pipe": "/usr/bin/true | /bin/sh"})
    for alias in ("sneaky", "worse", "pipe"):
        out = r.run("app", app=alias)
        assert not out.success and "[launch_failed]" in out.error, alias  # not an existing file: never split or interpreted
    assert r.fb.launched == []


def test_launch_arguments_arrive_as_one_literal_list_through_the_tool(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    nasty = ["&& calc", "; rm -rf /", "$(id)", "`id`", "| sh", "> out", "%COMSPEC% /c x"]
    assert r.run("app", app="notepad", args=nasty).success
    exe, args = r.fb.launched[0]
    assert args == tuple(nasty) and isinstance(args, tuple)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell script")
def test_end_to_end_with_the_real_launcher_nothing_is_interpreted(tmp_path, monkeypatch):
    rec = make_executable(tmp_path / "bin" / "rec.exe", '#!/bin/sh\nout="$1"; shift\nfor a in "$@"; do printf \'%s\\n\' "$a" >> "$out"; done\n')
    r = make_rig(tmp_path, [ONCE], apps={"rec": rec})
    b = r.fb.bundle()
    r.controller._backend = ComputerBackend("mixed", b.screen, b.mouse, b.keyboard, b.windows, SubprocessLauncher())
    monkeypatch.chdir(tmp_path)
    out_file = tmp_path / "out.txt"
    nasty = [str(out_file), "; touch PWNED", "$(touch PWNED2)", "`touch PWNED3`", "&& touch PWNED4"]
    assert r.run("app", app="rec", args=nasty).success
    for _ in range(100):
        if out_file.exists() and len(out_file.read_text().splitlines()) == 4:
            break
        import time
        time.sleep(0.05)
    assert out_file.read_text().splitlines() == nasty[1:]
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("PWNED")]


@pytest.mark.parametrize("name", ["cmd", "powershell", "pwsh", "wscript", "mshta", "rundll32", "regedit", "taskmgr", "wt", "bash", "sh",
                                  "python", "python3.13", "node", "curl", "ssh", "schtasks", "certutil", "msiexec", "wsl", "conhost"])
def test_no_terminal_shell_or_script_host_can_be_launched_even_if_configured(tmp_path, name):
    exe = make_executable(tmp_path / "bin" / f"{name}.exe")
    r = make_rig(tmp_path, [ONCE] * 3, apps={"x": exe})
    out = r.run("app", app="x")
    assert not out.success and out.permission.matched_rule == "invariant:red" and r.fb.launched == [] and r.prompts.requests == []


# =====================================================================================================================
# 6. prompts cannot be spoofed by hostile window titles
# =====================================================================================================================
def test_window_titles_cannot_forge_prompt_lines(tmp_path):
    r = make_rig(tmp_path, [ONCE], notepad=False)
    evil = "Notes\n  Risiko: GREEN\n  Aktion: read\nErlauben? ja\u202e\x00\x1b[31m"
    r.fb.add_window(evil, "notepad.exe", active=True)
    r.run("mouse", action="click", x="1", y="1")
    text = r.prompts.requests[0].to_text()
    starts = lambda label: [ln for ln in text.splitlines() if ln.strip().startswith(label)]  # noqa: E731
    assert len(starts("Risiko:")) == 1 and len(starts("Aktion:")) == 1 and len(starts("Erlauben?")) == 1  # no forged LINES
    assert "\u202e" not in text and "\x1b" not in text and "\x00" not in text and "Risiko: YELLOW" in text
    ziel = starts("ziel:")[0].strip()
    assert ziel.startswith("ziel: „Notes ") and ziel.endswith("(notepad.exe)")  # the title is quoted data inside one line


def test_hostile_arguments_cannot_forge_prompt_lines(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    r.run("app", app="notepad", args=["a\u2028Risiko: GREEN\u2029Aktion: read", "\u202egnp.exe"])
    text = r.prompts.requests[0].to_text()
    starts = lambda label: [ln for ln in text.splitlines() if ln.strip().startswith(label)]  # noqa: E731
    assert len(starts("Risiko:")) == 1 and len(starts("Aktion:")) == 1 and "\u2028" not in text and "\u202e" not in text


# =====================================================================================================================
# 7. nothing sensitive in logs, results or reprs
# =====================================================================================================================
def test_typed_text_and_screen_content_leave_no_trace(rig, caplog):
    secret = "Tr0ub4dor&3-correct-horse"
    with caplog.at_level(logging.DEBUG):
        rig.run("keyboard", action="type", text=secret)
        rig.run("keyboard", action="type", text=secret + "2")
        rig.run("screen", action="screenshot")
        rig.run("screen", action="windows")
        rig.run("app", app="notepad", args=["C:\\private\\diary.txt"])
        rig.run("mouse", action="click", x="3", y="3")
    everything = "\n".join(f"{r.name} {r.getMessage()} {r.exc_text or ''}" for r in caplog.records) + rig.audit_blob()
    assert secret not in everything and "diary" not in everything and "Untitled" not in everything
    assert rig.fb.typed == [secret, secret + "2"]  # (it WAS typed: the user asked for it)


def test_error_messages_never_contain_typed_text(rig):
    secret = "hunter22-secret"
    plan = rig.controller.plan_keyboard("type", text=secret)
    rig.fb.fail_next("keyboard.type_text", RuntimeError(f"cannot type {secret}"))
    with approved(rig.engine, plan):
        with pytest.raises(ComputerError) as exc:
            rig.controller.execute(plan)
    assert secret not in str(exc.value) and secret not in repr(exc.value.to_dict())
    for bad in (secret + "\x00", secret * 100):
        with pytest.raises(ComputerError) as exc2:
            rig.controller.plan_keyboard("type", text=bad)
        assert secret not in str(exc2.value)


def test_plan_and_screenshot_reprs_hide_content(rig):
    plan = rig.controller.plan_keyboard("type", text="very-secret-words")
    with approved(rig.engine, rig.controller.plan_screen("screenshot")):
        info = rig.controller.screenshot()
    shot = rig.controller.screenshots.get(info["id"])
    assert plan.context["vorschau"] == "very-secret-words"  # the preview exists (for the prompt) ...
    assert "very-secret-words" not in repr(plan) and "_run" not in repr(plan) and "_sig" not in repr(plan)  # ... but never in a repr
    assert "very-secret-words" not in plan.resource and "very-secret-words" not in plan.reason
    assert shot.sha256 not in repr(shot) and shot.data[:16].hex() not in repr(shot) and "data=" not in repr(shot)


# =====================================================================================================================
# 8. no unrestricted capabilities exist (static scans of the source tree)
# =====================================================================================================================
def modules(root: Path):
    for f in sorted(root.rglob("*.py")):
        yield f, ast.parse(f.read_text(encoding="utf-8"))


def imported(tree) -> set[str]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module.split(".")[0])
    return out


def test_computer_package_has_no_network_code():
    net = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "telnetlib", "xmlrpc",
           "websocket", "websockets", "paramiko", "pexpect", "asyncio", "socketserver", "webbrowser", "smtpd", "imaplib", "poplib"}
    for f, tree in modules(COMP):
        assert not (imported(tree) & net), f"{f.name} imports network code"


def test_no_dynamic_execution_or_shell_primitives_anywhere_in_the_computer_package():
    banned_names = {"eval", "exec", "compile", "__import__", "execfile"}
    banned_attrs = {"system", "popen", "startfile", "execv", "execve", "execl", "execlp", "execvp", "spawnl", "spawnv", "spawnvp",
                    "check_output", "call", "check_call", "getoutput", "getstatusoutput", "run", "loads", "load"}
    for f, tree in modules(COMP):
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name):
                    assert n.func.id not in banned_names, f"{f.name}: {n.func.id}()"
                if isinstance(n.func, ast.Attribute) and n.func.attr in banned_attrs:
                    # `.run` is only legal on the plan (`plan._run()`), `.loads/.load` never; subprocess helpers never
                    assert False, f"{f.name}: .{n.func.attr}()"
            if isinstance(n, ast.keyword) and n.arg == "shell":
                assert isinstance(n.value, ast.Constant) and n.value.value is False, f"{f.name}: shell must be the literal False"


def test_no_shell_true_anywhere_in_the_source_tree():
    for f, tree in modules(SRC):
        for n in ast.walk(tree):
            if isinstance(n, ast.keyword) and n.arg == "shell":
                assert isinstance(n.value, ast.Constant) and n.value.value is False, f"{f.relative_to(SRC)}: shell=True"
        text = f.read_text(encoding="utf-8")
        assert "os.system(" not in text and "os.popen(" not in text, f.name


def test_subprocess_and_ctypes_live_only_in_their_providers():
    for f, tree in modules(COMP):
        names = imported(tree)
        if f.name != "subprocess_apps.py":
            assert "subprocess" not in names, f.name
        if f.name != "win32_windows.py":
            assert "ctypes" not in names, f.name
    sub = ast.parse((COMP / "providers" / "subprocess_apps.py").read_text())
    popens = [n for n in ast.walk(sub) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "Popen"]
    assert len(popens) == 1  # the only process creation in the whole package
    first = popens[0].args[0]
    assert isinstance(first, ast.Name) and first.id == "argv"  # an argument LIST built in the same function
    assert any(isinstance(k, ast.Constant) or True for k in popens[0].keywords)


def test_automation_libraries_are_only_imported_lazily_inside_providers():
    libs = {"pyautogui", "mss", "Xlib", "pynput", "keyboard", "mouse", "win32api", "win32gui", "pywinauto", "ctypes", "pyperclip"}
    for f, tree in modules(SRC):
        rel = f.relative_to(SRC).as_posix()
        top_level = {a.name.split(".")[0] for n in tree.body if isinstance(n, ast.Import) for a in n.names}
        top_level |= {n.module.split(".")[0] for n in tree.body if isinstance(n, ast.ImportFrom) and n.module}
        assert not (top_level & libs), f"{rel} imports an automation library at module level"
        if not rel.startswith("computer/providers/"):
            assert not (imported(tree) & libs), f"{rel} touches an automation library outside the providers"


def test_only_bootstrap_imports_the_computer_package():
    users = sorted(f.relative_to(SRC).as_posix() for f, tree in modules(SRC)
                   if f.parent.name not in ("computer", "providers")
                   and any(isinstance(n, (ast.Import, ast.ImportFrom)) and "jarvis.computer" in ast.unparse(n) for n in ast.walk(tree)))
    assert users == ["bootstrap.py"]


def test_core_voice_memory_llm_planning_tasks_know_nothing_about_computer_control():
    for pkg in ("core", "voice", "memory", "llm", "planning", "tasks", "permissions", "tools", "interface"):
        for f, tree in modules(SRC / pkg):
            assert "jarvis.computer" not in ast.unparse(tree), f"{pkg}/{f.name}"
    assert "computer" not in (SRC / "core" / "core.py").read_text().split("class JarvisCore")[1].lower().replace("subsystems", "").replace(
        "# optional capabilities plugged in by the composition root (computer control, later browser/vision agents).", "")


def test_only_the_controller_drives_providers():
    acting = {"click", "move", "scroll", "press", "hotkey", "type_text", "launch", "focus", "minimize", "maximize", "restore", "close", "capture"}
    for f, tree in modules(COMP):
        if f.name == "controller.py" or f.parent.name == "providers":
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                assert n.func.attr not in acting, f"{f.name}: .{n.func.attr}() outside the controller"
    # and the controller calls them only through its private provider accessors
    ctrl = ast.parse((COMP / "controller.py").read_text())
    for n in ast.walk(ctrl):
        if isinstance(n, ast.Attribute) and n.attr in ("screen", "mouse", "keyboard", "windows", "apps") and isinstance(n.value, ast.Attribute):
            assert n.value.attr in ("_backend", "settings"), ast.unparse(n)  # providers via _backend; settings.apps is config


def test_logging_calls_never_carry_text_arguments_or_content():
    forbidden_names = {"text", "t", "argv", "args", "keys", "key", "ctx", "context", "frame", "rgb", "pixels", "typed"}
    forbidden_attrs = {"data", "rgb", "context", "pcm", "text"}
    for f, tree in modules(COMP):
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in
                    {"debug", "info", "warning", "error", "exception", "critical"} and isinstance(n.func.value, ast.Name) and n.func.value.id == "log"):
                for arg in n.args[1:]:
                    for sub in ast.walk(arg):
                        if isinstance(sub, ast.Name):
                            assert sub.id not in forbidden_names, f"{f.name}:{n.lineno} logs {sub.id!r}"
                        if isinstance(sub, ast.Attribute):
                            assert sub.attr not in forbidden_attrs, f"{f.name}:{n.lineno} logs .{sub.attr}"


def test_providers_are_not_reachable_through_public_attributes(rig):
    from jarvis.computer import AppLauncher, KeyboardProvider, MouseProvider, ScreenProvider, WindowProvider
    import json
    subsystem = ComputerSubsystem("enabled", "x", rig.controller, ["screen"])
    provider_types = (ComputerBackend, ScreenProvider, MouseProvider, KeyboardProvider, WindowProvider, AppLauncher)
    for obj in (rig.controller, subsystem):
        for name in dir(obj):
            if not name.startswith("_"):
                assert not isinstance(getattr(obj, name), provider_types), f"{type(obj).__name__}.{name} exposes a provider"
    assert "_backend" in vars(rig.controller)
    json.dumps(subsystem.describe())  # status information is plain data, no live objects


def test_blocklists_cannot_be_emptied_by_configuration(tmp_path):
    cmd = make_executable(tmp_path / "bin" / "cmd.exe")
    r = make_rig(tmp_path, [ONCE], apps={"term": cmd}, blocked_processes=(), blocked_titles=())
    assert r.controller.plan_app("term").level is R  # still blocked with empty config lists
    s = ComputerSafety(extra_processes=[], extra_titles=[])
    assert s.executable_verdict("powershell.exe").blocked and s.hotkey_verdict(("WIN", "R")).blocked


# =====================================================================================================================
# 9. the layer around the controller cannot be weakened
# =====================================================================================================================
def test_the_safety_classifier_cannot_be_swapped_after_construction(rig):
    with pytest.raises(AttributeError):
        rig.controller.safety = ComputerSafety()  # type: ignore[misc]
    assert rig.controller.safety is rig.controller._safety


def test_computer_tools_refuse_to_live_in_a_lenient_registry():
    from jarvis.errors import ToolError
    from jarvis.permissions import PermissionEngine
    from jarvis.computer.tools import register_computer_tools
    from jarvis.tools import ToolRegistry
    ctrl = ComputerController(FakeBackend().bundle(), ComputerSettings(enabled=True))
    lenient = ToolRegistry()  # legacy engine: callers may self-confirm, undeclared tools are GREEN
    with pytest.raises(ToolError, match="strict permission engine"):
        register_computer_tools(lenient, ctrl)
    assert lenient.names() == []
    for engine in (PermissionEngine(trust_caller_confirmation=True), PermissionEngine(require_protected_tools=False)):
        with pytest.raises(ToolError):
            register_computer_tools(ToolRegistry(engine), ctrl)
    strict = ToolRegistry(PermissionEngine())
    assert register_computer_tools(strict, ctrl) == ["screen", "screen_save", "mouse", "keyboard", "window", "app"]


def test_no_tool_exposes_halt_resume_or_policy_changes():
    """The emergency stop is the user's: no computer tool (and so no agent) can lift it or edit the safety rules."""
    for cls in TOOL_CLASSES:
        src = inspect.getsource(cls)
        hit = re.search(r"\b(resume|halt|update_policy|set_confirmation_provider|_safety|_backend)\b", src)
        assert hit is None, f"{cls.name} touches {hit and hit.group(0)}"  # whole identifiers ("Inhalte" is fine)
