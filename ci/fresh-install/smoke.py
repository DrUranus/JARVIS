"""Frischinstallations-Rauchtest: laeuft NACH `pip install` in einer neuen venv, ausserhalb des Quellbaums.

Prueft: Import + Version, CLI `jarvis --version`, `jarvis doctor` (Exit 0/1 erlaubt, alles andere ist ein Absturz), kontrollierter Start/Stopp von `jarvis-cc`
(nur Loopback, Ausgabe der URL, Seite antwortet, Port nach dem Stopp geschlossen). Keine Netzwerkzugriffe ausser 127.0.0.1, keine Schluessel, nichts wird aktiviert
ausser dem Control Center in einem temporaeren Arbeitsverzeichnis. Jeder Schritt schreibt eine klare Zeile `[OK]`/`[FEHLER]`; Exit-Code 0 nur, wenn alles bestanden ist."""
from __future__ import annotations

import http.client
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

FAILED: list[str] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK' if ok else 'FEHLER'}] {name}" + (f" - {detail}" if detail else ""), flush=True)
    if not ok:
        FAILED.append(name)


def run(args: list[str], env: dict, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def script(name: str) -> str:
    exe = shutil.which(name)
    if exe:
        return exe
    suffix = ".exe" if os.name == "nt" else ""
    cand = Path(sys.executable).parent / (name + suffix)
    return str(cand) if cand.exists() else name


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="jarvis-fresh-"))
    (work / "ws").mkdir()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "JARVIS_WORKSPACE": str(work / "ws"), "JARVIS_LOG_DIR": str(work / "logs"),
           "JARVIS_MEMORY_PATH": str(work / "m.db")}
    for key in [k for k in env if k.endswith("_API_KEY")]:
        env.pop(key)                                                                       # keine echten Schluessel im Rauchtest
    print(f"Python {sys.version.split()[0]} auf {sys.platform}; Arbeitsverzeichnis {work}", flush=True)
    os.chdir(work)                                                                         # nicht im Quellbaum: es zaehlt die installierte Fassung
    try:
        import jarvis
        step("Import jarvis", True, f"{jarvis.__version__} aus {Path(jarvis.__file__).parent}")
    except Exception as exc:                                                               # noqa: BLE001 - jeder Importfehler ist ein klarer Fehlschlag
        step("Import jarvis", False, repr(exc))
        return 1
    for mod in ("jarvis.interface.cli", "jarvis.control_center.launcher", "jarvis.bootstrap", "jarvis.interface.doctor"):
        try:
            __import__(mod)
            step(f"Import {mod}", True)
        except Exception as exc:                                                           # noqa: BLE001
            step(f"Import {mod}", False, repr(exc))
    res = run([script("jarvis"), "--version"], env)
    step("jarvis --version", res.returncode == 0 and "jarvis" in res.stdout, (res.stdout + res.stderr).strip()[:200])
    res = run([script("jarvis"), "doctor"], env)
    print(res.stdout[-3000:], flush=True)
    step("jarvis doctor (Exit 0 oder 1, kein Absturz)", res.returncode in (0, 1) and "Traceback" not in res.stderr, f"Exit {res.returncode} {res.stderr.strip()[-300:]}")
    cc_env = {**env, "JARVIS_AGENTS_ENABLED": "true", "JARVIS_GOALS_ENABLED": "true", "JARVIS_ASSISTANT_ENABLED": "true", "JARVIS_CONTROL_CENTER_ENABLED": "true", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([script("jarvis-cc")], env=cc_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines: list[str] = []
    found: list[str] = []

    def pump() -> None:
        for line in proc.stdout:                                                           # type: ignore[union-attr]
            lines.append(line)
            m = re.search(r"(http://127\.0\.0\.1:(\d+)/\?t=[\w-]+)", line)
            if m and not found:
                found.extend([m.group(1), m.group(2)])

    threading.Thread(target=pump, daemon=True).start()
    end = time.monotonic() + 60
    while time.monotonic() < end and not found and proc.poll() is None:
        time.sleep(0.1)
    if not found:                                                                          # Diagnose: Prozessstatus und Ausgabe, bevor aufgeraeumt wird
        print(f"jarvis-cc Exit-Status {proc.poll()}; Ausgabe bisher:\n{''.join(lines)[-1500:]}", flush=True)
    step("jarvis-cc startet und nennt eine Loopback-URL", bool(found), "" if found else "keine URL in 60 s")
    if found:
        port = int(found[1])
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/" + found[0].split("/", 3)[3], headers={"Host": f"127.0.0.1:{port}"})
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", "replace")
            conn.close()
            step("Control Center liefert die Seite (HTTP 200, NEXUS)", resp.status == 200 and "JARVIS" in body, f"HTTP {resp.status}")
        except OSError as exc:
            step("Control Center liefert die Seite (HTTP 200, NEXUS)", False, repr(exc))
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)
        time.sleep(0.5)
        step("jarvis-cc beendet, Port wieder geschlossen", proc.poll() is not None and not port_open(port))
    else:
        proc.kill()
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nErgebnis: {'BESTANDEN' if not FAILED else 'NICHT BESTANDEN: ' + ', '.join(FAILED)}", flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
