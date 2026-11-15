"""V2.1 Mission 7: Qualitaetspruefung eines Ergebnisses. Ein Agent gilt nie allein wegen seiner eigenen Erfolgsmeldung als erfolgreich: geprueft werden Anforderungen, Quellen,
Rechnungen, Widersprueche, Vollstaendigkeit, Freigaben, Budgets, Dateien und Reproduzierbarkeit. Reine Logik; Dateipruefung und Audit werden hereingereicht."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from jarvis.business import calc
from jarvis.quality.engine import MANDATORY, conflicts, evaluate

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
URL_A, URL_B = "https://a.example/preise", "https://b.example/liste"
AUDIT = [{"type": "confirmation_requested", "request_id": "q1"}, {"type": "confirmation_accepted", "request_id": "q1"}]


def good():
    return {"status": "SUCCEEDED",
            "requirements": [{"id": "r1", "text": "Preise vergleichen"}, {"id": "r2", "text": "Break-even berechnen"}, {"id": "r3", "text": "Bericht speichern"}],
            "coverage": {"r1": ["s1", "s2"], "r2": ["c1"], "r3": ["file:bericht.txt"]},
            "statements": [{"id": "s1", "basis": "FACT", "sources": [URL_A]}, {"id": "s2", "basis": "FACT", "sources": [URL_B]}, {"id": "s3", "basis": "ESTIMATE"}],
            "sources": [{"url": URL_A, "status": "ok"}, {"url": URL_B, "status": "ok"}],
            "calculations": [{"id": "c1", "op": "break_even", "inputs": {"fixed_costs": 900, "price": 120, "variable_cost": 30}, "claimed": 10},
                             {"id": "c2", "op": "sum", "inputs": [50, 80, 52.5], "claimed": 182.5}, {"id": "c3", "op": "margin", "inputs": {"revenue": 1920, "costs": 1380}, "claimed": 0.28125}],
            "figures": [{"label": "innenreinigung", "unit": "EUR", "value": 50, "source": URL_A}, {"label": "innenreinigung", "unit": "EUR", "value": 50.0, "source": URL_B}],
            "required_fields": {"empfehlung": "Modell A", "break_even": 10},
            "actions": [{"id": "a1", "side_effect": True, "external": False, "request_id": "q1"}],
            "budgets": [{"name": "llm_calls", "limit": 30, "used": 12, "binding": True}],
            "reproduction": {"first": "abc123", "second": "abc123"},
            "files": ["bericht.txt"]}


def break_even(inputs):
    """Der Aufrufer reicht die vorhandene Rechnung herein (business.calc); die Engine selbst importiert keine andere Schicht."""
    res = calc.break_even(inputs.get("fixed_costs"), inputs.get("price"), inputs.get("variable_cost"))
    return res["units"] if res["status"] == "COMPUTED" else None


def run(report, exists=lambda p: True, audit=AUDIT, **kw):
    kw.setdefault("calculators", {"break_even": break_even})
    return evaluate(report, file_exists=exists, audit_events=audit, **kw)


def status(v, name):
    return next(c.status for c in v.checks if c.name == name)


def codes(v, name):
    return next(c.codes for c in v.checks if c.name == name)


def test_a_complete_evidenced_result_is_accepted():
    v = run(good())
    assert v.accepted and v.failed == () and v.unknown == () and {c.name for c in v.checks} >= set(MANDATORY)
    assert all(c.status == "PASS" for c in v.checks)


def test_a_bare_success_message_is_never_enough():
    for report in ({"status": "SUCCEEDED"}, {"status": "SUCCEEDED", "summary": "alles erledigt"}, {}, None, "SUCCEEDED"):
        v = run(report)
        assert not v.accepted and "requirements" in v.failed
    v = run({**good(), "status": "FAILED"})
    assert v.accepted and v.self_reported == "FAILED"                       # die Selbstauskunft entscheidet in keine Richtung


def test_every_requirement_needs_existing_evidence():
    r = good()
    r["coverage"]["r2"] = []
    v = run(r)
    assert not v.accepted and codes(v, "requirements") == ("requirement_uncovered:r2",)
    r = good()
    r["coverage"]["r1"] = ["s99"]
    assert codes(run(r), "requirements") == ("evidence_unknown:r1",)
    r = good()
    del r["coverage"]["r3"]
    assert "requirement_uncovered:r3" in codes(run(r), "requirements")


def test_facts_need_sources_that_were_really_read():
    r = good()
    r["statements"][0]["sources"] = []
    assert codes(run(r), "sources") == ("fact_without_source:s1",)
    r = good()
    r["sources"][1]["status"] = "unavailable"
    assert codes(run(r), "sources") == ("source_not_read:s2",)
    r = good()
    r["statements"][1]["sources"] = ["https://erfunden.example/nie-gelesen"]              # absichtlich falsche Quelle
    assert codes(run(r), "sources") == ("source_not_read:s2",)
    r = good()
    r["statements"].append({"id": "s4"})
    assert codes(run(r), "sources") == ("basis_missing:s4",)
    r = good()
    r["statements"].append({"id": "s5", "basis": "GUARANTEED"})
    assert "basis_unknown:s5" in codes(run(r), "sources")


def test_calculations_are_recomputed_and_wrong_numbers_fail():
    r = good()
    r["calculations"][0]["claimed"] = 9                                       # falscher Break-even
    v = run(r)
    assert not v.accepted and codes(v, "calculations") == ("calculation_wrong:c1",)
    r = good()
    r["calculations"][1]["claimed"] = 180
    assert codes(run(r), "calculations") == ("calculation_wrong:c2",)
    r = good()
    r["calculations"].append({"id": "c9", "op": "magic", "inputs": [1], "claimed": 1})
    v = run(r)
    assert status(v, "calculations") == "UNKNOWN" and not v.accepted and "calculation_unverifiable:c9" in codes(v, "calculations")
    r = good()
    r["calculations"][0]["inputs"]["price"] = 20                             # Preis unter variablen Kosten: kein Break-even, also darf keiner behauptet werden
    assert codes(run(r), "calculations") == ("calculation_wrong:c1",)
    for bad in (float("nan"), float("inf"), "10", None, True):
        r = good()
        r["calculations"][0]["claimed"] = bad
        assert status(run(r), "calculations") == "FAIL"


def test_contradicting_figures_fail_unless_they_are_shown_as_a_conflict():
    r = good()
    r["figures"][1]["value"] = 80
    v = run(r)
    assert not v.accepted and codes(v, "consistency") == ("conflict:innenreinigung",)
    r["acknowledged_conflicts"] = ["innenreinigung"]
    assert run(r).accepted                                                     # ausgewiesener Widerspruch ist ehrlich, verschwiegener nicht
    assert conflicts([{"label": "x", "unit": "EUR", "value": 100, "source": "agent:a"}, {"label": "x", "unit": "EUR", "value": 100.4, "source": "agent:b"}]) == []
    assert conflicts([{"label": "x", "unit": "EUR", "value": 100, "source": "agent:a"}, {"label": "x", "unit": "USD", "value": 300, "source": "agent:b"}]) == []
    (c,) = conflicts([{"label": "umsatz", "unit": "EUR", "value": 1000, "source": "agent:finance"}, {"label": "umsatz", "unit": "EUR", "value": 1500, "source": "agent:business"}])
    assert c["label"] == "umsatz" and c["values"] == [1000.0, 1500.0] and c["sources"] == ["agent:business", "agent:finance"]


def test_missing_required_information_fails():
    r = good()
    r["required_fields"]["empfehlung"] = None
    v = run(r)
    assert not v.accepted and codes(v, "completeness") == ("missing:empfehlung",)
    r["required_fields"]["break_even"] = ""
    assert codes(run(r), "completeness") == ("missing:break_even", "missing:empfehlung")


def test_side_effects_and_external_actions_need_a_recorded_approval():
    r = good()
    assert status(run(r, audit=[]), "approvals") == "FAIL" and codes(run(r, audit=[]), "approvals") == ("unapproved_action:a1",)
    assert codes(run(r, audit=[{"type": "confirmation_requested", "request_id": "q1"}, {"type": "confirmation_rejected", "request_id": "q1"}]), "approvals") == ("unapproved_action:a1",)
    r["actions"].append({"id": "a2", "side_effect": False, "external": True, "request_id": None})
    assert codes(run(r), "approvals") == ("unapproved_action:a2",)
    r["actions"][1] = {"id": "a3", "side_effect": False, "external": False, "request_id": None}            # reines Lesen braucht keine Freigabe
    assert run(r).accepted
    r["actions"].append({"id": "a4", "side_effect": True, "external": False, "request_id": "q1"})          # dieselbe Freigabe deckt nicht zwei Aktionen
    assert codes(run(r), "approvals") == ("approval_reused:a4",)


def test_budgets_are_checked_and_unknown_use_of_a_binding_budget_fails_closed():
    r = good()
    r["budgets"][0]["used"] = 31
    assert codes(run(r), "budgets") == ("budget_exceeded:llm_calls",)
    r["budgets"][0]["used"] = None
    assert codes(run(r), "budgets") == ("budget_unknown:llm_calls",)
    r["budgets"][0]["binding"] = False
    assert run(r).accepted


def test_declared_files_must_really_exist():
    v = run(good(), exists=lambda p: False)
    assert not v.accepted and codes(v, "files") == ("file_missing:0",)
    v = run(good(), exists=None)
    assert status(v, "files") == "UNKNOWN" and not v.accepted                 # ungeprueft ist nicht bestanden

    def boom(path):
        raise OSError("kein Zugriff")
    assert codes(run(good(), exists=boom), "files") == ("file_missing:0",)
    r = good()
    r["files"] = ["../../etc/passwd"]
    r["coverage"]["r3"] = ["file:../../etc/passwd"]
    assert "file_path_invalid:0" in codes(run(r), "files")


def test_reproducibility_is_reported_and_only_blocks_when_required():
    r = good()
    r["reproduction"]["second"] = "zzz"
    assert codes(run(r), "reproducibility") == ("not_reproducible",) and not run(r).accepted
    r = good()
    del r["reproduction"]
    v = run(r)
    assert status(v, "reproducibility") == "UNKNOWN" and v.accepted and v.unknown == ("reproducibility",)
    assert not run(r, require_reproduction=True).accepted


def test_the_verdict_never_contains_content_and_survives_hostile_input():
    r = good()
    secret = "sk-GEHEIMER-INHALT-123456789012345"
    r["requirements"][0]["text"] = secret
    r["statements"][0]["text"] = secret
    r["figures"][1]["value"] = 999
    v = run(r)
    assert secret not in json.dumps(v.to_dict()) and "conflict:innenreinigung" in json.dumps(v.to_dict())
    for hostile in ({"requirements": "x", "coverage": 5, "statements": [1, None], "calculations": {"a": 1}, "figures": [[]], "actions": "alle", "budgets": [None], "files": 7},
                    {"requirements": [{"id": "r1"}], "coverage": {"r1": [{"evil": 1}]}}):
        assert not run(hostile).accepted


def test_one_failed_check_does_not_hide_the_others():
    r = good()
    r["calculations"][0]["claimed"] = 9
    r["figures"][1]["value"] = 80
    r["budgets"][0]["used"] = 99
    v = run(r, exists=lambda p: False)
    assert set(v.failed) == {"calculations", "consistency", "budgets", "files"}


def test_evaluation_does_not_change_its_input_and_is_deterministic():
    r = good()
    before = copy.deepcopy(r)
    assert run(r).to_dict() == run(r).to_dict() and r == before


def test_without_the_calculator_a_domain_formula_is_unverifiable_not_passed():
    v = evaluate(good(), file_exists=lambda p: True, audit_events=AUDIT)
    assert status(v, "calculations") == "UNKNOWN" and codes(v, "calculations") == ("calculation_unverifiable:c1",) and not v.accepted

    def broken(inputs):
        raise RuntimeError("Rechner defekt")
    assert codes(run(good(), calculators={"break_even": broken}), "calculations") == ("calculation_wrong:c1",)


def test_the_engine_is_pure_and_imports_no_other_layer():
    text = (SRC / "quality" / "engine.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    mods = {a.name for x in ast.walk(tree) if isinstance(x, ast.Import) for a in x.names} | {x.module for x in ast.walk(tree) if isinstance(x, ast.ImportFrom)}
    assert mods <= {"__future__", "dataclasses", "math", "typing"}, mods
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not calls & {"open", "exec", "eval", "compile", "__import__"}
