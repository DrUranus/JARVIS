"""Control Center <-> echtes UiBackend (Schritt cc-backend-binding): Startbefehl `jarvis-cc`, Einstellung `control_center.enabled`, nur Loopback, nichts startet
von selbst. Echte Engine/Registry, Fake-Provider (Mock-LLM), nur Loopback-Sockets, kein externes Netzwerk."""
import ast
import http.client
import json
import threading
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import ConfigError, ControlCenterSettings, Settings, load_settings
from jarvis.control_center import launcher
from jarvis.control_center.launcher import LauncherError, build_server
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.confirmation import ConfirmationRequest
from jarvis.permissions.levels import PermissionLevel
from jarvis.ui_contract import ConformanceHooks, run_conformance
from test_computer_integration import env_for

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"


def real_env(tmp_path, **extra):
    return env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true",
                   JARVIS_CONTROL_CENTER_ENABLED="true", JARVIS_ASSISTANT_CONFIRMATION_TIMEOUT_SECONDS="1", **extra)


def real_core(tmp_path, **extra):
    return build_core(load_settings(env=real_env(tmp_path, **extra)))


def cmd(type_, data=None, cid="c1"):
    return {"v": "1.0", "id": cid, "type": type_, "data": data or {}}


def wait_for(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def post(srv, body):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("POST", f"/command?t={srv.token}", body=json.dumps(body),
                 headers={"Host": f"127.0.0.1:{srv.port}", "Origin": f"http://127.0.0.1:{srv.port}", "Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, data


# ---- Einstellung: Standard aus ---------------------------------------------------------------------------------------------------------
def test_setting_is_off_by_default_and_not_in_the_shipped_config():
    assert ControlCenterSettings().enabled is False and Settings().control_center.enabled is False
    assert load_settings(env={}).control_center.enabled is False
    shipped = tomllib.loads((ROOT / "config" / "jarvis.toml").read_text(encoding="utf-8"))
    assert "control_center" not in shipped


def test_setting_can_be_enabled_by_environment_and_toml_only_explicitly(tmp_path):
    assert load_settings(env={"JARVIS_CONTROL_CENTER_ENABLED": "true"}).control_center.enabled is True
    toml = tmp_path / "c.toml"
    toml.write_text("[control_center]\nenabled = true\n", encoding="utf-8")
    assert load_settings(toml, env={}).control_center.enabled is True
    toml.write_text("[control_center]\nhost = \"0.0.0.0\"\n", encoding="utf-8")
    with pytest.raises(ConfigError):                                   # es gibt keine Einstellung fuer einen anderen Host
        load_settings(toml, env={})


# ---- Startbefehl: nur ausdruecklich, nur Loopback ----------------------------------------------------------------------------------------
def test_pyproject_defines_the_jarvis_cc_script_and_no_new_dependency():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["jarvis-cc"] == "jarvis.control_center.launcher:main"
    assert data["project"]["dependencies"] == []


def test_main_refuses_when_disabled_and_builds_nothing(tmp_path, monkeypatch, capsys):
    built = []
    monkeypatch.setattr(launcher, "build_core", lambda s: built.append(s))
    toml = tmp_path / "c.toml"
    toml.write_text("", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONTROL_CENTER_ENABLED", "false")
    assert launcher.main(["-c", str(toml)]) == 2
    assert built == [] and "control_center.enabled" in capsys.readouterr().err


def test_build_server_refuses_disabled_setting(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true")))
    with pytest.raises(LauncherError, match="control_center.enabled"):
        build_server(Settings(), core)


def test_build_server_refuses_without_a_real_backend(tmp_path):
    env = env_for(tmp_path, JARVIS_CONTROL_CENTER_ENABLED="true")                 # assistant.enabled fehlt: kein UiBackend
    settings = load_settings(env=env)
    core = build_core(settings)
    with pytest.raises(LauncherError, match="assistant"):
        build_server(settings, core)


def test_build_server_binds_loopback_only_and_listens_only_after_start(tmp_path):
    settings = load_settings(env=real_env(tmp_path))
    core = build_core(settings)
    before = threading.active_count()
    srv = build_server(settings, core)
    assert srv.host == "127.0.0.1" and srv.port is None and threading.active_count() == before     # gebaut, aber nichts lauscht
    assert srv.backend is core.subsystems["assistant"].ui                                           # das echte Backend, kein Fake
    assert type(srv.backend).__name__ == "ControllerUiBackend"
    srv.start()
    try:
        assert srv.url.startswith("http://127.0.0.1:")
        assert srv._httpd.server_address[0] == "127.0.0.1"
    finally:
        srv.stop()


def test_main_starts_serves_and_stops_on_interrupt(tmp_path, monkeypatch, capsys):
    toml = tmp_path / "c.toml"
    toml.write_text("[control_center]\nenabled = true\n[assistant]\nenabled = true\n[agents]\nenabled = true\n", encoding="utf-8")
    for k, v in env_for(tmp_path).items():
        monkeypatch.setenv(k, v)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    def interrupt(timeout=None):
        raise KeyboardInterrupt
    monkeypatch.setattr(launcher, "threading", SimpleNamespace(Event=lambda: SimpleNamespace(wait=interrupt)))     # nur im Launcher, nicht global
    assert launcher.main(["-c", str(toml)]) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:" in out and opened == []                     # Browser nur mit --open
    assert launcher.main(["-c", str(toml), "--open"]) == 0
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:")


# ---- Konformitaet des echten Backends ---------------------------------------------------------------------------------------------------
def make_real_backend(tmp_path):
    n = [0]

    def make():
        n[0] += 1
        return real_core(tmp_path / f"r{n[0]}").subsystems["assistant"].ui
    return make


def open_confirmation(backend):
    req = ConfirmationRequest(request_id="x", tool="keyboard", action="type", level=PermissionLevel.YELLOW, resource="keyboard://notepad", reason="Text tippen",
                              context={"fenster": "Notepad"}, session_allowed=True)
    t = threading.Thread(target=lambda: backend.confirmation_provider.confirm(req), daemon=True)
    t.start()
    assert wait_for(lambda: any(e["type"] == "confirmation_request" for e in backend.snapshot()))


def test_real_backend_passes_the_conformance_suite(tmp_path):
    def advance(b, seconds):                       # echte Zeit: confirmation_timeout_seconds = 1
        time.sleep(1.2)
        b.expire()
    for i in range(1, 8):
        (tmp_path / f"r{i}").mkdir()
    run_conformance(make_real_backend(tmp_path), ConformanceHooks(trigger_confirmation=open_confirmation, advance=advance))


# ---- Notaus-Knopf wirkt auf die echte Engine ---------------------------------------------------------------------------------------------
def test_emergency_button_engages_the_real_engine_through_the_server(tmp_path):
    core = real_core(tmp_path)
    srv = build_server(load_settings(env=real_env(tmp_path)), core)
    srv.start()
    try:
        assert core.permissions.emergency.engaged is False
        status, ack = post(srv, cmd("emergency_stop", cid="n1"))
        assert status == 200 and ack["data"]["ok"] is True
        assert core.permissions.emergency.engaged is True                                       # die echte Engine, nicht nur die Anzeige
        status, ack = post(srv, cmd("submit_text", {"text": "weiter"}, cid="n2"))
        assert ack["data"]["ok"] is False and ack["data"]["code"] == "emergency"
        # kein Befehl hebt den Notaus auf: reset_emergency ist nur eine Anfrage an die Engine
        post(srv, cmd("reset_emergency", cid="n3"))
        assert core.permissions.emergency.engaged is True
    finally:
        srv.stop()


def test_a_tool_call_while_the_stop_is_engaged_is_refused_by_the_engine(tmp_path):
    core = real_core(tmp_path)
    srv = build_server(load_settings(env=real_env(tmp_path)), core)
    srv.start()
    try:
        post(srv, cmd("emergency_stop", cid="n1"))
        assert "echo" in core.tools.names()                                                      # Demo-Werkzeug (Entwicklungsmodus)
        out = core.tools.execute("echo", text="hallo")
        assert out.success is False and "emergency stop" in out.error
    finally:
        srv.stop()


# ---- Produktivmodus: nur echte Ereignisse, kein zweiter Berechtigungsweg -------------------------------------------------------------------
def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    return mods, tree


def test_production_code_never_uses_the_fake_backend():
    for f in (SRC / "control_center").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "FakeUiBackend" not in text and "ui_contract.fake" not in text, f.name


def test_python_dash_m_control_center_is_the_same_productive_start():
    main_mods, tree = _imports(SRC / "control_center" / "__main__.py")
    assert "jarvis.control_center.launcher" in main_mods


def test_launcher_has_no_second_permission_path():
    mods, tree = _imports(SRC / "control_center" / "launcher.py")
    assert not any(m.startswith("jarvis.permissions") or m.startswith("jarvis.tools") for m in mods), mods
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"execute", "set_confirmation_provider", "confirmation_provider", "emergency", "budget", "reset"}, names
    assert "x0" not in (SRC / "control_center" / "launcher.py").read_text(encoding="utf-8").lower()


def test_bootstrap_does_not_start_or_import_the_control_center():
    text = (SRC / "bootstrap.py").read_text(encoding="utf-8")
    assert "control_center" not in text.replace("settings.control_center", "")
