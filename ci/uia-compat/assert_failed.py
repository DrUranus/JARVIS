"""Gegenprobe: beweist, dass ein absichtlich falscher Lauf des Tests aus dem erwarteten Grund rot war. Nutzung: assert_failed.py ERGEBNIS.json (--exact|--contains) NAME..."""
from __future__ import annotations

import json
import sys


def check(results: list[dict], names: list[str], exact: bool) -> bool:
    failed = {r["name"] for r in results if not r.get("ok") and r.get("blocking", True)}
    if not failed:
        return False
    return failed == set(names) if exact else set(names) <= failed


def main(argv: list[str]) -> int:
    data = json.load(open(argv[1], encoding="utf-8"))
    exact = argv[2] == "--exact"
    ok = check(data.get("checks", []), argv[3:], exact)
    failed = sorted(r["name"] for r in data.get("checks", []) if not r.get("ok") and r.get("blocking", True))
    print(f"Fehlgeschlagen: {failed}; erwartet ({'genau' if exact else 'mindestens'}): {argv[3:]} -> {'bestaetigt' if ok else 'NICHT wie erwartet'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
