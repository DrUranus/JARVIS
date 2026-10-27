"""Wertet einen pytest-JUnit-Bericht aus: Markdown-Zusammenfassung, Annotationen fuer Fehler, Nachweisdatei mit Commit.

Aufruf: junit_summary.py <junit.xml> <evidence.json>; Umgebung: HEAD_SHA, EVIDENCE_NAME. Exit 1, wenn kein Test bestanden hat,
ein Test fehlgeschlagen ist oder der Bericht fehlt. Uebersprungene Tests zaehlen nie als bestanden.
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

ID_RE = re.compile(r"[A-Za-z0-9_./:\[\]-]{1,200}")
MAX_ANNOTATIONS = 20


def summarize(path: str) -> dict:
    counts: collections.Counter = collections.Counter()
    failed: list[str] = []
    skipped: list[str] = []
    if not os.path.exists(path):
        return {"report": False, "passed": 0, "failed": 0, "skipped": 0, "failed_ids": [], "skipped_reasons": []}
    for c in ET.parse(path).getroot().iter("testcase"):
        ident = f"{c.get('classname')}::{c.get('name')}"
        if c.find("failure") is not None or c.find("error") is not None:
            counts["failed"] += 1
            failed.append(ident)
        elif c.find("skipped") is not None:
            counts["skipped"] += 1
            skipped.append((c.find("skipped").get("message") or "")[:100])
        else:
            counts["passed"] += 1
    return {"report": True, "passed": counts["passed"], "failed": counts["failed"], "skipped": counts["skipped"],
            "failed_ids": failed, "skipped_reasons": [f"{n}x {r}" for r, n in collections.Counter(skipped).most_common(5)]}


def verdict_ok(s: dict) -> bool:
    return bool(s["report"]) and s["passed"] > 0 and s["failed"] == 0


def main(argv: list[str]) -> int:
    junit, evidence = argv[1], argv[2]
    s = summarize(junit)
    name, sha = os.environ.get("EVIDENCE_NAME", "tests"), os.environ.get("HEAD_SHA", "unbekannt")
    print(f"### {name} - Commit `{sha}`\n")
    if not s["report"]:
        print("**Kein Testbericht vorhanden - nicht als bestanden zu werten.**")
    print(f"| PASSED | FAILED/ERROR | SKIPPED |\n|---|---|---|\n| {s['passed']} | {s['failed']} | {s['skipped']} |\n")
    for r in s["skipped_reasons"]:
        print(f"- uebersprungen: {r}")
    for ident in s["failed_ids"][:MAX_ANNOTATIONS]:
        safe = ident if ID_RE.fullmatch(ident) else "(Name nicht darstellbar)"
        print(f"- FAILED/ERROR: {safe}")
        print(f"::error title=Test fehlgeschlagen::{safe}", file=sys.stderr)
    ok = verdict_ok(s)
    with open(evidence, "w", encoding="utf-8") as fh:
        json.dump({"name": name, "head_sha": sha, "ok": ok, **{k: s[k] for k in ("passed", "failed", "skipped")}}, fh)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
