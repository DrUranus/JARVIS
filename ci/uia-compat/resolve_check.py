"""Prueft den Bericht von `pip install --dry-run --report` gegen die gepruften Pins: genau die vier Pakete, genau diese Versionen, nur Wheels (kein setup.py wird ausgefuehrt),
jeweils mit einem Hash aus requirements.txt, nichts zurueckgezogen. Nur Standardbibliothek."""
from __future__ import annotations

import json
import re
import sys

LINE = re.compile(r"([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9.+!-]*)((?:\s+--hash=sha256:[0-9a-f]{64})+)\s*(?:#.*)?")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(text: str) -> dict[str, tuple[str, set[str]]]:
    out: dict[str, tuple[str, set[str]]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE.fullmatch(line)
        if not m:
            raise ValueError(f"requirements: Zeile ist nicht 'name==version' mit sha256-Hash: {line[:80]!r}")
        out[norm(m.group(1))] = (m.group(2), set(re.findall(r"sha256:([0-9a-f]{64})", m.group(3))))
    return out


def verify(report: dict, requirements: str) -> list[str]:
    expected = parse_requirements(requirements)
    items = report.get("install") if isinstance(report, dict) else None
    if not isinstance(items, list):
        return ["Bericht ohne Liste 'install' (ungueltig)"]
    problems: list[str] = []
    seen: set[str] = set()
    for item in items:
        meta, info = item.get("metadata") or {}, item.get("download_info") or {}
        name = norm(str(meta.get("name", "")))
        seen.add(name)
        if name not in expected:
            problems.append(f"unerwartetes Paket in der Aufloesung: {name}")
            continue
        version, hashes = expected[name]
        if meta.get("version") != version:
            problems.append(f"{name}: Version {meta.get('version')} statt {version}")
        if not str(info.get("url", "")).endswith(".whl"):
            problems.append(f"{name}: kein Wheel ({str(info.get('url', ''))[-60:]}); Quellpakete fuehren Installationsskripte aus")
        sha = ((info.get("archive_info") or {}).get("hashes") or {}).get("sha256")
        if sha not in hashes:
            problems.append(f"{name}: Hash {sha} steht nicht in requirements.txt")
        if item.get("is_yanked"):
            problems.append(f"{name}: Version ist zurueckgezogen")
    for name in sorted(set(expected) - seen):
        problems.append(f"{name} fehlt in der Aufloesung")
    return problems


def main(argv: list[str]) -> int:
    report = json.load(open(argv[1], encoding="utf-8"))
    problems = verify(report, open(argv[2], encoding="utf-8").read())
    for item in report.get("install", []):
        print(f"  {item['metadata']['name']}=={item['metadata']['version']}  {item['download_info']['url'].rsplit('/', 1)[-1]}")
    for p in problems:
        print(f"::error::{p}")
    print("Aufloesung entspricht den Pruef-Pins." if not problems else f"{len(problems)} Abweichung(en): STOPP.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
