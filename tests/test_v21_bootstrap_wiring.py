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
