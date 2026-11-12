"""N3-D/N3-B: checkout-unabhaengige Pruefung der geschuetzten Dateien (Hash-Manifest) und der Sicherheitsinvarianten von bootstrap.py (AST).

Anforderungen aus der Freigabe: laeuft in JEDEM Checkout (kein git, kein Netzwerk, kein origin/main, KEIN Skip); eine stille Aenderung einer geschuetzten Datei macht den Test rot; das
Manifest wird nie automatisch neu erzeugt; Datei UND Manifest gemeinsam zu aendern gilt nicht als genehmigt, weil nur der Vergleich mit dem Manifest auf `main` (Gate G1, `--verify-against`)
oder der Owner-Review es erkennt - das ist hier als eigener Test festgehalten, nicht verschwiegen."""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tests" / "support" / "protected_manifest.py"
MANIFEST = ROOT / "tests" / "support" / "protected_manifest.json"
spec = importlib.util.spec_from_file_location("protected_manifest_under_test", TOOL)
pm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pm                                      # noetig fuer dataclasses mit 'from __future__ import annotations'
spec.loader.exec_module(pm)

MUST_BE_PROTECTED = ["src/jarvis/permissions/engine.py", "src/jarvis/permissions/emergency.py", "src/jarvis/permissions/audit.py", "src/jarvis/permissions/budget.py",
                     "src/jarvis/permissions/factory.py", "src/jarvis/permissions/policy.py", "config/jarvis.toml", "tests/test_emergency_stop.py", "tests/test_autonomy_invariants.py",
                     "tests/test_security_engine.py", "tests/test_security_bypass.py"]


def load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# ---- das echte Manifest gegen den echten Baum (kein Skip, kein git) ---------------------------------------------------------------------------------------------
def test_manifest_is_well_formed_and_has_a_traceable_origin():
    m = load_manifest()
    assert pm.validate_manifest(m) == []
    assert re.fullmatch(r"[0-9a-f]{40}", m["base_commit"]) and m["algorithm"] == "sha256-lf" and m["version"] == 1
    assert m["generated_by"].startswith("python -m tests.support.protected_manifest --write") and re.match(r"\d{4}-\d\d-\d\dT", m["generated_at"])


def test_every_required_file_is_listed():
    files = load_manifest()["files"]
    missing = [p for p in MUST_BE_PROTECTED if p not in files]
    assert not missing, missing                                       # das Manifest kann nicht still schrumpfen


def test_the_protected_files_on_disk_match_the_manifest_exactly():
    problems = pm.compare(load_manifest()["files"], pm.scan(ROOT))
    assert problems == [], "geschuetzte Dateien weichen vom Manifest ab (nur der Owner darf das Manifest aendern, siehe docs/TESTING.md):\n" + "\n".join(problems)


def _imports(tree):
    return {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}


def test_the_check_needs_no_git_no_network_and_never_skips():
    own = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assert not {"subprocess", "socket", "urllib", "http", "requests"} & _imports(own)
    skips = [n for n in ast.walk(own) if isinstance(n, ast.Attribute) and n.attr in ("skip", "skipif", "importorskip", "xfail")]
    assert skips == []                                                  # kein Skip, nirgends in dieser Datei
    tool = ast.parse(TOOL.read_text(encoding="utf-8"))
    assert not {"socket", "urllib", "http", "requests"} & _imports(tool)


# ---- Normalisierung --------------------------------------------------------------------------------------------------------------------------------------
def test_line_endings_and_bom_do_not_change_the_digest():
    assert pm.digest(b"a\nb\n") == pm.digest(b"a\r\nb\r\n") == pm.digest(b"\xef\xbb\xbfa\nb\n")
    assert pm.digest(b"a\nb\n") != pm.digest(b"a\nb \n") and pm.digest(b"a\n") != pm.digest(b"b\n")


# ---- Manipulationstests im tmp_path ----------------------------------------------------------------------------------------------------------------------------
def make_tree(tmp_path):
    for rel, text in {"src/jarvis/permissions/engine.py": "engine = 1\n", "src/jarvis/permissions/audit.py": "audit = 1\n", "src/jarvis/permissions/__init__.py": "",
                      "config/jarvis.toml": "[x]\nenabled = false\n", "tests/test_emergency_stop.py": "def test_a(): pass\n", "tests/test_autonomy_invariants.py": "x = 1\n",
                      "tests/test_security_engine.py": "y = 1\n", "src/jarvis/other.py": "free = 1\n"}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_scan_finds_only_the_protected_set_and_ignores_caches(tmp_path):
    root = make_tree(tmp_path)
    (root / "src/jarvis/permissions/__pycache__").mkdir()
    (root / "src/jarvis/permissions/__pycache__/engine.cpython-313.pyc").write_bytes(b"x")
    files = pm.scan(root)
    assert "src/jarvis/other.py" not in files and "src/jarvis/permissions/engine.py" in files and not any("pycache" in f or f.endswith(".pyc") for f in files)


@pytest.mark.parametrize("mutation,expect", [
    (lambda r: (r / "src/jarvis/permissions/engine.py").write_text("engine = 2\n"), "geaendert: src/jarvis/permissions/engine.py"),
    (lambda r: (r / "config/jarvis.toml").write_text("[x]\nenabled = true\n"), "geaendert: config/jarvis.toml"),
    (lambda r: (r / "src/jarvis/permissions/audit.py").unlink(), "fehlt: src/jarvis/permissions/audit.py"),
    (lambda r: (r / "src/jarvis/permissions/new_bypass.py").write_text("x = 1\n"), "neu: src/jarvis/permissions/new_bypass.py"),
    (lambda r: (r / "tests/test_security_new.py").write_text("x = 1\n"), "neu: tests/test_security_new.py"),
    (lambda r: (r / "tests/test_emergency_stop.py").write_text("def test_a(): assert True\n"), "geaendert: tests/test_emergency_stop.py"),
])
def test_any_change_deletion_or_addition_in_the_protected_set_is_found(tmp_path, mutation, expect):
    root = make_tree(tmp_path)
    manifest = pm.scan(root)
    assert pm.compare(manifest, pm.scan(root)) == []
    mutation(root)
    assert expect in pm.compare(manifest, pm.scan(root))


def test_the_report_never_contains_file_contents(tmp_path):
    root = make_tree(tmp_path)
    manifest = pm.scan(root)
    (root / "src/jarvis/permissions/engine.py").write_text("GEHEIMER-INHALT-123\n")
    assert "GEHEIMER-INHALT" not in "\n".join(pm.compare(manifest, pm.scan(root)))


# ---- Datei UND Manifest gemeinsam geaendert: nicht still genehmigt --------------------------------------------------------------------------------------------
def test_changing_file_and_manifest_together_passes_the_local_check_but_is_flagged_against_the_baseline_manifest(tmp_path):
    root = make_tree(tmp_path)
    baseline = pm.scan(root)
    (root / "src/jarvis/permissions/engine.py").write_text("engine = 'weakened'\n")
    regenerated = pm.scan(root)
    assert pm.compare(regenerated, pm.scan(root)) == []                       # ehrlich: lokal allein nicht erkennbar
    flagged = pm.diff_manifests(baseline, regenerated)
    assert flagged == ["geaendert: src/jarvis/permissions/engine.py"]          # ... aber Gate G1 (--verify-against <Referenz>) und der Owner-Review sehen es


def test_verify_against_fails_closed_when_the_reference_cannot_be_read_and_on_any_difference():
    cur = {"version": 1, "files": {"a.py": "1" * 64}}
    assert pm.verify_against(lambda ref: cur, cur, "origin/main") == []
    changed = {"version": 1, "files": {"a.py": "2" * 64}}
    out = pm.verify_against(lambda ref: changed, cur, "origin/main")
    assert out and "geaendert: a.py" in out[0] + "".join(out)

    def boom(ref):
        raise OSError("kein git")
    out = pm.verify_against(boom, cur, "origin/main")
    assert out and "nicht lesbar" in " ".join(out)                              # unlesbare Referenz = rot, kein stilles Gruen
    assert pm.verify_against(lambda ref: {"nonsense": 1}, cur, "origin/main")


def test_the_manifest_is_never_regenerated_by_a_test_or_without_explicit_owner_confirmation():
    own = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "") for n in ast.walk(own) if isinstance(n, ast.Call)}
    assert "build_manifest" not in called                                           # kein Test erzeugt das Manifest
    assert "--confirm-owner-review" in TOOL.read_text(encoding="utf-8")
    before = MANIFEST.read_bytes()
    assert pm.main(["--write", "--base-commit", "0" * 40]) == 2                  # ohne Bestaetigung: Abbruch
    assert pm.main(["--write", "--confirm-owner-review"]) == 2                   # ohne Herkunft (base-commit): Abbruch
    assert pm.main(["--write", "--confirm-owner-review", "--base-commit", "nicht-ein-sha"]) == 2
    assert MANIFEST.read_bytes() == before                                        # nichts geschrieben


def test_validate_manifest_rejects_broken_provenance_and_paths():
    good = load_manifest()
    for key, bad in (("base_commit", "nicht-ein-sha"), ("algorithm", "md5"), ("version", 2), ("generated_by", "")):
        m = dict(good, **{key: bad})
        assert pm.validate_manifest(m), key
    m = dict(good, files=dict(good["files"], **{"../etc/passwd": "0" * 64}))
    assert pm.validate_manifest(m)
    m = dict(good, files=dict(good["files"], **{"/abs/path.py": "0" * 64}))
    assert pm.validate_manifest(m)
    m = dict(good, files={**good["files"], "x.py": "zz"})
    assert pm.validate_manifest(m)
    assert pm.validate_manifest({}) and pm.validate_manifest("kaputt")


# ---- N3-B: Sicherheitsinvarianten von bootstrap.py (AST) ---------------------------------------------------------------------------------------------------------
def bootstrap_source():
    return (ROOT / "src" / "jarvis" / "bootstrap.py").read_text(encoding="utf-8")


def test_the_real_bootstrap_keeps_its_security_invariants():
    assert pm.check_bootstrap(bootstrap_source()) == []


BASE = '''
def build_core(settings):
    provider = create_provider(settings.llm)
    guard = SecretGuard.from_environment(extra=[])
    permissions = build_permission_engine(settings, redactor=guard)
    tools = register_builtin_tools(ToolRegistry(permissions), include_demo=True)
    core = JarvisCore(provider=provider, tools=tools)
    if assistant_ui is not None and settings.security.confirmation != "deny":
        permissions.set_confirmation_provider(assistant_ui.confirmation_provider, source="assistant")
    register_emergency_components(core)
    return core
'''


def test_the_checker_accepts_the_reference_shape():
    assert pm.check_bootstrap(BASE) == []


@pytest.mark.parametrize("name,source,fragment", [
    ("engine not built", BASE.replace("permissions = build_permission_engine(settings, redactor=guard)", "permissions = None"), "build_permission_engine"),
    ("engine built twice", BASE.replace("tools = ", "permissions = build_permission_engine(settings)\n    tools = "), "genau einmal"),
    ("engine constructed directly", BASE.replace("permissions = build_permission_engine(settings, redactor=guard)", "permissions = PermissionEngine()"), "PermissionEngine"),
    ("legacy engine", BASE.replace("permissions = build_permission_engine(settings, redactor=guard)", "permissions = PermissionEngine.legacy()"), "PermissionEngine"),
    ("registry without the engine", BASE.replace("ToolRegistry(permissions)", "ToolRegistry()"), "ToolRegistry"),
    ("second registry", BASE.replace("core = JarvisCore", "other = ToolRegistry(permissions)\n    core = JarvisCore"), "ToolRegistry"),
    ("subsystem before the engine", BASE.replace("    permissions = build_permission_engine(settings, redactor=guard)", "    early = build_files(settings)\n    permissions = build_permission_engine(settings, redactor=guard)"), "vor der Berechtigungspruefung"),
    ("tools before the engine", BASE.replace("    permissions = build_permission_engine(settings, redactor=guard)", "    t0 = register_builtin_tools(None)\n    permissions = build_permission_engine(settings, redactor=guard)"), "vor der Berechtigungspruefung"),
    ("emergency reset", BASE.replace("register_emergency_components(core)", "permissions.emergency.reset()\n    register_emergency_components(core)"), "Not-Aus"),
    ("emergency engage", BASE.replace("register_emergency_components(core)", "core.permissions.emergency.engage('x')\n    register_emergency_components(core)"), "Not-Aus"),
    ("emergency stoppers not registered", BASE.replace("    register_emergency_components(core)\n", ""), "register_emergency_components"),
    ("confirmation provider unconditional", BASE.replace('    if assistant_ui is not None and settings.security.confirmation != "deny":\n    ', ""), "set_confirmation_provider"),
    ("confirmation provider for 'allow' mode", BASE.replace('!= "deny"', '== "allow"'), "set_confirmation_provider"),
    ("no build_core", BASE.replace("def build_core", "def build_other"), "build_core"),
    ("no return of core", BASE.replace("return core", "return None"), "return"),
])
def test_the_checker_finds_every_weakened_bootstrap(name, source, fragment):
    problems = pm.check_bootstrap(source)
    assert problems and any(fragment in p for p in problems), (name, problems)


def test_the_checker_survives_unparsable_source():
    assert pm.check_bootstrap("def build_core(:") != []
