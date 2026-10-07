"""Targeted window input: input for a specific window, brought to the front and re-verified before every input.

Real PermissionEngine + ToolRegistry + fake backend. The approval is for ONE window; whatever changes afterwards
(window closed, replaced, moved, blocked, focus refused, focus stolen mid-typing) must stop the input before it is sent.
"""
from dataclasses import replace

import pytest

from computer_util import NO, ONCE, make_rig


@pytest.fixture
def rig(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 20)
    r.other = r.fb.add_window("Editor B", "editor.exe", left=0, top=0, width=40, height=30)  # not active
    return r


def calls(r, prefix):
    return [c[0] for c in r.fb.calls if c[0].startswith(prefix)]


def order(r):
    return [c[0] for c in r.fb.calls if c[0] in ("windows.focus", "keyboard.type_text", "keyboard.press", "keyboard.hotkey", "mouse.click")]


# ---- keyboard ---------------------------------------------------------------------------------------------------------------------------
def test_text_goes_to_the_named_window_after_it_was_focused_and_verified(rig):
    assert rig.fb.active_handle != rig.other.handle
    out = rig.run("keyboard", action="type", text="hello", window=rig.other.handle)
    assert out.success, out.error
    assert rig.fb.active_handle == rig.other.handle and rig.fb.typed == ["hello"]
    assert order(rig) == ["windows.focus", "keyboard.type_text"]  # focus first, input second
    assert out.permission.resolved_resource == "keyboard://text@editor.exe"  # the URI format (and so every policy glob) is unchanged


def test_the_confirmation_names_the_window_and_the_text_never_leaves_the_prompt(rig):
    rig.run("keyboard", action="type", text="private note", window=rig.other.handle)
    blob = rig.prompt_blob()
    assert str(rig.other.handle) in blob and "Editor B" in blob and "Vordergrund" in blob


def test_press_and_hotkey_are_targeted_too(rig):
    assert rig.run("keyboard", action="press", key="enter", window=rig.other.handle).success
    assert rig.run("keyboard", action="hotkey", keys="ctrl+s", window=rig.other.handle).success
    assert order(rig)[:2] == ["windows.focus", "keyboard.press"]


def test_a_window_that_is_already_active_is_not_refocused(rig):
    active = rig.fb.active_handle
    assert rig.run("keyboard", action="type", text="x", window=active).success
    assert "windows.focus" not in order(rig)


def test_a_minimized_window_is_restored_by_focusing_it(rig):
    rig.fb.windows[rig.other.handle] = replace(rig.other, minimized=True)
    assert rig.run("keyboard", action="type", text="x", window=rig.other.handle).success
    assert rig.fb.windows[rig.other.handle].minimized is False


def test_denial_by_the_user_sends_and_focuses_nothing(tmp_path):
    r = make_rig(tmp_path, [NO])
    o = r.fb.add_window("Editor B", "editor.exe")
    out = r.run("keyboard", action="type", text="x", window=o.handle)
    assert not out.success and r.fb.typed == [] and "windows.focus" not in order(r)


@pytest.mark.parametrize("process", ["cmd.exe", "powershell.exe", "python.exe", "taskmgr.exe"])
def test_protected_windows_stay_red_even_when_named_explicitly(rig, process):
    w = rig.fb.add_window("whatever", process)
    out = rig.run("keyboard", action="type", text="x", window=w.handle)
    assert not out.success and out.permission.level.value == "red" and rig.fb.typed == [] and order(rig) == []
    assert rig.prompts.requests == [] or all(str(w.handle) not in q.to_text() for q in rig.prompts.requests)


def test_unknown_window_is_rejected(rig):
    out = rig.run("keyboard", action="type", text="x", window=99999)
    assert not out.success and rig.fb.typed == []


def test_forbidden_keys_are_red_with_or_without_a_window(rig):
    out = rig.run("keyboard", action="hotkey", keys="win+r", window=rig.other.handle)
    assert not out.success and out.permission.level.value == "red" and order(rig) == []


# ---- the target is re-verified after approval ------------------------------------------------------------------------------------------
def _after_confirmation(rig, action):
    orig = rig.prompts.confirm

    def hook(request):
        choice = orig(request)
        action()
        return choice

    rig.prompts.confirm = hook


def test_window_closed_after_approval(rig):
    _after_confirmation(rig, lambda: (rig.fb.windows.pop(rig.other.handle), rig.fb.z_order.remove(rig.other.handle)))
    out = rig.run("keyboard", action="type", text="x", window=rig.other.handle)
    assert not out.success and out.output["code"] in ("window_not_found", "target_changed") and rig.fb.typed == []


def test_handle_reused_by_another_program_after_approval(rig):
    _after_confirmation(rig, lambda: rig.fb.windows.__setitem__(rig.other.handle, replace(rig.other, pid=777, process="other.exe")))
    out = rig.run("keyboard", action="type", text="x", window=rig.other.handle)
    assert not out.success and out.output["code"] in ("target_changed", "not_authorized") and rig.fb.typed == []
    assert "windows.focus" not in order(rig)


def test_window_turns_into_a_blocked_one_after_approval(rig):
    _after_confirmation(rig, lambda: rig.fb.windows.__setitem__(rig.other.handle, replace(rig.other, title="Windows PowerShell")))
    out = rig.run("keyboard", action="type", text="x", window=rig.other.handle)
    assert not out.success and rig.fb.typed == [] and order(rig) == []


def test_focus_refused_by_the_os_sends_nothing(rig):
    rig.fb.focus_denied.add(rig.other.handle)
    out = rig.run("keyboard", action="type", text="x", window=rig.other.handle)
    assert not out.success and rig.fb.typed == [] and "keyboard.type_text" not in order(rig)


def test_focus_that_silently_did_nothing_is_caught_by_the_read_back(rig):
    rig.fb.focus_ignored.add(rig.other.handle)
    out = rig.run("keyboard", action="type", text="x", window=rig.other.handle)
    assert not out.success and out.output["code"] == "target_changed" and rig.fb.typed == []


def test_focus_moving_away_in_the_middle_of_a_long_text_stops_the_typing(rig):
    stolen = []

    def steal(chunk):
        if not stolen:
            stolen.append(chunk)
            rig.fb.active_handle = next(h for h in rig.fb.windows if h != rig.other.handle)

    rig.fb.on_type = steal
    out = rig.run("keyboard", action="type", text="A" * 50, window=rig.other.handle)
    assert not out.success and out.output["code"] == "target_changed"
    assert "".join(rig.fb.typed) == "A" * 16  # only the first, verified chunk was sent


def test_long_text_without_interference_is_typed_completely_in_verified_chunks(rig):
    text = "".join(chr(97 + i % 26) for i in range(100))
    assert rig.run("keyboard", action="type", text=text, window=rig.other.handle).success
    assert "".join(rig.fb.typed) == text and len(rig.fb.typed) == 7


def test_untargeted_typing_is_also_verified_per_chunk(rig):
    stolen = []

    def steal(chunk):
        if not stolen:
            stolen.append(1)
            rig.fb.active_handle = rig.other.handle

    rig.fb.on_type = steal
    out = rig.run("keyboard", action="type", text="B" * 40)
    assert not out.success and "".join(rig.fb.typed) == "B" * 16


# ---- mouse -------------------------------------------------------------------------------------------------------------------------------
def test_click_relative_to_a_window_focuses_it_first(rig):
    rig.fb.windows[rig.other.handle] = replace(rig.other, left=10, top=5, width=20, height=20)
    out = rig.run("mouse", action="click", x=3, y=4, window=rig.other.handle)
    assert out.success, out.error
    assert order(rig) == ["windows.focus", "mouse.click"]
    assert rig.fb.cursor == (13, 9) and rig.fb.active_handle == rig.other.handle
    assert out.permission.resolved_resource == "screen://monitor/0/13/9"  # same URI scheme as monitor-relative clicks


def test_point_outside_the_window_is_rejected(rig):
    out = rig.run("mouse", action="click", x=500, y=1, window=rig.other.handle)
    assert not out.success and rig.fb.calls_named("mouse.click") == []


def test_window_and_monitor_cannot_be_combined_and_minimized_windows_are_refused(rig):
    assert not rig.run("mouse", action="click", x=1, y=1, window=rig.other.handle, monitor=0).success
    rig.fb.windows[rig.other.handle] = replace(rig.other, minimized=True)
    assert not rig.run("mouse", action="click", x=1, y=1, window=rig.other.handle).success
    assert rig.fb.calls_named("mouse.click") == []


def test_window_moved_after_approval_is_not_clicked(rig):
    _after_confirmation(rig, lambda: rig.fb.windows.__setitem__(rig.other.handle, replace(rig.other, left=20, top=10)))
    out = rig.run("mouse", action="click", x=1, y=1, window=rig.other.handle)
    assert not out.success and out.output["code"] in ("target_changed", "not_authorized") and rig.fb.calls_named("mouse.click") == []


def test_protected_window_cannot_be_clicked_by_handle(rig):
    w = rig.fb.add_window("Terminal", "WindowsTerminal.exe", left=0, top=0, width=30, height=30)
    out = rig.run("mouse", action="click", x=1, y=1, window=w.handle)
    assert not out.success and out.permission.level.value == "red" and rig.fb.calls_named("mouse.click") == []


def test_the_pointer_must_really_be_over_the_approved_window(rig):
    # focus "succeeds" but a window we did not approve is on top at that point: the click is refused
    overlay = rig.fb.add_window("Overlay", "overlay.exe", left=0, top=0, width=64, height=48)
    bundle = rig.fb.bundle()
    rig.controller._backend = bundle
    bundle.windows.window_at = lambda x, y: replace(overlay)  # type: ignore[method-assign]
    out = rig.run("mouse", action="click", x=1, y=1, window=rig.other.handle)
    assert not out.success and rig.fb.calls_named("mouse.click") == []


def test_window_replaced_by_another_process_while_being_focused(rig):
    """Between planning and the read-back the handle now belongs to another process (same name, new pid)."""
    bundle = rig.fb.bundle()
    rig.controller._backend = bundle
    real_focus = bundle.windows.focus

    def focus_then_swap(handle):
        real_focus(handle)
        rig.fb.windows[handle] = replace(rig.fb.windows[handle], pid=4242)

    bundle.windows.focus = focus_then_swap  # type: ignore[method-assign]
    out = rig.run("keyboard", action="type", text="x", window=rig.other.handle)
    assert not out.success and out.output["code"] == "target_changed" and rig.fb.typed == []
