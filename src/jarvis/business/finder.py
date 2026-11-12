"""Business-Finder (WP04): compares business candidates the OWNER names, from the owner's frame, the owner's numbers and the research results that were handed over.

What it is: deterministic arithmetic and fixed rules. No LLM, no tools, no network, nothing is sent, ordered, published or stored. It does NOT invent ideas, markets, prices,
costs, sources or revenues: a value is GIVEN (owner), FACT (a source stated it), INFERENCE (computed here from GIVEN/FACT data), ESTIMATE (an assumption, says from what) or
UNKNOWN. Missing data stays UNKNOWN and is shown.

Evaluation logic and its limits (also in README / docs/TESTING.md):
- Matrix: 10 criteria, 5 = most favourable for the owner. Four are derived from GIVEN numbers (startup_cost, time_effort, skill_fit, time_to_income: INFERENCE), six are rated by the
  owner (GIVEN or ESTIMATE). The overall score is the weighted mean of the rated criteria and is shown ONLY if the rated weight share (coverage) is >= 60 % AND the share backed by
  GIVEN/FACT/INFERENCE ratings (evidence coverage) is >= 40 %. Otherwise there is no overall score, only the list of gaps. These thresholds are heuristics, not facts.
- Plausibility rules P1-P7 are warnings, not proofs: they point at inputs to double-check. Their thresholds (90 % margin, 5 % market share) are heuristics.
- P5 compares a scenario with a market size only if the market size is stated by >= 2 independent hosts, without conflict, in the candidate's currency, and the owner says whether
  the figure is per month or per year. Otherwise P5 is "not_evaluated" and says why.
- Scenario figures (revenue, costs, units) are per month. A score or a scenario is NOT a forecast and NOT a promise of income.
- Follow-up tasks are proposals for existing agents or the owner; each needs the owner's approval; external actions (purchase, payment, contract, registration, publishing,
  sending) are only listed as blocked and are never executed or planned as steps."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from jarvis.business import calc as K
from jarvis.business.errors import InvalidBusinessInput
from jarvis.business.models import clip, number
from jarvis.research.analysis import label_key
from jarvis.research.handoff import ResearchData, pick_figure

CRITERIA = ("demand", "competition", "startup_cost", "running_costs", "time_effort", "scalability", "risk", "skill_fit", "time_to_income", "goal_fit")
DERIVED = ("startup_cost", "time_effort", "skill_fit", "time_to_income")
OWNER_RATED = tuple(c for c in CRITERIA if c not in DERIVED)
MAX_CANDIDATES, MAX_LIST, MAX_SOURCE_URLS, MAX_NEXT_STEPS, MAX_UNITS = 5, 10, 5, 5, 6
MIN_COVERAGE, MIN_EVIDENCE = 0.6, 0.4                    # heuristics
P2_MARGIN, P5_SHARE = 0.90, 0.05                         # heuristics
RESULT_BUDGET = 11_000                                   # characters of the finder report inside the 20 000 character task result
AREAS = ("legal", "platform", "payment_liability", "scaling", "time", "privacy", "reputation")
AREA_WORDS = {"legal": ("gewerb", "genehmig", "lizenz", "erlaubnis", "gesetz", "vorschrift", "regulier", "zulassung"),
              "platform": ("plattform", "marktplatz", "ebay", "amazon"), "payment_liability": ("haftung", "zahlungsausfall", "rückbuchung", "chargeback"),
              "scaling": ("skalier",), "time": ("zeitaufwand", "arbeitszeit"), "privacy": ("datenschutz", "dsgvo"), "reputation": ("rufschädig", "reputation")}
LEGAL_NOTE = "Rechtslage nicht geprüft; keine Rechtsberatung - vor einer Umsetzung rechtlich prüfen lassen."
DISCLAIMER = "Entwurf, keine Prognose, keine Ertragszusage. Bewertung aus gegebenen Eingaben und gelesenen Quellen; Annahmen (ESTIMATE) und Lücken (UNKNOWN) sind markiert."
_EXTERNAL = re.compile(r"(kauf|bezahl|zahl|überweis|vertrag|unterschreib|gründ|anmeld|registrier|veröffentlich|publizier|poste|versend|sende|e-?mail|nachricht|anruf|bestell|abschließ|"
                       r"eröffn|einzahl|abonnier|beauftrag|miet|kündig|buy|purchase|pay|sign|regist|publish|post\b|send|order|contract|launch|account|subscri|hire|rent|deposit)", re.IGNORECASE)
_TOP = {"kind", "frame", "candidates", "research"}
_FRAME = {"interests", "skills", "hours_per_week", "start_budget_limit", "legal_area", "risk_tolerance", "exclusions", "weights"}
_CAND = {"name", "description", "source_urls", "required_skills", "plan", "ratings", "currency", "market_period", "risk_notes", "next_steps"}
_PLAN = {"price", "price_label", "variable_cost", "fixed_costs", "investment", "units", "hours_needed_per_week"}


# ---- input -------------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Frame:
    interests: tuple[str, ...]
    skills: tuple[str, ...]
    hours_per_week: float | None
    start_budget_limit: float | None
    legal_area: str
    risk_tolerance: str
    exclusions: tuple[str, ...]
    weights: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {"basis": "GIVEN", "interests": list(self.interests), "skills": list(self.skills), "hours_per_week": self.hours_per_week,
                "start_budget_limit": self.start_budget_limit, "legal_area": self.legal_area, "risk_tolerance": self.risk_tolerance, "exclusions": list(self.exclusions),
                "weights": dict(self.weights)}


@dataclass(frozen=True)
class Candidate:
    name: str
    description: str
    source_urls: tuple[str, ...]
    required_skills: tuple[str, ...]
    plan: Mapping[str, Any]
    ratings: Mapping[str, tuple[float, str, str]]
    currency: str
    market_period: str
    risk_notes: Mapping[str, str]
    next_steps: tuple[str, ...]


def _obj(value: Any, what: str, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidBusinessInput(f"{what} must be an object")
    extra = sorted(str(k)[:30] for k in value if k not in allowed)
    if extra:
        raise InvalidBusinessInput(f"{what}: unknown keys {extra}; allowed: {sorted(allowed)}")
    return value


def _text(value: Any, what: str, limit: int, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise InvalidBusinessInput(f"{what} is required")
        return ""
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value):
        raise InvalidBusinessInput(f"{what} must be plain text of at most {limit} characters" + (" (not empty)" if required else ""))
    return value.strip()


def _texts(value: Any, what: str, limit: int, count: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > count:
        raise InvalidBusinessInput(f"{what} is a list of at most {count} texts")
    return tuple(_text(v, what, limit, required=True) for v in value)


def _opt_number(value: Any, what: str, *, positive: bool = False) -> float | None:
    return None if value is None else number(value, what, positive=positive, non_negative=not positive)


def parse_frame(raw: Any) -> Frame:
    f = _obj(raw, "frame", _FRAME)
    if not f:
        raise InvalidBusinessInput("frame must not be empty: name at least one of interests, skills, hours_per_week, start_budget_limit, legal_area, risk_tolerance, exclusions")
    tol = f.get("risk_tolerance", "")
    if tol not in ("", "low", "medium", "high"):
        raise InvalidBusinessInput("risk_tolerance is one of low, medium, high")
    weights = f.get("weights") or {}
    if not isinstance(weights, Mapping) or set(weights) - set(CRITERIA):
        raise InvalidBusinessInput(f"weights is an object over the criteria {list(CRITERIA)}")
    w = {c: number(weights.get(c, 1), f"weight {c}", positive=True) for c in CRITERIA}
    if any(v > 100 for v in w.values()):
        raise InvalidBusinessInput("a weight is at most 100")
    return Frame(_texts(f.get("interests"), "interests", 80, MAX_LIST), _texts(f.get("skills"), "skills", 80, MAX_LIST), _opt_number(f.get("hours_per_week"), "hours_per_week"),
                 _opt_number(f.get("start_budget_limit"), "start_budget_limit"), _text(f.get("legal_area"), "legal_area", 60), tol,
                 _texts(f.get("exclusions"), "exclusions", 80, MAX_LIST), w)


def _url(value: Any) -> str:
    u = _text(value, "source url", 500, required=True)
    p = urlsplit(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise InvalidBusinessInput("source_urls are http(s) addresses")
    return u


def parse_candidate(raw: Any) -> Candidate:
    c = _obj(raw, "candidate", _CAND)
    plan = _obj(c.get("plan") or {}, "plan", _PLAN)
    units = plan.get("units")
    if units is not None and (not isinstance(units, Mapping) or not 1 <= len(units) <= MAX_UNITS):
        raise InvalidBusinessInput(f"units is an object with 1..{MAX_UNITS} named scenarios")
    clean: dict[str, Any] = {"price": _opt_number(plan.get("price"), "price", positive=True), "variable_cost": _opt_number(plan.get("variable_cost"), "variable_cost"),
                             "fixed_costs": _opt_number(plan.get("fixed_costs"), "fixed_costs"), "investment": _opt_number(plan.get("investment"), "investment"),
                             "hours_needed_per_week": _opt_number(plan.get("hours_needed_per_week"), "hours_needed_per_week"),
                             "price_label": _text(plan.get("price_label"), "price_label", 60),
                             "units": None if units is None else {_text(k, "scenario name", 30, required=True): number(v, "units", non_negative=True) for k, v in units.items()}}
    ratings: dict[str, tuple[float, str, str]] = {}
    raw_ratings = c.get("ratings") or {}
    if not isinstance(raw_ratings, Mapping):
        raise InvalidBusinessInput("ratings is an object")
    for key, r in raw_ratings.items():
        if key not in OWNER_RATED:
            raise InvalidBusinessInput(f"ratings: {str(key)[:30]!r} cannot be rated by the owner; allowed: {list(OWNER_RATED)} ({list(DERIVED)} are derived from the numbers)")
        r = _obj(r, f"rating {key}", {"value", "basis", "source"})
        value = number(r.get("value"), f"rating {key}")
        basis = r.get("basis", "ESTIMATE")
        if not 1 <= value <= 5 or basis not in ("GIVEN", "ESTIMATE"):
            raise InvalidBusinessInput(f"rating {key}: value 1..5 and basis GIVEN or ESTIMATE (FACT/INFERENCE are never accepted from the input)")
        ratings[key] = (value, basis, _text(r.get("source"), "rating source", 300))
    notes_raw = c.get("risk_notes") or {}
    if not isinstance(notes_raw, Mapping) or set(notes_raw) - set(AREAS):
        raise InvalidBusinessInput(f"risk_notes is an object over {list(AREAS)}")
    period = c.get("market_period", "")
    if period not in ("", "month", "year"):
        raise InvalidBusinessInput("market_period is month or year")
    urls = c.get("source_urls") or []
    if not isinstance(urls, (list, tuple)) or len(urls) > MAX_SOURCE_URLS:
        raise InvalidBusinessInput(f"source_urls is a list of at most {MAX_SOURCE_URLS} addresses")
    return Candidate(_text(c.get("name"), "name", 80, required=True), _text(c.get("description"), "description", 300), tuple(_url(u) for u in urls),
                     _texts(c.get("required_skills"), "required_skills", 80, MAX_LIST), clean, ratings, _text(c.get("currency"), "currency", 8).upper(), period,
                     {k: _text(v, f"risk note {k}", 300) for k, v in notes_raw.items()}, _texts(c.get("next_steps"), "next_steps", 200, MAX_NEXT_STEPS))


def parse_input(data: Mapping[str, Any]) -> tuple[Frame, tuple[Candidate, ...]]:
    _obj(data, "input", _TOP)
    if "frame" not in data or "candidates" not in data:
        raise InvalidBusinessInput("business_finder needs frame and candidates (no data is invented)")
    raw = data["candidates"]
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= MAX_CANDIDATES:
        raise InvalidBusinessInput(f"candidates is a list of 1..{MAX_CANDIDATES} entries")
    cands = tuple(parse_candidate(c) for c in raw)
    if len({c.name.lower() for c in cands}) != len(cands):
        raise InvalidBusinessInput("candidate names must be unique")
    return parse_frame(data["frame"]), cands


# ---- research slice --------------------------------------------------------------------------------------------------------------------------------
def _norm(url: Any) -> str:
    return str(url).strip().rstrip("/").lower()


def slice_research(research: ResearchData, urls: tuple[str, ...]) -> ResearchData:
    """Only what the candidate's own source URLs say (the finder never attributes other pages to a candidate)."""
    keep = {_norm(u) for u in urls}
    sources = tuple(s for s in research.sources if _norm(s.get("url")) in keep)
    figures = tuple(f for f in research.figures if _norm(f.get("source_url")) in keep)
    claims = tuple(c for c in research.claims if keep & {_norm(u) for u in c.get("sources", []) if isinstance(u, str)})
    conflicts = tuple(c for c in research.conflicts if any(isinstance(e, Mapping) and _norm(e.get("source")) in keep for e in c.get("entries", [])))
    return ResearchData(sources, figures, claims, conflicts, research.uncertainties)


# ---- one candidate ---------------------------------------------------------------------------------------------------------------------------------
Helpers = Mapping[str, Callable[..., Any]]            # {"competitors": f(ResearchData) -> list[Competitor], "overview": f(ResearchData) -> (dict, list), "market": f(ResearchData) -> dict}


def _cost(value: float | None, basis: str = "GIVEN") -> dict[str, Any]:
    return {"value": value, "basis": basis if value is not None else "UNKNOWN"}


def _price(c: Candidate, rd: ResearchData) -> dict[str, Any]:
    if c.plan["price"] is not None:
        return _cost(c.plan["price"])
    label = c.plan["price_label"]
    fig = pick_figure(rd, label) if label else None
    if fig is None:
        return _cost(None)
    if any(x.get("label") == label_key(str(fig["label"])) and x.get("unit") == fig["unit"] for x in rd.conflicts):
        return {"value": None, "basis": "UNKNOWN", "note": "sources conflict on this figure: no number is taken from them"}
    return {"value": float(fig["value"]), "basis": "ESTIMATE", "note": f"taken from a sourced figure ({fig['label']}) at {fig['source_url']}; not a recommendation"}


def _scenarios(c: Candidate, price: dict[str, Any], costs: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    need = {"price": price["value"], "variable_cost": costs["variable_unit"]["value"], "fixed_costs": costs["fixed_monthly"]["value"], "units": c.plan["units"]}
    missing = [k for k, v in need.items() if v is None]
    if missing:
        return K.unknown("missing data: " + ", ".join(missing)), None
    return K.scenarios(need["price"], need["variable_cost"], need["fixed_costs"], need["units"]), ("INFERENCE" if price["basis"] == "GIVEN" else "ESTIMATE")


def _rule(rule: str, status: str, text: str = "", **extra: Any) -> dict[str, Any]:
    if status == "ok":
        return {"rule": rule, "status": "ok"}                                     # compact: nothing to explain
    out = {"rule": rule, "status": status, "basis": "INFERENCE" if status in ("warning", "violation") else "UNKNOWN"}
    if text:
        out["reason" if status == "not_evaluated" else "text"] = text
    return out | extra


def _plausibility(frame: Frame, c: Candidate, price: dict[str, Any], costs: dict[str, Any], scen: dict[str, Any], scen_basis: str | None, market: dict[str, Any]) -> list[dict[str, Any]]:
    computed = scen.get("status") != "UNKNOWN"
    rows = list(scen.values()) if computed else []
    out: list[dict[str, Any]] = []
    # P1 no profit
    if computed:
        loss = sorted(k for k, v in scen.items() if v["profit"] <= 0)
        out.append(_rule("P1", "warning", f"Szenario(en) ohne Gewinn: {', '.join(loss)} (Gewinn <= 0)") if loss else _rule("P1", "ok"))
    else:
        out.append(_rule("P1", "not_evaluated", scen["reason"]))
    # P2 unusually high margin (heuristic)
    if computed:
        high = sorted(k for k, v in scen.items() if v["margin"] is not None and v["margin"] > P2_MARGIN)
        out.append(_rule("P2", "warning", f"Marge über {P2_MARGIN:.0%} in {', '.join(high)}: ungewöhnlich hoch (Heuristik-Schwelle; Warnsignal, kein Beweis für fehlerhafte Daten) - Preis und Kosten prüfen",
                         threshold=P2_MARGIN) if high else _rule("P2", "ok", threshold=P2_MARGIN))
    else:
        out.append(_rule("P2", "not_evaluated", scen["reason"], threshold=P2_MARGIN))
    # P3 capacity
    need, have = c.plan["hours_needed_per_week"], frame.hours_per_week
    if need is None or have is None:
        out.append(_rule("P3", "not_evaluated", "hours_needed_per_week (candidate) and hours_per_week (frame) are both needed"))
    else:
        out.append(_rule("P3", "warning", f"braucht {need:g} h/Woche, der Rahmen bietet {have:g} h/Woche (Kapazität überschritten)") if need > have else _rule("P3", "ok"))
    # P4 start budget (hard owner limit)
    inv, limit = costs["startup"]["value"], frame.start_budget_limit
    if inv is None or limit is None:
        out.append(_rule("P4", "not_evaluated", "investment (candidate) and start_budget_limit (frame) are both needed"))
    else:
        out.append(_rule("P4", "violation", f"Investition {inv:g} überschreitet das Startbudget (start_budget_limit {limit:g})") if inv > limit else _rule("P4", "ok"))
    # P5 share of a documented market size (only with a corroborated, comparable figure)
    out.append(_p5(c, rows, market))
    # P6 scenario inputs that are not given
    if computed:
        out.append(_rule("P6", "warning", "die Szenarien nutzen einen aus einer Quelle übernommenen Preis (ESTIMATE), keinen vom Owner genannten") if scen_basis == "ESTIMATE" else _rule("P6", "ok"))
    else:
        out.append(_rule("P6", "not_evaluated", scen["reason"]))
    # P7 completeness
    out.append(_rule("P7", "ok") if computed else _rule("P7", "not_evaluated", scen["reason"] + " - no scenario is computed from incomplete numbers"))
    return out


def _p5(c: Candidate, rows: list[dict[str, Any]], market: dict[str, Any]) -> dict[str, Any]:
    ms = market.get("market_size", {})
    if not rows:
        return _rule("P5", "not_evaluated", "no scenario revenue (see P7)", threshold=P5_SHARE)
    if not c.currency or not c.market_period:
        return _rule("P5", "not_evaluated", "currency and market_period of the candidate are needed to compare with a market size", threshold=P5_SHARE)
    if ms.get("status") != "FACT":
        return _rule("P5", "not_evaluated", "no source stated a market size", threshold=P5_SHARE)
    values = ms.get("values", [])
    hosts = {_host(v.get("source")) for v in values if v.get("unit") == c.currency}
    if ms.get("conflict"):
        return _rule("P5", "not_evaluated", "the market size figures of the sources conflict", threshold=P5_SHARE)
    if len(hosts) < 2 or any(v.get("unit") != c.currency for v in values):
        return _rule("P5", "not_evaluated", f"a market size in {c.currency} from at least two independent hosts is needed (found {len(hosts)})", threshold=P5_SHARE,
                     market_source_count=len(hosts))
    size = min(float(v["value"]) for v in values)
    top = max(r["revenue"] for r in rows) * (12 if c.market_period == "year" else 1)
    share = top / size if size > 0 else None
    if share is None:
        return _rule("P5", "not_evaluated", "the documented market size is zero", threshold=P5_SHARE)
    base = {"threshold": P5_SHARE, "share": round(share, 4), "market_source_count": len(hosts)}
    if share > P5_SHARE:
        return _rule("P5", "warning", f"der höchste Szenario-Umsatz ist {share:.1%} der belegten Marktgröße (Heuristik-Schwelle {P5_SHARE:.0%}; ein lokaler Anbieter kann in einem kleinen Markt "
                                      "legitim mehr Anteil haben - Geltungsbereich der Marktzahl prüfen)", **base)
    return _rule("P5", "ok", **base)


def _host(url: Any) -> str:
    try:
        return (urlsplit(str(url)).hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def _band(ratio: float, bands: tuple[tuple[float, int], ...]) -> int:
    return next((v for limit, v in bands if ratio <= limit + 1e-12), 1)


def _derived(frame: Frame, c: Candidate, costs: dict[str, Any], payback: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    inv, limit = costs["startup"]["value"], frame.start_budget_limit
    if inv is not None and limit is not None:
        v = (5 if inv == 0 else 1) if limit == 0 else _band(inv / limit, ((0.25, 5), (0.5, 4), (0.75, 3), (1.0, 2)))
        out["startup_cost"] = {"value": v, "basis": "INFERENCE"}
    need, have = c.plan["hours_needed_per_week"], frame.hours_per_week
    if need is not None and have is not None:
        v = (5 if need == 0 else 1) if have == 0 else _band(need / have, ((0.25, 5), (0.5, 4), (0.75, 3), (1.0, 2)))
        out["time_effort"] = {"value": v, "basis": "INFERENCE"}
    if c.required_skills and frame.skills:
        mine = {s.lower() for s in frame.skills}
        frac = sum(1 for s in c.required_skills if s.lower() in mine) / len(c.required_skills)
        out["skill_fit"] = {"value": round(1 + 4 * frac, 2), "basis": "INFERENCE"}
    if payback.get("status") == "COMPUTED":
        m = payback["months"]
        out["time_to_income"] = {"value": 5 if m <= 6 else 4 if m <= 12 else 3 if m <= 24 else 2 if m <= 36 else 1, "basis": "INFERENCE"}
    return out


def _score(weights: Mapping[str, float], ratings: Mapping[str, Mapping[str, Any]]) -> tuple[float | None, float, float, list[str]]:
    total = sum(weights[c] for c in CRITERIA)
    got = sum(weights[c] for c in CRITERIA if c in ratings)
    ev = sum(weights[c] for c in CRITERIA if c in ratings and ratings[c]["basis"] in ("GIVEN", "FACT", "INFERENCE"))
    cov, evc = got / total, ev / total
    notes: list[str] = []
    if cov + 1e-9 < MIN_COVERAGE:
        notes.append(f"Abdeckung {cov:.0%} < {MIN_COVERAGE:.0%}: keine Gesamtnote")
        return None, cov, evc, notes
    if evc + 1e-9 < MIN_EVIDENCE:
        notes.append(f"belegte Abdeckung {evc:.0%} < {MIN_EVIDENCE:.0%} (nur Annahmen): keine Gesamtnote")
        return None, cov, evc, notes
    return sum(weights[c] * ratings[c]["value"] for c in ratings) / got, cov, evc, notes


def _matrix(frame: Frame, c: Candidate, derived: dict[str, dict[str, Any]], plaus: list[dict[str, Any]], excluded: list[str]) -> dict[str, Any]:
    ratings: dict[str, dict[str, Any]] = dict(derived)
    for key, (value, basis, source) in c.ratings.items():
        ratings[key] = {"value": value, "basis": basis} | ({"source": clip(source, 120)} if source else {})
    score, cov, evc, notes = _score(frame.weights, ratings)
    sens: dict[str, list[float | None]] = {}
    if score is not None:
        for key, r in ratings.items():
            pair = []
            for d in (-1, 1):
                mod = {**ratings, key: {**r, "value": min(5, max(1, r["value"] + d))}}
                s = _score(frame.weights, mod)[0]
                pair.append(None if s is None else round(s, 2))
            sens[key] = pair
    blocked = False
    if excluded:
        notes.append("excluded by the owner's exclusions: " + ", ".join(excluded) + " - not ranked")
        blocked = True
    if any(p["rule"] == "P4" and p["status"] == "violation" for p in plaus):
        notes.append("Startbudget (start_budget_limit) überschritten - not ranked")
        blocked = True
    return {"ratings": ratings, "coverage": round(cov, 4), "evidence_coverage": round(evc, 4), "score": None if score is None else round(score, 2),
            "ranked": score is not None and not blocked, "notes": notes, "unknown": [k for k in CRITERIA if k not in ratings], "sensitivity": sens,
            "min_coverage": MIN_COVERAGE, "min_evidence_coverage": MIN_EVIDENCE}


def _risks(c: Candidate, rd: ResearchData) -> list[dict[str, Any]]:
    out = []
    facts = [x for x in rd.claims if x.get("kind") == "FACT" and x.get("sources")]
    for area in AREAS:
        note = c.risk_notes.get(area)
        hit = next((x for x in facts if any(w in str(x.get("text", "")).lower() for w in AREA_WORDS[area])), None)
        legal = " " + LEGAL_NOTE if area == "legal" else ""
        if note:
            out.append({"area": area, "status": "GIVEN", "basis": "GIVEN", "text": clip(note, 200) + legal, "sources": []})
        elif hit:
            out.append({"area": area, "status": "SOURCED", "basis": "FACT", "text": "source states: " + clip(str(hit["text"]), 160) + legal, "sources": [hit["sources"][0]]})
        else:
            out.append({"area": area, "status": "UNKNOWN", "text": "UNKNOWN" + legal, "sources": []} if area == "legal" else {"area": area, "status": "UNKNOWN"})
    return out


def _follow_ups(c: Candidate, cand: dict[str, Any], start: int) -> list[dict[str, Any]]:
    """Proposals only. Each needs the owner's approval; external actions are listed as blocked and never planned."""
    tasks: list[dict[str, Any]] = []

    def add(text: str, agent: str, capability: str | None) -> None:
        tasks.append({"id": f"F{start + len(tasks) + 1}", "candidate": clip(c.name, 40), "text": clip(text, 110), "agent": agent, "capability": capability,
                      "requires_owner_approval": True, "status": "proposed"})

    if cand["break_even"]["status"] == "UNKNOWN" or cand["scenarios"].get("status") == "UNKNOWN":
        add("fehlende Preis-/Kostenangaben mit echten Angeboten belegen und den Finder erneut ausführen", "owner", None)
    if cand["source_support"] != "full":
        add("fehlende Quellen lesen lassen (Research mit zusätzlichen URLs des Owners)", "research", "research.web")
    if cand["scenarios"].get("status") != "UNKNOWN":
        add("Szenarien mit einer Finanzanalyse vertiefen (finance, scenario_analysis)", "finance", "finance.analyze")
    if cand["matrix"]["score"] is None:
        add("fehlende Bewertungskriterien ergänzen: " + ", ".join(cand["matrix"]["unknown"][:6]), "owner", None)
    if any(r["area"] == "legal" and r["status"] == "UNKNOWN" for r in cand["risks"]):
        add("rechtliche Anforderungen prüfen lassen (Fachperson)", "owner", None)
    for text in c.next_steps:
        if _EXTERNAL.search(text):
            tasks.append({"id": f"F{start + len(tasks) + 1}", "candidate": clip(c.name, 40), "text": clip(text, 100), "agent": "owner", "capability": None, "requires_owner_approval": True,
                          "status": "blocked_external", "reason_code": "external_action_not_supported"})
        else:
            add(text, "owner", None)
    return tasks


def _round(v: Any) -> Any:
    """Two decimals are enough for a draft and keep the result small."""
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


def _lean(d: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: d[k] for k in keys if k in d}


def _flat_conflict(x: Mapping[str, Any]) -> dict[str, Any]:
    """Agent results may nest at most 8 levels: entries become short texts (host=value)."""
    return {"label": clip(str(x.get("label", "")), 50), "unit": str(x.get("unit", ""))[:8],
            "values": [f"{clip(_host(e.get('source')), 40)}={e.get('value')}" for e in list(x.get("entries", []))[:4] if isinstance(e, Mapping)]}


def _comp_lines(comps: list[Any], overview: Mapping[str, Any]) -> dict[str, Any]:
    """Agent results may nest at most 8 levels and a goal keeps 8 000 characters of a step result: competitors and prices become short texts."""
    prices = [f"{clip(k, 50)}: n={v.get('n')}, {v.get('min'):g}-{v.get('max'):g}, median {v.get('median'):g}" + (" [conflict]" if v.get("conflict") else "")
              for k, v in list(overview.items())[:4] if isinstance(v.get("min"), (int, float))]
    return {"competitors": [f"{clip(c.name, 40)}: {c.positioning}" for c in comps[:5]], "prices": prices}


def analyse_candidate(frame: Frame, c: Candidate, research: ResearchData, helpers: Helpers) -> dict[str, Any]:
    rd = slice_research(research, c.source_urls)
    ok = {_norm(s["url"]) for s in rd.ok_sources}
    unread = [u for u in c.source_urls if _norm(u) not in ok]
    support = "none" if not ok else "full" if not unread else "partial"
    price = _price(c, rd)
    costs = {"startup": _cost(c.plan["investment"]), "fixed_monthly": _cost(c.plan["fixed_costs"]), "variable_unit": _cost(c.plan["variable_cost"]), "price": price}
    be = _lean(K.break_even(costs["fixed_monthly"]["value"], price["value"], costs["variable_unit"]["value"]), ("status", "reason", "units", "contribution_margin"))
    scen, scen_basis = _scenarios(c, price, costs)
    payback: dict[str, Any] = K.unknown("scenarios or investment missing")
    if scen.get("status") != "UNKNOWN":
        base = scen.get("base") or min(scen.values(), key=lambda s: s["profit"])
        payback = _lean(K.payback_months(costs["startup"]["value"], base["profit"]), ("status", "reason", "months"))
    market = helpers["market"](rd)
    plaus = _plausibility(frame, c, price, costs, scen, scen_basis, market)
    text = f"{c.name} {c.description}".lower()
    excluded = [x for x in frame.exclusions if x.lower() in text]
    matrix = _matrix(frame, c, _derived(frame, c, costs, payback), plaus, excluded)
    assumptions = [{"name": k, "value": v["value"], "basis": v["basis"], "note": clip(v.get("note", "stated by the owner"), 160)}
                   for k, v in (("investment", costs["startup"]), ("fixed_costs", costs["fixed_monthly"]), ("variable_cost", costs["variable_unit"]), ("price", price)) if v["value"] is not None]
    comps = helpers["competitors"](rd)
    overview, _ = helpers["overview"](rd)
    cand: dict[str, Any] = {
        "name": c.name, "description": clip(c.description, 200), "source_support": support, "sources": [s["url"] for s in rd.ok_sources], "unread_sources": unread,
        "source_conflicts": [_flat_conflict(x) for x in rd.conflicts][:3], "source_conflict_count": len(rd.conflicts), "excluded_by": excluded, "costs": costs, "break_even": _round(be), "scenarios": _round(scen), "scenario_basis": scen_basis,
        "payback": _round(payback), "market": market.get("market_size", {}), "competition": _comp_lines(comps, overview),
        "plausibility": plaus, "matrix": matrix, "risks": _risks(c, rd), "assumptions": assumptions}
    return cand


# ---- report ----------------------------------------------------------------------------------------------------------------------------------------
def build_report(frame: Frame, candidates: tuple[Candidate, ...], research: ResearchData, helpers: Helpers, check_cancelled: Callable[[], None]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for c in candidates:
        check_cancelled()
        row = analyse_candidate(frame, c, research, helpers)
        row["follow_up_count"] = 0
        tasks += (new := _follow_ups(c, row, len(tasks)))
        row["follow_up_count"] = len(new)
        rows.append(row)
    total = len(tasks)
    tasks = [t for t in tasks if t["status"] == "blocked_external"][:MAX_TASKS] + [t for t in tasks if t["status"] != "blocked_external"]
    tasks = tasks[:MAX_TASKS]
    ranked = sorted((r for r in rows if r["matrix"]["ranked"]), key=lambda r: (-round(r["matrix"]["score"], 9), -r["matrix"]["evidence_coverage"], r["name"]))
    unknown_weight = [r["name"] for r in rows if r["matrix"]["score"] is None]
    rep: dict[str, Any] = {"frame": frame.to_dict(), "candidates": rows, "ranking": [r["name"] for r in ranked],
                           "ranking_note": ("candidates without an overall score are not ranked: " + ", ".join(unknown_weight)) if unknown_weight else "",
                           "follow_up_tasks": tasks, "follow_up_total": total,
                           "external_actions": "purchases, payments, contracts, registrations, publishing and sending are never done by JARVIS here; such steps are listed as blocked_external only",
                           "legal_notice": LEGAL_NOTE,
                           "method": "Note = gewichteter Mittelwert (5 = günstig), nur bei Abdeckung >= 60 % und belegter Abdeckung >= 40 % (Heuristiken); P1-P7 sind Warnungen, keine Beweise",
                           "truncated": False, "detail_level": 0}
    if frame.risk_tolerance == "low":
        rep["risk_note"] = "risk tolerance is low: " + "; ".join(f"{r['name']}: {sum(1 for x in r['risks'] if x['status'] == 'UNKNOWN')} risk area(s) UNKNOWN" for r in rows)
    return rep


GOAL_OUTPUT_LIMIT = 7_800          # the goal engine stores at most 8 000 characters of a step result (goals/policy.MAX_OUTPUT_CHARS); a test keeps this in step
MAX_LEVEL = 7
MAX_TASKS = 14                                       # follow-up proposals listed in total (the total is reported)


def shrink(rep: dict[str, Any], level: int) -> None:
    """Drop detail in a fixed order (cumulative per level) and say so; ranking, scores, warnings, conflicts and gaps stay until the very end."""
    rep["truncated"], rep["detail_level"] = True, level
    cands = rep["candidates"]
    if level == 1:
        rep["frame"] = dict(rep["frame"], interests=rep["frame"]["interests"][:3], skills=rep["frame"]["skills"][:3], exclusions=rep["frame"]["exclusions"][:3])
        for c in cands:
            c["matrix"].pop("sensitivity", None)
            c["competition"], c["market"], c["sources"] = {}, {}, []
            for x in c["matrix"]["ratings"].values():
                x.pop("source", None)
    elif level == 2:
        for c in cands:
            c["assumptions"] = []
            c["matrix"]["ratings"] = {k: f"{v['value']:g} {v['basis']}" for k, v in c["matrix"]["ratings"].items()}
            for p in c["plausibility"]:
                if p["status"] not in ("warning", "violation"):
                    p.pop("reason", None), p.pop("text", None), p.pop("basis", None)
    elif level == 3:
        for c in cands:
            if c["scenarios"].get("status") != "UNKNOWN":
                c["scenarios"] = {k: {"revenue": v["revenue"], "profit": v["profit"]} for k, v in c["scenarios"].items()}
            c["costs"] = {k: v["value"] for k, v in c["costs"].items()}
            c["risks"] = [dict(x, text=clip(x["text"], 80)) if "text" in x else x for x in c["risks"] if x["status"] != "UNKNOWN" or x["area"] == "legal"]
    elif level == 4:
        for c in cands:
            c["description"] = clip(c["description"], 40)
            c["source_conflicts"] = [f"{x['label']} ({x['unit']}): {len(x['values'])} sources" for x in c["source_conflicts"]]
        rep["follow_up_tasks"] = ([t for t in rep["follow_up_tasks"] if t["status"] == "blocked_external"][:6] + [t for t in rep["follow_up_tasks"] if t["status"] != "blocked_external"][:6])
    elif level == 5:
        keep = ("name", "source_support", "excluded_by", "source_conflicts", "source_conflict_count", "break_even", "payback", "scenario_basis", "matrix", "plausibility", "risks")
        rep["candidates"] = [{k: c[k] for k in keep} for c in cands]
        for c in rep["candidates"]:
            c["plausibility"] = [{"rule": p["rule"], "status": p["status"]} for p in c["plausibility"] if p["status"] in ("warning", "violation")]
            c["risks"] = [x for x in c["risks"] if x["area"] == "legal"]
            c["matrix"] = {k: c["matrix"][k] for k in ("score", "coverage", "evidence_coverage", "ranked", "notes", "unknown")}
    elif level == 6:
        rep["follow_up_tasks"] = rep["follow_up_tasks"][:4]
        rep["frame"] = {k: rep["frame"][k] for k in ("risk_tolerance", "legal_area")}
        rep.pop("method", None)
        rep.pop("external_actions", None)
        for c in rep["candidates"]:
            c["risks"] = [dict(x, text=clip(x["text"], 40)) for x in c["risks"]]
            c["matrix"]["notes"] = [clip(n, 70) for n in c["matrix"]["notes"]]
    elif level == 7:                                    # pathological inputs only: identity, score, warnings, conflict labels, gaps, break-even and payback remain
        rep["ranking"] = [clip(n, 40) for n in rep["ranking"]]
        rep["follow_up_tasks"] = rep["follow_up_tasks"][:3]
        for c in rep["candidates"]:
            c["name"], c["risks"] = clip(c["name"], 40), []
            c["source_conflicts"] = [clip(x, 40) for x in c["source_conflicts"]]
            c["matrix"]["notes"] = [clip(n, 40) for n in c["matrix"]["notes"]]
            c["matrix"] = {k: c["matrix"][k] for k in ("score", "ranked", "coverage", "evidence_coverage", "notes", "unknown")}
            c["break_even"], c["payback"] = _lean(c["break_even"], ("status", "units")), _lean(c["payback"], ("status", "months"))


def fit(rep: dict[str, Any], measure: Callable[[dict[str, Any], int], int], limit: int = GOAL_OUTPUT_LIMIT) -> tuple[dict[str, Any], int]:
    """The report and its detail level such that measure(report, level) <= limit (measure builds the whole task result for that level)."""
    level = 0
    while measure(rep, level) > limit and level < MAX_LEVEL:
        level += 1
        shrink(rep, level)
    return rep, level
