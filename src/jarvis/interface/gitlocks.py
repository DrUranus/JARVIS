"""Sicherer Diagnoseablauf fuer Git-Sperrdateien (`*.lock` in `.git`), typisch in OneDrive-Ordnern ("Unable to create '.git/index.lock': File exists").

`python -m jarvis.interface.gitlocks [PFAD]` ist standardmaessig NUR LESEND: es listet die Sperrdateien, prueft, ob Git-Prozesse laufen, und sagt je Datei, ob sie
verwaist aussieht. Entfernt wird nichts, ausser mit `--remove --yes`, und dann nur eine Datei, die ALLE Bedingungen erfuellt: Name endet auf `.lock`, liegt innerhalb von `.git`,
ist eine kleine regulaere Datei (kein Link, kein Ordner), mindestens `--min-age` Sekunden alt, und unmittelbar vor dem Loeschen laufen nachweislich keine Git-Prozesse.
Ist die Prozessliste nicht lesbar, wird nie geloescht. Es werden keine Prozesse beendet und keine anderen Dateien angefasst."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

MIN_AGE_DEFAULT = 120.0           # Sekunden: juengere Sperren gehoeren sehr wahrscheinlich zu einer laufenden Aktion
MAX_LOCK_BYTES = 4096             # eine echte Sperrdatei ist (fast) leer; eine groessere Datei wird nie automatisch entfernt
MAX_SCAN = 200


@dataclass(frozen=True)
class LockFile:
    path: Path
    size: int
    age: float
    removable_shape: bool         # kleine regulaere Datei innerhalb von .git, kein Link


@dataclass(frozen=True)
class Verdict:
    lock: LockFile
    state: str                    # active | unknown | young | orphan | unsafe
    why: str


def find_git_dir(start: str | os.PathLike[str]) -> Path | None:
    p = Path(start).resolve()
    for cand in (p, *p.parents):
        g = cand / ".git"
        if g.is_dir():
            return g
        if g.is_file():                                     # Worktree/Submodul: "gitdir: <pfad>"
            try:
                first = g.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            except (OSError, IndexError):
                return None
            if first.startswith("gitdir:"):
                target = Path(first[7:].strip())
                target = target if target.is_absolute() else (cand / target)
                return target.resolve() if target.is_dir() else None
    return None


def scan(git_dir: Path, now: float | None = None) -> list[LockFile]:
    """Alle `*.lock`-Dateien in `.git` (nicht in `objects/pack`, begrenzt)."""
    now = time.time() if now is None else now
    root = git_dir.resolve()
    out: list[LockFile] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if Path(dirpath).name == "pack" and Path(dirpath).parent.name == "objects":
            dirnames[:] = []
            continue
        for name in filenames:
            if not name.endswith(".lock"):
                continue
            f = Path(dirpath) / name
            try:
                st = f.lstat()
            except OSError:
                continue
            inside = root in f.resolve().parents if not f.is_symlink() else False
            regular = f.is_file() and not f.is_symlink()
            out.append(LockFile(f, st.st_size, max(0.0, now - st.st_mtime), bool(regular and inside and st.st_size <= MAX_LOCK_BYTES)))
            if len(out) >= MAX_SCAN:
                return out
    return sorted(out, key=lambda l: str(l.path))


def git_processes(platform: str | None = None, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                  proc_root: str = "/proc") -> list[str] | None:
    """Namen laufender Git-Prozesse; None, wenn die Liste nicht lesbar ist (dann gilt: unbekannt, nie loeschen)."""
    platform = sys.platform if platform is None else platform
    names: list[str] = []
    try:
        if platform.startswith("win"):
            cp = run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=20, check=False)
            if cp.returncode != 0:
                return None
            for line in cp.stdout.splitlines():
                first = line.split(",")[0].strip().strip('"').lower()
                if first.startswith("git") and first.endswith(".exe"):
                    names.append(first)
        else:
            root = Path(proc_root)
            if not root.is_dir():
                return None
            for d in root.iterdir():
                if d.name.isdigit():
                    try:
                        comm = (d / "comm").read_text(encoding="utf-8", errors="replace").strip().lower()
                    except OSError:
                        continue
                    if comm.startswith("git"):
                        names.append(comm)
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted(names)


def judge(locks: Sequence[LockFile], procs: list[str] | None, min_age: float = MIN_AGE_DEFAULT) -> list[Verdict]:
    out = []
    for l in locks:
        if not l.removable_shape:
            out.append(Verdict(l, "unsafe", "keine kleine regulaere Datei innerhalb von .git (Link, Ordner oder zu gross): wird nie automatisch entfernt"))
        elif procs is None:
            out.append(Verdict(l, "unknown", "die Prozessliste ist nicht lesbar: es wird nichts entfernt"))
        elif procs:
            out.append(Verdict(l, "active", f"Git-Prozess(e) laufen ({', '.join(sorted(set(procs))[:4])}): Sperre nicht entfernen, erst beenden lassen"))
        elif l.age < min_age:
            out.append(Verdict(l, "young", f"erst {int(l.age)} s alt (< {int(min_age)} s): kurz warten und erneut pruefen"))
        else:
            out.append(Verdict(l, "orphan", f"kein Git-Prozess und {int(l.age)} s alt: sieht verwaist aus (haeufig nach Absturz oder OneDrive-Sync)"))
    return out


def in_onedrive(path: Path, env: dict[str, str] | None = None) -> bool:
    env = dict(os.environ) if env is None else env
    p = str(path).lower()
    roots = [env.get(k, "").lower() for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    return "onedrive" in p or any(r and p.startswith(r) for r in roots)


def report(git_dir: Path, verdicts: Sequence[Verdict], procs: list[str] | None) -> str:
    lines = [f"Git-Sperrdateien in {git_dir} (nur lesend, es wird nichts entfernt)"]
    if in_onedrive(git_dir):
        lines.append("  Hinweis: Das Repository liegt in einem OneDrive-Ordner. OneDrive kann Dateien waehrend Git-Aktionen sperren oder verzoegert synchronisieren; "
                     "ein Klon ausserhalb von OneDrive (z. B. C:\\dev\\JARVIS) vermeidet das Problem dauerhaft. SQLite-Dateien (Gedaechtnis, Journal) gehoeren ebenfalls nicht in OneDrive.")
    lines.append(f"  Git-Prozesse: {'unbekannt (Liste nicht lesbar)' if procs is None else (', '.join(procs) if procs else 'keine')}")
    if not verdicts:
        lines.append("  Keine *.lock-Dateien gefunden. Ein Git-Fehler hat dann eine andere Ursache (Rechte, Antivirus, OneDrive-Synchronisation pausieren).")
    for v in verdicts:
        rel = v.lock.path
        lines.append(f"  [{v.state.upper():7}] {rel} ({v.lock.size} Byte): {v.why}")
    if any(v.state == "orphan" for v in verdicts):
        lines.append("  Entfernen (nur verwaiste, nach erneuter Prozesspruefung): python -m jarvis.interface.gitlocks <Pfad> --remove --yes")
    return "\n".join(lines)


def remove_orphans(git_dir: Path, min_age: float = MIN_AGE_DEFAULT, procs_fn: Callable[[], list[str] | None] = git_processes) -> list[Path]:
    """Entfernt genau die verwaisten Sperren; Prozessliste und Alter werden unmittelbar vor jedem Loeschen erneut geprueft."""
    removed: list[Path] = []
    for v in judge(scan(git_dir), procs_fn(), min_age):
        if v.state != "orphan":
            continue
        fresh = judge(scan_one(git_dir, v.lock.path), procs_fn(), min_age)
        if len(fresh) == 1 and fresh[0].state == "orphan":
            try:
                v.lock.path.unlink()
                removed.append(v.lock.path)
            except OSError:
                pass
    return removed


def scan_one(git_dir: Path, path: Path) -> list[LockFile]:
    return [l for l in scan(git_dir) if l.path == path]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.interface.gitlocks", description="Git-Sperrdateien sicher diagnostizieren (standardmaessig nur lesend)")
    ap.add_argument("path", nargs="?", default=".", help="Repository-Ordner (Standard: aktueller Ordner)")
    ap.add_argument("--remove", action="store_true", help="verwaiste Sperren entfernen (nur zusammen mit --yes)")
    ap.add_argument("--yes", action="store_true", help="bestaetigt --remove")
    ap.add_argument("--min-age", type=float, default=MIN_AGE_DEFAULT, help=f"Mindestalter in Sekunden (Standard {int(MIN_AGE_DEFAULT)})")
    args = ap.parse_args(argv)
    git_dir = find_git_dir(args.path)
    if git_dir is None:
        print(f"Kein Git-Repository gefunden ab {Path(args.path).resolve()}.", file=sys.stderr)
        return 2
    procs = git_processes()
    verdicts = judge(scan(git_dir), procs, max(0.0, args.min_age))
    print(report(git_dir, verdicts, procs))
    if args.remove and not args.yes:
        print("  --remove braucht zusaetzlich --yes; nichts wurde entfernt.")
        return 1
    if args.remove and args.yes:
        removed = remove_orphans(git_dir, max(0.0, args.min_age))
        print(f"  Entfernt: {len(removed)} Datei(en)." + "".join(f"\n    {p}" for p in removed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
