"""NEXUS-Einrichtungs- und Diagnosebereich (E2): nur lesend, Schluessel nur gesetzt/nicht gesetzt, deutsche Hinweise, nichts wird eingeschaltet.

Simulierte Diagnoseergebnisse (find_spec/env/Einstellungen injiziert), echter Server und echter Kern fuer die Verdrahtung, Node-DOM fuer die Anzeige. Kein Netzwerk."""
from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import jarvis.control_center as cc
from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.control_center.launcher import build_server
from jarvis.control_center.server import ControlCenterServer
from jarvis.control_center.setup_view import build_report
from jarvis.control_center.views import ReadViews, ViewError
from jarvis.ui_contract import FakeUiBackend
from test_computer_integration import env_for

WEB = Path(cc.__file__).parent / "web"
HARNESS = Path(__file__).parent / "support" / "cc_dom_harness.js"
NODE = shutil.which("node")
SECRET = "sk-TESTSECRETVALUE1234567890abcdef"


def finder(missing=()):
    return lambda name: None if name in missing else object()


def core_settings(tmp_path, env_extra=None, **flags):
    env = env_for(tmp_path, **flags)
    s = load_settings(env=env)
    return build_core(s), s


def comp(rep, name):
    return next(c for c in rep["components"] if c["name"] == name)


# ---- Bericht aus simulierten Diagnoseergebnissen ----------------------------------------------------------------------------------------------
def test_defaults_report_python_version_install_status_and_off_components(tmp_path):
    core, s = core_settings(tmp_path)
    rep = build_report(core, s, env={}, find_spec=finder())
    assert re.fullmatch(r"3\.\d+\.\d+", rep["python"]) and rep["platform"] and rep["jarvis"]
    assert comp(rep, "Sprachmodell")["state"] == "hint" and "Testmodus" in comp(rep, "Sprachmodell")["text"]
    assert comp(rep, "Sprache")["state"] == "off" and "Konsole" in comp(rep, "Sprache")["text"]
    assert comp(rep, "Browser")["state"] == "off" and comp(rep, "Webrecherche")["state"] == "off" and comp(rep, "Dateien und Office")["state"] == "off"
    assert comp(rep, "Agenten")["state"] == "off" and rep["agents"] == []
    assert rep["security"] == {"mode": "standard", "confirmation": "cli"} and "schaltet nichts ein" in rep["note"]


def test_missing_components_are_named_with_a_german_fix_and_nothing_is_enabled(tmp_path):
    core, s = core_settings(tmp_path, JARVIS_VOICE_STT_PROVIDER="mock", JARVIS_BROWSER_ENABLED="true", JARVIS_RESEARCH_ENABLED="true", JARVIS_RESEARCH_SEARCH_ENABLED="true",
                            JARVIS_AGENTS_ENABLED="true")
    before = (s.browser.enabled, s.research.search_enabled, s.files.enabled, s.computer.enabled, s.security.mode, s.security.confirmation)
    rep = build_report(core, s, env={}, find_spec=finder(missing=("sounddevice", "playwright", "webview")))
    assert comp(rep, "Sprache")["state"] == "hint" and "sounddevice" in comp(rep, "Sprache")["text"] and '".[voice]"' in comp(rep, "Sprache")["text"]
    assert comp(rep, "Browser")["state"] == "hint" and "playwright install" in comp(rep, "Browser")["text"]
    assert comp(rep, "Webrecherche")["state"] == "hint" and "BRAVE_SEARCH_API_KEY" in comp(rep, "Webrecherche")["text"]
    assert comp(rep, "Mini-Overlay")["state"] == "off" and ".[ui]" in comp(rep, "Mini-Overlay")["text"]
    assert (s.browser.enabled, s.research.search_enabled, s.files.enabled, s.computer.enabled, s.security.mode, s.security.confirmation) == before      # nichts geschaltet


def test_api_keys_are_only_set_or_not_set_never_the_value(tmp_path):
    core, s = core_settings(tmp_path, JARVIS_RESEARCH_ENABLED="true", JARVIS_RESEARCH_SEARCH_ENABLED="true")
    env = {"BRAVE_SEARCH_API_KEY": SECRET, "OPENAI_API_KEY": SECRET + "x", "JARVIS_LLM_API_KEY": ""}
    rep = build_report(core, s, env=env, find_spec=finder())
    blob = json.dumps(rep, ensure_ascii=False)
    assert SECRET not in blob and "TESTSECRETVALUE" not in blob
    assert rep["keys"]["OPENAI_API_KEY"] is True and rep["keys"]["JARVIS_LLM_API_KEY"] is False
    assert comp(rep, "Webrecherche")["state"] == "ok" and "gesetzt" in comp(rep, "Webrecherche")["text"]


def test_agent_status_with_reasons_is_listed(tmp_path):
    core, s = core_settings(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_FILES_ENABLED="true")
    rep = build_report(core, s, env={}, find_spec=finder())
    by = {a["id"]: a for a in rep["agents"]}
    assert by["coding"]["status"] == "DISABLED" and "not available" in by["coding"]["reason"] and by["research"]["status"] == "DISABLED"
    assert comp(rep, "Agenten")["state"] in ("ok", "hint") and comp(rep, "Dateien und Office")["state"] == "ok"      # ohne Agent-Umbau unabhaengig vom Datei-Agent (PR E1)


def test_doctor_lines_follow_the_report_and_errors_are_counted():
    from jarvis.interface.doctor import diagnose
    d = diagnose(env={}, find_spec=finder(missing=("tkinter",)))
    assert d["python"] and d["modules"]["tkinter"] is False and set(d["keys"]) >= {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"} and d["errors"] == 0 and d["hints"] >= 1


# ---- View-Schicht -----------------------------------------------------------------------------------------------------------------------------
def test_view_returns_the_report_redacted_and_bounded_and_rejects_parameters():
    rep = {"python": "3.14.6", "platform": "win32", "jarvis": "0.1.0", "errors": 0, "hints": 1, "note": "n",
           "items": [{"level": "HINWEIS", "text": "token " + SECRET}] * 100, "components": [{"name": "X", "state": "ok", "text": "t"}] * 50, "agents": [], "keys": {"A": True}, "security": {"mode": "standard"}}
    v = ReadViews(doctor=lambda: rep)
    out = v.doctor({})
    assert out["available"] and len(out["items"]) <= 60 and len(out["components"]) <= 20 and SECRET not in json.dumps(out)
    with pytest.raises(ViewError):
        v.doctor({"x": "1"})
    assert ReadViews().doctor({})["available"] is False and "Diagnosebericht" in ReadViews().doctor({})["reason"]
    boom = ReadViews(doctor=lambda: (_ for _ in ()).throw(RuntimeError("secret internals " + SECRET))).doctor({})
    assert boom["available"] is False and SECRET not in json.dumps(boom) and "internals" not in json.dumps(boom)


# ---- Server und echter Kern -------------------------------------------------------------------------------------------------------------------
def get(srv, path, token=True):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    c.request("GET", path + ((("&" if "?" in path else "?") + f"t={srv.token}") if token else ""), headers={"Host": f"127.0.0.1:{srv.port}"})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def test_server_with_the_real_core_serves_the_report_read_only_and_with_token(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", SECRET)
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_CONTROL_CENTER_ENABLED="true")
    s = load_settings(env=env)
    core = build_core(s)
    srv = build_server(s, core)
    srv.start()
    try:
        status, body = get(srv, "/view/doctor")
        data = json.loads(body)
        assert status == 200 and data["available"] and data["components"] and data["agents"] and SECRET.encode() not in body
        assert data["keys"]["JARVIS_LLM_API_KEY"] is False
        assert get(srv, "/view/doctor", token=False)[0] == 401
        c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        c.request("POST", f"/view/doctor?t={srv.token}", body="{}", headers={"Host": f"127.0.0.1:{srv.port}", "Origin": f"http://127.0.0.1:{srv.port}", "Content-Type": "application/json"})
        assert c.getresponse().status in (404, 405)                                                  # kein Schreibweg
        assert get(srv, "/view/doctor?x=1")[0] == 400
        assert core.permissions.emergency.engaged is False                                           # der Abruf aendert nichts
    finally:
        srv.stop()


def test_server_without_views_has_no_doctor_route():
    srv = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    srv.start()
    try:
        assert get(srv, "/view/doctor")[0] == 404
    finally:
        srv.stop()


def test_the_setup_module_is_read_only_by_structure():
    src = (Path(cc.__file__).parent / "setup_view.py").read_text(encoding="utf-8")
    for forbidden in ("open(", "write", "subprocess", "socket", "urllib", "jarvis.permissions", "jarvis.tools", "set_confirmation", "enabled = True", ".enabled=True"):
        assert forbidden not in src, forbidden


# ---- Anzeige (Node-DOM) -----------------------------------------------------------------------------------------------------------------------
pytestmark_node = pytest.mark.skipif(NODE is None, reason="node fehlt (ein uebersprungener Test gilt nicht als bestanden)")


def run_dom(tmp_path, steps):
    f = tmp_path / "scenario.json"
    f.write_text(json.dumps(steps), encoding="utf-8")
    out = subprocess.run([NODE, str(HARNESS), str(WEB), str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


REPORT = {"available": True, "limit": 0, "python": "3.14.6", "platform": "win32", "jarvis": "0.1.0", "errors": 1, "hints": 2, "note": "Nur lesend",
          "security": {"mode": "standard", "confirmation": "cli"}, "keys": {"BRAVE_SEARCH_API_KEY": True, "OPENAI_API_KEY": False},
          "components": [{"name": "Browser", "state": "hint", "text": "Playwright fehlt"}, {"name": "Sprache", "state": "off", "text": "nur Konsole"}],
          "agents": [{"id": "files", "status": "AVAILABLE", "reason": ""}, {"id": "coding", "status": "DISABLED", "reason": "tool coding is not available"}],
          "items": [{"level": "FEHLER", "text": "Konfiguration ungültig"}, {"level": "HINWEIS", "text": "pywebview fehlt"}]}


@pytestmark_node
def test_dom_shows_report_in_german_and_keys_only_as_set_or_not_set_and_sends_no_command(tmp_path):
    snaps = run_dom(tmp_path, [{"views": {"doctor": REPORT}}, {"snap": "start"}, {"clickId": "doctor-refresh"}, {"snap": "a"}])
    assert snaps["start"]["fetched"] == [] and snaps["start"]["text"]["doctor-list"] == ""           # nichts, bevor der Mensch pruefen laesst
    t = snaps["a"]["text"]
    assert "Python 3.14.6" in t["doctor-summary"] and "1 Fehler" in t["doctor-summary"] and "standard" in t["doctor-summary"]
    lst = t["doctor-list"]
    assert "Playwright fehlt" in lst and "Hinweis | Browser" in lst and "Agent coding: DISABLED" in lst and "gesetzt" in lst and "nicht gesetzt" in lst
    assert "FEHLER: Konfiguration ungültig" in lst and "pywebview fehlt" in lst
    assert snaps["a"]["sent"] == [] and snaps["a"]["fetched"] == ["doctor"]


@pytestmark_node
def test_dom_unavailable_report_is_shown_as_such_not_faked(tmp_path):
    snaps = run_dom(tmp_path, [{"views": {"doctor": {"available": False, "items": [], "reason": "Die Diagnose konnte nicht erstellt werden."}}}, {"clickId": "doctor-refresh"}, {"snap": "a"}])
    assert "Diagnose konnte nicht" in snaps["a"]["text"]["doctor-note"] and snaps["a"]["text"]["doctor-list"] == ""


def test_html_has_the_panel_and_js_uses_get_only():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for i in ("doctor-panel", "doctor-refresh", "doctor-note", "doctor-summary", "doctor-list"):
        assert f'id="{i}"' in html
    js = (WEB / "app.js").read_text(encoding="utf-8")
    body = re.search(r"function renderDoctor\(.*?\n\}", js, re.S).group(0)
    for bad in ("send(", "fetch(", "innerHTML", "POST"):
        assert bad not in body
