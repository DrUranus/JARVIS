"""V2-Vorbereitung (Bereich D): das Standard-Aus-Pruefskript und sein Windows-Wrapper. Das Skript meldet Abweichungen, statt sie zu verstecken; der Wrapper ist ein Trockenlauf-Standard
ohne Rechteerhoehung, Installation oder Volllauf."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_v2_defaults_under_test", ROOT / "scripts" / "v2" / "verify_v2_defaults.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
PS1 = (ROOT / "scripts" / "v2" / "run-v2-prep-checks.ps1").read_text(encoding="utf-8")


def run(monkeypatch, capsys, flags=None):
    if flags is not None:
        monkeypatch.setattr(mod, "FLAGS", flags)
    monkeypatch.setattr(mod, "_run", lambda args: (0, "stub"))                      # Waechterlaeufe sind eigene Tests; hier nur die Standardwerte
    code = mod.main([])
    return code, json.loads(capsys.readouterr().out)


def test_everything_new_is_off_by_default_and_nothing_starts(monkeypatch, capsys):
    code, rep = run(monkeypatch, capsys)
    assert code == 0 and rep["deviations"] == [] and rep["ok"] is True and rep["flags_checked"] >= 20 and rep["default_subsystems_available"] == []


def test_a_default_that_is_on_is_reported_and_fails(monkeypatch, capsys):
    from jarvis.config import Settings
    flags = dict(mod.FLAGS)
    flags["agents.quality_gate"] = lambda s: not Settings().agents.quality_gate         # simuliert "Standard AN"
    code, rep = run(monkeypatch, capsys, flags)
    assert code == 1 and any("quality_gate" in d for d in rep["deviations"])


def test_a_failing_watcher_run_makes_the_report_fail(monkeypatch, capsys):
    monkeypatch.setattr(mod, "_run", lambda args: (1, "FAILED"))
    assert mod.main([]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_the_flag_list_covers_every_v2_switch_that_exists():
    from jarvis.config import AgentsSettings, BusinessSettings, GoalsSettings
    assert {"quality_gate", "agent_budgets_enabled", "artifacts"} <= set(AgentsSettings.__dataclass_fields__) and "strategist" in BusinessSettings.__dataclass_fields__ and "plan_analysis" in GoalsSettings.__dataclass_fields__
    for key in ("agents.quality_gate", "business.strategist", "goals.plan_analysis", "agents.artifacts", "goals.replanning", "self_improvement.enabled"):
        assert key in mod.FLAGS


# ---- Windows-Wrapper: statische Pruefung (PowerShell laeuft hier nicht) -----------------------------------------------------------------------------
def test_the_wrapper_is_a_dry_run_by_default_and_has_no_elevation_installation_or_network():
    assert "[switch]$Execute" in PS1 and "TROCKENLAUF" in PS1
    for bad in ("Invoke-Expression", "iex ", "RunAs", "Set-ExecutionPolicy", "Start-Process", "Invoke-WebRequest", "curl ", "wget ", "pip install", "reg add", "HKLM", "HKCU", "netsh", "Remove-Item", "git ", "schtasks", "New-Service"):
        assert bad not in PS1, bad


def test_the_wrapper_runs_a_fixed_existing_test_list_and_never_the_full_suite():
    listed = re.findall(r'"(tests\\[A-Za-z0-9_]+\.py)"', PS1)
    assert len(listed) >= 8 and len(set(listed)) == len(listed)
    for rel in listed:
        assert (ROOT / rel.replace("\\", "/")).is_file(), rel
    assert "pytest -q -p no:cacheprovider -rfEs @tests" in PS1 and "tests\\ " not in PS1.replace('"tests\\', "")


def test_skipped_tests_count_as_not_passed_in_the_wrapper():
    assert "^SKIPPED" in PS1 and "NICHT bestanden" in PS1
