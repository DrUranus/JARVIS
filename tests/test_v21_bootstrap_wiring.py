"""V2.1: enge Zusatzpruefung der bootstrap.py-Verdrahtung des Not-Aus-Guards (Aufgabe 2).

Hintergrund: `test_the_ui_tool_only_touches_computer_and_documentation_files` (historischer UIA-Bereichswaechter) verbietet jede Aenderung an bootstrap.py gegenueber origin/main.
Dieser Waechter bleibt UNVERAENDERT. Weil der Not-Aus-Guard laut Projektregel nur in bootstrap.py verdrahtet werden darf, prueft DIESER Test, dass die Aenderung genau und nur
die lesende Guard-Verdrahtung ist - der Sicherheitszweck des Waechters (keine stille Aenderung der Verdrahtung, kein Umgehen der PermissionEngine) bleibt damit vollstaendig erhalten:

  1. Alles ausser `emergency_guard`, `speech_guard` und dem Schluesselwort `stop_guard` ist STRUKTURGLEICH zum geprueften V2.0-Stand (Commit 7c2b4b7): gleiche Funktionen,
     gleiche Aufrufe in gleicher Reihenfolge, gleiche Textkonstanten (Fingerabdruck unten; versionsunabhaengig, nur Namen und Konstanten, keine ast.dump-Formatierung).
  2. `emergency_guard` ist reine Lesefunktion (nur `.engaged` und `.reason`, kein Aufruf ausser dem Guard selbst) und `speech_guard` liefert dasselbe wie vorher.
  3. `stop_guard` kommt genau einmal vor, als Schluesselwort von `build_agents`, mit dem Wert `emergency_guard(core)`.
Aendert jemand bootstrap.py legitim, schlaegt dieser Test an und der Fingerabdruck wird bewusst vom Owner neu gesetzt (wie das Manifest N3-D)."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "jarvis" / "bootstrap.py"
BASELINE_7C2B4B7 = "883d2ab65ed0d615a3bfa73b9d67740be5d45ac9250668c6a45b04abc2240a94"
EXEMPT = ("emergency_guard", "speech_guard")


def fingerprint(source: str) -> str:
    tree = ast.parse(source)
    parts: list[str] = []
    for fn in (n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name in EXEMPT)):
        skip = {id(x) for k in ast.walk(fn) if isinstance(k, ast.keyword) and k.arg == "stop_guard" for x in ast.walk(k)}          # das Schluesselwort samt Wert
        for n in ast.walk(fn):
            if id(n) in skip:
                continue
            if isinstance(n, ast.Call):
                f = n.func
                parts.append("call:" + (f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else type(f).__name__) + ":" + ",".join(k.arg or "**" for k in n.keywords if k.arg != "stop_guard"))
            elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                parts.append(f"def:{n.name}")
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                parts.append("str:" + n.value)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                parts.append("import:" + (getattr(n, "module", None) or "") + ":" + ",".join(a.name for a in n.names))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def wiring_problems(source: str) -> list[str]:
    """Alle Teilpruefungen dieser Datei als Funktion ueber einen Quelltext (fuer Negativtests und den Vorschlag fuer den historischen Waechter). Leere Liste = in Ordnung."""
    problems: list[str] = []
    t = ast.parse(source)
    if fingerprint(source) != BASELINE_7C2B4B7:
        problems.append("bootstrap weicht ausserhalb der Guard-Verdrahtung vom V2.0-Stand ab")
    guard = next((n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == "emergency_guard"), None)
    if guard is None:
        problems.append("emergency_guard fehlt")
    else:
        if any(isinstance(n, ast.Call) for n in ast.walk(guard)) or {n.attr for n in ast.walk(guard) if isinstance(n, ast.Attribute)} - {"permissions", "emergency", "engaged", "reason"}:
            problems.append("emergency_guard ist keine reine Lesefunktion")
    uses = [n for n in ast.walk(t) if isinstance(n, ast.keyword) and n.arg == "stop_guard"]
    ok = len(uses) == 1 and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "build_agents" and uses[0] in c.keywords for c in ast.walk(t))
    v = uses[0].value if uses else None
    if not (ok and isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "emergency_guard" and [a.id for a in v.args if isinstance(a, ast.Name)] == ["core"]):
        problems.append("stop_guard ist nicht genau einmal als emergency_guard(core) an build_agents gebunden")
    return problems


def tree():
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def func(t, name):
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == name)


def test_everything_except_the_guard_wiring_is_structurally_identical_to_the_reviewed_v20_state():
    assert fingerprint(SOURCE.read_text(encoding="utf-8")) == BASELINE_7C2B4B7


def test_the_guard_is_a_pure_read_of_the_latch():
    g = func(tree(), "emergency_guard")
    attrs = {n.attr for n in ast.walk(g) if isinstance(n, ast.Attribute)}
    calls = [n for n in ast.walk(g) if isinstance(n, ast.Call)]
    assert attrs <= {"permissions", "emergency", "engaged", "reason"} and not calls
    assert not {n.id for n in ast.walk(g) if isinstance(n, ast.Name)} & {"engage", "reset", "trigger", "run_stoppers"}


def test_speech_guard_delegates_and_keeps_its_behaviour():
    from jarvis.bootstrap import emergency_guard, speech_guard
    off = type("C", (), {"permissions": type("P", (), {"emergency": type("E", (), {"engaged": False, "reason": ""})()})()})()
    on = type("C", (), {"permissions": type("P", (), {"emergency": type("E", (), {"engaged": True, "reason": "x"})()})()})()
    assert speech_guard(off)() is None and emergency_guard(off)() is None
    assert speech_guard(on)() == emergency_guard(on)() == "Notaus aktiv (x)"


def test_stop_guard_appears_exactly_once_as_a_keyword_of_build_agents_with_the_read_only_guard():
    t = tree()
    uses = [n for n in ast.walk(t) if isinstance(n, ast.keyword) and n.arg == "stop_guard"]
    assert len(uses) == 1
    call = next(c for c in ast.walk(t) if isinstance(c, ast.Call) and any(k is uses[0] for k in c.keywords))
    assert isinstance(call.func, ast.Name) and call.func.id == "build_agents"
    v = uses[0].value
    assert isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "emergency_guard" and [a.id for a in v.args] == ["core"] and not v.keywords


def test_the_n3_invariants_of_bootstrap_still_hold():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pm_wiring", ROOT / "tests" / "support" / "protected_manifest.py")
    pm = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = pm
    spec.loader.exec_module(pm)
    assert pm.check_bootstrap(SOURCE.read_text(encoding="utf-8")) == []


# ---- Negativtests: jede Abweichung wird gefunden -------------------------------------------------------------------------------------------------------------
def real() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_the_real_source_has_no_wiring_problems():
    assert wiring_problems(real()) == []


@pytest.mark.parametrize("name,mutate", [
    ("extra call in build_core", lambda s: s.replace("    return core\n", "    sneak()\n    return core\n", 1)),
    ("guard engages the latch", lambda s: s.replace("        em = core.permissions.emergency\n        return f\"Notaus aktiv", "        em = core.permissions.emergency\n        em.engage('x')\n        return f\"Notaus aktiv", 1)),
    ("guard reads something else", lambda s: s.replace("em.engaged else None\n    return guard\n\n\ndef speech_guard", "em.engaged and core.tools else None\n    return guard\n\n\ndef speech_guard", 1)),
    ("guard removed", lambda s: s.replace("def emergency_guard(", "def other_guard(", 1)),
    ("stop_guard bound to something else", lambda s: s.replace("stop_guard=emergency_guard(core)", "stop_guard=None", 1)),
    ("second stop_guard", lambda s: s.replace("return core\n", "build_agents(stop_guard=emergency_guard(core))\n    return core\n", 1)),
    ("new import", lambda s: s.replace("import sys\n", "import sys\nimport subprocess\n", 1)),
    ("security.confirmation guard weakened", lambda s: s.replace('!= "deny"', '!= "never"', 1)),
    ("function renamed", lambda s: s.replace("def build_core", "def build_core_x", 1)),
])
def test_every_mutation_of_the_wiring_is_found(name, mutate):
    mutated = mutate(real())
    assert mutated != real(), name
    assert wiring_problems(mutated) != [], name
