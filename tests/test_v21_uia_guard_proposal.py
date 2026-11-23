"""V2.1 VORSCHLAG (nicht angewendet): eng begrenzte Anpassung des historischen UIA-Bereichswaechters `test_the_ui_tool_only_touches_computer_and_documentation_files`.

Der historische Test bleibt UNVERAENDERT. Hier steht nur die vorgeschlagene Regel als reine Funktion (`proposed_guard`) samt Negativtests; sie benutzt kein git und keinen Checkout-Zustand.
Zweck des historischen Tests: die UI-Tool-Arbeit (#66) darf `bootstrap.py`, `permissions/`, `config/`, `.github/`, `.claude/`, `CLAUDE.md`, `pyproject.toml` und die Sicherheitstests nicht
anfassen. Vorschlag: dieselbe Verbotsliste, ABER `bootstrap.py` ist erlaubt, solange `wiring_problems(bootstrap.py) == []` (Struktur gleich V2.0 ausser der lesenden Guard-Verdrahtung)."""
from __future__ import annotations

import re

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


# ---- Beispielkonfigurationen: KEINE pauschale Ausnahme fuer config/, nur INHALTLICH geprueft ---------------------------------------------------------------
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

from jarvis.redaction import SecretDetector  # noqa: E402

EXAMPLE_NAME = re.compile(r"^config/[a-z0-9][a-z0-9_.\-]*\.example\.toml$")                   # genau eine Ebene, nur *.example.toml (nie jarvis.toml, nie ein Unterordner)
ALLOWED_TABLES = frozenset({"control_center", "assistant", "agents", "goals", "journal", "files", "llm", "browser", "research"})   # alles, was KEINE Sicherheitsregel setzt
FORBIDDEN_KEYS = frozenset({"audit_strict", "audit_enabled", "audit_green", "confirmation", "allowed_roots", "denied_paths", "policy_file", "paper_trading_only", "allow_prepare",
                            "allow_activation", "repo_path", "max_attempts_per_step", "api_key", "key_path", "private_hosts_allowed"})
SECRETISH_KEY = re.compile(r"(^|_)(token|secret|password|passwd|credential|api_?key|access_?key)$")        # trifft "token", "api_key", "x_secret" - nicht "max_tokens"
MAX_EXAMPLE_BYTES = 20_000


def example_config_problems(rel: str, text: str) -> list[str]:
    """Leere Liste = die Datei ist ein harmloses Beispiel (nur nicht-sicherheitsrelevante Abschnitte, keine Sicherheitsschluessel, keine Geheimnisse, gueltiges TOML)."""
    problems: list[str] = []
    if not EXAMPLE_NAME.match(rel):
        return [f"{rel}: kein Beispiel-Dateiname (config/<name>.example.toml)"]
    if len(text.encode("utf-8")) > MAX_EXAMPLE_BYTES:
        return [f"{rel}: zu gross"]
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return [f"{rel}: kein gueltiges TOML"]

    def walk(node, path=""):
        for k, v in node.items():
            if str(k).lower() in FORBIDDEN_KEYS or SECRETISH_KEY.search(str(k).lower()):
                problems.append(f"{rel}: Sicherheits-/Geheimnisschluessel {path}{k}")
            if isinstance(v, dict):
                walk(v, f"{path}{k}.")
    for table in data:
        if table not in ALLOWED_TABLES:
            problems.append(f"{rel}: Abschnitt [{table}] ist nicht erlaubt")
    walk(data)
    if SecretDetector().find(text):
        problems.append(f"{rel}: enthaelt etwas, das wie ein Geheimnis aussieht")
    return problems


def proposed_guard_v2(changed: list[str], bootstrap_source: str, read=lambda rel: (ROOT / rel).read_text(encoding="utf-8")) -> list[str]:
    """Vorschlag: wie `proposed_guard`, zusaetzlich sind Beispielkonfigurationen erlaubt, wenn ihr INHALT `example_config_problems == []` ergibt."""
    forbidden = proposed_guard(changed, bootstrap_source)
    out = []
    for f in forbidden:
        if f.startswith("config/") and f != "config/jarvis.toml":
            try:
                if example_config_problems(f, read(f)) == []:
                    continue
            except OSError:
                pass
        out.append(f)
    return out


def test_the_real_example_configs_pass_the_content_check():
    for rel in ("config/nexus.live.example.toml", "config/nexus.example.toml"):
        assert example_config_problems(rel, (ROOT / rel).read_text(encoding="utf-8")) == [], rel
    assert proposed_guard_v2(["config/nexus.live.example.toml"], real()) == []


def test_policy_example_is_not_covered_because_it_sets_rules():
    text = (ROOT / "config/policy.example.toml").read_text(encoding="utf-8")
    assert example_config_problems("config/policy.example.toml", text) != []               # Abschnitt [rule]: gehoert in die Owner-Pruefung, keine stille Ausnahme


@pytest.mark.parametrize("rel", ["config/jarvis.toml", "config/nexus.toml", "config/sub/x.example.toml", "config/x.example.toml.bak", "config/../config/jarvis.toml", "src/jarvis/config.py", "config/EXAMPLE.toml"])
def test_only_exact_example_file_names_qualify(rel):
    assert example_config_problems(rel, "[agents]\nenabled = true\n") != []
    assert proposed_guard_v2([rel], real(), read=lambda r: "[agents]\nenabled = true\n") == [rel] if rel.startswith("config/") else True


@pytest.mark.parametrize("body", ["[security]\naudit_strict = false\n", "[agents]\naudit_strict = false\n", "[assistant]\nconfirmation = \"allow\"\n", "[files]\nallowed_roots = [\"C:/\"]\n",
                                  "[finance]\npaper_trading_only = false\n", "[self_improvement]\nallow_activation = true\n", "[llm]\napi_key = \"x\"\n", "[llm]\ntoken = \"x\"\n",
                                  "[agents]\nenabled = true\n[security]\nconfirmation = \"deny\"\n", "[llm]\nprovider = \"sk-" + "a1" * 12 + "\"\n", "[agents\nbroken", "[unknown_table]\nx = 1\n",
                                  "[goals]\nmax_attempts_per_step = 50\n", "[browser]\nprivate_hosts_allowed = [\"10.0.0.1\"]\n"])
def test_every_security_relevant_or_secret_content_keeps_a_config_file_forbidden(body):
    assert example_config_problems("config/x.example.toml", body) != []
    assert proposed_guard_v2(["config/x.example.toml"], real(), read=lambda r: body) == ["config/x.example.toml"]


def test_a_real_example_that_is_changed_into_something_dangerous_is_found():
    base = (ROOT / "config/nexus.live.example.toml").read_text(encoding="utf-8")
    assert example_config_problems("config/nexus.live.example.toml", base + "\n[security]\nconfirmation = \"allow\"\n") != []


def test_the_extension_does_not_loosen_any_other_protected_path():
    for path in ("src/jarvis/permissions/engine.py", ".github/workflows/tests.yml", "tests/test_emergency_stop.py", "pyproject.toml", "CLAUDE.md"):
        assert proposed_guard_v2(["config/nexus.live.example.toml", path], real()) == [path]
