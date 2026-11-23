"""Simuliert das Zusammenfuehren eines Branches/PR-Heads in einem WEGWERF-Worktree und berichtet nur, was passieren wuerde (Konflikte, geschuetzte Dateien). Reproduzierbar, plattformunabhaengig.

    python scripts/v2/simulate_pr_merge.py origin/claude/v2-186-finalisierung [--base HEAD]

Garantien: der Worktree ist DETACHED (kein Branch wird angelegt oder bewegt), es wird nichts committet, gepusht oder geloescht ausser dem eigenen temporaeren Verzeichnis; der Merge wird
immer abgebrochen; Index und Arbeitsverzeichnis des aufrufenden Checkouts bleiben unberuehrt. Exit 0 = sauber, 1 = Konflikte, 2 = Eingabefehler."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def git(cwd: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300, check=check)


def simulate(repo: Path, ref: str, base: str = "HEAD") -> dict[str, object]:
    for r in (base, ref):
        if git(repo, "rev-parse", "--verify", "--quiet", f"{r}^{{commit}}").returncode != 0:
            return {"ok": False, "error": f"unbekannte Referenz: {r}"}
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-sim-merge-"))
    wt = tmp / "wt"
    try:
        add = git(repo, "worktree", "add", "--detach", str(wt), base)
        if add.returncode != 0:
            return {"ok": False, "error": "Worktree konnte nicht angelegt werden"}
        merge = git(wt, "merge", "--no-commit", "--no-ff", ref)
        conflicts = sorted(git(wt, "diff", "--name-only", "--diff-filter=U").stdout.split())
        touched = sorted(set(git(wt, "diff", "--name-only", "HEAD").stdout.split()) | set(conflicts))
        manifest: set[str] = set()
        for r in (base, ref):                                   # die Manifeste beider Seiten (nicht aus dem Merge-Stand: dort kann das Manifest selbst im Konflikt stehen)
            shown = git(repo, "show", f"{r}:tests/support/protected_manifest.json")
            try:
                manifest |= set(json.loads(shown.stdout).get("files", {})) if shown.returncode == 0 else set()
            except ValueError:
                pass
        return {"ok": True, "base": base, "ref": ref, "clean": merge.returncode == 0 and not conflicts, "conflicts": conflicts, "protected_conflicts": [c for c in conflicts if c in manifest],
                "protected_touched": [t for t in touched if t in manifest], "changed_files": len(touched)}
    finally:
        git(wt, "merge", "--abort")
        git(repo, "worktree", "remove", "--force", str(wt))
        git(repo, "worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ref")
    ap.add_argument("--base", default="HEAD")
    a = ap.parse_args(argv)
    rep = simulate(Path(__file__).resolve().parents[2], a.ref, a.base)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    return 2 if not rep["ok"] else 0 if rep["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
