"""Sicherheitsstruktur der Abnahme-Skripte (scripts/abnahme): Standard ist ein Trockenlauf; keine UAC-Bestaetigung, keine Rechteerhoehung, keine Installation, keine Richtlinienaenderung,
kein Netzwerk. Reine Textpruefung (Windows-PowerShell wird hier nicht ausgefuehrt)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = (ROOT / "scripts" / "abnahme" / "run-abnahme.ps1").read_text(encoding="utf-8")
PY = (ROOT / "scripts" / "abnahme" / "tts_first_sound.py").read_text(encoding="utf-8")
FORBIDDEN_PS = ("RunAs", "Set-ExecutionPolicy", "pip install", "Invoke-WebRequest", "Invoke-RestMethod", "Invoke-Expression", "iex ", "reg add", "reg.exe", "netsh", "schtasks", "New-Service",
                "sc.exe", "consent.exe", "Start-Process", "Stop-Process", "taskkill", "Install-", "winget", "choco ", "Set-MpPreference", "Add-MpPreference", "bcdedit", "net user", "icacls", "takeown")


def test_the_default_is_a_dry_run_and_the_real_run_needs_an_explicit_switch():
    assert "[switch]$Execute" in PS1 and "TROCKENLAUF" in PS1
    assert PS1.count("if (-not $Execute)") >= 5


def test_the_powershell_script_contains_nothing_that_elevates_installs_or_changes_policy():
    found = [w for w in FORBIDDEN_PS if w.lower() in PS1.lower()]
    assert found == [], found
    assert all("env:" in line for line in PS1.splitlines() if "Remove-Item" in line)          # Remove-Item nur fuer eigene Umgebungsvariablen


def test_the_script_refuses_to_run_elevated():
    assert "IsInRole" in PS1 and "NICHT erhoehten" in PS1 and "exit 2" in PS1


def test_the_script_only_calls_existing_repository_tools():
    called = set(re.findall(r"(tests\\[A-Za-z0-9_]+\.py|ci\\[A-Za-z0-9_\-\\]+\.py|scripts\\abnahme\\[A-Za-z0-9_]+\.py)", PS1))
    assert called, "keine Skript-/Testverweise gefunden"
    missing = [rel for rel in called if not (ROOT / rel.replace("\\", "/")).exists()]
    assert missing == [], missing


def test_the_measuring_helper_imports_only_the_standard_library_and_the_existing_provider():
    tree = ast.parse(PY)
    top = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert top <= {"__future__", "argparse", "json", "platform", "statistics", "sys", "tempfile", "threading", "time", "wave", "pathlib", "jarvis"}, top
    for forbidden in ("socket", "urllib", "requests", "subprocess", "os.system"):
        assert forbidden not in PY


def test_the_owner_guide_states_the_open_status_and_the_uac_rule():
    doc = (ROOT / "docs" / "WINDOWS_V2_ABNAHME_KURZ.md").read_text(encoding="utf-8")
    assert "#186 bleibt offen" in doc and "bestätigt oder bedient UAC nie" in doc and "TROCKENLAUF" in doc and "installiert nichts" in doc and "-Execute" in doc
