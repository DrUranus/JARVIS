"""Ende-zu-Ende-Test (Backlog-Schritt uia-windows-e2e): klassisches Notepad, gesteuert nur ueber den kontrollierten Weg.

Kette: ToolRegistry.execute -> PermissionEngine (jede Aktion YELLOW, ScriptedConfirmation) -> ComputerController -> echte Provider (Win32, pywinauto-Worker).
Ablauf: Notepad per `app` starten, Baum per `ui` lesen, Text per UIA-Wertmuster (`ui_act set_value`) setzen, Ergebnis per `ui find` lesen, Fenster per `window close` schliessen.
Nur Windows (der Windows-CI-Lauf ist der Nachweis; ein Linux-Lauf ist keiner). Fehlt unter Windows die Bibliothek oder ein Fenster, schlaegt der Test fehl: kein Ueberspringen.
Ist kein interaktiver Desktop verfuegbar (kein Fenster erscheint), schlaegt er mit einer klaren Meldung fehl; nichts wird abgeschwaecht.
Harmlos: nur der Text unten, keine echten Daten oder Konten; nichts wird gespeichert. Aufgeraeumt wird nur, was dieser Test selbst gestartet hat (neue Notepad-Prozesse)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

WINDOWS = sys.platform == "win32"
TEXT = "JARVIS UIA Ende-zu-Ende-Pruefung 123"
NO_DESKTOP = "kein interaktiver Desktop: nach dem Start erscheint kein Notepad-Fenster (Schritt blockiert, nichts wird abgeschwaecht)"


def wait_for(fn, what: str, seconds: float = 60.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = fn()
        if found:
            return found
        time.sleep(0.5)
    raise AssertionError(f"{what}: nicht gefunden nach {seconds:g} s")


def notepad_windows(registry) -> list[dict]:
    out = registry.execute("ui", action="windows")
    assert out.success, out.error
    return [w for w in out.output if str(w["process"]).lower() == "notepad.exe"]


@pytest.mark.skipif(not WINDOWS, reason="UI Automation gibt es nur unter Windows; der Windows-CI-Lauf ist der Nachweis")
class TestNotepadEndToEnd:
    def test_launch_read_set_text_read_back_and_close_notepad(self, tmp_path):
        assert importlib.util.find_spec("pywinauto") is not None, "pywinauto fehlt: pip install -e .[dev] oder .[uia]; das ist ein Fehler, kein Skip"
        from computer_util import ONCE
        from jarvis.computer import ComputerBackend, ComputerController
        from jarvis.computer.policy import baseline_rules
        from jarvis.computer.providers.pywinauto_uia import create_uia_provider
        from jarvis.computer.providers.pywinauto_uia_actions import create_uia_action_provider
        from jarvis.computer.providers.subprocess_apps import SubprocessLauncher
        from jarvis.computer.providers.win32_windows import Win32Windows
        from jarvis.computer.tools import register_computer_tools
        from jarvis.config import ComputerSettings
        from jarvis.permissions import Policy, ScriptedConfirmation
        from jarvis.tools import ToolRegistry
        from secutil import make_engine

        tmp_path.mkdir(parents=True, exist_ok=True)
        prompts = ScriptedConfirmation([ONCE] * 40)
        engine, sink, _ws = make_engine(tmp_path, confirmation=prompts)
        windows = Win32Windows()
        reader, actor = create_uia_provider(call_timeout=60.0, max_calls=300), create_uia_action_provider(call_timeout=60.0, max_calls=300)
        # Standard-Alias „notepad“ (use_default_apps): der vorhandene, kontrollierte Startweg; keine ungelisteten Programme
        settings = ComputerSettings(enabled=True, uia_enabled=True, uia_actions_enabled=True, apps={}, use_default_apps=True, action_delay=0.0)
        controller = ComputerController(ComputerBackend("win32", windows=windows, apps=SubprocessLauncher(), ui=reader, ui_actions=actor), settings, own_pids=())
        engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
        registry = ToolRegistry(engine)
        names = register_computer_tools(registry, controller)
        assert {"app", "ui", "ui_act", "window"} <= set(names)

        before = {w["handle"] for w in notepad_windows(registry)}
        known_pids = {w.pid for w in windows.list_windows() if w.process.lower() == "notepad.exe"}
        launched_pid = None
        try:
            started = registry.execute("app", app="notepad")
            assert started.success, (started.error, started.output)
            launched_pid = started.output.get("pid")

            def new_window():
                return next((w for w in notepad_windows(registry) if w["handle"] not in before), None)

            try:
                win = wait_for(new_window, "neues Notepad-Fenster", 60.0)
            except AssertionError as exc:
                raise AssertionError(f"{NO_DESKTOP}: {exc}") from None
            h = win["handle"]
            assert win["readable"] is True

            # Baum lesen: ein Textfeld (Edit oder Document) muss vorhanden sein
            tree = registry.execute("ui", action="tree", window=h)
            assert tree.success, tree.error
            assert tree.output["node_count"] > 1

            def editor():
                for kind in ("Edit", "Document"):
                    found = registry.execute("ui", action="find", window=h, control_type=kind)
                    assert found.success, found.error
                    if found.output["count"] == 1:
                        return found.output["matches"][0]
                return None

            field = wait_for(editor, "Textfeld des Editors", 30.0)
            selector = {"automation_id": field["automation_id"]} if field["automation_id"] else {"control_type": field["control_type"], "name_equals": field["name"]}
            selector.setdefault("control_type", field["control_type"])

            # Text per UIA-Wertmuster setzen (YELLOW, bestaetigt); die Meldung enthaelt den Text nicht
            done = registry.execute("ui_act", action="set_value", window=h, value=TEXT, **selector)
            assert done.success, (done.error, done.output)
            assert done.output["verified"] is True and done.output["performed"] is True and TEXT not in json.dumps(done.output)

            # Ergebnis unabhaengig lesen
            back = registry.execute("ui", action="find", window=h, **selector)
            assert back.success and back.output["count"] == 1, (back.error, back.output)
            # `ui find` liest absichtlich keine Werte (siehe uia_worker); der Wert wird ueber den Lese-Zustand des Aktions-Providers (UiState) geprueft
            from jarvis.computer.uia import ControlType
            from jarvis.computer.uia_actions import UiTarget
            hit = back.output["matches"][0]
            state = actor.read_state(h, UiTarget(runtime_id=hit["runtime_id"], name=hit["name"], control_type=ControlType(hit["control_type"]), automation_id=hit["automation_id"]))
            assert state.value == TEXT

            # Jede Aktion erfordert YELLOW-Freigabe. Der Wert darf in der bewussten
            # Bestaetigungsvorschau erscheinen, nicht aber im Audit-Journal.
            assert prompts.requests and all(r.level.value == "yellow" for r in prompts.requests)
            assert {r.tool for r in prompts.requests} >= {"app", "ui", "ui_act"}
            assert TEXT not in json.dumps([e.to_dict() for e in sink.events])

            # Fenster schliessen (sanft wie das X); Notepad fragt wegen des geaenderten Textes ggf. nach: „Nicht speichern“ ueber denselben Weg
            closed = registry.execute("window", action="close", handle=h)
            assert closed.success, (closed.error, closed.output)

            def gone() -> bool:
                current = notepad_windows(registry)
                if all(w["handle"] != h for w in current):
                    return True
                for dialog in (w for w in current if w["handle"] not in before and w["handle"] != h):
                    buttons = registry.execute("ui", action="find", window=dialog["handle"], control_type="Button")
                    if not buttons.success:
                        continue
                    for b in buttons.output["matches"]:
                        label = str(b["name"]).lower()
                        if "save" in label and ("don" in label or "nicht" in label):          # „Don't Save“ / „Nicht speichern“
                            registry.execute("ui_act", action="invoke", window=dialog["handle"], control_type="Button", name_equals=b["name"])
                return False

            wait_for(gone, "geschlossenes Notepad-Fenster", 30.0)
        finally:
            reader.shutdown()
            actor.shutdown()
            # Aufraeumen: nur Prozesse, die dieser Test selbst gestartet hat (neue Notepad-Prozesse und die gemeldete PID)
            own = {w.pid for w in windows.list_windows() if w.process.lower() == "notepad.exe" and w.pid not in known_pids}
            if isinstance(launched_pid, int) and launched_pid not in known_pids:
                own.add(launched_pid)
            for pid in own:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
        leftover = [p for p in own if any(w.pid == p for w in windows.list_windows())]
        assert not leftover, f"Notepad-Prozesse des Tests laufen noch: {leftover}"


def test_the_notepad_test_never_skips_for_a_missing_library_and_uses_no_raw_input():
    text = Path(__file__).read_text(encoding="utf-8")
    marker = "pytest.mark." + "skipif(not WINDOWS"
    assert text.count(marker) == 1 and ("import" + "orskip") not in text and ("pytest." + "skip(") not in text
    assert ("import " + "pyautogui") not in text and ("Application" + "(") not in text and ("click" + "_input") not in text
    assert ('execute("key' + 'board"') not in text and ('execute("mo' + 'use"') not in text       # Text nur ueber das UIA-Muster, nie per Tastatur oder Maus


def test_the_test_stays_on_the_controlled_path_and_cleans_up():
    text = Path(__file__).read_text(encoding="utf-8")
    assert "registry.execute(" in text and "taskkill" in text and "known_pids" in text      # Aufraeumen nur eigener Prozesse
    assert "ui_act" in text and "set_value" in text
