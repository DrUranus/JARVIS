"""V2.1 (Mission 2): Business Strategist - the pure core. NOT an agent yet and not wired: it adds what the existing Business-Finder lacks and reuses its building blocks.

  A  discover        idea HYPOTHESES from a small catalogue of business types, matched to the owner's profile by explainable rules. No market figure is ever produced here:
                     every hypothesis lists the questions research has to answer first.
  B  research_brief  the questions per topic for the Research agent (a draft: starting research is a separate, approved step); audit_statements flags every statement
                     that is neither sourced nor marked as an assumption.
  C  financial_model contribution margin, break-even, scenarios, payback (all from business.calc - no second calculation engine), month-by-month liquidity with a ramp-up
                     and a one-factor sensitivity analysis. Inputs carry their basis (FACT with source / GIVEN / ESTIMATE); the result is only as firm as its weakest input;
                     missing inputs give UNKNOWN parts, never a guess.
  D  rank / explain  the Finder's own score (finder._score) with every contribution shown, and a sentence why A ranks before B.
  E  blueprint       30- and 90-day plan, costs, tools, acquisition drafts, risks with countermeasures. Everything is a PROPOSAL that needs the owner's approval; steps that
                     would act in the outside world (register, publish, pay, contact ...) are marked blocked_external exactly as in the Finder.
No network, no file, no process; nothing is sent, bought or published."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from jarvis.business import calc, finder
from jarvis.business.errors import InvalidBusinessInput
from jarvis.business.models import number

BASES = ("FACT", "GIVEN", "ESTIMATE")
STATEMENT_BASES = ("FACT", "GIVEN", "INFERENCE", "ESTIMATE", "UNKNOWN")
STEPS_PCT = (-20, -10, 10, 20)
NOTE = "Hypothese aus dem Abgleich mit dem Profil; keine Marktaussage, keine Prognose. Erst die Recherchefragen klären."
_URL = re.compile(r"^https?://[^\s/]+\S*$", re.IGNORECASE)
_PROFILE = {"skills", "interests", "hours_per_week", "start_budget_limit", "exclusions"}
_MODEL = {"price", "variable_cost", "fixed_costs_month", "startup_capital", "units_month", "ramp_months", "months"}


def _a(title: str, skills: str, interests: str, min_hours: int, capital: str, risk_areas: str, questions: Sequence[str], tools: Sequence[str], acquisition: Sequence[str]) -> dict[str, Any]:
    return {"title": title, "skills": tuple(skills.split()), "interests": tuple(interests.split()), "min_hours": min_hours, "capital": capital,
            "risk_areas": tuple(risk_areas.split()), "questions": tuple(questions), "tools": tuple(tools), "acquisition": tuple(acquisition)}


ARCHETYPES: dict[str, dict[str, Any]] = {
    "ai_automation": _a("KI-Automatisierung für Unternehmen", "python programm automatis ki daten api", "automatis ki software prozess", 10, "low", "legal privacy scaling",
                        ("Welche wiederkehrenden Abläufe kosten kleine Betriebe der Region nachweislich Zeit?", "Welche Anbieter gibt es und zu welchen Preisen?",
                         "Welche Datenschutzpflichten gelten bei Kundendaten?"), ("Entwicklungsumgebung", "Testdaten ohne Personenbezug"),
                        ("Fallbeispiel als Entwurf", "Liste möglicher Ansprechpartner (nur Recherche)")),
    "web_design": _a("Webdesign und Webseiten-Erstellung", "webdesign web design html css wordpress grafik", "design web gestalt", 8, "low", "legal reputation time",
                     ("Wie viele Betriebe der Zielbranche haben keine oder eine veraltete Webseite?", "Welche Preise nennen Wettbewerber öffentlich?", "Welche Pflichtangaben braucht eine Webseite?"),
                     ("Design- und Entwicklungswerkzeug", "Beispielseiten"), ("Portfolio-Entwurf", "Angebotsvorlage als Entwurf")),
    "local_services": _a("Lokale Dienstleistungen", "handwerk service reinig garten montage", "lokal region dienstleist", 10, "medium", "legal time reputation",
                         ("Welche Dienstleistungen werden lokal nachgefragt (belegbare Anzeichen)?", "Welche Genehmigungen oder Nachweise sind nötig?", "Welche Preise sind üblich?"),
                         ("Arbeitsmittel je nach Leistung", "Terminplanung"), ("Leistungsbeschreibung als Entwurf", "Aushang-Entwurf")),
    "mobile_car_detailing": _a("Mobile Fahrzeugaufbereitung", "fahrzeug auto aufbereit pflege reinig lack", "auto fahrzeug kfz", 10, "medium", "legal time reputation",
                               ("Welche Preise nennen Anbieter in der Region für Innen- und Außenaufbereitung?", "Welche Auflagen gelten für Wasser, Abwasser und Reinigungsmittel unterwegs?",
                                "Wie viele Anbieter gibt es im Einzugsgebiet?"), ("Reinigungsausrüstung", "Fahrzeug für die Anfahrt", "Terminplanung"),
                               ("Leistungs- und Preisliste als Entwurf", "Vorher-Nachher-Beispiele (eigene Fahrzeuge)")),
    "digital_products": _a("Digitale Produkte", "schreib design vorlage kurs content programm", "wissen kurs vorlage digital", 6, "low", "platform legal reputation",
                           ("Für welches Thema gibt es belegbare Nachfrage?", "Welche Plattformbedingungen und Gebühren gelten?", "Welche vergleichbaren Produkte gibt es zu welchem Preis?"),
                           ("Erstellungswerkzeug", "Verkaufsplattform (erst nach Entscheidung)"), ("Produktbeschreibung als Entwurf",)),
    "b2b_leadgen": _a("B2B-Leadgenerierung", "vertrieb akquise sales recherche crm", "b2b vertrieb sales", 8, "low", "legal privacy reputation",
                      ("Welche Branchen kaufen Kontakte oder Termine ein, und zu welchen Konditionen?", "Was ist bei Ansprache und Datenschutz rechtlich zulässig?",
                       "Welche Anbieter gibt es bereits?"), ("Kontaktverwaltung", "Recherchequellen"), ("Angebotsentwurf", "Zielkundenprofil als Entwurf")),
    "content_production": _a("Automatisierte Content-Produktion", "schreib text video schnitt redaktion content ki", "content medien text video", 8, "low", "platform reputation legal",
                             ("Welche Auftraggeber vergeben regelmäßig Inhalte, zu welchen Sätzen?", "Welche Kennzeichnungs- und Urheberrechtsfragen stellen sich?",
                              "Wie unterscheiden sich vorhandene Angebote?"), ("Schreib- und Schnittwerkzeug", "Qualitätsprüfung durch einen Menschen"), ("Arbeitsproben als Entwurf",)),
    "ecommerce": _a("E-Commerce-Geschäftsmodelle", "einkauf handel logistik shop marketing", "handel produkt shop", 12, "high", "platform payment_liability legal scaling",
                    ("Für welche Produkte gibt es belegbare Nachfrage und welche Margen sind öffentlich nachvollziehbar?", "Welche Pflichten gelten (Widerruf, Gewährleistung, Verpackung)?",
                     "Welche Plattform- und Zahlungsgebühren fallen an?"), ("Shop- oder Plattformzugang (erst nach Entscheidung)", "Lager oder Lieferant"), ("Sortimentsentwurf",)),
}
COUNTERMEASURES = {"legal": "Vor dem Start rechtlich prüfen lassen; bis dahin nur recherchieren und entwerfen.", "platform": "Bedingungen und Gebühren der Plattform belegen; nicht von einer einzigen Plattform abhängig planen.",
                   "payment_liability": "Zahlungs- und Haftungsfragen vor dem ersten Verkauf klären; keine Zahlungen ohne Freigabe.", "scaling": "Erst mit wenigen Aufträgen prüfen, ob Qualität und Zeit reichen.",
                   "time": "Zeitbedarf je Auftrag messen und mit dem Wochenrahmen abgleichen.", "privacy": "Nur nötige Daten erheben; Datenschutzpflichten vorab klären.",
                   "reputation": "Leistung zuerst an eigenen Beispielen zeigen; Bewertungen nicht erfinden."}
TOPICS = {"demand": "Welche belegbaren Anzeichen für Nachfrage gibt es{r}?", "target_groups": "Welche Zielgruppen kommen in Frage{r} und woran erkennt man sie?",
          "competitors": "Welche Wettbewerber gibt es{r}?", "prices": "Welche Preise werden öffentlich genannt{r}?", "entry_barriers": "Welche Einstiegshürden (Kapital, Nachweise, Ausrüstung) bestehen?",
          "legal": "Welche rechtlichen Pflichten und Risiken sind zu klären?", "acquisition": "Über welche Wege werden Kunden üblicherweise gewonnen{r}?",
          "scalability": "Was begrenzt das Wachstum (Zeit, Personal, Kapital)?"}


# ---- A ----------------------------------------------------------------------------------------------------------------------------------------------------
def _texts(value: Any, what: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > 30 or not all(isinstance(v, str) and len(v) <= 100 for v in value):
        raise InvalidBusinessInput(f"{what} is a short list of texts")
    return tuple(v.strip() for v in value if v.strip())


def _profile(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not raw or set(raw) - _PROFILE:
        raise InvalidBusinessInput("profile: an object with skills, interests, hours_per_week, start_budget_limit, exclusions")
    hours, budget = raw.get("hours_per_week"), raw.get("start_budget_limit")
    return {"skills": _texts(raw.get("skills"), "skills"), "interests": _texts(raw.get("interests"), "interests"), "exclusions": _texts(raw.get("exclusions"), "exclusions"),
            "hours": None if hours is None else number(hours, "hours_per_week", positive=True), "budget": None if budget is None else number(budget, "start_budget_limit", non_negative=True)}


def _matches(entries: Sequence[str], keywords: Sequence[str]) -> list[str]:
    return [e for e in entries if any(k in e.lower() or e.lower() in k for k in keywords)]


def discover(profile: Any, limit: int = 5) -> list[dict[str, Any]]:
    p = _profile(profile)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= len(ARCHETYPES):
        raise InvalidBusinessInput("limit 1..%d" % len(ARCHETYPES))
    found = []
    for key in sorted(ARCHETYPES):
        a = ARCHETYPES[key]
        hay = (a["title"] + " " + " ".join(a["skills"] + a["interests"])).lower()
        if any(x.lower() in hay for x in p["exclusions"]):
            continue
        reasons = [f"Fähigkeit „{s}“ passt zur Vorlage" for s in _matches(p["skills"], a["skills"])] + [f"Interesse „{s}“ passt zur Vorlage" for s in _matches(p["interests"], a["interests"])]
        matched = len(reasons)
        gaps = [] if matched else ["keine passende Fähigkeit und kein passendes Interesse angegeben"]
        if p["hours"] is None:
            gaps.append("hours_per_week UNKNOWN: Zeitrahmen nicht angegeben")
        elif p["hours"] >= a["min_hours"]:
            reasons.append("angegebener Zeitrahmen reicht für den angenommenen Mindestaufwand (ESTIMATE)")
        else:
            gaps.append("angegebener Zeitrahmen liegt unter dem angenommenen Mindestaufwand der Vorlage (ESTIMATE)")
        if p["budget"] is None:
            gaps.append("start_budget_limit UNKNOWN: Startbudget nicht angegeben")
        elif a["capital"] == "high":
            gaps.append("Kapitalbedarf dieser Vorlage ist typischerweise höher als bei den anderen (ESTIMATE, zu belegen)")
        found.append((-matched, len(gaps), key, {"id": key, "title": a["title"], "basis": "HYPOTHESIS", "fit": {"matches": matched, "reasons": reasons, "gaps": gaps},
                                                  "research_questions": list(a["questions"]), "risk_areas": list(a["risk_areas"]), "note": NOTE}))
    found.sort(key=lambda t: t[:3])
    return [t[3] for t in found[:limit]]


# ---- B ----------------------------------------------------------------------------------------------------------------------------------------------------
def research_brief(archetype: str, region: str | None = None) -> dict[str, Any]:
    if archetype not in ARCHETYPES:
        raise InvalidBusinessInput("unknown business type")
    if region is not None and (not isinstance(region, str) or not region.strip() or len(region) > 80):
        raise InvalidBusinessInput("region is a short text")
    r = f" in {region.strip()}" if region else ""
    a = ARCHETYPES[archetype]
    topics = {k: [q.format(r=r)] for k, q in TOPICS.items()}
    topics["prices"].append(a["questions"][0])
    topics["legal"] += [q for q in a["questions"] if "recht" in q.lower() or "pflicht" in q.lower() or "auflagen" in q.lower() or "genehmig" in q.lower()]
    return {"archetype": archetype, "title": a["title"], "region": region, "topics": topics, "status": "draft", "requires_owner_approval": True,
            "rule": "Jede Aussage im Ergebnis braucht eine Quelle (URL, Abrufzeit) oder die Kennzeichnung ESTIMATE; fehlende Daten sind UNKNOWN."}


def audit_statements(statements: Sequence[Any]) -> list[dict[str, Any]]:
    """Statements that are neither sourced nor explicitly an assumption. Returns [{index, code}] - never the text."""
    problems = []
    for i, s in enumerate(statements if isinstance(statements, (list, tuple)) else []):
        basis = s.get("basis") if isinstance(s, Mapping) else None
        sources = s.get("sources") if isinstance(s, Mapping) else None
        if basis is None:
            code = "basis_missing"
        elif basis not in STATEMENT_BASES:
            code = "basis_unknown"
        elif basis == "FACT" and not sources:
            code = "fact_without_source"
        elif basis == "FACT" and not (isinstance(sources, (list, tuple)) and all(isinstance(u, str) and _URL.match(u) for u in sources)):
            code = "source_invalid"
        else:
            continue
        problems.append({"index": i, "code": code})
    return problems


# ---- C ----------------------------------------------------------------------------------------------------------------------------------------------------
def _num(raw: Any, what: str, **rule: bool) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) - {"value", "basis", "source"} or raw.get("basis") not in BASES:
        raise InvalidBusinessInput(f"{what}: an object {{value, basis: FACT|GIVEN|ESTIMATE, source}}")
    out: dict[str, Any] = {"value": number(raw.get("value"), what, **rule), "basis": raw["basis"]}
    source = raw.get("source")
    if raw["basis"] == "FACT":
        if not isinstance(source, str) or not _URL.match(source) or len(source) > 500:
            raise InvalidBusinessInput(f"{what}: a FACT needs a source URL")
        out["source"] = source
    elif source is not None:
        raise InvalidBusinessInput(f"{what}: only a FACT carries a source")
    return out


def financial_model(data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping) or set(data) - _MODEL:
        raise InvalidBusinessInput("model input: price, variable_cost, fixed_costs_month, startup_capital, units_month, ramp_months, months")
    months, ramp = data.get("months", 12), data.get("ramp_months", 0)
    if isinstance(months, bool) or not isinstance(months, int) or not 1 <= months <= 60 or isinstance(ramp, bool) or not isinstance(ramp, int) or not 0 <= ramp <= months:
        raise InvalidBusinessInput("months 1..60, ramp_months 0..months (whole numbers)")
    inp: dict[str, Any] = {}
    for key, rule in (("price", {"positive": True}), ("variable_cost", {"non_negative": True}), ("fixed_costs_month", {"non_negative": True}), ("startup_capital", {"non_negative": True})):
        if key in data:
            inp[key] = _num(data[key], key, **rule)
    if "units_month" in data:
        units = data["units_month"]
        if not isinstance(units, Mapping) or not 1 <= len(units) <= 6 or not all(isinstance(k, str) and 0 < len(k) <= 30 for k in units):
            raise InvalidBusinessInput("units_month: 1..6 named scenarios")
        inp["units_month"] = {k: _num(v, f"units_month.{k}", non_negative=True) for k, v in units.items()}
    missing = sorted(k for k in ("price", "variable_cost", "fixed_costs_month", "startup_capital", "units_month") if k not in inp)

    def val(key: str) -> float | None:
        return inp[key]["value"] if key in inp else None
    p, v, f, cap = val("price"), val("variable_cost"), val("fixed_costs_month"), val("startup_capital")
    units = {k: n["value"] for k, n in inp.get("units_month", {}).items()}
    bases = {k: ("ESTIMATE" if any(n["basis"] == "ESTIMATE" for n in x.values()) else "FACT" if all(n["basis"] == "FACT" for n in x.values()) else "GIVEN") if k == "units_month" else x["basis"]
             for k, x in inp.items()}
    out: dict[str, Any] = {"inputs": inp, "missing": missing, "months": months, "ramp_months": ramp,
                           "estimated_inputs": sorted(k for k, b in bases.items() if b == "ESTIMATE"), "given_inputs": sorted(k for k, b in bases.items() if b == "GIVEN"),
                           "verified_inputs": sorted(k for k, b in bases.items() if b == "FACT")}
    out["basis"] = "ESTIMATE" if out["estimated_inputs"] else "GIVEN" if out["given_inputs"] else "FACT" if out["verified_inputs"] else "UNKNOWN"
    out["contribution_margin"] = {"value": p - v, "formula": "price - variable cost"} if p is not None and v is not None else calc.unknown("missing data: price or variable cost")
    out["break_even"] = calc.break_even(f, p, v)
    ready = p is not None and v is not None and f is not None and bool(units)
    out["scenarios"] = {k: calc.scenario(p, v, f, u) for k, u in units.items()} if ready else {}
    ref = None
    if ready:
        ref = "base" if "base" in units else sorted(units, key=lambda k: (units[k], k))[len(units) // 2]
    out["reference_scenario"] = ref
    profit = out["scenarios"][ref]["profit"] if ref else None
    out["payback"] = calc.payback_months(cap, profit)
    if ready and cap is not None:
        cash, level = [-cap], units[ref]
        for i in range(1, months + 1):
            u = level * min(1.0, i / ramp) if ramp else level
            cash.append(cash[-1] + u * (p - v) - f)
        low = min(cash)
        out["liquidity"] = {"status": "COMPUTED", "cash_by_month": cash, "need": max(0.0, -low), "low_month": cash.index(low),
                            "positive_from_month": next((i for i, c in enumerate(cash) if c >= 0), None), "formula": "cumulative: -startup + sum(units x (price - variable cost) - fixed costs), linear ramp-up"}
    else:
        out["liquidity"] = calc.unknown("missing data: " + ", ".join(missing or ["units_month"]))
    if ready:
        u0 = units[ref]

        def prof(pp: float, vv: float, uu: float, ff: float) -> float:
            return uu * (pp - vv) - ff
        k = lambda s: 1 + s / 100                                    # noqa: E731
        factors = {"price": {str(s): prof(p * k(s), v, u0, f) for s in STEPS_PCT}, "variable_cost": {str(s): prof(p, v * k(s), u0, f) for s in STEPS_PCT},
                   "units": {str(s): prof(p, v, u0 * k(s), f) for s in STEPS_PCT}, "fixed_costs": {str(s): prof(p, v, u0, f * k(s)) for s in STEPS_PCT}}
        base = prof(p, v, u0, f)
        out["sensitivity"] = {"status": "COMPUTED", "base_profit": base, "steps_pct": list(STEPS_PCT), "factors": factors,
                              "strongest": max(sorted(factors), key=lambda n: abs(factors[n][str(STEPS_PCT[-1])] - base)), "note": "je ein Faktor verändert, alle anderen unverändert"}
    else:
        out["sensitivity"] = calc.unknown("missing data: " + ", ".join(missing or ["units_month"]))
    return out


# ---- D ----------------------------------------------------------------------------------------------------------------------------------------------------
def _ratings(item: Any) -> tuple[str, dict[str, dict[str, Any]]]:
    if not isinstance(item, Mapping) or not isinstance(item.get("name"), str) or not item["name"].strip() or not isinstance(item.get("ratings"), Mapping):
        raise InvalidBusinessInput("an idea needs a name and ratings")
    out = {}
    for c, r in item["ratings"].items():
        if c not in finder.CRITERIA or not isinstance(r, Mapping) or r.get("basis") not in ("FACT", "GIVEN", "INFERENCE", "ESTIMATE"):
            raise InvalidBusinessInput("ratings: known criteria with {value 1..5, basis}")
        value = number(r.get("value"), c)
        if not 1 <= value <= 5:
            raise InvalidBusinessInput("a rating is within 1..5")
        out[c] = {"value": value, "basis": r["basis"]}
    return item["name"].strip(), out


def _weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    w = {c: 1.0 for c in finder.CRITERIA}
    for k, v in (weights or {}).items():
        if k not in w:
            raise InvalidBusinessInput("weights: known criteria only")
        w[k] = number(v, f"weight {k}", non_negative=True)
    if sum(w.values()) <= 0:
        raise InvalidBusinessInput("at least one weight must be positive")
    return w


def rank(items: Sequence[Any], weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    w = _weights(weights)
    parsed = [_ratings(i) for i in (items if isinstance(items, (list, tuple)) else [])]
    if not parsed or len({n for n, _ in parsed}) != len(parsed):
        raise InvalidBusinessInput("at least one idea; names must be unique")
    rows = []
    for name, ratings in parsed:
        score, coverage, evidence, notes = finder._score(w, ratings)
        got = sum(w[c] for c in ratings)
        rows.append({"name": name, "score": score, "coverage": coverage, "evidence": evidence, "notes": notes,
                     "contributions": {c: w[c] * ratings[c]["value"] / got for c in ratings} if score is not None else {}})
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0), r["name"]))
    return {"ranking": rows, "weights": w, "method": "gewichteter Mittelwert der Bewertungen 1-5 (Finder-Verfahren); ohne ausreichende belegte Abdeckung keine Gesamtnote",
            "disclaimer": finder.DISCLAIMER}


def explain(a: Any, b: Any, weights: Mapping[str, float] | None = None) -> str:
    """Why one idea ranks before the other: the weighted difference per criterion, largest first. No percentages, no promise."""
    w = _weights(weights)
    (na, ra), (nb, rb) = _ratings(a), _ratings(b)
    sa, sb = finder._score(w, ra)[0], finder._score(w, rb)[0]
    if sa is None or sb is None:
        return f"{na} und {nb} sind nicht vergleichbar: mindestens eine Idee hat keine Gesamtnote (zu wenig belegte Bewertungen)."
    first, second, rf, rs = (na, nb, ra, rb) if (sa, nb) >= (sb, na) else (nb, na, rb, ra)
    total = sum(w.values())
    parts = sorted(((w[c] * (rf[c]["value"] - rs[c]["value"]) / total, c) for c in finder.CRITERIA if c in rf and c in rs and rf[c]["value"] != rs[c]["value"]), key=lambda t: (-abs(t[0]), t[1]))
    detail = "; ".join(f"{c} {d:+.3f} ({rf[c]['value']:g} gegen {rs[c]['value']:g}, Gewicht {w[c]:g})" for d, c in parts) or "keine Unterschiede in den gemeinsamen Kriterien"
    return f"{first} vor {second} (Note {max(sa, sb):.2f} gegen {min(sa, sb):.2f}): {detail}"


# ---- E ----------------------------------------------------------------------------------------------------------------------------------------------------
def _task(text: str, phase: int, kind: str, external: bool = False) -> dict[str, Any]:
    t = {"text": text[:200], "phase_days": phase, "kind": kind, "status": "blocked_external" if external else "proposed", "requires_owner_approval": True}
    if external:
        t["reason_code"] = "external_action_not_supported"
    return t


def blueprint(name: str, model: Mapping[str, Any], archetype: str | None = None, next_steps: Sequence[str] = ()) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip() or len(name) > 120 or not isinstance(model, Mapping) or "inputs" not in model:
        raise InvalidBusinessInput("blueprint: a name and a financial_model result")
    if archetype is not None and archetype not in ARCHETYPES:
        raise InvalidBusinessInput("unknown business type")
    a = ARCHETYPES.get(archetype or "", {})
    d30 = [_task(f"Fehlende Eingabe klären: {k}", 30, "clarify") for k in model.get("missing", [])]
    d30 += [_task(f"Schätzung belegen: {k} (Quelle, Angebot oder eigene Messung)", 30, "evidence") for k in model.get("estimated_inputs", [])]
    d30 += [_task(f"Recherche: {q}", 30, "research") for q in a.get("questions", ())[:3]]
    d30 += [_task(s, 30, "owner_step", external=bool(finder._EXTERNAL.search(s))) for s in _texts(list(next_steps), "next_steps")[:8]]
    d90 = [_task("Ist-Werte der ersten Aufträge mit dem Referenzszenario vergleichen", 90, "review"), _task("Modell mit belegten Werten neu rechnen und Rangfolge prüfen", 90, "review"),
           _task("Wirksamsten Weg der Kundengewinnung anhand eigener Daten bestimmen (Entwürfe, Freigabe je Maßnahme)", 90, "review")]
    strongest = (model.get("sensitivity") or {}).get("strongest")
    if strongest:
        d90.append(_task(f"Stärksten Hebel der Sensitivitätsanalyse beobachten: {strongest}", 90, "review"))
    inputs = model["inputs"]
    liq = model.get("liquidity", {})
    costs = {k: inputs[k] for k in ("startup_capital", "fixed_costs_month", "variable_cost") if k in inputs}
    costs["liquidity_need"] = {"value": liq["need"], "basis": model.get("basis")} if liq.get("status") == "COMPUTED" else calc.unknown(liq.get("reason", "not computed"))
    risks = [{"area": r, "countermeasure": COUNTERMEASURES[r]} for r in (a.get("risk_areas") or ("legal", "time"))]
    return {"name": name.strip(), "archetype": archetype, "basis": model.get("basis"), "days_30": d30, "days_90": d90, "costs": costs, "tools_needed": list(a.get("tools", ("noch zu bestimmen",))),
            "acquisition": [{"draft": x, "status": "draft", "requires_owner_approval": True} for x in a.get("acquisition", ("Leistungsbeschreibung als Entwurf",))], "risks": risks,
            "next_steps": [t["text"] for t in d30[:3]], "legal_note": finder.LEGAL_NOTE, "disclaimer": finder.DISCLAIMER}
