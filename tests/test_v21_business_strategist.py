"""V2.1 Mission 2: Business Strategist - Kern (Ideenhypothesen, Finanzmodell, erklaerte Rangfolge, 30/90-Tage-Plan). Reine Logik auf den vorhandenen Business-Bausteinen
(calc, finder); keine Marktzahlen aus dem Nichts, keine externen Aktionen, kein Netzwerk."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from jarvis.business import calc, finder
from jarvis.business.errors import InvalidBusinessInput
from jarvis.business.strategist import ARCHETYPES, audit_statements, blueprint, discover, explain, financial_model, rank, research_brief

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
PROFILE = {"skills": ["Fahrzeugpflege", "Python", "Webdesign"], "interests": ["Autos", "Automatisierung"], "hours_per_week": 15, "start_budget_limit": 3000, "exclusions": ["Glücksspiel"]}


def num(v, basis="GIVEN", source=None):
    return {"value": v, "basis": basis, **({"source": source} if source else {})}


def inputs(**over):
    base = {"price": num(120), "variable_cost": num(30), "fixed_costs_month": num(900), "startup_capital": num(2500),
            "units_month": {"pessimistic": num(8, "ESTIMATE"), "base": num(16, "ESTIMATE"), "optimistic": num(28, "ESTIMATE")}, "ramp_months": 3, "months": 12}
    base.update(over)
    return base


# ---- A: Opportunity Discovery ----------------------------------------------------------------------------------------------------------------------------
def test_the_catalogue_covers_the_eight_named_business_types():
    assert {"ai_automation", "web_design", "local_services", "mobile_car_detailing", "digital_products", "b2b_leadgen", "content_production", "ecommerce"} <= set(ARCHETYPES)


def test_discovery_returns_explained_hypotheses_and_no_market_numbers():
    found = discover(PROFILE, limit=5)
    assert 3 <= len(found) <= 5 and found[0]["id"] in ("mobile_car_detailing", "web_design", "ai_automation")
    for h in found:
        assert h["basis"] == "HYPOTHESIS" and h["fit"]["reasons"] and h["research_questions"] and "keine Marktaussage" in h["note"]
        assert not re.search(r"\d+\s*(€|EUR|%|Kunden|Euro)", json.dumps(h, ensure_ascii=False)), h["id"]      # keine erfundenen Zahlen
    car = next(h for h in found if h["id"] == "mobile_car_detailing")
    assert any("Fahrzeugpflege" in r for r in car["fit"]["reasons"])


def test_discovery_is_deterministic_respects_exclusions_and_names_gaps():
    assert discover(PROFILE) == discover(dict(PROFILE))
    no_car = discover({**PROFILE, "exclusions": ["Fahrzeug"]})
    assert "mobile_car_detailing" not in [h["id"] for h in no_car]
    blank = discover({"skills": [], "interests": [], "hours_per_week": None, "start_budget_limit": None, "exclusions": []})
    assert blank and all(h["fit"]["gaps"] for h in blank) and all("UNKNOWN" in " ".join(h["fit"]["gaps"]) for h in blank)


def test_discovery_can_propose_ideas_the_user_did_not_name_and_says_why():
    found = discover({"skills": ["Vertrieb", "Kaltakquise"], "interests": ["B2B"], "hours_per_week": 10, "start_budget_limit": 500, "exclusions": []})
    assert found[0]["id"] == "b2b_leadgen" and any("Vertrieb" in r for r in found[0]["fit"]["reasons"])


@pytest.mark.parametrize("bad", [None, [], {"skills": "x"}, {"skills": [], "interests": [], "hours_per_week": -1, "start_budget_limit": None, "exclusions": []}, {"unknown": 1}])
def test_discovery_refuses_malformed_profiles(bad):
    with pytest.raises(InvalidBusinessInput):
        discover(bad)


# ---- B: Research-Auftrag und Aussagenpruefung ------------------------------------------------------------------------------------------------------------------
def test_research_brief_lists_questions_for_every_required_topic_and_starts_nothing():
    b = research_brief("mobile_car_detailing", region="Köln")
    assert set(b["topics"]) == {"demand", "target_groups", "competitors", "prices", "entry_barriers", "legal", "acquisition", "scalability"}
    assert all(q for q in b["topics"].values()) and b["status"] == "draft" and b["requires_owner_approval"] is True and "Köln" in json.dumps(b, ensure_ascii=False)


def test_every_statement_needs_a_source_or_an_explicit_assumption():
    ok = [{"text": "Innenreinigung ab 50 €", "basis": "FACT", "sources": ["https://a.example/x"]}, {"text": "16 Aufträge im Monat", "basis": "ESTIMATE"},
          {"text": "Budget 3000", "basis": "GIVEN"}]
    assert audit_statements(ok) == []
    bad = [{"text": "Der Markt wächst stark", "basis": "FACT"}, {"text": "ohne Kennzeichnung"}, {"text": "x", "basis": "FACT", "sources": ["nicht-eine-url"]},
           {"text": "sicher profitabel", "basis": "GUARANTEED"}]
    problems = audit_statements(bad)
    assert [p["index"] for p in problems] == [0, 1, 2, 3] and {p["code"] for p in problems} == {"fact_without_source", "basis_missing", "source_invalid", "basis_unknown"}


# ---- C: Finanzmodell --------------------------------------------------------------------------------------------------------------------------------------
def test_the_model_reuses_the_existing_calculations_and_shows_every_formula_input():
    m = financial_model(inputs())
    assert m["break_even"] == calc.break_even(900, 120, 30) and m["break_even"]["units"] == 10
    assert m["contribution_margin"]["value"] == 90 and m["scenarios"]["base"] == calc.scenario(120, 30, 900, 16)
    assert m["scenarios"]["pessimistic"]["profit"] == 8 * 90 - 900 and m["scenarios"]["optimistic"]["profit"] == 28 * 90 - 900
    assert m["payback"] == calc.payback_months(2500, 16 * 90 - 900)
    assert m["basis"] == "ESTIMATE" and "units_month" in m["estimated_inputs"]            # das Ergebnis ist so belastbar wie die schwaechste Eingabe


def test_liquidity_follows_the_ramp_up_month_by_month():
    m = financial_model(inputs())
    cash = m["liquidity"]["cash_by_month"]
    assert cash[0] == -2500 and len(cash) == 13
    month1 = -2500 + (16 / 3) * 90 - 900
    assert cash[1] == pytest.approx(month1) and cash[3] == pytest.approx(cash[2] + 16 * 90 - 900)
    assert m["liquidity"]["need"] == pytest.approx(-min(cash)) and m["liquidity"]["low_month"] == cash.index(min(cash))
    assert m["liquidity"]["positive_from_month"] == next(i for i, c in enumerate(cash) if c >= 0)


def test_a_business_that_never_pays_back_is_reported_as_unknown_not_as_a_number():
    m = financial_model(inputs(price=num(25)))                           # Preis unter variablen Kosten
    assert m["break_even"]["status"] == "UNKNOWN" and m["payback"]["status"] == "UNKNOWN" and m["liquidity"]["positive_from_month"] is None
    assert "never" in m["break_even"]["reason"] or "nie" in m["break_even"]["reason"]


def test_missing_inputs_give_unknown_parts_and_name_what_is_missing():
    data = inputs()
    del data["startup_capital"]
    m = financial_model(data)
    assert m["payback"]["status"] == "UNKNOWN" and m["liquidity"]["status"] == "UNKNOWN" and "startup_capital" in m["missing"]
    assert m["break_even"]["status"] == "COMPUTED"                         # was berechenbar ist, wird berechnet


def test_sensitivity_changes_one_input_at_a_time_and_names_the_strongest_lever():
    m = financial_model(inputs())
    s = m["sensitivity"]
    base = 16 * 90 - 900
    assert s["base_profit"] == base and s["steps_pct"] == [-20, -10, 10, 20]
    assert s["factors"]["price"]["-10"] == pytest.approx(16 * (108 - 30) - 900) and s["factors"]["units"]["20"] == pytest.approx(19.2 * 90 - 900)
    assert s["factors"]["variable_cost"]["10"] == pytest.approx(16 * (120 - 33) - 900) and s["factors"]["fixed_costs"]["-20"] == pytest.approx(16 * 90 - 720)
    assert s["strongest"] == "price"


def test_verified_estimated_and_given_numbers_stay_separate():
    m = financial_model(inputs(price=num(120, "FACT", "https://a.example/preise"), fixed_costs_month=num(900, "ESTIMATE")))
    assert m["inputs"]["price"] == {"value": 120.0, "basis": "FACT", "source": "https://a.example/preise"}
    assert set(m["estimated_inputs"]) == {"fixed_costs_month", "units_month"} and m["given_inputs"] == ["startup_capital", "variable_cost"] and m["verified_inputs"] == ["price"]


@pytest.mark.parametrize("over", [{"price": num(120, "FACT")}, {"price": num(120, "GUESS")}, {"price": 120}, {"price": num(float("nan"))}, {"price": num(-5)},
                                  {"months": 0}, {"months": 61}, {"ramp_months": -1}, {"units_month": {}}, {"extra": 1}, {"price": num(True)}])
def test_invalid_model_inputs_are_refused(over):
    with pytest.raises(InvalidBusinessInput):
        financial_model(inputs(**over))


# ---- D: Rangfolge -----------------------------------------------------------------------------------------------------------------------------------------
def rated(name, basis="GIVEN", **vals):
    return {"name": name, "ratings": {c: {"value": vals.get(c, 3), "basis": basis} for c in finder.CRITERIA}}


def test_ranking_uses_the_finder_score_and_explains_every_contribution():
    a, b, c = rated("A", demand=5, risk=4), rated("B", demand=2, scalability=5), rated("C")
    r = rank([b, c, a])
    assert [x["name"] for x in r["ranking"]] == ["A", "B", "C"] or [x["name"] for x in r["ranking"]][0] == "A"
    top = r["ranking"][0]
    weights = {k: 1.0 for k in finder.CRITERIA}
    expected, *_ = finder._score(weights, a["ratings"])
    assert top["score"] == pytest.approx(expected) and sum(top["contributions"].values()) == pytest.approx(top["score"])
    text = explain(a, b)
    assert "A vor B" in text and "demand" in text and "scalability" in text and "%" not in text


def test_ideas_resting_only_on_assumptions_get_no_total_and_rank_last_with_the_reason():
    r = rank([rated("Belegt", demand=4), rated("Vermutet", basis="ESTIMATE", demand=5, scalability=5)])
    assert [x["name"] for x in r["ranking"]] == ["Belegt", "Vermutet"]
    assert r["ranking"][1]["score"] is None and any("Annahmen" in n for n in r["ranking"][1]["notes"])


def test_ranking_rejects_unknown_criteria_and_bad_values():
    for bad in ([{"name": "x", "ratings": {"magic": {"value": 5, "basis": "GIVEN"}}}], [{"name": "x", "ratings": {"demand": {"value": 9, "basis": "GIVEN"}}}], [rated("a"), rated("a")], []):
        with pytest.raises(InvalidBusinessInput):
            rank(bad)


# ---- E: Umsetzungsplan -----------------------------------------------------------------------------------------------------------------------------------------
def test_blueprint_has_both_plans_costs_risks_and_only_proposals():
    m = financial_model(inputs())
    bp = blueprint("Mobile Fahrzeugaufbereitung", m, archetype="mobile_car_detailing", next_steps=["Preise von drei Wettbewerbern erheben", "Gewerbe anmelden", "Flyer veröffentlichen"])
    assert bp["days_30"] and bp["days_90"] and bp["costs"]["startup_capital"]["value"] == 2500 and bp["costs"]["fixed_costs_month"]["value"] == 900
    assert bp["risks"] and all(r["countermeasure"] for r in bp["risks"]) and bp["acquisition"] and bp["tools_needed"]
    tasks = bp["days_30"] + bp["days_90"]
    assert all(t["status"] in ("proposed", "blocked_external") and t["requires_owner_approval"] is True for t in tasks)
    ext = [t for t in tasks if t["status"] == "blocked_external"]
    assert {t["text"] for t in ext} >= {"Gewerbe anmelden", "Flyer veröffentlichen"} and all(t["reason_code"] == "external_action_not_supported" for t in ext)
    assert not any(t["status"] in ("done", "started", "executed") for t in tasks) and "keine Ertragszusage" in bp["disclaimer"]


def test_blueprint_turns_model_gaps_into_first_tasks():
    data = inputs()
    del data["startup_capital"]
    bp = blueprint("Idee", financial_model(data))
    assert any("startup_capital" in t["text"] for t in bp["days_30"])
    estimates = [t for t in bp["days_30"] if "Schätzung" in t["text"]]
    assert estimates                                                    # geschaetzte Eingaben sollen zuerst belegt werden


def test_the_whole_result_is_plain_bounded_json():
    m = financial_model(inputs())
    bp = blueprint("Idee", m, archetype="web_design")
    blob = json.dumps({"model": m, "blueprint": bp, "ideas": discover(PROFILE)}, ensure_ascii=False)
    assert len(blob) < 20_000 and "NaN" not in blob and "Infinity" not in blob


def test_the_module_is_pure_and_adds_no_second_calculation_engine():
    text = (SRC / "business" / "strategist.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    mods = {a.name for x in ast.walk(tree) if isinstance(x, ast.Import) for a in x.names} | {x.module for x in ast.walk(tree) if isinstance(x, ast.ImportFrom)}
    assert mods <= {"__future__", "typing", "re", "jarvis.business", "jarvis.business.errors", "jarvis.business.models"}, mods
    assert "calc.break_even(" in text and "calc.scenario(" in text and "calc.payback_months(" in text and "finder._score(" in text
