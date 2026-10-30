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
