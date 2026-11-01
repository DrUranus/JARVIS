"""Echte Windows-Integrationstests der bestehenden, rein lesenden UIA-Funktionen (kein neuer Schritt, kein Produktionscode, keine Aktion).

Nur Windows (der Windows-CI-Lauf ist der Nachweis; ein Linux-Lauf ist keiner). Fehlt unter Windows die Bibliothek oder das Fenster, schlaegt der Test fehl: kein Ueberspringen.
1. Das Tool `ui` ueber die echte Kette ToolRegistry -> PermissionEngine -> Controller -> echter UIA-Provider (Worker-Prozess) an einem echten Notepad-Fenster:
   windows, tree, find, Sperrliste, Notaus. Nur lesend; der Test beendet nur den von ihm selbst gestarteten Notepad-Prozess.
2. Ein echtes Passwortfeld (WinForms-Fenster aus PowerShell, nur von diesem Test gestartet): der Provider meldet `is_password` und kein Wert taucht irgendwo auf.
Auf jeder Plattform laufen die Strukturtests unten (nie ein Skip wegen fehlender Bibliothek, keine ausfuehrenden Aufrufe)."""
from __future__ import annotations

import ast
import base64
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
THIS = Path(__file__)
WINDOWS = sys.platform == "win32"
SECRET = "geheim-test-123"


def _walk(node):
    yield node
    for c in node.get("children", []) if isinstance(node, dict) else node.children:
        yield from _walk(c)


def _wait(fn, what: str, seconds: float = 90.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = fn()
        if found:
            return found
        time.sleep(1)
    raise AssertionError(f"{what}: nicht gefunden nach {seconds:g} s")


@pytest.mark.skipif(not WINDOWS, reason="UI Automation gibt es nur unter Windows; der Windows-CI-Lauf ist der Nachweis")
class TestToolOnARealWindow:
    @staticmethod
    def stack(tmp_path, **settings_kw):
        assert importlib.util.find_spec("pywinauto") is not None, "pywinauto fehlt: pip install -e .[dev] oder .[uia]; das ist ein Fehler, kein Skip"
        from computer_util import ONCE
        from jarvis.computer import ComputerBackend, ComputerController
        from jarvis.computer.policy import baseline_rules
        from jarvis.computer.providers.pywinauto_uia import create_uia_provider
        from jarvis.computer.providers.win32_windows import Win32Windows
        from jarvis.computer.tools import register_computer_tools
        from jarvis.config import ComputerSettings
        from jarvis.permissions import Policy, ScriptedConfirmation
        from jarvis.tools import ToolRegistry
        from secutil import make_engine
        tmp_path.mkdir(parents=True, exist_ok=True)
        engine, sink, _ws = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE] * 60))
        uia = create_uia_provider(call_timeout=60.0, max_calls=200)
        settings = ComputerSettings(enabled=True, uia_enabled=True, apps={}, use_default_apps=False, action_delay=0.0, **settings_kw)
        controller = ComputerController(ComputerBackend("win32", windows=Win32Windows(), ui=uia), settings, own_pids=())
        engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
        registry = ToolRegistry(engine)
        names = register_computer_tools(registry, controller)
        assert "ui" in names
        return registry, controller, uia, sink

    def test_the_ui_tool_reads_a_real_notepad_window_and_respects_blocks_and_the_halt(self, tmp_path):
        registry, controller, uia, sink = self.stack(tmp_path / "a")
        proc = subprocess.Popen(["notepad.exe"])
        try:
            def notepad():
                out = registry.execute("ui", action="windows")
                assert out.success, out.error
                return next((w for w in out.output if re.search(r"(?i)notepad|untitled", w["title"])), None)

            win = _wait(notepad, "Notepad-Fenster in ui action=windows")
            assert win["readable"] is True and win["process"].lower().startswith("notepad") and win["handle"] > 0
            assert uia.calls_used == 0, "die Fensterliste darf den UIA-Worker nicht brauchen"

            tree = registry.execute("ui", action="tree", window=win["handle"], max_depth=8, max_nodes=300)
            assert tree.success, (tree.error, tree.output)
            root = tree.output["tree"]
            nodes = list(_walk(root))
            assert tree.output["node_count"] == len(nodes) > 3 and root["rect"][2] > 0 and root["rect"][3] > 0
            assert {n["control_type"] for n in nodes} & {"Edit", "Document"}
            assert not any(n["is_password"] for n in nodes) and tree.output["window"]["handle"] == win["handle"]

            kind = next(n["control_type"] for n in nodes if n["control_type"] in ("Edit", "Document"))
            found = registry.execute("ui", action="find", window=win["handle"], control_type=kind, max_depth=8, max_nodes=300)
            assert found.success and found.output["count"] >= 1 and all(isinstance(m["children"], int) for m in found.output["matches"])
            before = uia.calls_used
            assert before == 2

            # eigene Sperre: dasselbe Fenster ist fuer ein anderes Regelwerk gesperrt -> RED, nie eine Rueckfrage, nie ein Worker-Aufruf
            r2, _c2, uia2, _s2 = self.stack(tmp_path / "b", blocked_titles=("notepad", "untitled"))
            try:
                blocked = r2.execute("ui", action="tree", window=win["handle"])
                assert not blocked.success and uia2.calls_used == 0 and uia2.workers_started == 0
                listed = r2.execute("ui", action="windows")
                assert next(w for w in listed.output if w["handle"] == win["handle"])["readable"] is False
            finally:
                uia2.shutdown()

            # Notaus des Controllers: weitere Lesezugriffe scheitern, der Worker wird beendet; nach resume geht es wieder
            controller.halt("test")
            halted = registry.execute("ui", action="tree", window=win["handle"])
            assert not halted.success and not uia.worker_running and uia.calls_used == before
            controller.resume()
            again = registry.execute("ui", action="tree", window=win["handle"], max_depth=2, max_nodes=20)
            assert again.success and again.output["node_count"] <= 20
        finally:
            uia.shutdown()
            proc.terminate()               # nur der von diesem Test selbst gestartete Notepad-Prozess

    def test_a_real_password_field_has_no_value_anywhere(self):
        assert importlib.util.find_spec("pywinauto") is not None, "pywinauto fehlt: pip install -e .[dev] oder .[uia]; das ist ein Fehler, kein Skip"
        from jarvis.computer.providers.pywinauto_uia import create_uia_provider
        from jarvis.computer.uia import UiLimits, UiQuery
        script = ("Add-Type -AssemblyName System.Windows.Forms; "
                  "$f = New-Object System.Windows.Forms.Form; $f.Text = 'JARVIS UIA Passwort-Test'; $f.Width = 420; $f.Height = 200; "
                  "$u = New-Object System.Windows.Forms.TextBox; $u.Name = 'user'; $u.Text = 'alice-sichtbar'; $u.Left = 10; $u.Top = 10; $u.Width = 300; "
                  "$p = New-Object System.Windows.Forms.TextBox; $p.Name = 'pass'; $p.UseSystemPasswordChar = $true; $p.Text = '" + SECRET + "'; $p.Left = 10; $p.Top = 50; $p.Width = 300; "
                  "$f.Controls.Add($u); $f.Controls.Add($p); [void]$f.ShowDialog()")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        proc = subprocess.Popen(["powershell.exe", "-NoProfile", "-Sta", "-NonInteractive", "-EncodedCommand", encoded], creationflags=subprocess.CREATE_NO_WINDOW)
        provider = create_uia_provider(call_timeout=60.0, max_calls=200)
        try:
            win = _wait(lambda: next((w for w in provider.list_windows() if "JARVIS UIA Passwort-Test" in w.title), None), "WinForms-Testfenster")
            snap = provider.describe(win.handle, UiLimits(max_depth=8, max_nodes=300))
            edits = [e for e in _walk(snap.root) if e.control_type.value == "Edit"]
            assert len(edits) >= 2, [(e.control_type.value, e.name, e.automation_id) for e in _walk(snap.root)]
            by_id = {e.automation_id: e for e in edits}
            assert by_id["pass"].is_password is True and by_id["user"].is_password is False
            found = provider.find(win.handle, UiQuery(control_type="Edit"), UiLimits(max_depth=8, max_nodes=300))
            blob = json.dumps(snap.info(), default=str) + json.dumps(found.info(), default=str) + repr(snap) + repr(found)
            assert SECRET not in blob and all(e.value is None for e in edits if e.is_password)
            assert next(m for m in found.matches if m.automation_id == "pass").is_password is True
        finally:
            provider.shutdown()
            proc.terminate()               # nur der von diesem Test selbst gestartete PowerShell-Prozess


# ---- auf jeder Plattform: Struktur ----------------------------------------------------------------------------------------------------------
def test_the_real_tests_never_skip_for_a_missing_library_and_never_act():
    src = THIS.read_text(encoding="utf-8")
    tree = ast.parse(src)
    skips = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("skipif", "skip", "importorskip", "xfail")]
    assert len(skips) == 1 and skips[0].attr == "skipif"                      # genau eine Bedingung: die Plattform
    marks = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "skipif"]
    assert len(marks) == 1 and ast.unparse(marks[0].args[0]) == "not WINDOWS"
    acting = {"click", "click_input", "invoke", "type_keys", "send_keys", "set_edit_text", "set_text", "kill"}
    stopped = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            assert n.func.attr not in acting, n.func.attr
            if n.func.attr == "terminate":
                stopped.append(ast.unparse(n.func.value))
    assert stopped == ["proc", "proc"]               # nur die selbst gestarteten Testprozesse (Notepad, PowerShell-Testfenster)
