"""Isolierter, rein lesender Windows-Kompatibilitaetstest fuer pywinauto 0.6.9 (laeuft nur in der CI in einer temporaeren Umgebung, nicht Teil von JARVIS).

Geprueft wird nacheinander: Python-Version gleich der Erwartung, Windows, installierte Versionen gleich den Pins, Import, COM/UIA-Wurzel, Aufzaehlen der Fenster, ein echtes
Notepad-Fenster finden, es lesen (Titel, Klasse, Typ, Rechteck, Baum, IsPassword), Lesen in einem eigenen Thread (Worker-Prozess) und als Hinweis aus einem fremden Thread. Jede Pruefung, die nicht gelingt, ist ein Fehler; es gibt
keinen Ausweg ueber Ueberspringen. Nur Lesen: keine Eingaben, keine Klicks, keine Beendigung von Prozessen. Gestartet wird ausschliesslich das Programm, dessen Fenster gelesen wird.
Umgebungsvariablen: EXPECT_PYTHON (z. B. 3.13), UIA_COMPAT_WINDOW_RE, UIA_COMPAT_WAIT, UIA_COMPAT_NO_START (nur Gegenproben), UIA_COMPAT_PROGRAM, UIA_COMPAT_OUT."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from importlib import metadata
from pathlib import Path

PINS = {"pywinauto": "0.6.9", "six": "1.17.0", "comtypes": "1.4.17", "pywin32": "312"}
DEFAULT_WINDOW_RE = r"(?i)notepad|untitled"
# Aufrufe, die etwas veraendern wuerden; der Test enthaelt keinen davon (Teile zusammengesetzt, damit diese Liste sich nicht selbst findet)
FORBIDDEN = tuple("".join(parts) for parts in (
    (".", "click"), (".", "double_", "click"), ("type_", "keys"), ("send_", "keys"), (".", "kill"), ("termi", "nate"), ("task", "kill"), ("set_", "edit_text"),
    ("set_", "text"), (".", "invoke("), ("Send", "Input"), ("mouse", "_event"), ("Applic", "ation("), (".", "close("), ("os.", "system"),
))


def forbidden_calls(source: str) -> list[str]:
    return [token for token in FORBIDDEN if token in source]


def python_problem(expected: str | None, version_info) -> str | None:
    if not expected or not re.fullmatch(r"3\.\d{1,2}", expected):
        return f"EXPECT_PYTHON fehlt oder ist ungueltig: {expected!r}"
    actual = f"{version_info[0]}.{version_info[1]}"
    return None if actual == expected else f"Python {actual} statt der erwarteten Version {expected}"


def match_title(titles: list[str], regex: str) -> str | None:
    return next((t for t in titles if t and re.search(regex, t)), None)


def verdict(results: list[dict]) -> int:
    if not results:
        return 1                                    # kein Ergebnis ist nie ein Erfolg
    return 1 if any(r["blocking"] and not r["ok"] for r in results) else 0


# ---- Pruefungen (jede wirft bei Misserfolg) ---------------------------------------------------------------------------------------------
def check_python(env, ctx):
    problem = python_problem(env.get("EXPECT_PYTHON"), sys.version_info)
    if problem:
        raise AssertionError(problem)
    return f"Python {sys.version.split()[0]}"


def check_platform(env, ctx):
    if sys.platform != "win32":
        raise AssertionError(f"Plattform {sys.platform} statt win32")
    return "win32"


def check_versions(env, ctx):
    got = {}
    for name, version in PINS.items():
        got[name] = metadata.version(name)
        if got[name] != version:
            raise AssertionError(f"{name} {got[name]} statt {version}")
    return ", ".join(f"{k} {v}" for k, v in got.items())


def check_imports(env, ctx):
    import comtypes  # noqa: F401
    import pythoncom  # noqa: F401
    import pywinauto
    import six  # noqa: F401
    import win32api  # noqa: F401
    return f"pywinauto {getattr(pywinauto, '__version__', '?')}, comtypes, pythoncom, win32api, six"


def check_com_uia(env, ctx):
    from pywinauto.uia_element_info import UIAElementInfo
    root = UIAElementInfo()                          # Wurzelelement des Desktops ueber IUIAutomation (COM)
    children = root.children()
    if not children:
        raise AssertionError("UIA-Wurzel ohne Kindelemente")
    return f"Wurzel {root.control_type!r} mit {len(children)} Kindelementen"


def check_enumerate(env, ctx):
    from pywinauto import Desktop
    titles = [w.window_text() for w in Desktop(backend="uia").windows()]
    if not titles:
        raise AssertionError("keine Fenster aufgezaehlt")
    return f"{len(titles)} Fenster, Beispiele: {[t for t in titles if t][:5]}"


def check_window(env, ctx):
    from pywinauto import Desktop
    regex = env.get("UIA_COMPAT_WINDOW_RE") or DEFAULT_WINDOW_RE
    wait = float(env.get("UIA_COMPAT_WAIT") or 40)
    if env.get("UIA_COMPAT_NO_START") != "1":
        ctx["proc"] = subprocess.Popen([env.get("UIA_COMPAT_PROGRAM") or "notepad.exe"])
    deadline, titles = time.monotonic() + wait, []
    while True:
        wins = Desktop(backend="uia").windows()
        titles = []
        for w in wins:
            try:
                titles.append(w.window_text())
            except Exception:  # noqa: BLE001 - ein verschwundenes Fenster
                titles.append("")
        hit = match_title(titles, regex)
        if hit is not None:
            ctx["window"] = wins[titles.index(hit)]
            return f"Fenster gefunden: {hit!r}"
        if time.monotonic() >= deadline:
            raise AssertionError(f"kein Fenster passend zu {regex!r} nach {wait:g} s; sichtbar: {[t for t in titles if t][:8]}")
        time.sleep(1)


def check_read(env, ctx):
    win = ctx.get("window")
    if win is None:
        raise AssertionError("kein Fenster aus dem vorigen Schritt")
    info = win.element_info
    rect = win.rectangle()
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise AssertionError(f"leeres Rechteck {rect}")
    nodes = win.descendants()[:300]
    if not nodes:
        raise AssertionError("Fenster ohne Unterelemente")
    types = sorted({d.element_info.control_type for d in nodes})
    editor = next((d for d in nodes if d.element_info.control_type in ("Edit", "Document")), None)
    if editor is None:
        raise AssertionError(f"kein Edit/Document-Element; vorhandene Typen: {types}")
    password = editor.element_info.element.CurrentIsPassword
    if password:
        raise AssertionError("IsPassword ist wahr fuer das Textfeld")
    return (f"Titel {win.window_text()!r}, Typ {info.control_type!r}, Prozess {info.process_id}, {width}x{height}, aktiviert {win.is_enabled()}, "
            f"sichtbar {win.is_visible()}, {len(nodes)} Unterelemente, Typen {types[:8]}, Textfeld {editor.element_info.control_type!r} IsPassword={bool(password)}")


def check_dedicated_thread(env, ctx):
    """Unterstuetztes Muster: ein einziger Thread (nicht der Hauptthread) besitzt alle UIA-Aufrufe. Laeuft in einem eigenen Prozess, damit die UIA-Verbindung dort zum ersten
    Mal im Worker-Thread entsteht."""
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve())], env={**os.environ, **env, "UIA_COMPAT_MODE": "worker", "UIA_COMPAT_NO_START": "1"},
                          capture_output=True, text=True, timeout=150)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("UIA_COMPAT_WORKER ")), None)
    if line is None:
        raise AssertionError(f"keine Antwort des Worker-Prozesses (Exit {proc.returncode}): {proc.stderr[-300:]!r}")
    data = json.loads(line.split(" ", 1)[1])
    if not data.get("ok"):
        raise AssertionError(str(data.get("detail")))
    return str(data["detail"])


def check_cross_thread(env, ctx):
    """Hinweis, kein Fehler des Tests: Die im Hauptthread erzeugte UIA-Verbindung wird aus einem zweiten Thread benutzt (waehrend der Hauptthread wartet)."""
    out: dict = {}

    def worker():
        try:
            from pywinauto import Desktop
            out["titles"] = [w.window_text() for w in Desktop(backend="uia").windows()]
        except BaseException as exc:  # noqa: BLE001 - wird im Hauptthread gemeldet
            out["error"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(20)
    if thread.is_alive():
        raise AssertionError("Querzugriff aus einem zweiten Thread haengt (20 s): UIA-Aufrufe muessen in dem Thread bleiben, der die Verbindung erzeugt hat")
    if "error" in out:
        raise AssertionError(out["error"])
    return f"Querzugriff funktioniert, {len(out['titles'])} Fenster"


def main_worker() -> int:
    out: dict = {}

    def work():
        try:
            env, ctx = dict(os.environ), {}
            out.update(ok=True, detail=" | ".join([check_window(env, ctx), check_read(env, ctx)])[:500])
        except BaseException as exc:  # noqa: BLE001
            out.update(ok=False, detail=f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(float(os.environ.get("UIA_COMPAT_WORKER_TIMEOUT") or 90))
    if thread.is_alive():
        out = {"ok": False, "detail": "Worker-Thread haengt"}
    print("UIA_COMPAT_WORKER " + json.dumps(out))
    sys.stdout.flush()
    os._exit(0 if out.get("ok") else 1)          # hart beenden, auch wenn ein Thread haengt (Worker-Prozess der Pruefung)


def check_source(env, ctx):
    found = forbidden_calls(Path(__file__).read_text(encoding="utf-8"))
    if found:
        raise AssertionError(f"veraendernde Aufrufe im Test: {found}")
    return "keine Eingabe-, Klick- oder Beendigungsaufrufe im Testskript"


CHECKS = (
    ("python_version", check_python, True), ("platform", check_platform, True), ("versions", check_versions, True), ("imports", check_imports, True),
    ("com_uia_root", check_com_uia, True), ("enumerate", check_enumerate, True), ("window", check_window, True), ("read_window", check_read, True),
    ("dedicated_thread", check_dedicated_thread, True),
    ("cross_thread_reuse", check_cross_thread, False),                        # nur Hinweis: zeigt, dass die UIA-Verbindung an ihren Thread gebunden ist
    ("readonly_source", check_source, True),
)


def run_checks(env) -> list[dict]:
    results, ctx = [], {}
    for name, fn, blocking in CHECKS:
        try:
            ok, detail = True, fn(env, ctx)
        except BaseException as exc:  # noqa: BLE001 - jede Abweichung ist ein Fehlschlag, kein Absturz
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append({"name": name, "ok": ok, "blocking": blocking, "detail": str(detail)[:600]})
    return results


def main() -> int:
    if os.environ.get("UIA_COMPAT_MODE") == "worker":
        return main_worker()
    results = run_checks(dict(os.environ))
    for r in results:
        line = f"{'OK  ' if r['ok'] else ('FAIL' if r['blocking'] else 'HINT')} {r['name']}: {r['detail']}"
        print(line.encode("ascii", "replace").decode())
    out = os.environ.get("UIA_COMPAT_OUT") or "uia-compat-result.json"
    Path(out).write_text(json.dumps({"python": sys.version, "platform": sys.platform, "checks": results}, indent=2), encoding="utf-8")
    code = verdict(results)
    print(f"Gesamtergebnis: {'bestanden' if code == 0 else 'FEHLGESCHLAGEN'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
