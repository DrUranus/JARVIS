"""V2-02 Plan-Evaluationsharness (Kern): prueft Plaene reproduzierbar gegen feste Faelle und gegen Invarianten. Nur Testwerkzeug, keine Produktivfunktion.

* Keine Bindung an einen Anbieter: Planquelle ist jede Funktion `plan(goal, ctx, max_steps) -> Sequence[GoalStep]` (der Vorlagen-Planer, oder ein `GoalPlanner` mit beliebigem
  `Decomposer`). Ein Zerleger ist untrusted: der Planer prueft jeden Vorschlag selbst und faellt sonst auf die Vorlage zurueck - das Harness belegt genau das.
* Kein Netzwerk, kein Dateizugriff ausser dem tmp-Verzeichnis des Aufrufers, keine Prozesse. Der Vorlagen-Planer laeuft mit dem echten Kern (Fake-Browser).
* Reproduzierbar: feste Ziel-IDs, Plan-Fingerabdruck unabhaengig von Zufalls-IDs und Zeit, sortierte Ausgabe, Gesamt-Digest.

Aufruf (manuell): `python tests/plan_eval.py --report` (JSON) oder `--update-golden` (nur nach bewusster Planaenderung, im PR begruenden)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from jarvis.goals import policy as P
from jarvis.goals.context import GoalContext
from jarvis.goals.errors import PlanningError
from jarvis.goals.models import Goal, GoalStep

PlanFn = Callable[[Goal, GoalContext, int], Sequence[GoalStep]]
GOLDEN = Path(__file__).with_name("plan_eval_golden.json")
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")
MAX_INPUT_CHARS = 5_000


def valid_case_id(value: str) -> bool:
    return isinstance(value, str) and bool(_ID.match(value))


@dataclass(frozen=True)
class Expect:
    outcome: str = "plan"                                   # "plan" oder "refusal"
    kind: str = ""                                          # Etikett fuer die Abdeckung: files, research, refusal, gap, limit, injection ...
    agents: tuple[str, ...] | None = None                   # Agenten der Nicht-Auswertungsschritte in Reihenfolge (None = nicht geprueft)
    capabilities: frozenset = frozenset()                   # muessen im Plan vorkommen
    forbidden_capabilities: frozenset = frozenset()         # duerfen nicht vorkommen
    reason: str = ""                                        # Textteil der Ablehnung (nur bei refusal)
    known_gap: str = ""                                     # dokumentierte Luecke: aktuelles Verhalten wird festgehalten, nicht gutgeheissen


@dataclass(frozen=True)
class Case:
    id: str
    objective: str
    context: Mapping[str, Any] = field(default_factory=dict)
    max_steps: int = 10
    expect: Expect = field(default_factory=Expect)


@dataclass(frozen=True)
class Result:
    case_id: str
    passed: bool
    outcome: str                                            # "plan", "refusal" oder "crash"
    findings: tuple[str, ...]
    shape: tuple[Mapping[str, Any], ...]
    reason: str
    fingerprint: str


@dataclass(frozen=True)
class Report:
    results: tuple[Result, ...]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {"digest": self.digest, "cases": [{"id": r.case_id, "passed": r.passed, "outcome": r.outcome, "fingerprint": r.fingerprint,
                                                   "findings": list(r.findings), "reason": r.reason[:120], "shape": list(r.shape)} for r in self.results]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)


def plan_shape(steps: Sequence[GoalStep]) -> tuple[dict[str, Any], ...]:
    """Kanonische Form: unabhaengig von Schritt-IDs, Zeit und Zufall (Abhaengigkeiten als Indizes)."""
    index = {s.step_id: i for i, s in enumerate(steps)}
    return tuple({"i": i, "agent": s.assigned_agent, "caps": sorted(s.required_capabilities), "deps": sorted(index.get(d, -1) for d in s.dependencies),
                  "attempts": s.max_attempts} for i, s in enumerate(steps))


def fingerprint(outcome: str, shape: Sequence[Mapping[str, Any]], reason_key: str = "") -> str:
    blob = json.dumps({"outcome": outcome, "shape": list(shape), "reason": reason_key}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _jsonable(value: Any, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_jsonable(v, depth + 1) for v in value)
    if isinstance(value, Mapping):
        return all(isinstance(k, str) and _jsonable(v, depth + 1) for k, v in value.items())
    return False


def invariants(steps: Sequence[GoalStep], max_steps: int, available: frozenset | None) -> list[str]:
    """Gelten fuer JEDEN Plan, unabhaengig von der Quelle."""
    out: list[str] = []
    if not 1 <= len(steps) <= min(max_steps, P.MAX_STEPS_HARD):
        out.append(f"Schrittzahl {len(steps)} ausserhalb 1..{min(max_steps, P.MAX_STEPS_HARD)}")
    ids = [s.step_id for s in steps]
    if len(set(ids)) != len(ids):
        out.append("doppelte Schritt-IDs")
    seen: set[str] = set()
    for s in steps:
        if any(d not in seen for d in s.dependencies):
            out.append(f"{s.step_id}: Abhaengigkeit auf einen spaeteren oder unbekannten Schritt")
        seen.add(s.step_id)
        if s.max_attempts > P.MAX_ATTEMPTS_HARD or s.max_attempts < 1:
            out.append(f"{s.step_id}: Versuche {s.max_attempts} ausserhalb 1..{P.MAX_ATTEMPTS_HARD}")
        if s.timeout is not None and not 0 < s.timeout <= P.MAX_TIMEOUT:
            out.append(f"{s.step_id}: Zeitlimit ausserhalb der Grenzen")
        if s.assigned_agent is None and s.required_capabilities:
            out.append(f"{s.step_id}: Auswertungsschritt mit Faehigkeiten")
        if s.assigned_agent is not None and not s.required_capabilities:
            out.append(f"{s.step_id}: Agentenschritt ohne Faehigkeit")
        if available is not None and not s.required_capabilities <= available:
            out.append(f"{s.step_id}: Faehigkeit ausserhalb des Verfuegbaren: {sorted(s.required_capabilities - available)[:3]}")
        if not _jsonable(dict(s.input)) or len(json.dumps(dict(s.input), default=str)) > MAX_INPUT_CHARS:
            out.append(f"{s.step_id}: Eingabe nicht einfach/zu gross")
    evaluations = [s for s in steps if s.assigned_agent is None]
    if steps and (not evaluations or steps[-1].assigned_agent is not None):
        out.append("Auswertungsschritt fehlt oder steht nicht am Ende")
    return out


def evaluate_case(case: Case, plan: PlanFn, available: frozenset | None = None) -> Result:
    goal = Goal(case.objective, goal_id="eval-" + case.id)
    ctx = GoalContext(goal.goal_id, case.objective, None, (), dict(case.context))
    exp = case.expect
    findings: list[str] = []
    try:
        steps = tuple(plan(goal, ctx, case.max_steps))
    except PlanningError as exc:
        reason = str(exc)
        if exp.outcome != "refusal":
            findings.append(f"unerwartete Ablehnung: {reason[:100]}")
        elif exp.reason and exp.reason.lower() not in reason.lower():
            findings.append(f"Ablehnungsgrund passt nicht: erwartet '{exp.reason}', erhalten '{reason[:100]}'")
        return Result(case.id, not findings, "refusal", tuple(findings), (), reason, fingerprint("refusal", (), _reason_key(reason)))
    except Exception as exc:  # noqa: BLE001 - jede andere Ausnahme ist ein Befund, nie eine stille Ablehnung
        return Result(case.id, False, "crash", (f"unerwartete Ausnahme {type(exc).__name__}",), (), "", fingerprint("crash", ()))
    shape = plan_shape(steps)
    if exp.outcome != "plan":
        findings.append("Plan erhalten, Ablehnung erwartet")
    findings += invariants(steps, case.max_steps, available)
    agents = tuple(s.assigned_agent for s in steps if s.assigned_agent is not None)
    if exp.agents is not None and agents != exp.agents:
        findings.append(f"Agenten {agents} statt {exp.agents}")
    caps = frozenset().union(*(s.required_capabilities for s in steps)) if steps else frozenset()
    if not exp.capabilities <= caps:
        findings.append(f"Faehigkeiten fehlen: {sorted(exp.capabilities - caps)}")
    if caps & exp.forbidden_capabilities:
        findings.append(f"verbotene Faehigkeiten im Plan: {sorted(caps & exp.forbidden_capabilities)}")
    return Result(case.id, not findings, "plan", tuple(findings), shape, "", fingerprint("plan", shape))


def _reason_key(reason: str) -> str:
    """Stabiler Schluessel aus dem Ablehnungstext (Ziffern/Quoten normalisiert), damit Textaenderungen im Detail den Fingerabdruck nicht kippen."""
    return re.sub(r"\d+", "#", reason.lower())[:60]


def run_suite(cases: Sequence[Case], plan: PlanFn, available: frozenset | None = None) -> Report:
    results = tuple(sorted((evaluate_case(c, plan, available) for c in cases), key=lambda r: r.case_id))
    digest = hashlib.sha256("\n".join(f"{r.case_id}:{r.fingerprint}:{int(r.passed)}" for r in results).encode()).hexdigest()[:16]
    return Report(results, digest)


def compare_golden(report: Report, golden: Mapping[str, str]) -> list[str]:
    now = {r.case_id: r.fingerprint for r in report.results}
    diffs = [f"{k}: Fall fehlt in der Golden-Datei" for k in sorted(set(now) - set(golden))]
    diffs += [f"{k}: Fall nicht mehr vorhanden" for k in sorted(set(golden) - set(now))]
    diffs += [f"{k}: Fingerabdruck {golden[k]} -> {now[k]}" for k in sorted(set(now) & set(golden)) if now[k] != golden[k]]
    return diffs


class ReplayDecomposer:
    """Spielt aufgezeichnete Zerlegungen ab (`objective -> Liste von Schritt-Vorschlaegen`). Anbieterunabhaengig: die Aufzeichnung kann von jedem Modell stammen.
    Unbekannte Ziele loesen LookupError aus; der Planer faellt dann auf die Vorlage zurueck."""

    def __init__(self, records: Mapping[str, Any]) -> None:
        self.records = dict(records)
        self.calls: list[str] = []

    def __call__(self, goal: Goal, ctx: GoalContext, max_steps: int, baseline: Sequence[GoalStep], allowed: frozenset) -> Any:
        self.calls.append(goal.objective)
        if goal.objective not in self.records:
            raise LookupError("keine Aufzeichnung")
        return self.records[goal.objective]

    @classmethod
    def from_file(cls, path: Path | str) -> "ReplayDecomposer":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
            raise ValueError("Aufzeichnung muss ein Objekt {Ziel: Vorschlaege} sein")
        return cls(data)


def make_template_planner(workdir: Path | str, decomposer: Callable | None = None, *, web_search: bool = False) -> tuple[Any, frozenset]:
    """Echter Kern (Fake-Browser, kein Netzwerk) -> (GoalPlanner, verfuegbare Faehigkeiten). Optional mit Zerleger."""
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from jarvis.goals.planner import GoalPlanner
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    (work / "ws").mkdir(exist_ok=True)
    env = {"JARVIS_WORKSPACE": str(work / "ws"), "JARVIS_LOG_DIR": str(work / "logs"), "JARVIS_MEMORY_PATH": str(work / "m.db"), "JARVIS_AGENTS_ENABLED": "true",
           "JARVIS_GOALS_ENABLED": "true", "JARVIS_FILES_ENABLED": "true", "JARVIS_OFFICE_ENABLED": "true", "JARVIS_BROWSER_ENABLED": "true",
           "JARVIS_BROWSER_PROVIDER": "fake", "JARVIS_RESEARCH_ENABLED": "true", "JARVIS_CODING_ENABLED": "true"}
    agents = build_core(load_settings(env=env)).subsystems["agents"]
    return GoalPlanner(agents.planner, max_attempts=2, decomposer=decomposer, web_search=web_search), frozenset(agents.planner.available_capabilities())


def make_mock_llm_planner(workdir: Path | str, responder: Callable, *, web_search: bool = False) -> tuple[Any, frozenset, Any]:
    """Wie make_template_planner, aber mit dem ECHTEN LLMDecomposer ueber den lokalen MockProvider (kein Netzwerk, kein Anbieter).
    `responder(request) -> str` liefert die Modellantwort; -> (GoalPlanner, Faehigkeiten, MockProvider mit `calls`)."""
    from jarvis.goals.llm_planner import LLMDecomposer
    from jarvis.llm.mock import MockProvider
    provider = MockProvider(responder)
    planner, available = make_template_planner(workdir, decomposer=LLMDecomposer(provider), web_search=web_search)
    return planner, available, provider


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    from plan_eval_cases import CASES
    ap = argparse.ArgumentParser(description="Plan-Evaluationsharness (Vorlagen-Planer)")
    ap.add_argument("--report", action="store_true", help="JSON-Bericht ausgeben")
    ap.add_argument("--update-golden", action="store_true", help="Golden-Datei neu schreiben (nur nach bewusster Planaenderung)")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        planner, available = make_template_planner(tmp)
        report = run_suite(CASES, planner.plan, available)
    if args.update_golden:
        failed = [r.case_id for r in report.results if not r.passed]
        if failed:
            print("Golden-Datei nicht geschrieben, Faelle fehlgeschlagen:", failed, file=sys.stderr)
            return 1
        GOLDEN.write_text(json.dumps({r.case_id: r.fingerprint for r in report.results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("Golden-Datei geschrieben:", GOLDEN)
        return 0
    print(report.to_json() if args.report else f"{sum(r.passed for r in report.results)}/{len(report.results)} Faelle bestanden, Digest {report.digest}")
    return 0 if all(r.passed for r in report.results) else 1


if __name__ == "__main__":
    sys.exit(main())
