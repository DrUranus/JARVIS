"""REAL end-to-end test of computer control on a live (virtual) X11 display. No fakes: real pyautogui mouse/keyboard
(XTEST), real mss screenshots, real python-xlib window management, real subprocess launching, a real X client
(tests/realgui/x11_app.py), the real PermissionEngine and the production wiring (build_core).

Skipped automatically where Xvfb or the optional libraries are unavailable (e.g. Windows, minimal CI images).
The harness runs in a subprocess so no automation library is ever imported into the pytest process.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent / "realgui"
PROBE = ("import importlib.util as u, sys\n"
         "sys.exit(0 if all(u.find_spec(m) for m in ('Xlib', 'mss', 'pyautogui')) else 1)\n")  # installed? (no import: no display yet)

pytestmark = pytest.mark.skipif(sys.platform != "linux" or shutil.which("Xvfb") is None,
                                reason="needs Linux and Xvfb (virtual X11 display)")


def free_display() -> int:
    for n in range(90, 140):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not os.path.exists(f"/tmp/.X{n}-lock"):
            return n
    raise RuntimeError("no free X display number")


@pytest.fixture(scope="module")
def xvfb():
    probe = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("optional libraries not installed: pip install -e '.[computer]'")
    n = free_display()
    proc = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if os.path.exists(f"/tmp/.X11-unix/X{n}"):
            break
        time.sleep(0.05)
    else:
        proc.kill()
        pytest.skip("Xvfb did not start")
    time.sleep(0.3)
    yield f":{n}"
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def report(xvfb, tmp_path_factory):
    work = tmp_path_factory.mktemp("x11real")
    env = {**os.environ, "DISPLAY": xvfb}
    done = subprocess.run([sys.executable, str(HERE / "x11_e2e.py"), str(work)], env=env, capture_output=True, text=True, timeout=180)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("REPORT:")]
    assert lines, f"no report. stdout={done.stdout[-1500:]} stderr={done.stderr[-1500:]}"
    rep = json.loads(lines[-1][len("REPORT:"):])
    rep["_work"] = work
    return rep


def ok(report, name):
    s = report["steps"][name]
    assert s["ok"], f"{name}: {s.get('error')}"
    return s


def denied(report, name, rule):
    s = report["steps"][name]
    assert not s["ok"] and s["rule"] == rule, f"{name}: {s}"
    return s


def test_the_real_backend_is_available_and_enabled(report):
    st = report["status"]
    assert st["status"] == "enabled", st
    assert st["backend"] == "x11" and set(st["capabilities"]) == {"screen", "mouse", "keyboard", "windows", "apps"}


def test_screen_monitor_and_screenshots_are_real(report):
    mons = ok(report, "monitors")["output"]
    assert (mons[0]["width"], mons[0]["height"], mons[0]["primary"]) == (1280, 800, True)
    shot = ok(report, "screenshot_before")
    assert shot["scope"] == "automatic" and shot["output"]["bytes"] == 1280 * 800 * 3 and "data" not in shot["output"]


def test_launching_the_test_application_is_confirmed_and_the_window_appears(report):
    assert ok(report, "launch_main")["scope"] == "once"
    win = report["steps"]["window_found"]["output"]
    assert win["title"] == "JARVIS Test App" and win["process"] == "jarvis-xapp" and win["class"] == "JarvisXApp"
    assert win["rect"][2:] == [420, 220]


def test_the_screen_visibly_changes_and_the_verify_step_detects_it(report):
    d = ok(report, "compare_launch")["output"]
    assert d["comparable"] and not d["identical"] and d["changed_pixels"] > 50_000 and d["bbox"][0] >= 60
    t = ok(report, "compare_typed")["output"]  # typing drew squares inside the window only
    assert not t["identical"] and 0 < t["changed_pixels"] < 5_000 and t["bbox"][0] >= 60 and t["bbox"][2] <= 481


def test_focus_click_type_and_hotkey_reach_the_real_application(report):
    ok(report, "focus")
    assert ok(report, "active_window")["output"]["title"] == "JARVIS Test App"
    ok(report, "click")
    click = report["steps"]["app_saw_click"]
    assert click["ok"] and click["output"].split()[0] == "1"  # button 1, delivered to the window
    ok(report, "type")
    assert report["steps"]["app_saw_text"]["output"] == "jarvis test 123"  # exactly the typed characters, via real key events
    ok(report, "hotkey")
    assert report["steps"]["app_saw_hotkey"]["output"] == "ctrl+s"
    for name in ("focus", "click", "type", "hotkey", "launch_main"):
        assert report["steps"][name]["scope"] == "once" and report["steps"][name]["rule"] == "user:confirmed"


def test_unsafe_requests_are_refused_on_the_real_desktop(report):
    s = report["steps"]["click_outside_screen"]
    assert not s["ok"] and "[invalid_coordinates]" in s["error"] and "x 0..1279, y 0..799" in s["error"]
    denied(report, "win_r_hotkey", "invariant:red")
    denied(report, "launch_cmd", "invariant:red")
    denied(report, "launch_unlisted_path", "invariant:red")


def test_a_terminal_like_window_receives_no_input_and_cannot_be_closed(report):
    ok(report, "launch_term")
    ok(report, "focus_terminal")  # focusing is harmless and allowed ...
    s = denied(report, "type_into_terminal", "invariant:red")  # ... typing into it is not
    assert "command or security surface" in s["error"]
    denied(report, "close_terminal_window", "invariant:red")
    assert report["steps"]["terminal_received_nothing"]["ok"]  # the real app recorded no key at all
    assert report["terminal_text_in_audit"] is False


def test_saving_a_screenshot_is_explicit_confirmed_and_never_overwrites(report):
    s = ok(report, "save_screenshot")
    assert s["scope"] == "once" and s["output"]["path"].endswith("ws/shots/final.png")
    assert report["saved_png"]["exists"] and report["saved_png"]["signature_ok"] and report["saved_png"]["bytes"] > 1000
    again = report["steps"]["save_again_refused"]
    assert not again["ok"] and "already exists" in again["error"]
    denied(report, "save_outside_refused", "fs:outside_roots")


def test_the_application_is_closed_gracefully_and_disappears(report):
    assert ok(report, "close_app")["scope"] == "once"
    assert report["steps"]["window_gone"]["ok"] and report["steps"]["app_exited_cleanly"]["ok"]  # WM_DELETE_WINDOW, no kill


def test_the_emergency_stop_works_for_real(report):
    ok(report, "move_to_corner")
    s = report["steps"]["failsafe_trips"]
    assert not s["ok"] and s["output"]["code"] == "failsafe"  # pyautogui fail-safe: pointer in the corner aborts input
    ok(report, "works_again_after_leaving_corner")


def test_nothing_typed_or_sensitive_was_recorded(report):
    assert report["typed_text_in_audit"] is False and report["typed_text_in_log"] is False
    assert {"keyboard.type", "keyboard.hotkey", "mouse.click", "app.launch", "window.close", "screen_save.save"} <= set(report["audit_actions"])
    assert report["prompts_shown"] >= 12  # every consequential action was put to the user
    work = report["_work"]
    everything = "\n".join(p.read_text(errors="replace") for p in work.rglob("*") if p.is_file() and p.suffix in (".jsonl", ".log"))
    assert "jarvis test 123" not in everything and "should-never-be-typed" not in everything
