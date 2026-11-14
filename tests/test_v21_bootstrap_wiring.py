"""V2.1: enge Zusatzpruefung der bootstrap.py-Verdrahtung des Not-Aus-Guards (Aufgabe 2).

Hintergrund: `test_the_ui_tool_only_touches_computer_and_documentation_files` (historischer UIA-Bereichswaechter) verbietet jede Aenderung an bootstrap.py gegenueber origin/main.
Dieser Waechter bleibt UNVERAENDERT. Weil der Not-Aus-Guard laut Projektregel nur in bootstrap.py verdrahtet werden darf, prueft DIESER Test, dass die Aenderung genau und nur
die lesende Guard-Verdrahtung ist - der Sicherheitszweck des Waechters (keine stille Aenderung der Verdrahtung, kein Umgehen der PermissionEngine) bleibt damit vollstaendig erhalten:

  1. Alles ausser `emergency_guard`, `speech_guard` und dem Schluesselwort `stop_guard` ist STRUKTURGLEICH zum geprueften V2.0-Stand (Commit 7c2b4b7): gleiche Funktionen,
     der VOLLSTAENDIGE kanonische AST ist gleich (jede Bedingung, jeder Operator, jedes Argument, jede Reihenfolge, Konstante, Docstring, jeder Import); nur Kommentare und Formatierung sind frei. Eigene Kanonform, kein ast.dump.
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
BASELINE_7C2B4B7 = "cff1cd58e8462dfe6071bdc8e64d1ade5da28651476af5971ea6fc930a7f78e8"
EXEMPT = ("emergency_guard", "speech_guard")
EMERGENCY_GUARD_SHAPE = "1401caeba54bd28e0f83228929f424dc2ceb69d7a2377490d11b88bd4f5d20c1"
SPEECH_GUARD_SHAPE = "61689cda645c4cf3e8a8305e0aee63250a87ae0c2223ecb86fbc6df1634d137a"


def canonical(node: object) -> str:
    """Vollstaendige, formatunabhaengige Form eines AST: Knotenart, alle Felder (Namen, Operatoren, Konstanten, Reihenfolge) - ohne Zeilen, Spalten, Kommentare. Leere Felder
    (None, []) werden ausgelassen, damit Python-Versionen mit zusaetzlichen leeren Feldern (z. B. type_params) dasselbe ergeben. Eigenes Format, kein ast.dump."""
    out: list[str] = []

    def walk(n: object) -> None:
        if isinstance(n, ast.AST):
            out.append(type(n).__name__ + "(")
            for name, value in ast.iter_fields(n):
                if value is None or value == []:
                    continue
                out.append(name + "=")
                walk(value)
            out.append(")")
        elif isinstance(n, list):
            out.append("[")
            for x in n:
                walk(x)
                out.append(",")
            out.append("]")
        else:
            out.append(repr(n))
    walk(node)
    return "".join(out)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _without_docstring(fn: ast.FunctionDef) -> ast.FunctionDef:
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return ast.FunctionDef(fn.name, fn.args, body, fn.decorator_list, fn.returns)            # nur die Felder, die zaehlen (keine Zeilen)


class _DropStopGuard(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        node.keywords = [k for k in node.keywords if k.arg != "stop_guard"]
        return node


def fingerprint(source: str) -> str:
    """Fingerabdruck von bootstrap.py OHNE `emergency_guard`, `speech_guard` und das Schluesselwort `stop_guard`: der vollstaendige kanonische AST (jede Aenderung - Bedingung, Operator,
    Argument, Reihenfolge, Konstante, Docstring, Import, Funktion - aendert ihn). Die ausgenommenen Teile werden unten einzeln und ebenso genau gepinnt."""
    tree = ast.parse(source)
    tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name in EXEMPT)]
    return digest(canonical(_DropStopGuard().visit(tree)))


def shape(source: str, name: str) -> str | None:
    fn = next((n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name), None)
    return None if fn is None else digest(canonical(_without_docstring(fn)))


def wiring_problems(source: str) -> list[str]:
    """Alle Teilpruefungen dieser Datei als Funktion ueber einen Quelltext (fuer Negativtests und den Vorschlag fuer den historischen Waechter). Leere Liste = in Ordnung."""
    problems: list[str] = []
    t = ast.parse(source)
    if fingerprint(source) != BASELINE_7C2B4B7:
        problems.append("bootstrap weicht ausserhalb der Guard-Verdrahtung vom V2.0-Stand ab")
    if shape(source, "emergency_guard") != EMERGENCY_GUARD_SHAPE:
        problems.append("emergency_guard hat nicht genau die geprueften Form")
    if shape(source, "speech_guard") != SPEECH_GUARD_SHAPE:
        problems.append("speech_guard hat nicht genau die geprueften Form")
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


# ---- Option B: die Pruefung muss mindestens so streng sein wie "bootstrap.py darf sich nicht aendern" (vollstaendiger AST-Vergleich) -----------------------------------
@pytest.mark.parametrize("name,mutate", [
    ("condition flipped", lambda s: s.replace("if provider is not original_provider", "if provider is original_provider", 1)),
    ("arguments swapped", lambda s: s.replace("build_computer(settings, tools, permissions)", "build_computer(settings, permissions, tools)", 1)),
    ("argument widened", lambda s: s.replace("ToolRegistry(permissions)", "ToolRegistry(permissions or None)", 1)),
    ("statement dropped", lambda s: s.replace("    core.history = build_history(settings, core, guard)\n", "", 1)),
    ("statement reordered", lambda s: s.replace("    register_emergency_components(core)\n    return core", "    return core\n    register_emergency_components(core)", 1)),
    ("keyword value changed", lambda s: s.replace("budget_audit=agent_budget_audit(permissions.audit)", "budget_audit=None", 1)),
    ("docstring of another function changed", lambda s: s.replace("Why a microphone recording must not start", "Why a microphone recording may start", 1)),
    ("guard reads another attribute", lambda s: s.replace("f\"Notaus aktiv ({em.reason})\" if em.engaged else None\n    return guard\n\n\ndef speech_guard", "f\"Notaus aktiv ({em.source})\" if em.engaged else None\n    return guard\n\n\ndef speech_guard", 1)),
    ("speech_guard no longer delegates", lambda s: s.replace("    return emergency_guard(core)\n", "    return lambda: None\n", 1)),
    ("operator changed in guard", lambda s: s.replace("if em.engaged else None\n    return guard\n\n\ndef speech_guard", "if not em.engaged else None\n    return guard\n\n\ndef speech_guard", 1)),
])
def test_option_b_every_semantic_change_is_found_not_only_additions(name, mutate):
    mutated = mutate(real())
    assert mutated != real(), name
    assert wiring_problems(mutated) != [], name


def test_comments_blank_lines_and_formatting_are_not_changes():
    src = real().replace("    register_emergency_components(core)\n    return core", "    # kommentar\n\n    register_emergency_components(core)   # noch einer\n    return core", 1)
    assert src != real() and wiring_problems(src) == []


def test_the_canonical_form_is_complete_and_independent_of_ast_dump_formatting():
    a, b = ast.parse("x = f(1, y=2)\n"), ast.parse("x   =   f( 1 ,\n y = 2 )  # c\n")
    assert canonical(a) == canonical(b) and canonical(a) != canonical(ast.parse("x = f(1, y=3)\n")) and canonical(a) != canonical(ast.parse("x = f(1, z=2)\n"))
