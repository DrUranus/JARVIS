"""Self-Improvement Lab (V2.1 M4) - reine Bewertung eines Aenderungsvorschlags anhand von Messdaten.

Eingaben sind TEXTE und ZAHLEN, die jemand anderes erzeugt hat (JUnit-Berichte, Ausgabe von scripts/bench/v21_bench.py, Dateilisten eines Diffs).
Dieses Modul startet keinen Prozess, liest und schreibt keine Datei, kennt kein Netzwerk und keine andere JARVIS-Schicht. Es bereitet keinen Code
vor (das bleibt in [self_improvement] gesperrt, bis eine Isolation belegt ist) und kann nichts uebernehmen: jedes Urteil traegt
requires_owner_approval = True und may_apply = False. Ein uebersprungener oder verschwundener Test gilt nie als bestanden.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from jarvis.errors import JarvisError

MAX_XML_BYTES = 20_000_000
MIN_RUNS = 3          # darunter ist eine Zeitmessung kein Vergleich
TOLERANCE = 0.20      # Abweichung des Medians, ab der ueberhaupt ein Befund moeglich ist
# Dateien, die ein Verbesserungsvorschlag nie anfassen darf (Sicherheitsgrenzen, Freigabe, Not-Aus, deren Tests, Automatisierung).
PROTECTED = (".github/", ".claude/", "CLAUDE.md", "config/jarvis.toml", "src/jarvis/permissions/", "src/jarvis/ui_contract/", "src/jarvis/bootstrap.py",
             "src/jarvis/self_improvement/", "src/jarvis/lab/", "tests/support/protected_manifest", "tests/test_security", "tests/test_emergency_stop.py",
             "tests/test_autonomy_invariants.py", "tests/test_protected_files.py")


class LabError(JarvisError):
    """Die Eingabe ist kein verwertbarer Nachweis."""


@dataclass(frozen=True)
class TestRun:
    __test__ = False
    passed: frozenset[str]
    failed: frozenset[str]
    skipped: frozenset[str]
    failures: tuple[tuple[str, str], ...] = ()

    @property
    def all(self) -> frozenset[str]:
        return self.passed | self.failed | self.skipped


@dataclass(frozen=True)
class TestDiff:
    __test__ = False
    regressions: tuple[str, ...]
    fixed: tuple[str, ...]
    new_skips: tuple[str, ...]
    removed: tuple[str, ...]
    added: tuple[str, ...]


@dataclass(frozen=True)
class BenchDiff:
    case: str
    state: str  # faster | slower | same | incomparable | missing
    ratio: float | None = None
    why: str = ""


@dataclass(frozen=True)
class Cluster:
    shape: str
    count: int
    tests: tuple[str, ...]


@dataclass(frozen=True)
class Assessment:
    verdict: str  # improvement | no_evidence | reject
    reasons: tuple[str, ...]
    protected_touched: tuple[str, ...] = ()
    requires_owner_approval: bool = field(default=True, init=False)
    may_apply: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_junit(text: str) -> TestRun:
    if not isinstance(text, str) or len(text) > MAX_XML_BYTES:
        raise LabError("junit: kein Text oder zu gross")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise LabError("junit: DOCTYPE/ENTITY wird nicht verarbeitet")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise LabError("junit: kein gueltiges XML") from exc
    passed, failed, skipped, failures = set(), set(), set(), []
    for tc in root.iter("testcase"):
        name = f"{tc.get('classname') or ''}::{tc.get('name') or ''}"
        bad = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        if bad is not None:
            failed.add(name)
            failures.append((name, f"{bad.get('message') or ''} {bad.text or ''}".strip()[:2000]))
        elif tc.find("skipped") is not None:
            skipped.add(name)
        else:
            passed.add(name)
    passed -= failed | skipped  # derselbe Name mehrfach: das schlechteste Ergebnis zaehlt
    skipped -= failed
    if not (passed or failed or skipped):
        raise LabError("junit: kein einziger Testfall - ein leerer Lauf ist kein Nachweis")
    return TestRun(frozenset(passed), frozenset(failed), frozenset(skipped), tuple(failures))


def compare_tests(before: TestRun, after: TestRun) -> TestDiff:
    added = after.all - before.all
    return TestDiff(regressions=tuple(sorted((before.passed & after.failed) | (added & after.failed))), fixed=tuple(sorted(before.failed & after.passed)),
                    new_skips=tuple(sorted((before.passed | before.failed) & after.skipped)), removed=tuple(sorted(before.all - after.all)), added=tuple(sorted(added)))


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def compare_bench(before: Mapping[str, Any], after: Mapping[str, Any], *, tolerance: float = TOLERANCE, min_runs: int = MIN_RUNS) -> dict[str, BenchDiff]:
    out: dict[str, BenchDiff] = {}
    b_env, a_env = before.get("environment") or {}, after.get("environment") or {}
    same_env = bool(b_env) and all(b_env.get(k) == a_env.get(k) for k in ("cpus", "platform", "python"))
    b_cases, a_cases = before.get("cases") or {}, after.get("cases") or {}
    for case in sorted(set(b_cases) | set(a_cases)):
        b, a = b_cases.get(case), a_cases.get(case)
        if not isinstance(b, Mapping) or not isinstance(a, Mapping):
            out[case] = BenchDiff(case, "missing", why="nur in einer Messung vorhanden")
            continue
        vals = [_num(x.get(k)) for x in (b, a) for k in ("median_s", "min_s", "max_s")]
        runs = min(int(before.get("runs") or 0), int(after.get("runs") or 0))
        if not same_env:
            out[case] = BenchDiff(case, "incomparable", why="andere Maschine/Plattform/Python-Version")
        elif runs < min_runs:
            out[case] = BenchDiff(case, "incomparable", why=f"weniger als {min_runs} Laeufe")
        elif b.get("n") != a.get("n"):
            out[case] = BenchDiff(case, "incomparable", why="andere Groesse")
        elif None in vals or not vals[0]:
            out[case] = BenchDiff(case, "incomparable", why="Messwerte fehlen")
        else:
            b_med, b_min, b_max, a_med, a_min, a_max = vals
            ratio = round(a_med / b_med, 3)
            # Befund nur, wenn der Median deutlich abweicht UND die Streuungen sich nicht ueberlappen.
            state = "slower" if ratio > 1 + tolerance and a_min > b_max else "faster" if ratio < 1 - tolerance and a_max < b_min else "same"
            out[case] = BenchDiff(case, state, ratio)
    return out


_NOISE = ((re.compile(r"0x[0-9a-fA-F]+"), "<hex>"), (re.compile(r"(?:[A-Za-z]:)?[\\/][^\s:'\"]+"), "<path>"), (re.compile(r"\d+"), "<n>"), (re.compile(r"\s+"), " "))


def cluster_failures(failures: Iterable[tuple[str, str]]) -> list[Cluster]:
    groups: dict[str, list[str]] = {}
    for name, message in failures:
        shape = str(message)[:400]
        for rx, rep in _NOISE:
            shape = rx.sub(rep, shape)
        groups.setdefault(shape.strip()[:200], []).append(str(name))
    return sorted((Cluster(s, len(t), tuple(sorted(t))) for s, t in groups.items()), key=lambda c: (-c.count, c.shape))


def _norm(path: str) -> str:
    p = str(path).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def assess(*, tests: TestDiff, bench: Mapping[str, BenchDiff] | None = None, touched_files: Sequence[str] = (), deleted_files: Sequence[str] = (),
           protected: Sequence[str] = PROTECTED) -> Assessment:
    reasons: list[str] = []
    files = [_norm(f) for f in (*touched_files, *deleted_files)]
    hit = tuple(sorted(f for f in files if any(f == p or f.startswith(p) for p in protected)))
    if hit:
        reasons.append("protected_file")
    if any(f.startswith("/") or ".." in f.split("/") or re.match(r"^[A-Za-z]:", f) for f in files):
        reasons.append("path_outside_repository")
    if any(_norm(f).startswith("tests/") for f in deleted_files):
        reasons.append("test_deleted")
    for flag, items in (("regression", tests.regressions), ("new_skip", tests.new_skips), ("removed_test", tests.removed)):
        if items:
            reasons.append(flag)
    states = {d.state for d in (bench or {}).values()}
    if "slower" in states:
        reasons.append("slower")
    if reasons:
        return Assessment("reject", tuple(reasons), hit)
    better = [r for r, ok in (("fixed", bool(tests.fixed)), ("faster", "faster" in states)) if ok]
    return Assessment("improvement", tuple(better)) if better else Assessment("no_evidence", ("nothing_measurably_better",))
