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
    with mss.mss() as sct:
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
        time.sleep(3)                                                                    # Seite laden, Kern zeichnen
        shot = grab(box, "overlay_before")
        pixels = {tuple(shot.rgb[i:i + 3]) for i in range(0, len(shot.rgb), 3 * 7)}
        report["distinct_colors"] = len(pixels)
        assert len(pixels) > 40, "das Overlay zeigt keinen gezeichneten Kern (nur Einheitsfarbe)"
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
