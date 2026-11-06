"""Nativer Windows-Desktop-Test des Mini-Overlays (pywebview/WebView2) gegen die ECHTE Engine.

Das ist KEIN Headless-Test: `jarvis-cc --overlay --overlay-on-top` startet ein echtes Fenster, das hier ueber die Win32-API gefunden, vermessen und mit der Maus bedient
wird (kein Eingriff in die Seite, keine Bruecke). Geprueft werden: Fenster "JARVIS" erscheint, Groesse ca. 140x140, Always-on-Top, der Kern ist gezeichnet (Screenshot),
ein echter Mausklick auf NOTAUS loest den Notaus der Engine aus (belegt ueber den Ereignisstrom des Servers). Beweise: Screenshots und JSON in JARVIS_GUI_EVIDENCE/native.

Laeuft nur mit JARVIS_NATIVE_GUI=1 auf einem interaktiven Windows-Desktop (Workflow-Job `native-desktop`); sonst uebersprungen, und ein uebersprungener Test gilt nie als
bestanden. Voraussetzungen: `pip install -e ".[dev,ui,computer]"` (pywebview, mss), WebView2-Laufzeit."""
from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.skipif(os.name != "nt", reason="nur Windows: natives pywebview-Fenster (ein uebersprungener Test gilt nicht als bestanden)"),
              pytest.mark.skipif(os.environ.get("JARVIS_NATIVE_GUI") != "1", reason="JARVIS_NATIVE_GUI=1 fehlt: nur auf einem interaktiven Windows-Desktop (nicht bestanden, nur uebersprungen)")]

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("JARVIS_GUI_EVIDENCE", ROOT / "reports" / "gui")) / "native"
GWL_EXSTYLE, WS_EX_TOPMOST = -20, 0x00000008
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


def user32():
    import ctypes
    return ctypes.windll.user32


def find_window(title: str, timeout: float):
    import ctypes
    from ctypes import wintypes
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hwnd = user32().FindWindowW(None, title)
        if hwnd and user32().IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32().GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right - rect.left > 20:
                return hwnd, (rect.left, rect.top, rect.right, rect.bottom)
        time.sleep(0.25)
    return None, None


def click(x: int, y: int) -> None:
    user32().SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    user32().mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32().mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def grab(box, name):
    import mss
    import mss.tools
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (mss.MSS() if hasattr(mss, 'MSS') else mss.mss()) as sct:
        shot = sct.grab({"left": box[0], "top": box[1], "width": box[2] - box[0], "height": box[3] - box[1]})
        mss.tools.to_png(shot.rgb, shot.size, output=str(EVIDENCE / f"{name}.png"))
        full = sct.grab(sct.monitors[0])
        mss.tools.to_png(full.rgb, full.size, output=str(EVIDENCE / f"{name}_desktop.png"))
    return shot


OUTPUT: list[str] = []


def read_url(proc, timeout: float) -> str:
    found: list[str] = []

    def pump():
        for line in proc.stdout:
            OUTPUT.append(line.rstrip())
            m = re.search(r"(http://127\.0\.0\.1:\d+/\?t=[\w-]+)", line)
            if m and not found:
                found.append(m.group(1))

    threading.Thread(target=pump, daemon=True).start()
    end = time.monotonic() + timeout
    while time.monotonic() < end and not found:
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    assert found, "keine Control-Center-URL in der Ausgabe (Start fehlgeschlagen?). Ausgabe:\n" + "\n".join(OUTPUT[-30:])
    return found[0]


def saw_emergency(url: str, timeout: float) -> bool:
    port = int(re.search(r":(\d+)/", url).group(1))
    token = re.search(r"t=([\w-]+)", url).group(1)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("GET", f"/events?t={token}&since=0", headers={"Host": f"127.0.0.1:{port}"})
    resp = conn.getresponse()
    end = time.monotonic() + timeout
    try:
        while time.monotonic() < end:
            line = resp.fp.readline().decode("utf-8", "replace")
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                if ev.get("type") == "emergency" and ev["data"].get("engaged") is True:
                    return True
    except (OSError, ValueError):
        return False
    finally:
        conn.close()
    return False


def test_native_overlay_window_always_on_top_and_real_emergency_click(tmp_path):
    from test_control_center_binding import real_env
    env = {**os.environ, **real_env(tmp_path), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "jarvis.control_center", "--overlay", "--overlay-on-top"], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    report: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        url = read_url(proc, 90)
        hwnd, box = find_window("JARVIS", 60)
        assert hwnd, "das Overlay-Fenster 'JARVIS' erschien nicht (WebView2-Laufzeit?)"
        width, height = box[2] - box[0], box[3] - box[1]
        report.update({"window": box, "size": [width, height]})
        assert 100 <= width <= 260 and 100 <= height <= 260, f"Overlay nicht ca. 140x140: {width}x{height}"       # DPI-Skalierung erlaubt
        topmost = bool(user32().GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
        report["always_on_top"] = topmost
        assert topmost, "--overlay-on-top: das Fenster ist nicht Always-on-Top"
        deadline = time.monotonic() + 45                                                 # WebView2 braucht auf dem Runner etwas, bis die Seite steht
        distinct = 0
        while time.monotonic() < deadline:
            shot = grab(box, "overlay_before")
            distinct = len({tuple(shot.rgb[i:i + 3]) for i in range(0, len(shot.rgb), 3 * 5)})
            if distinct > 40:
                break
            time.sleep(2)
        report["distinct_colors"] = distinct
        assert distinct > 40, f"das Overlay zeigt keinen gezeichneten Kern ({distinct} Farben). Ausgabe:\n" + "\n".join(OUTPUT[-30:])
        click(box[0] + width // 2, box[1] + max(10, int(height * 0.1)))                  # NOTAUS liegt oben im Overlay
        engaged = saw_emergency(url, 20)
        report["emergency_event"] = engaged
        time.sleep(1.5)
        grab(box, "overlay_after")
        assert engaged, "kein emergency-Ereignis nach dem Mausklick auf NOTAUS (Klick traf den Knopf nicht oder wirkte nicht)"
    finally:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "native_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (EVIDENCE / "native_stdout.txt").write_text("\n".join(OUTPUT), encoding="utf-8")
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)


# ---- Overlay gegen das deterministische Fake-Backend: Klick auf den Kern, Freigabedialog im echten Fenster, Stabilitaet ----------------------------------------------
VK_ESCAPE, KEYEVENTF_KEYUP = 0x1B, 0x0002


def post_command(url: str, type_: str, data: dict, cid: str) -> int:
    port = int(re.search(r":(\d+)/", url).group(1))
    token = re.search(r"t=([\w-]+)", url).group(1)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    body = json.dumps({"v": "1.0", "id": cid, "type": type_, "data": data})
    conn.request("POST", f"/command?t={token}", body=body, headers={"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"})
    status = conn.getresponse().status
    conn.close()
    return status


def wait_event(url: str, pred, timeout: float):
    port = int(re.search(r":(\d+)/", url).group(1))
    token = re.search(r"t=([\w-]+)", url).group(1)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("GET", f"/events?t={token}&since=0", headers={"Host": f"127.0.0.1:{port}"})
    resp = conn.getresponse()
    end = time.monotonic() + timeout
    try:
        while time.monotonic() < end:
            line = resp.fp.readline().decode("utf-8", "replace")
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                if pred(ev):
                    return ev
    except (OSError, ValueError):
        return None
    finally:
        conn.close()
    return None


def count_color(shot, test) -> int:
    n = 0
    for i in range(0, len(shot.rgb), 3):
        if test(shot.rgb[i], shot.rgb[i + 1], shot.rgb[i + 2]):
            n += 1
    return n


def test_native_overlay_core_click_opens_main_window_confirmation_dialog_and_stability(tmp_path):
    marker = tmp_path / "opened.txt"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "JARVIS_HOST_MARKER": str(marker)}
    proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "support" / "native_overlay_host.py")], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    report: dict = {}
    host_out: list[str] = []
    try:
        found: list[str] = []

        def pump():
            for line in proc.stdout:
                host_out.append(line.rstrip())
                m = re.search(r"HOST (http://127\.0\.0\.1:\d+/\?t=[\w-]+)", line)
                if m and not found:
                    found.append(m.group(1))

        threading.Thread(target=pump, daemon=True).start()
        end = time.monotonic() + 90
        while time.monotonic() < end and not found and proc.poll() is None:
            time.sleep(0.1)
        assert found, "Testhost startete nicht. Ausgabe:\n" + "\n".join(host_out[-30:])
        url = found[0]
        hwnd, box = find_window("JARVIS", 60)
        assert hwnd, "Overlay-Fenster erschien nicht. Ausgabe:\n" + "\n".join(host_out[-30:])
        width, height = box[2] - box[0], box[3] - box[1]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:                                               # Seite steht, wenn der Kern gezeichnet ist
            shot = grab(box, "host_before")
            if len({tuple(shot.rgb[i:i + 3]) for i in range(0, len(shot.rgb), 3 * 5)}) > 40:
                break
            time.sleep(2)
        # 1) Klick auf den Kern: der Server ruft den Rueckruf (Hauptfenster oeffnen), ausgeloest durch einen echten Mausklick im echten Fenster
        report["core_clicks"] = 0
        for attempt in range(4):                                                         # der erste Klick auf ein inaktives Fenster kann nur den Fokus setzen
            if attempt == 0:
                click(box[0] + width // 2, box[1] + width // 2 - 10 + int(height * 0.12))
            else:
                click(box[0] + width // 2, box[1] + int(height * (0.5 + 0.08 * attempt)))
            report["core_clicks"] += 1
            deadline = time.monotonic() + 4
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.2)
            if marker.exists():
                break
        report["core_click_opens_main"] = marker.exists()
        assert marker.exists(), "Klick auf den Kern oeffnete das Hauptfenster nicht (kein Rueckruf)"
        # 2) Freigabedialog im echten Fenster: sichtbar (goldener Rand), Escape lehnt ab (fail-closed)
        assert post_command(url, "submit_text", {"text": "!confirm"}, "nat1") == 200
        time.sleep(2.5)
        shot = grab(box, "host_dialog")
        gold = count_color(shot, lambda r, g, b: r > 200 and 150 < g < 230 and b < 90)
        report["dialog_gold_pixels"] = gold
        assert gold > 30, f"kein Freigabedialog im Fenster sichtbar (goldene Pixel: {gold})"
        user32().SetForegroundWindow(hwnd)
        time.sleep(0.5)
        user32().keybd_event(VK_ESCAPE, 0, 0, 0)
        time.sleep(0.1)
        user32().keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
        closed = wait_event(url, lambda e: e.get("type") == "confirmation_closed", 20)
        report["dialog_escape_outcome"] = (closed or {}).get("data", {}).get("outcome")
        assert closed and closed["data"]["outcome"] == "denied", f"Escape lehnte die Rueckfrage nicht ab: {closed}"
        # 3) Stabilitaet: Fenster besteht weiter, gleiche Groesse, Prozess laeuft, Not-Aus per Klick wirkt auch nach dem Dialog
        time.sleep(3)
        hwnd2, box2 = find_window("JARVIS", 5)
        report["still_open"] = bool(hwnd2) and proc.poll() is None
        assert hwnd2 and proc.poll() is None and (box2[2] - box2[0], box2[3] - box2[1]) == (width, height)
        click(box[0] + width // 2, box[1] + max(10, int(height * 0.1)))
        em = wait_event(url, lambda e: e.get("type") == "emergency" and e["data"].get("engaged") is True, 20)
        report["emergency_after_dialog"] = bool(em)
        assert em, "Not-Aus nach dem Dialog wirkte nicht"
        grab(box, "host_after")
    finally:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "native_host_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (EVIDENCE / "native_host_stdout.txt").write_text("\n".join(host_out), encoding="utf-8")
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
