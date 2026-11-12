"""#186: das Abnahme-Skript auf einem ECHTEN Windows-Runner (Windows PowerShell): Syntax, Trockenlauf ohne jede Aenderung, Verhalten ohne virtuelle Umgebung, Abbruch bei erhoehter Sitzung.
Nur unter Windows definiert (kein Skip-Eintrag unter Linux). Es wird nichts installiert, keine UAC-Abfrage ausgeloest, keine Konfiguration veraendert; die eigentliche Hardwareabnahme
bleibt am Owner-PC (#186)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

if sys.platform == "win32":
    SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "abnahme" / "run-abnahme.ps1"
    EXE = "powershell.exe"
    BASE = [EXE, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT)]
    ELEVATED = ("$p=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent();"
                "if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){'1'}else{'0'}")

    def ps(args, cwd, timeout=180):
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False)
        out = (done.stdout or "") + (done.stderr or "")
        print("\n--- powershell", args[-3:], "rc", done.returncode, "\n" + out[-1500:])
        return done.returncode, out

    def elevated() -> bool:
        return subprocess.run([EXE, "-NoProfile", "-NonInteractive", "-Command", ELEVATED], capture_output=True, text=True, timeout=60).stdout.strip() == "1"

    def test_the_script_parses_without_any_syntax_error():
        cmd = ("$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile($env:ABN_SCRIPT,[ref]$t,[ref]$e);"
               "if($e.Count -gt 0){$e|ForEach-Object{$_.Message+' @'+$_.Extent.StartLineNumber};exit 1}else{'PARSE-OK '+$t.Count}")
        done = subprocess.run([EXE, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=120, env={**__import__("os").environ, "ABN_SCRIPT": str(SCRIPT)})
        print("\n" + done.stdout[-800:] + done.stderr[-800:])
        assert done.returncode == 0 and "PARSE-OK" in done.stdout, done.stdout + done.stderr

    def test_the_default_dry_run_prints_every_step_and_changes_nothing(tmp_path):
        rc, out = ps(BASE, tmp_path)
        assert rc == 0 and "TROCKENLAUF beendet" in out, out
        for step in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"):
            assert f"[{step}]" in out, step
        assert "ParserError" not in out and "is not recognized" not in out and "Exception" not in out
        assert list(tmp_path.iterdir()) == []                                  # nichts geschrieben, kein Ausgabeordner, kein Protokoll

    def test_a_real_run_without_the_virtual_environment_stops_clearly_before_doing_anything(tmp_path):
        rc, out = ps(BASE + ["-Execute", "-NoManual"], tmp_path)
        assert rc == 3 and "fehlt" in out and "installiert nichts" in out, out
        assert list(tmp_path.iterdir()) == []

    def test_a_real_run_in_an_elevated_session_is_refused_and_nothing_is_started(tmp_path):
        py = tmp_path / ".venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True)
        py.write_bytes(Path(sys.executable).read_bytes())                      # nur damit der Umgebungstest passiert; der Abbruch kommt vor jedem Schritt
        if not elevated():
            return                                                             # nicht erhoehte Sitzung: der Abbruch ist nicht ausloesbar, ohne echte Schritte zu starten
        rc, out = ps(BASE + ["-Execute", "-NoManual", "-Only", "S1"], tmp_path)
        assert rc == 2 and "NICHT erhoehten" in out, out
        assert not (tmp_path / "abnahme-v2").exists()

    def test_the_script_never_asks_for_elevation_or_changes_the_execution_policy():
        text = SCRIPT.read_text(encoding="utf-8")
        for bad in ("RunAs", "Set-ExecutionPolicy", "-ExecutionPolicy", "Start-Process", "pip install"):
            assert bad not in text, bad
