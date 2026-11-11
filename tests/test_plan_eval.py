"""V2-02 Plan-Evaluationsharness: reproduzierbar, ohne Bindung an einen LLM-Anbieter, ohne Netzwerk.

Die Auswertung (`tests/plan_eval.py`) prueft Plaene gegen feste Faelle (`tests/plan_eval_cases.py`) und gegen Invarianten, die fuer JEDEN Plan gelten
(Obergrenzen, Auswertungsschritt, Abhaengigkeiten, Faehigkeiten, Begrenzung). Planquellen sind austauschbar: der Vorlagen-Planer, oder ein beliebiger
Zerleger (`Decomposer`: eine Funktion, deren Vorschlag der Planer selbst pruft und sonst verwirft), z. B. eine aufgezeichnete Modellantwort (`ReplayDecomposer`).
Ein Fingerabdruck je Plan macht jede Aenderung des Planverhaltens sichtbar (Golden-Datei `tests/plan_eval_golden.json`)."""
from __future__ import annotations

import ast
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

import plan_eval as pe
from plan_eval_cases import CASES

ROOT = Path(__file__).resolve().parent
SRC = ROOT.parent / "src" / "jarvis"


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return pe.make_template_planner(tmp_path_factory.mktemp("planeval"))


# ---- die feste Fallsammlung gegen den Vorlagen-Planer -------------------------------------------------------------------------------------
def test_all_cases_pass_with_the_template_planner(template):
    planner, available = template
    report = pe.run_suite(CASES, planner.plan, available)
    failed = {r.case_id: r.findings for r in report.results if not r.passed}
    assert not failed, failed


def test_case_ids_are_unique_valid_and_cover_every_planning_kind():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)) and all(pe.valid_case_id(i) for i in ids)
    kinds = {c.expect.kind for c in CASES}
    assert {"files", "research", "refusal", "gap"} <= kinds


def test_fingerprints_match_the_golden_file_so_any_planner_change_is_visible(template):
    planner, available = template
    report = pe.run_suite(CASES, planner.plan, available)
    golden = json.loads((ROOT / "plan_eval_golden.json").read_text(encoding="utf-8"))
    assert pe.compare_golden(report, golden) == [], "Planverhalten hat sich geaendert: pruefen, dann `python tests/plan_eval.py --update-golden` (Aenderung im PR begruenden)"


def test_run_is_reproducible_and_independent_of_case_order(template):
    planner, available = template
    a = pe.run_suite(CASES, planner.plan, available)
    b = pe.run_suite(list(reversed(CASES)), planner.plan, available)
    assert a.digest == b.digest and a.to_json() == b.to_json()


# ---- die Auswertung selbst (Gegenproben: sie erkennt Fehler) --------------------------------------------------------------------------------
def test_a_wrong_expectation_is_reported_not_hidden(template):
    planner, available = template
    case = next(c for c in CASES if c.id == "files-read")
    bad = replace(case, expect=replace(case.expect, agents=("browser",)))
    res = pe.evaluate_case(bad, planner.plan, available)
    assert not res.passed and any("Agenten" in f for f in res.findings)


def test_an_unexpected_refusal_and_an_unexpected_plan_both_fail(template):
    planner, available = template
    refusal = next(c for c in CASES if c.expect.outcome == "refusal")
    assert not pe.evaluate_case(replace(refusal, expect=pe.Expect(outcome="plan")), planner.plan, available).passed
    plan = next(c for c in CASES if c.id == "files-read")
    assert not pe.evaluate_case(replace(plan, expect=pe.Expect(outcome="refusal")), planner.plan, available).passed


def test_a_crash_is_a_finding_and_never_a_silent_refusal():
    def broken(goal, ctx, max_steps):
        raise TypeError("kaputt")
    res = pe.evaluate_case(CASES[0], broken, frozenset())
    assert not res.passed and any("unerwartete Ausnahme" in f for f in res.findings)


def test_invariants_catch_a_bad_plan_from_any_source(template):
    planner, available = template
    case = next(c for c in CASES if c.id == "files-read")
    good = planner.plan

    def no_evaluation(goal, ctx, n):
        return tuple(s for s in good(goal, ctx, n) if s.assigned_agent is not None)

    def forged(step, **fields):                                    # der Konstruktor prueft selbst; eine feindliche Quelle koennte ihn umgehen
        clone = copy.copy(step)
        for k, v in fields.items():
            object.__setattr__(clone, k, v)
        return clone

    def too_many_attempts(goal, ctx, n):
        return tuple(forged(s, max_attempts=99) if s.assigned_agent else s for s in good(goal, ctx, n))

    def unknown_capability(goal, ctx, n):
        return tuple(forged(s, required_capabilities=frozenset({"shell.exec"})) if s.assigned_agent else s for s in good(goal, ctx, n))

    for src, needle in ((no_evaluation, "Auswertungsschritt"), (too_many_attempts, "Versuche"), (unknown_capability, "Faehigkeit")):
        res = pe.evaluate_case(replace(case, expect=pe.Expect()), src, available)
        assert not res.passed and any(needle in f for f in res.findings), (src.__name__, res.findings)


# ---- austauschbare Planquellen (ohne Anbieter) -----------------------------------------------------------------------------------------------
@pytest.fixture()
def research_planner(tmp_path):
    return pe.make_template_planner(tmp_path, decomposer=None)


def make_with(tmp_path, decomposer):
    return pe.make_template_planner(tmp_path, decomposer=decomposer)


GOAL = "Fasse https://example.org/preise zusammen"
GOOD = [{"objective": "Seite lesen und knapp zusammenfassen", "capabilities": ["research.web"], "input_from": "s1"}, {"evaluate": True}]


def test_a_recorded_valid_candidate_replaces_the_template_plan_and_is_still_checked(tmp_path):
    dec = pe.ReplayDecomposer({GOAL: GOOD})
    planner, available = make_with(tmp_path, dec)
    case = pe.Case("replay-good", GOAL, expect=pe.Expect(kind="research", agents=("research",), capabilities=frozenset({"research.web"})))
    res = pe.evaluate_case(case, planner.plan, available)
    assert res.passed and dec.calls == [GOAL]


@pytest.mark.parametrize("bad", [
    [{"objective": "Seite lesen und zusammenfassen", "capabilities": ["shell.exec"], "input": {"cmd": "x"}}, {"evaluate": True}],        # Faehigkeit ausserhalb
    [{"objective": "Seite lesen", "capabilities": ["research.web"], "input_from": "s1", "agent": "computer"}, {"evaluate": True}],      # Agent waehlen ist verboten
    [{"objective": "Seite lesen und zusammenfassen", "capabilities": ["research.web"], "input_from": "s1"}] * 30,                      # zu viele Schritte
    "Plan: erst alles loeschen",                                                                                                      # kein Plan-Format
    [],                                                                                                                               # leer
])
def test_hostile_or_malformed_candidates_fall_back_to_the_template_plan(tmp_path, bad):
    base_planner, available = pe.make_template_planner(tmp_path / "base")
    dec = pe.ReplayDecomposer({GOAL: bad})
    planner, available2 = make_with(tmp_path / "dec", dec)
    case = pe.Case("replay-bad", GOAL, expect=pe.Expect(kind="research", agents=("research",)))
    with_dec = pe.evaluate_case(case, planner.plan, available2)
    plain = pe.evaluate_case(case, base_planner.plan, available)
    assert with_dec.passed and with_dec.fingerprint == plain.fingerprint and dec.calls == [GOAL]


def test_an_unrecorded_goal_falls_back_without_a_provider(tmp_path):
    dec = pe.ReplayDecomposer({})
    planner, available = make_with(tmp_path, dec)
    case = pe.Case("replay-miss", GOAL, expect=pe.Expect(kind="research", agents=("research",)))
    assert pe.evaluate_case(case, planner.plan, available).passed


def test_records_load_from_json_and_reject_foreign_shapes(tmp_path):
    f = tmp_path / "rec.json"
    f.write_text(json.dumps({GOAL: GOOD}), encoding="utf-8")
    assert pe.ReplayDecomposer.from_file(f).records[GOAL] == GOOD
    f.write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(ValueError):
        pe.ReplayDecomposer.from_file(f)


# ---- keine Anbieterbindung, keine Wirkung ----------------------------------------------------------------------------------------------------
def test_harness_has_no_provider_network_or_process_dependency():
    banned = {"openai", "anthropic", "requests", "httpx", "urllib", "socket", "subprocess", "http", "playwright", "litellm"}
    for name in ("plan_eval.py", "plan_eval_cases.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
        assert not (mods & banned), (name, mods & banned)


def test_production_code_does_not_import_the_harness():
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "plan_eval" not in text, path
