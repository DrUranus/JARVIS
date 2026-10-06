"""Real end-to-end run of JARVIS computer control against a live (virtual) X11 display.

Runs the SAME code path as production: load_settings -> build_core -> ToolRegistry -> PermissionEngine ->
ComputerController -> pyautogui/mss/xlib providers -> a real X server. Prints a JSON report.
Run inside Xvfb:   DISPLAY=:99 python x11_e2e.py <workdir>
"""
import json
import os
import sys
import time
import types
from pathlib import Path

try:  # pyautogui's optional MouseInfo helper insists on tkinter; this harness does not need it
    import tkinter  # noqa: F401
except ImportError:
    sys.modules.setdefault("mouseinfo", types.ModuleType("mouseinfo"))

work = Path(sys.argv[1])
here = Path(__file__).resolve().parent
(work / "ws" / "shots").mkdir(parents=True, exist_ok=True)
(work / "bin").mkdir(exist_ok=True)

wrapper = work / "bin" / "jarvis-xapp"
wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{here / "x11_app.py"}" "$@"\n')
wrapper.chmod(0o755)
cfg = work / "jarvis.toml"
cfg.write_text(f'''workspace = "{work / "ws"}"
log_dir = "{work / "logs"}"
[memory]
path = "{work / "memory.db"}"
[computer]
enabled = true
backend = "x11"
action_delay = 0.15
type_interval = 0.03
[computer.apps]
xapp = "{wrapper}"
''')

from jarvis.bootstrap import build_core  # noqa: E402
from jarvis.config import load_settings  # noqa: E402
from jarvis.permissions import ScriptedConfirmation  # noqa: E402

report: dict = {"steps": {}}
steps = report["steps"]
core = build_core(load_settings(cfg, env={}))
sub = core.subsystems["computer"]
report["status"] = sub.describe()
if sub.status != "enabled":
    print(json.dumps(report))
    sys.exit(0)
answers = ScriptedConfirmation(["allow_once"] * 40)
core.permissions.set_confirmation_provider(answers)
run = core.tools.execute


def step(name, result):
    steps[name] = {"ok": result.success, "output": result.output if result.success else result.output, "error": result.error,
                   "scope": getattr(getattr(result, "permission", None), "scope", None) and result.permission.scope.value,
                   "rule": getattr(getattr(result, "permission", None), "matched_rule", None)}
    return result


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.1)
    return None


def find_window(title):
    r = run("screen", action="windows")
    return next((w for w in (r.output or []) if w["title"] == title), None)


def launch(title, x_off, name):
    rec = work / f"{name}.txt"
    ready = work / f"{name}.ready"
    r = step(f"launch_{name}", run("app", app="xapp", args=[str(rec), str(ready), title, str(x_off)]))
    if r.success:
        wait_for(lambda: ready.exists())
        wait_for(lambda: find_window(title))
    return rec, r


# 1. observe -----------------------------------------------------------------------------------------------------------
r = step("monitors", run("screen", action="monitors"))
mon = r.output[0]
before = step("screenshot_before", run("screen", action="screenshot"))

# 2. launch the harmless test application (confirmed) --------------------------------------------------------------------
rec, _ = launch("JARVIS Test App", 0, "main")
win = find_window("JARVIS Test App")
steps["window_found"] = {"ok": win is not None, "output": win}
after = step("screenshot_after_launch", run("screen", action="screenshot"))
step("compare_launch", run("screen", action="compare", a=before.output["id"], b=after.output["id"]))

# 3. focus, inspect, click, type ---------------------------------------------------------------------------------------------
step("focus", run("window", action="focus", handle=str(win["handle"])))
step("active_window", run("screen", action="active_window"))
cx, cy = win["rect"][0] + win["rect"][2] // 2, win["rect"][1] + win["rect"][3] // 2
step("click", run("mouse", action="click", x=str(cx), y=str(cy)))
wait_for(lambda: (Path(str(rec) + ".clicks")).exists())
steps["app_saw_click"] = {"ok": Path(str(rec) + ".clicks").exists(), "output": Path(str(rec) + ".clicks").read_text().strip() if Path(str(rec) + ".clicks").exists() else None}
step("type", run("keyboard", action="type", text="jarvis test 123"))
step("hotkey", run("keyboard", action="hotkey", keys="ctrl+s"))
wait_for(lambda: rec.exists() and rec.read_text() == "jarvis test 123")
steps["app_saw_text"] = {"ok": rec.exists() and rec.read_text() == "jarvis test 123", "output": rec.read_text() if rec.exists() else None}
steps["app_saw_hotkey"] = {"ok": Path(str(rec) + ".hotkeys").exists(), "output": Path(str(rec) + ".hotkeys").read_text().strip() if Path(str(rec) + ".hotkeys").exists() else None}
final = step("screenshot_final", run("screen", action="screenshot"))
step("compare_typed", run("screen", action="compare", a=after.output["id"], b=final.output["id"]))

# 4. safety on the real desktop ------------------------------------------------------------------------------------------------
step("click_outside_screen", run("mouse", action="click", x=str(mon["width"] + 50), y="5"))
step("win_r_hotkey", run("keyboard", action="hotkey", keys="win+r"))
step("launch_cmd", run("app", app="cmd"))
step("launch_unlisted_path", run("app", app="/bin/sh"))
term_rec, term_launch = launch("Windows PowerShell", 200, "term")
term = find_window("Windows PowerShell")
if term:
    step("focus_terminal", run("window", action="focus", handle=str(term["handle"])))
    step("type_into_terminal", run("keyboard", action="type", text="rm -rf /tmp/should-never-be-typed"))
    step("close_terminal_window", run("window", action="close", handle=str(term["handle"])))
steps["terminal_received_nothing"] = {"ok": not term_rec.exists(), "output": term_rec.read_text() if term_rec.exists() else None}

# 5. save the screenshot (explicit, confirmed file write) --------------------------------------------------------------------------
step("save_screenshot", run("screen_save", id=final.output["id"], path="shots/final.png"))
step("save_again_refused", run("screen_save", id=final.output["id"], path="shots/final.png"))
step("save_outside_refused", run("screen_save", id=final.output["id"], path="../escape.png"))

# 6. close the test application gracefully -------------------------------------------------------------------------------------------
win = find_window("JARVIS Test App")
step("close_app", run("window", action="close", handle=str(win["handle"])))
gone = wait_for(lambda: find_window("JARVIS Test App") is None)
steps["window_gone"] = {"ok": bool(gone), "output": None}
steps["app_exited_cleanly"] = {"ok": bool(wait_for(lambda: Path(str(rec) + ".closed").exists())), "output": None}

# 7. emergency stop: pointer in a screen corner (pyautogui fail-safe) ---------------------------------------------------------------------
step("move_to_corner", run("mouse", action="move", x="0", y="0"))
step("failsafe_trips", run("mouse", action="click", x="100", y="100"))
from Xlib import display as _d  # noqa: E402

dd = _d.Display()
dd.screen().root.warp_pointer(300, 300)
dd.sync()
step("works_again_after_leaving_corner", run("mouse", action="move", x="310", y="310"))

# cleanup of the PowerShell-titled helper window (outside JARVIS: it cannot and must not close it)
term_pid = (term_launch.output or {}).get("pid")
if term_pid:
    try:
        os.kill(int(term_pid), 15)
    except OSError:
        pass

# 8. what was recorded ------------------------------------------------------------------------------------------------------------------
audit = (work / "logs" / "audit.jsonl").read_text() if (work / "logs" / "audit.jsonl").exists() else ""
logs = (work / "logs" / "jarvis.log").read_text() if (work / "logs" / "jarvis.log").exists() else ""
saved = work / "ws" / "shots" / "final.png"
report["saved_png"] = {"exists": saved.exists(), "signature_ok": saved.exists() and saved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n",
                       "bytes": saved.stat().st_size if saved.exists() else 0}
report["typed_text_in_audit"] = "jarvis test 123" in audit
report["typed_text_in_log"] = "jarvis test 123" in logs
report["terminal_text_in_audit"] = "should-never-be-typed" in audit
report["audit_actions"] = sorted({f"{e.get('tool')}.{e.get('action')}" for e in (json.loads(l) for l in audit.splitlines()) if e.get("tool") and e.get("action")})
report["prompts_shown"] = len(answers.requests)
print("REPORT:" + json.dumps(report, default=str))
