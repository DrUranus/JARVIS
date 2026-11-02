"""Regression tests for bounded low-interruption routine instructions.

These assertions protect against accidental removal of owner gates. They do not
assert that GitHub Actions or Windows CI has run.
"""
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / ".github" / "automation" / "jarvis_automation.py"


def test_routine_instructions_delegate_ordinary_design_decisions():
    source = SOURCE.read_text(encoding="utf-8")
    assert "Treffe gewoehnliche technische Design- und Implementierungsentscheidungen" in source
    assert "dokumentierte konservative Defaults" in source
    assert "nicht nach einer Besitzerfreigabe" in source


def test_routine_instructions_preserve_owner_security_gates():
    source = SOURCE.read_text(encoding="utf-8")
    assert "Nicht freigegebene Cloud-Datenuebertragung" in source
    assert "PermissionEngine, Not-Aus und geschuetzte Pfade" in source
    assert "keine fehlende Abnahme oder Sicherheitsfreigabe in einen Erfolg" in source


def test_controller_still_requires_continue_and_successful_tests():
    source = SOURCE.read_text(encoding="utf-8")
    assert 'report.get("next_action") != "continue"' in source
    assert "tests_allow_continue(report.get(" in source
    assert "acceptance_problem(state)" in source
    assert "select_next_item(items, done, blocked=set())" in source
