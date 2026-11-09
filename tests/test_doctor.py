"""`jarvis doctor` / `/doctor`: nur lesen und berichten (ohne Netz, ohne echte Schluessel, ohne Subsysteme zu starten)."""
import os
import sys
from types import SimpleNamespace

import pytest

from jarvis.config import load_settings
from jarvis.interface import cli, doctor

SECRET = "sk-geheim-1234567890"


def _find(missing=()):
    return lambda name: None if name in missing else object()


def run(env=None, cfg=None, missing=(), settings=None):
    return doctor.run_doctor(config_path=cfg, settings=settings, env=env or {}, find_spec=_find(missing))


def test_defaults_ok_exit_zero_and_german():
    text, code = run()
    assert code == 0
    for word in ("Python", "tkinter", "sounddevice", "numpy", "playwright", "Konfiguration", "Sicherheitsmodus", "Subsysteme"):
        assert word in text
    active = text.split("Aktive Subsysteme:")[1].splitlines()[0]
    for off in ("computer", "browser", "coding", "agents", "goals", "finance"):
        assert off not in active  # Standard: alles Riskante aus


def test_keys_only_set_or_not_set_never_value():
    text, _ = run(env={"OPENAI_API_KEY": SECRET, "JARVIS_LLM_API_KEY": SECRET})
    assert SECRET not in text
    assert "OPENAI_API_KEY: gesetzt" in text
    assert "ANTHROPIC_API_KEY: nicht gesetzt" in text


def test_missing_optional_modules_are_hints_not_errors():
    text, code = run(missing=("tkinter", "sounddevice", "numpy", "playwright"))
    assert code == 0
    assert "nicht verfügbar" in text and "pip install" in text


def test_invalid_config_is_error_exit_one(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("bogus = 1\n")
    text, code = run(cfg=str(f))
    assert code == 1 and "FEHLER" in text and "Konfiguration" in text


def test_missing_config_file_is_error(tmp_path):
    _, code = run(cfg=str(tmp_path / "nope.toml"))
    assert code == 1


def test_invalid_env_value_is_error():
    _, code = run(env={"JARVIS_MODE": "chaos"})
    assert code == 1


def test_reports_active_subsystems_without_activating(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[browser]\nenabled = true\n[history]\nenabled = true\n")
    text, code = run(cfg=str(f))
    assert code == 0 and "browser" in text.split("Aktive Subsysteme:")[1].splitlines()[0]
    # reiner Lesezugriff: nichts angelegt
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.toml"]


def test_no_files_created_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run()
    assert list(tmp_path.iterdir()) == []


def test_security_mode_reported():
    text, _ = run(settings=load_settings(env={}))
    assert "standard" in text and "audit_strict" in text and "Paper-Trading" in text


def test_hint_when_security_loosened(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[security]\naudit_strict = false\n")
    text, _ = run(cfg=str(f))
    assert "HINWEIS" in text and "audit_strict" in text


def test_doctor_does_not_build_core_or_import_optional(monkeypatch):
    monkeypatch.setattr(cli, "build_core", lambda *a, **k: pytest.fail("doctor darf keinen Core bauen"))
    before = set(sys.modules)
    run()
    assert not ({"sounddevice", "playwright", "numpy"} & (set(sys.modules) - before))


def test_main_doctor_subcommand_exit_codes(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "build_core", lambda *a, **k: pytest.fail("kein Core"))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["doctor"]) == 0
    assert "Python" in capsys.readouterr().out
    bad = tmp_path / "bad.toml"
    bad.write_text("bogus = 1\n")
    assert cli.main(["-c", str(bad), "doctor"]) == 1
    assert "FEHLER" in capsys.readouterr().out


def test_chat_command_doctor_and_help():
    assert "/doctor" in cli.HELP
    settings = load_settings(env={})
    out = cli.run_command(SimpleNamespace(), "/doctor", settings)  # Core wird nicht angefasst
    assert "Sicherheitsmodus" in out and "Python" in out


def test_chat_doctor_uses_loaded_settings_and_hides_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    s = load_settings(env={"JARVIS_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": SECRET})
    out = cli.run_command(SimpleNamespace(), "/doctor", s)
    assert SECRET not in out and "ANTHROPIC_API_KEY: gesetzt" in out


# --- cc-windows-start (B8): Control-Center-Voraussetzungen, nur lesend ---
def run_cc(webview2=None, platform="win32", settings=None, env=None):
    return doctor.run_doctor(settings=settings or load_settings(env={}), env=env or {}, find_spec=_find(),
                             webview2_probe=webview2, platform=platform)


def test_cc_section_german_and_default_off():
    text, code = run_cc(webview2=lambda: "128.0.1")
    assert code == 0
    assert "Control Center" in text and "jarvis-cc" in text
    assert "control_center.enabled = false" in text and "Der Doctor schaltet nichts ein" in text
    assert "Canvas-2D" in text and "2D-Rückfall" in text      # 3D/WebView2: Voraussetzung und Rueckfall benannt
    assert "Mini-Overlay" in text and "jarvis-cc --overlay" in text and "Standard: aus" in text   # optional, nur ausdruecklich gestartet
    assert "Notaus" in text and "geschlossenem Hauptfenster" in text


def test_webview2_found_missing_and_not_windows():
    ok, _ = run_cc(webview2=lambda: "128.0.1")
    assert "WebView2-Laufzeit: gefunden (Version 128.0.1)" in ok
    miss, code = run_cc(webview2=lambda: None)
    assert code == 0 and "HINWEIS" in miss and "WebView2-Laufzeit: nicht gefunden" in miss
    lin, code = run_cc(platform="linux")
    assert code == 0 and "nur unter Windows prüfbar" in lin


def test_webview2_probe_failure_is_hint_not_error():
    def boom():
        raise OSError("kein Zugriff")
    text, code = run_cc(webview2=boom)
    assert code == 0 and "nicht prüfbar" in text


def test_cc_prerequisites_reported_without_activating():
    s = load_settings(env={"JARVIS_CONTROL_CENTER_ENABLED": "true"})
    text, code = run_cc(webview2=lambda: None, settings=s)
    assert code == 0
    assert "control_center.enabled = true" in text and "assistant.enabled" in text and "agents.enabled" in text
    assert s.control_center.enabled is True and s.assistant.enabled is False   # unveraendert


def test_cc_check_is_read_only_and_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("socket.socket", lambda *a, **k: pytest.fail("kein Netz/Server"))
    run_cc(webview2=lambda: "1")
    assert list(tmp_path.iterdir()) == []


def test_doctor_does_not_import_control_center_or_start_it():
    before = set(sys.modules)
    run_cc(webview2=lambda: "1")
    assert not any(m.startswith("jarvis.control_center") for m in set(sys.modules) - before)


def test_cc_overlay_prerequisite_pywebview_reported_read_only():
    ok, code = doctor.run_doctor(settings=load_settings(env={}), env={}, find_spec=_find(), webview2_probe=lambda: "1", platform="win32")
    assert "pywebview: verfügbar" in ok and code == 0
    miss, code = doctor.run_doctor(settings=load_settings(env={}), env={}, find_spec=_find(("webview",)), webview2_probe=lambda: "1", platform="win32")
    assert code == 0 and "pywebview: nicht installiert" in miss and ".[ui]" in miss and "HINWEIS" in miss


# ---- OneDrive-Pfade (nur Hinweis) ------------------------------------------------------------------------------------------------------------
def test_onedrive_paths_are_a_hint_with_the_safe_alternative_and_other_paths_are_ok():
    here = doctor.run_doctor(env={}, find_spec=_find(()), cwd=r"C:\Users\x\OneDrive\Dokumente\JARVIS")
    assert "OneDrive-Ordner erkannt" in here[0] and "gitlocks" in here[0] and here[1] == 0          # Hinweis, kein Fehler
    plain = doctor.run_doctor(env={}, find_spec=_find(()), cwd=r"C:\dev\JARVIS")
    assert "kein OneDrive-Ordner erkannt" in plain[0]
    via_env = doctor.run_doctor(env={"OneDrive": r"D:\Sync"}, find_spec=_find(()), cwd=r"D:\Sync\proj")
    assert "OneDrive-Ordner erkannt" in via_env[0]

