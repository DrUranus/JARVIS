"""N3-D/N3-B: Hash-Manifest der geschuetzten Dateien und AST-Pruefung der Sicherheitsinvarianten von bootstrap.py.

Reine Standardbibliothek, KEIN git im Testpfad, kein Netzwerk. Das Manifest (`tests/support/protected_manifest.json`) haelt SHA-256 (Zeilenenden auf LF und BOM entfernt, damit
Windows-`autocrlf` denselben Hash ergibt) der Dateien, die PermissionEngine, X0/Not-Aus, Audit, den UI-Vertrag, die Sicherheitsstandards und deren Tests bilden. Herkunft steht im Manifest:
`base_commit` (Stand von `main`, auf dem es erzeugt wurde), Zeitpunkt, Erzeugungsbefehl.

Wichtig und ehrlich: Dieser Vergleich allein kann nicht erkennen, dass ein Branch eine geschuetzte Datei UND das Manifest gemeinsam aendert. Das erkennt nur der Vergleich mit dem Manifest
einer Referenz ausserhalb des Branches:
    python -m tests.support.protected_manifest --verify-against origin/main        (Gate G1, mit vollem Verlauf; unlesbare Referenz = Fehler, nie stilles Gruen)
und der Owner-Review (CODEOWNERS). Das Manifest wird NIE automatisch neu erzeugt: `--write` verlangt `--confirm-owner-review` und ist kein Teil eines Tests."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).resolve().with_suffix(".json")
VERSION = 1
ALGORITHM = "sha256-lf"
GENERATED_BY = "python -m tests.support.protected_manifest --write --confirm-owner-review"
PATHS_DOC = ["src/jarvis/permissions/**/*.py", "src/jarvis/ui_contract/**", "config/jarvis.toml", "tests/test_emergency_stop.py", "tests/test_autonomy_invariants.py", "tests/test_security_*.py"]
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def normalize(data: bytes) -> bytes:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n")


def digest(data: bytes) -> str:
    return hashlib.sha256(normalize(data)).hexdigest()


def _skip(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo")


def protected_paths(root: Path) -> list[Path]:
    found: list[Path] = []
    for sub, pattern in (("src/jarvis/permissions", "*.py"), ("src/jarvis/ui_contract", "*")):
        base = root / sub
        if base.is_dir():
            found += [p for p in base.rglob(pattern) if p.is_file() and not _skip(p)]
    for rel in ("config/jarvis.toml", "tests/test_emergency_stop.py", "tests/test_autonomy_invariants.py"):
        if (root / rel).is_file():
            found.append(root / rel)
    tests = root / "tests"
    if tests.is_dir():
        found += [p for p in tests.glob("test_security_*.py") if p.is_file()]
    return sorted(set(found))


def scan(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in protected_paths(root)}


def compare(manifest_files: dict[str, str], scanned: dict[str, str]) -> list[str]:
    """Abweichungen zwischen Manifest und Baum. Meldet nur Pfade, nie Inhalte."""
    out = [f"geaendert: {p}" for p in sorted(manifest_files) if p in scanned and scanned[p] != manifest_files[p]]
    out += [f"fehlt: {p}" for p in sorted(manifest_files) if p not in scanned]
    out += [f"neu: {p}" for p in sorted(scanned) if p not in manifest_files]
    return out


def diff_manifests(base_files: dict[str, str], new_files: dict[str, str]) -> list[str]:
    """Unterschied zweier Manifeste (Referenz vs. Branch): jeder Eintrag verlangt eine ausdrueckliche Owner-Entscheidung."""
    return compare(base_files, new_files)


def validate_manifest(m: Any) -> list[str]:
    if not isinstance(m, dict):
        return ["Manifest ist kein Objekt"]
    problems: list[str] = []
    if m.get("version") != VERSION:
        problems.append("version unbekannt")
    if m.get("algorithm") != ALGORITHM:
        problems.append("algorithm unbekannt")
    if not isinstance(m.get("base_commit"), str) or not _COMMIT.match(m["base_commit"]):
        problems.append("base_commit ist kein 40-stelliger SHA (Herkunft fehlt)")
    if not isinstance(m.get("generated_at"), str) or not re.match(r"\d{4}-\d\d-\d\dT", m.get("generated_at") or ""):
        problems.append("generated_at fehlt")
    if not isinstance(m.get("generated_by"), str) or not m["generated_by"].strip():
        problems.append("generated_by fehlt")
    files = m.get("files")
    if not isinstance(files, dict) or not files:
        return problems + ["files fehlt oder leer"]
    for path, h in files.items():
        if not isinstance(path, str) or path.startswith(("/", "\\")) or ".." in path.split("/") or re.match(r"^[A-Za-z]:", path) or "\\" in path:
            problems.append(f"unzulaessiger Pfad: {str(path)[:80]}")
        if not isinstance(h, str) or not _SHA.match(h):
            problems.append(f"unzulaessiger Hash fuer {str(path)[:80]}")
    if list(files) != sorted(files):
        problems.append("files nicht sortiert")
    return problems


def build_manifest(root: Path, base_commit: str, now: datetime | None = None) -> dict[str, Any]:
    return {"version": VERSION, "algorithm": ALGORITHM, "base_commit": base_commit, "generated_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generated_by": GENERATED_BY, "paths": PATHS_DOC, "files": dict(sorted(scan(root).items()))}


def verify_against(read_ref_manifest: Callable[[str], Any], current: Any, ref: str) -> list[str]:
    """Gate G1: das Manifest dieses Baums muss dem der Referenz (z. B. origin/main) entsprechen. Unlesbare/ungueltige Referenz = Fehler (fail closed)."""
    try:
        base = read_ref_manifest(ref)
    except Exception as exc:  # noqa: BLE001 - jeder Lesefehler ist ein Fehler, nie ein stilles Gruen
        return [f"Referenz-Manifest von {ref} nicht lesbar ({type(exc).__name__}): kein Vergleich moeglich"]
    if not isinstance(base, dict) or not isinstance(base.get("files"), dict) or not isinstance(current, dict) or not isinstance(current.get("files"), dict):
        return [f"Referenz-Manifest von {ref} oder aktuelles Manifest ungueltig"]
    return diff_manifests(base["files"], current["files"])


# ---- N3-B: Sicherheitsinvarianten von bootstrap.py -----------------------------------------------------------------------------------------------------------
EMERGENCY_WRITERS = frozenset({"reset", "reset_emergency_stop", "engage", "disengage", "trigger", "run_stoppers"})


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def check_bootstrap(source: str) -> list[str]:
    """AST-Pruefung der Verdrahtung: eine PermissionEngine, vor allem anderen gebaut, an die ToolRegistry uebergeben; Not-Aus wird nur registriert, nie ausgeloest oder aufgehoben;
    der Bestaetigungsanbieter nur unter `security.confirmation != "deny"`. Meldet Texte, wirft nie."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["bootstrap.py nicht parsebar"]
    problems: list[str] = []
    core = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_core"), None)
    if core is None:
        return ["build_core fehlt"]
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    if any(isinstance(c.func, ast.Name) and c.func.id == "PermissionEngine" or isinstance(c.func, ast.Attribute) and c.func.attr == "legacy" and "PermissionEngine" in ast.dump(c.func) for c in calls):
        problems.append("PermissionEngine wird in bootstrap.py direkt gebaut (nur build_permission_engine ist erlaubt)")
    registries = [c for c in calls if _call_name(c) == "ToolRegistry"]
    if len(registries) != 1 or not (registries[0].args and isinstance(registries[0].args[0], ast.Name) and registries[0].args[0].id == "permissions"):
        problems.append("ToolRegistry muss genau einmal mit der PermissionEngine (permissions) gebaut werden")
    assigns = [n for n in ast.walk(core) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and _call_name(n.value) == "build_permission_engine"
               and any(isinstance(t, ast.Name) and t.id == "permissions" for t in n.targets)]
    engine_calls = [c for c in ast.walk(core) if isinstance(c, ast.Call) and _call_name(c) == "build_permission_engine"]
    if not assigns:
        problems.append("build_core: permissions = build_permission_engine(...) fehlt")
    elif len(engine_calls) != 1:
        problems.append("build_permission_engine muss in build_core genau einmal aufgerufen werden")
    else:
        line = assigns[0].lineno
        early = sorted({_call_name(c) or "?" for c in ast.walk(core) if isinstance(c, ast.Call) and c.lineno < line
                        and ((_call_name(c) or "").startswith(("build_", "register_")) or _call_name(c) in ("ToolRegistry", "JarvisCore"))})
        if early:
            problems.append(f"vor der Berechtigungspruefung wird bereits gebaut/registriert: {', '.join(early)}")
    if any(isinstance(c.func, ast.Attribute) and c.func.attr in EMERGENCY_WRITERS for c in calls):
        problems.append("bootstrap.py loest den Not-Aus aus oder hebt ihn auf (engage/reset/trigger/run_stoppers sind nicht erlaubt)")
    body_calls = [c for c in ast.walk(core) if isinstance(c, ast.Call)]
    if not any(_call_name(c) == "register_emergency_components" for c in body_calls):
        problems.append("build_core: register_emergency_components(core) fehlt")
    for n in ast.walk(core):
        if isinstance(n, ast.Call) and _call_name(n) == "set_confirmation_provider":
            guarded = False
            for parent in ast.walk(core):
                if isinstance(parent, ast.If) and any(x is n for x in ast.walk(parent)) and any(isinstance(cmp, ast.Compare) and any(isinstance(o, ast.NotEq) for o in cmp.ops)
                                                                                                  and any(isinstance(k, ast.Constant) and k.value == "deny" for k in cmp.comparators)
                                                                                                  for cmp in ast.walk(parent.test)):
                    guarded = True
            if not guarded:
                problems.append("set_confirmation_provider nur unter security.confirmation != \"deny\"")
    if not any(isinstance(r, ast.Return) and isinstance(r.value, ast.Name) and r.value.id == "core" for r in ast.walk(core)):
        problems.append("build_core muss core zurueckgeben (return core)")
    return problems


# ---- Kommandozeile (nur fuer den Owner / Gate G1; nicht von Tests benutzt) -------------------------------------------------------------------------------------------
def _git_show_manifest(ref: str) -> Any:
    out = subprocess.run(["git", "show", f"{ref}:tests/support/protected_manifest.json"], cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="protected_manifest", description="Hash-Manifest der geschuetzten Dateien (N3-D). Nur lesend, ausser --write (Owner).")
    ap.add_argument("--check", action="store_true", help="Baum gegen das Manifest pruefen (Standard)")
    ap.add_argument("--verify-against", metavar="REF", help="Manifest mit dem der Referenz vergleichen (Gate G1), z. B. origin/main")
    ap.add_argument("--write", action="store_true", help="Manifest NEU erzeugen (nur Owner-Entscheidung)")
    ap.add_argument("--confirm-owner-review", action="store_true", help="bestaetigt, dass der Owner die Aenderung geprueft hat (Pflicht fuer --write)")
    ap.add_argument("--base-commit", help="SHA von main, auf dem das Manifest erzeugt wird (Herkunft)")
    a = ap.parse_args(argv)
    if a.write:
        if not a.confirm_owner_review or not a.base_commit or not _COMMIT.match(a.base_commit):
            print("Abbruch: --write braucht --confirm-owner-review und --base-commit <40-stelliger SHA>. Nichts geschrieben.", file=sys.stderr)
            return 2
        new = build_manifest(ROOT, a.base_commit)
        old = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {"files": {}}
        for line in diff_manifests(old.get("files", {}), new["files"]) or ["(keine Aenderung der Hashes)"]:
            print("  " + line)
        MANIFEST_PATH.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Manifest geschrieben: {MANIFEST_PATH.relative_to(ROOT)} ({len(new['files'])} Dateien). Im PR vom Owner pruefen lassen.")
        return 0
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    problems = validate_manifest(manifest) + compare(manifest.get("files", {}), scan(ROOT))
    if a.verify_against:
        problems += verify_against(_git_show_manifest, manifest, a.verify_against)
    for p in problems:
        print(p)
    print("OK" if not problems else f"{len(problems)} Abweichung(en)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
