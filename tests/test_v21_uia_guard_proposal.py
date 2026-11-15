"""V2.1 VORSCHLAG (nicht angewendet): eng begrenzte Anpassung des historischen UIA-Bereichswaechters `test_the_ui_tool_only_touches_computer_and_documentation_files`.

Der historische Test bleibt UNVERAENDERT. Hier steht nur die vorgeschlagene Regel als reine Funktion (`proposed_guard`) samt Negativtests; sie benutzt kein git und keinen Checkout-Zustand.
Zweck des historischen Tests: die UI-Tool-Arbeit (#66) darf `bootstrap.py`, `permissions/`, `config/`, `.github/`, `.claude/`, `CLAUDE.md`, `pyproject.toml` und die Sicherheitstests nicht
anfassen. Vorschlag: dieselbe Verbotsliste, ABER `bootstrap.py` ist erlaubt, solange `wiring_problems(bootstrap.py) == []` (Struktur gleich V2.0 ausser der lesenden Guard-Verdrahtung)."""
from __future__ import annotations

import pytest

from test_v21_bootstrap_wiring import real, wiring_problems

FORBIDDEN_PREFIXES = ("src/jarvis/permissions/", ".github/", ".claude/", "config/", "tests/test_security_")
FORBIDDEN_FILES = ("src/jarvis/bootstrap.py", "CLAUDE.md", "pyproject.toml", "tests/test_emergency_stop.py", "tests/test_autonomy_invariants.py")
# Dateiliste der urspruenglichen UI-Tool-Aenderung (git show --name-only c239b81), unveraenderlich:
ORIGINAL_UIA_CHANGE = ("README.md", "docs/TESTING.md", "src/jarvis/computer/controller.py", "src/jarvis/computer/resources.py", "src/jarvis/computer/safety.py",
                       "src/jarvis/computer/tools.py", "src/jarvis/computer/uia_output.py", "tests/test_computer_uia.py", "tests/test_computer_uia_tools.py")


def historic_guard(changed: list[str]) -> list[str]:
    """Genau die Regel des historischen Tests (zum Vergleich)."""
    return [f for f in changed if f.startswith(FORBIDDEN_PREFIXES) or f in FORBIDDEN_FILES]


def proposed_guard(changed: list[str], bootstrap_source: str) -> list[str]:
    forbidden = historic_guard(changed)
    if "src/jarvis/bootstrap.py" in forbidden and wiring_problems(bootstrap_source) == []:
        forbidden.remove("src/jarvis/bootstrap.py")
    return forbidden


def test_the_original_change_is_clean_under_both_rules():
    assert historic_guard(list(ORIGINAL_UIA_CHANGE)) == [] and proposed_guard(list(ORIGINAL_UIA_CHANGE), real()) == []


def test_the_v21_change_set_is_exactly_the_conflict_the_proposal_resolves():
    changed = ["src/jarvis/bootstrap.py", "src/jarvis/agents/orchestrator.py", "tests/test_v21_bootstrap_wiring.py"]
    assert historic_guard(changed) == ["src/jarvis/bootstrap.py"] and proposed_guard(changed, real()) == []


@pytest.mark.parametrize("path", ["src/jarvis/permissions/engine.py", "src/jarvis/permissions/emergency.py", ".github/workflows/tests.yml", ".claude/settings.json", "config/jarvis.toml",
                                  "CLAUDE.md", "pyproject.toml", "tests/test_security_engine.py", "tests/test_emergency_stop.py", "tests/test_autonomy_invariants.py"])
def test_every_other_protected_path_stays_forbidden_even_together_with_a_clean_bootstrap(path):
    assert proposed_guard(["src/jarvis/bootstrap.py", path], real()) == [path]
    assert proposed_guard([path], real()) == [path]


@pytest.mark.parametrize("mutate", [lambda s: s.replace("    return core\n", "    sneak()\n    return core\n", 1), lambda s: s.replace("stop_guard=emergency_guard(core)", "stop_guard=None", 1),
                                    lambda s: s.replace("em.engaged else None\n    return guard\n\n\ndef speech_guard", "em.engaged and core.tools else None\n    return guard\n\n\ndef speech_guard", 1),
                                    lambda s: s.replace('!= "deny"', '!= "never"', 1)])
def test_a_bootstrap_change_beyond_the_guard_wiring_stays_forbidden(mutate):
    assert proposed_guard(["src/jarvis/bootstrap.py"], mutate(real())) == ["src/jarvis/bootstrap.py"]


def test_the_historic_rule_itself_is_not_weakened_by_the_proposal_for_other_files():
    assert historic_guard(["src/jarvis/computer/tools.py", "docs/x.md"]) == [] and proposed_guard(["src/jarvis/computer/tools.py"], "def broken(:") == []
