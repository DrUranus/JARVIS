"""Prueft die installierten Pakete in der Test-Umgebung: Lizenzangaben (keine fehlende Angabe, kein GPL/AGPL/LGPL), Lizenzdateien (nur Bericht), .pth-Dateien (nur die bekannte
von pywin32) und Skripte (nur Bericht). Laeuft mit dem Python der Test-Umgebung, nur Standardbibliothek. Es wird nichts ausgefuehrt."""
from __future__ import annotations

import re
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

PACKAGES = ("pywinauto", "six", "comtypes", "pywin32")
COPYLEFT = re.compile(r"(?i)\b[al]?gpl\b|general public license")
LICENSE_FILE = re.compile(r"(?i)(^|[/\\])(licen[cs]e|copying)[^/\\]*$")
ALLOWED_PTH = {"pywin32.pth": {"win32", "win32\\lib", "pythonwin", "import pywin32_bootstrap"}}      # kleingeschrieben verglichen


def license_problems(name: str, license_field: str, classifiers: list[str], files: list[str]) -> list[str]:
    problems: list[str] = []
    license_classifiers = [c for c in classifiers if c.startswith("License ::")]
    has_info = bool(license_field.strip()) or bool(license_classifiers) or any(LICENSE_FILE.search(f) for f in files)
    if not has_info:
        problems.append(f"{name}: keine Lizenzangabe (weder Feld, Klassifikator noch Datei)")
    if COPYLEFT.search(" ".join([license_field[:2000], *license_classifiers])):
        problems.append(f"{name}: Copyleft-Hinweis in den Lizenzangaben ({license_field[:60]!r}, {license_classifiers[:2]})")
    return problems


def pth_problems(pth: dict[str, list[str]]) -> list[str]:
    problems: list[str] = []
    for fname, lines in pth.items():
        if fname not in ALLOWED_PTH:
            problems.append(f"unbekannte .pth-Datei (fuehrt beim Start Pfade oder Code ein): {fname}")
            continue
        for line in (l.strip() for l in lines):
            if line and not line.startswith("#") and line.lower() not in ALLOWED_PTH[fname]:
                problems.append(f"{fname}: unerwartete Zeile {line[:60]!r}")
    return problems


def main() -> int:
    problems: list[str] = []
    for name in PACKAGES:
        dist = metadata.distribution(name)
        meta = dist.metadata
        files = [str(f) for f in (dist.files or [])]
        license_field = meta.get("License-Expression") or meta.get("License") or ""
        classifiers = meta.get_all("Classifier") or []
        found = [f for f in files if LICENSE_FILE.search(f)]
        scripts = [f for f in files if re.search(r"(?i)scripts[/\\]", f)]
        print(f"{name} {dist.version}")
        print(f"  Lizenz-Feld: {license_field[:70]!r}  Klassifikatoren: {[c for c in classifiers if c.startswith('License ::')]}")
        print(f"  Lizenzdateien: {found or 'keine im Paket'}")
        print(f"  Skripte/Programme im Paket: {len(scripts)} {scripts[:6]}")
        problems += license_problems(name, license_field, classifiers, files)
    pth = {p.name: p.read_text(encoding="utf-8", errors="replace").splitlines() for p in Path(sysconfig.get_paths()["purelib"]).glob("*.pth")}
    for fname, lines in pth.items():
        print(f".pth {fname}: {[l for l in lines if l.strip()]}")
    problems += pth_problems(pth)
    for p in problems:
        print(f"::error::{p}")
    print("Lizenz- und Pfaddatei-Pruefung bestanden." if not problems else f"{len(problems)} Befund(e): STOPP.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
