"""Skip-Bericht (WP08): liest die Ausgabe von `pytest -rs`, gruppiert die Skip-Gruende und vergleicht mit tests/support/skip_baseline.json.

Aufruf:  python tests/support/skip_report.py pytest.txt --platform windows [--strict] [--json] [--baseline PFAD]
Exit-Codes: 0 in Ordnung | 1 mehr Skips als die Baseline-Obergrenze | 2 (nur mit --strict) unbekannter Grund | 3 Baseline fehlt/ungueltig.
Ein uebersprungener Test gilt nie als bestanden: das Werkzeug macht nur sichtbar. Reine Textverarbeitung (kein Netzwerk, keine Prozesse, keine Pytest-Ausfuehrung)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

BASELINE_PATH = Path(__file__).resolve().parent / "skip_baseline.json"
CATEGORIES = ("interaktiv (nur PC-Abnahme #186/G9)", "bekannte Luecke (Windows-Nachweis fehlt)", "optionale Bibliothek fehlt", "Umgebung",
              "Netzwerk/extern noetig", "plattformbedingt", "unbekannt")
INTERACTIVE = CATEGORIES[0]
_LINE = re.compile(r"^SKIPPED \[(\d+)\] (.+?):(\d+): (.*)$")
_MAX_LINE = 2000
_SUMMARY = re.compile(r"\bin [\d.]+s\b")


@dataclass(frozen=True)
class SkipItem:
    count: int
    path: str
    line: int
    reason: str


@dataclass
class Report:
    platform: str
    items: list[SkipItem] = field(default_factory=list)
    baseline_max: int | None = None
    by_category: dict[str, int] = field(default_factory=dict)
    unknown_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(i.count for i in self.items)

    def exit_code(self, strict: bool = False) -> int:
        if self.baseline_max is not None and self.total > self.baseline_max:
            return 1
        if strict and self.unknown_reasons:
            return 2
        return 0

    def as_dict(self) -> dict[str, Any]:
        return {"platform": self.platform, "total": self.total, "baseline_max": self.baseline_max, "by_category": self.by_category,
                "unknown_reasons": self.unknown_reasons, "warnings": self.warnings}


def parse(text: str) -> list[SkipItem]:
    out: list[SkipItem] = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if len(line) > _MAX_LINE:
            continue
        m = _LINE.match(line)
        if m:
            out.append(SkipItem(int(m.group(1)), m.group(2), int(m.group(3)), m.group(4).strip()))
    return out


def summary_counts(text: str) -> tuple[int, int] | None:
    """(passed, skipped) from the last pytest summary line, else None."""
    for raw in reversed(str(text).splitlines()):
        line = raw.strip()
        if len(line) <= _MAX_LINE and _SUMMARY.search(line):
            p, s = re.search(r"(\d+) passed", line), re.search(r"(\d+) skipped", line)
            if p or s:
                return int(p.group(1)) if p else 0, int(s.group(1)) if s else 0
    return None


def _categorize(reason: str, known: Sequence[Mapping[str, str]]) -> str | None:
    for entry in known:
        try:
            if re.search(entry["pattern"], reason, re.IGNORECASE):
                return entry["category"]
        except (re.error, KeyError, TypeError):
            continue
    return None


def build_report(text: str, platform: str, baseline: Mapping[str, Any]) -> Report:
    rep = Report(platform=platform)
    known = baseline.get("known_reasons", []) if isinstance(baseline, Mapping) else []
    section = baseline.get(platform) if isinstance(baseline, Mapping) else None
    if isinstance(section, Mapping) and isinstance(section.get("max_skipped"), int):
        rep.baseline_max = section["max_skipped"]
    rep.items = parse(text)
    cats: Counter[str] = Counter()
    unknown: list[str] = []
    for item in rep.items:
        cat = _categorize(item.reason, known)
        if cat is None:
            cat = "unbekannt"
            if item.reason not in unknown:
                unknown.append(item.reason)
        cats[cat] += item.count
    rep.by_category = dict(cats)
    rep.unknown_reasons = unknown
    if rep.baseline_max is not None and rep.total > rep.baseline_max:
        rep.warnings.append(f"{rep.total} Skips sind mehr als die Baseline-Obergrenze {rep.baseline_max} ({platform}); jeden neuen Skip begruenden")
    counts = summary_counts(text)
    if counts is not None and counts[1] != rep.total:
        rep.warnings.append(f"Summenzeile nennt {counts[1]} Skips, die Liste ergibt {rep.total} (fehlt '-rs' oder ist die Ausgabe gekuerzt?)")
    if unknown:
        rep.warnings.append(f"{len(unknown)} unbekannte Skip-Gruende (nicht in der Baseline)")
    return rep


def format_report(rep: Report) -> str:
    lines = [f"Skip-Bericht ({rep.platform})", f"Uebersprungen gesamt: {rep.total}" + (f" (Baseline-Obergrenze {rep.baseline_max})" if rep.baseline_max is not None else "")]
    for cat in CATEGORIES:
        if rep.by_category.get(cat):
            lines.append(f"  {rep.by_category[cat]:4d}  {cat}")
    for reason in rep.unknown_reasons:
        lines.append(f"  unbekannter Grund: {reason}")
    lines += [f"WARNUNG: {w}" for w in rep.warnings]
    if rep.by_category.get(INTERACTIVE):
        lines.append("Hinweis: interaktive Skips sind NICHT bestanden; sie werden nur durch die Abnahme am Windows-PC belegt.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Skip-Bericht aus `pytest -rs`")
    ap.add_argument("input", help="Datei mit der pytest-Ausgabe oder - fuer stdin")
    ap.add_argument("--platform", required=True, choices=("windows", "linux"))
    ap.add_argument("--baseline", default=str(BASELINE_PATH))
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        if not isinstance(baseline, dict) or baseline.get("schema") != 1 or args.platform not in baseline:
            raise ValueError("unbekanntes Baseline-Schema")
    except (OSError, ValueError) as exc:
        print(f"FEHLER: Baseline nicht lesbar ({type(exc).__name__}): kein stilles Gruen", file=sys.stderr)
        return 3
    text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8", errors="replace")
    rep = build_report(text, args.platform, baseline)
    print(json.dumps(rep.as_dict(), ensure_ascii=False, indent=2) if args.json else format_report(rep))
    return rep.exit_code(strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
