"""Echte Windows-Integrationstests der UIA-Aktionen (Backlog-Schritt uia-actions) an einem echten Testfenster.

Nur Windows (der Windows-CI-Lauf ist der Nachweis; ein Linux-Lauf ist keiner). Fehlt unter Windows die Bibliothek oder das Fenster, schlaegt der Test fehl: kein Ueberspringen.
Das Testfenster ist eine kleine WinForms-Anwendung (jarvis_uia_testform.exe), die dieser Test selbst mit Add-Type uebersetzt und startet (kein Terminal-Prozess, damit die
Sperrliste nicht greift): Textfeld, Passwortfeld, Kontrollkaestchen, zwei Optionsfelder, Schaltflaeche (setzt ein Textfeld auf „geklickt“), Statustext.
Geprueft wird die echte Kette ToolRegistry -> PermissionEngine -> Controller -> echter UIA-Aktions-Provider (Worker-Prozess, pywinauto) und die Rueckmeldung ueber den
tatsaechlich gelesenen Zustand. Beendet wird nur der vom Test selbst gestartete Prozess. Auf jeder Plattform laufen die Strukturtests (kein Skip wegen fehlender Bibliothek)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = sys.platform == "win32"
TITLE = "JARVIS Aktionen-Pruefung"
SECRET = "geheim-test-123"

CSHARP = r'''
using System;
using System.Windows.Forms;
public class TestForm : Form
{
    [STAThread]
    public static void Main() { Application.EnableVisualStyles(); Application.Run(new TestForm()); }
    public TestForm()
    {
        Text = "JARVIS Aktionen-Pruefung"; Width = 480; Height = 360;
        TextBox user = new TextBox(); user.Name = "user"; user.Text = "alt"; user.Left = 10; user.Top = 10; user.Width = 300;
        TextBox pass = new TextBox(); pass.Name = "pass"; pass.UseSystemPasswordChar = true; pass.Text = "geheim-test-123"; pass.Left = 10; pass.Top = 50; pass.Width = 300;
        CheckBox news = new CheckBox(); news.Name = "news"; news.Text = "Newsletter"; news.Left = 10; news.Top = 90; news.Width = 200;
        RadioButton a = new RadioButton(); a.Name = "optA"; a.Text = "Option A"; a.Left = 10; a.Top = 120; a.Width = 100;
        RadioButton b = new RadioButton(); b.Name = "optB"; b.Text = "Option B"; b.Left = 120; b.Top = 120; b.Width = 100;
        Label status = new Label(); status.Name = "status"; status.Text = "bereit"; status.Left = 10; status.Top = 200; status.Width = 300;
        Button ok = new Button(); ok.Name = "ok"; ok.Text = "Weiter"; ok.Left = 10; ok.Top = 160; ok.Width = 100;
        ok.Click += delegate(object s, EventArgs e) { status.Text = "geklickt"; };
        Controls.AddRange(new Control[] { user, pass, news, a, b, ok, status });
    }
}
'''


def _wait(fn, what: str, seconds: float = 90.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = fn()
        if found:
            return found
        time.sleep(1)
    raise AssertionError(f"{what}: nicht gefunden nach {seconds:g} s")


def build_test_form(directory: Path) -> Path:
    exe = directory / "jarvis_uia_testform.exe"
    (directory / "form.cs").write_text(CSHARP, encoding="utf-8")
    script = directory / "build.ps1"
    script.write_text("$src = Get-Content -Raw -Encoding UTF8 '" + str(directory / "form.cs") + "'\n"
                      "Add-Type -TypeDefinition $src -ReferencedAssemblies System.Windows.Forms,System.Drawing -OutputAssembly '" + str(exe) + "' -OutputType WindowsApplication\n",
                      encoding="utf-8")
    done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True, text=True, timeout=180)
    assert exe.exists(), f"Testfenster konnte nicht uebersetzt werden: {done.stdout[-500:]} {done.stderr[-500:]}"
    return exe


@pytest.mark.skipif(not WINDOWS, reason="UI Automation gibt es nur unter Windows; der Windows-CI-Lauf ist der Nachweis")
class TestActionsOnARealWindow:
    @staticmethod
    def stack(tmp_path):
        assert importlib.util.find_spec("pywinauto") is not None, "pywinauto fehlt: pip install -e .[dev] oder .[uia]; das ist ein Fehler, kein Skip"
        from computer_util import ONCE
        from jarvis.computer import ComputerBackend, ComputerController
        from jarvis.computer.policy import baseline_rules
        from jarvis.computer.providers.pywinauto_uia import create_uia_provider
        from jarvis.computer.providers.pywinauto_uia_actions import create_uia_action_provider
        from jarvis.computer.providers.win32_windows import Win32Windows
        from jarvis.computer.tools import register_computer_tools
        from jarvis.config import ComputerSettings
        from jarvis.permissions import Policy, ScriptedConfirmation
        from jarvis.tools import ToolRegistry
        from secutil import make_engine
        tmp_path.mkdir(parents=True, exist_ok=True)
        prompts = ScriptedConfirmation([ONCE] * 80)
        engine, sink, _ws = make_engine(tmp_path, confirmation=prompts)
        reader, actor = create_uia_provider(call_timeout=60.0, max_calls=300), create_uia_action_provider(call_timeout=60.0, max_calls=300)
        settings = ComputerSettings(enabled=True, uia_enabled=True, uia_actions_enabled=True, apps={}, use_default_apps=False, action_delay=0.0)
        controller = ComputerController(ComputerBackend("win32", windows=Win32Windows(), ui=reader, ui_actions=actor), settings, own_pids=())
        engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
        registry = ToolRegistry(engine)
        names = register_computer_tools(registry, controller)
        assert "ui" in names and "ui_act" in names
        return registry, controller, reader, actor, sink, prompts

    def test_the_actions_work_on_a_real_window_and_report_the_state_that_was_read(self, tmp_path):
        registry, controller, reader, actor, sink, prompts = self.stack(tmp_path / "engine")
        exe = build_test_form(tmp_path)
        proc = subprocess.Popen([str(exe)])
        try:
            def window():
                out = registry.execute("ui", action="windows")
                assert out.success, out.error
                return next((w for w in out.output if w["title"] == TITLE), None)

            win = _wait(window, "Testfenster in ui action=windows")
            h = win["handle"]
            assert win["readable"] is True and win["process"].lower().startswith("jarvis_uia_testform")

            def act(**kw):
                return registry.execute("ui_act", window=h, **kw)

            # set_value: Wert setzen, danach den Wert lesen
            out = act(action="set_value", automation_id="user", value="neuer Wert")
            assert out.success, (out.error, out.output)
            assert out.output["verified"] is True and out.output["performed"] is True and "neuer Wert" not in json.dumps(out.output)

            # toggle: off -> on, im Zustand nach der Aktion gelesen
            out = act(action="toggle", automation_id="news")
            assert out.success, (out.error, out.output)
            assert out.output["verified"] is True and out.output["state_before"]["toggle_state"] == "off" and out.output["state_after"]["toggle_state"] == "on"

            # select: Optionsfeld
            out = act(action="select", automation_id="optB")
            assert out.success, (out.error, out.output)
            assert out.output["verified"] is True and out.output["state_after"]["selected"] is True

            # focus: die Meldung muss dem gelesenen Fokuszustand entsprechen (ehrlich, auch wenn das Fenster nicht im Vordergrund ist)
            out = act(action="focus", automation_id="user")
            assert out.output["verified"] in (True, False) and out.success is out.output["verified"], (out.error, out.output)

            # invoke: Schaltflaeche; Wirkung ueber eine getrennte Lesung (ui find) belegt
            out = act(action="invoke", automation_id="ok")
            assert out.success, (out.error, out.output)
            assert out.output["verified"] is None and out.output["performed"] is True
            _wait(lambda: registry.execute("ui", action="find", window=h, name_equals="geklickt").output.get("count"), "Statustext „geklickt“", 30)

            # jede Aktion wurde bestaetigt (YELLOW)
            assert len(prompts.requests) >= 5 and all(r.level.value == "yellow" for r in prompts.requests if r.tool == "ui_act")

            # Passwortfeld: immer abgelehnt, keine Rueckfrage, kein Aktions-Aufruf
            before_calls, before_prompts = actor.calls_used, len(prompts.requests)
            for kw in ({"action": "set_value", "value": "x"}, {"action": "focus"}, {"action": "invoke"}):
                denied = act(automation_id="pass", **kw)
                assert not denied.success
            assert actor.calls_used == before_calls and len(prompts.requests) == before_prompts
            assert SECRET not in json.dumps([e.to_dict() for e in sink.events]) + "".join(r.to_text() + json.dumps(dict(r.context)) for r in prompts.requests)

            # Notaus: weitere Aktionen scheitern, der Worker wird beendet; nach resume geht es wieder
            controller.halt("test")
            halted = act(action="toggle", automation_id="news")
            assert not halted.success and not actor.worker_running
            controller.resume()
            again = act(action="toggle", automation_id="news")
            assert again.success and again.output["verified"] is True and again.output["state_after"]["toggle_state"] == "off"
        finally:
            reader.shutdown()
            actor.shutdown()
            proc.terminate()               # nur der vom Test selbst gestartete Prozess

    def test_blocked_windows_never_reach_the_action_worker(self, tmp_path):
        registry, controller, reader, actor, sink, prompts = self.stack(tmp_path / "engine")
        exe = build_test_form(tmp_path)
        proc = subprocess.Popen([str(exe)])
        try:
            win = _wait(lambda: next((w for w in registry.execute("ui", action="windows").output if w["title"] == TITLE), None), "Testfenster")
            from jarvis.computer import ComputerBackend, ComputerController
            from jarvis.computer.providers.win32_windows import Win32Windows
            from jarvis.config import ComputerSettings
            locked = ComputerController(ComputerBackend("win32", windows=Win32Windows(), ui=reader, ui_actions=actor),
                                        ComputerSettings(enabled=True, uia_enabled=True, uia_actions_enabled=True, apps={}, use_default_apps=False, blocked_titles=("aktionen-pruefung",)),
                                        own_pids=())
            plan = locked.plan_ui_act("toggle", window=win["handle"], automation_id="news")
            assert plan.blocked and actor.calls_used == 0 and actor.workers_started == 0
        finally:
            reader.shutdown()
            actor.shutdown()
            proc.terminate()


def test_the_windows_test_never_skips_for_a_missing_library_and_uses_no_input_tools():
    text = Path(__file__).read_text(encoding="utf-8")
    marker = "pytest.mark." + "skipif(not WINDOWS"
    assert text.count(marker) == 1 and ("import" + "orskip") not in text and ("pytest." + "skip(") not in text
    assert ("import " + "pyautogui") not in text and ("Application" + "(") not in text and ("click" + "_input") not in text
