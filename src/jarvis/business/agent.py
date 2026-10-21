"""BusinessAgent: turns research results (from parent tasks) and the user's own numbers into structured business analyses and DRAFTS. It has NO tools:
it cannot read the web, write files, or send anything - there is nothing here that contacts anybody. Outreach (e-mails, messages, offers) is not
something this agent can do; if it ever got such a tool it would be an ordinary YELLOW tool behind the permission engine.
Every number is labelled GIVEN / FACT / INFERENCE / ESTIMATE / UNKNOWN; missing data is UNKNOWN, not guessed."""
from __future__ import annotations

import json
import re
import statistics
import time
from collections import defaultdict
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from jarvis.agents import policy as AP
from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentOutcome
from jarvis.business import calc as K
from jarvis.business.errors import InvalidBusinessInput
from jarvis.business.models import Assumption, Basis, BusinessResult, Competitor, Entry, clip, number
from jarvis.research.analysis import label_key
from jarvis.research.handoff import ResearchData, collect, pick_figure

def site_of(url: object) -> str:
    """The site a URL belongs to: host (and a non-default port) without a leading 'www.'."""
    try:
        p = urlsplit(str(url))
        host = (p.hostname or "").removeprefix("www.")
        return host + (f":{p.port}" if p.port and p.port not in (80, 443) else "")
    except ValueError:
        return ""


KINDS = ("market_analysis", "competitor_analysis", "business_plan", "business_analysis", "marketing_draft", "lead_list")
EXTERNAL_KINDS = frozenset({"send", "send_email", "email", "message", "send_message", "dm", "outreach", "cold_outreach", "contact", "offer", "send_offer",
                            "contract", "order", "purchase", "payment", "post", "publish"})
MARKET_WORDS = ("markt", "market", "marktvolumen", "marktgröße", "market size", "umsatz")
MAX_TEXT = 300


class BusinessAgent(Agent):
    id = "business"
    name = "Business Agent"
    description = ("Market and competitor analysis, business plan calculations, business-data analysis, marketing drafts and lead preparation from research results "
                   "and given numbers. Labels every number; UNKNOWN when data is missing. Drafts and analyses only - sends nothing.")
    capabilities = frozenset({AP.BUSINESS_ANALYZE})
    tool_names = frozenset()

    def __init__(self, *, max_steps: int = 20, timeout: float = 120.0, max_result_chars: int = 20_000, monotonic: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self.max_steps, self.timeout, self.max_result_chars = max_steps, timeout, max_result_chars
        self._mono = monotonic

    def perform(self, task: AgentTask, ctx: AgentContext) -> AgentOutcome:
        if AP.BUSINESS_ANALYZE not in ctx.allowed_capabilities:
            return AgentOutcome.blocked("this task does not allow the capability business.analyze", code="capability_not_allowed")
        data = dict(task.input)
        kind = str(data.get("kind", "")).lower().strip()
        if kind in EXTERNAL_KINDS or any(w in kind for w in ("send", "email", "outreach", "contract", "payment")):
            return AgentOutcome.blocked("this agent sends nothing and contacts nobody: outreach, offers and contracts need a separate, permission-checked action and "
                                        "your explicit confirmation", code="external_action_not_supported")
        if kind not in KINDS:
            return AgentOutcome.failed(f"unknown business task kind {kind[:30]!r}; known: {', '.join(KINDS)}", code="invalid_input")
        deadline = self._mono() + self.timeout
        research = collect(ctx.parent_results, data.get("research"))
        try:
            result = getattr(self, "_" + kind)(task.objective, data, research)
        except InvalidBusinessInput as exc:
            return AgentOutcome.failed(str(exc), code="invalid_input")
        if self._mono() > deadline:
            return AgentOutcome.failed("the business task exceeded its time limit", code="timeout")
        return AgentOutcome.ok(clip(result.summary, 400), result.to_dict(self.max_result_chars))

    # ---- shared pieces -----------------------------------------------------------------------------------------------------------------
    def _cap(self, items: Any, what: str) -> list[Any]:
        if items is None:
            return []
        if not isinstance(items, (list, tuple)):
            raise InvalidBusinessInput(f"{what} must be a list")
        if len(items) > self.max_steps:
            raise InvalidBusinessInput(f"{what} has {len(items)} entries; at most {self.max_steps} are processed")
        return list(items)

    @staticmethod
    def _given_assumptions(data: Mapping[str, Any]) -> list[Assumption]:
        raw = data.get("assumptions") or {}
        if not isinstance(raw, Mapping) or len(raw) > 30:
            raise InvalidBusinessInput("assumptions is an object of up to 30 named values")
        return [Assumption(str(k)[:80], v if isinstance(v, (int, float, str, bool)) else str(v)[:200], Basis.GIVEN, "stated by the user") for k, v in raw.items()]

    @staticmethod
    def _sources(research: ResearchData) -> tuple[dict[str, Any], ...]:
        return tuple({k: v for k, v in s.items() if k in ("url", "title", "source", "retrieved_at", "status", "note")} for s in research.sources)

    @staticmethod
    def _confidence(research: ResearchData, extra_unknowns: int = 0) -> dict[str, Any]:
        ok = len(research.ok_sources)
        reasons = [f"{ok} source(s) read"]
        score = min(ok, 5) / 5 * 0.6
        if research.conflicts:
            score -= 0.2
            reasons.append(f"{len(research.conflicts)} conflict(s) between sources")
        corro = sum(1 for c in research.claims if c.get("corroborated"))
        if corro:
            score += min(corro, 5) / 5 * 0.2
            reasons.append(f"{corro} corroborated statement(s)")
        if extra_unknowns:
            score -= min(extra_unknowns, 5) * 0.05
            reasons.append(f"{extra_unknowns} item(s) UNKNOWN")
        if ok == 0:
            reasons.append("no research data: the analysis rests on the given numbers only")
        score = round(max(0.0, min(1.0, score)), 2)
        return {"level": "high" if score >= 0.7 else "medium" if score >= 0.35 else "low", "score": score, "reasons": reasons}

    def _competitors_from(self, data: Mapping[str, Any], research: ResearchData) -> list[Competitor]:
        """One competitor per source host; names from the user's `competitors` list (name/url) where given. Prices are the sourced figures of that page."""
        names: dict[str, str] = {}
        for c in self._cap(data.get("competitors"), "competitors"):
            if isinstance(c, Mapping) and isinstance(c.get("url"), str):
                names[site_of(c["url"])] = clip(str(c.get("name") or ""), 120)
        by_host: dict[str, dict[str, Any]] = {}
        for s in research.ok_sources:
            host = site_of(s["url"])
            by_host.setdefault(host, {"url": s["url"], "title": s.get("title") or host})
        comps = []
        for host, info in list(by_host.items())[: self.max_steps]:
            prices: dict[str, dict[str, Any]] = {}
            for f in research.figures:
                if site_of(f["source_url"]) == host and f["unit"] in ("EUR", "USD"):
                    prices.setdefault(label_key(str(f["label"])), {"value": f["value"], "unit": f["unit"], "basis": Basis.FACT.value, "source": f["source_url"]})
            offers = tuple(clip(c.get("text", ""), 200) for c in research.claims if c.get("kind") == "FACT"
                           and any(site_of(u) == host for u in c.get("sources", [])))[:5]
            comps.append(Competitor(names.get(host) or clip(str(info["title"]), 120), str(info["url"]), prices, offers))
        return self._position(comps)

    @staticmethod
    def _position(comps: list[Competitor]) -> list[Competitor]:
        """Positioning (INFERENCE): a competitor's price vs the median of the same price label across competitors; needs >= 3 competitors with that price."""
        by_label: dict[str, list[float]] = defaultdict(list)
        for c in comps:
            for label, p in c.prices.items():
                by_label[label].append(p["value"])
        out = []
        for c in comps:
            ratios, strengths, weaknesses = [], [], []
            for label, p in c.prices.items():
                vals = by_label[label]
                if len(vals) >= 3:
                    med = statistics.median(vals)
                    if med > 0:
                        ratios.append(p["value"] / med)
                        src = (p["source"],)
                        if p["value"] == min(vals):
                            strengths.append(Entry(f"lowest price for '{label}' ({p['value']:g} {p['unit']}) among {len(vals)} sources", Basis.INFERENCE, src))
                        if p["value"] == max(vals):
                            weaknesses.append(Entry(f"highest price for '{label}' ({p['value']:g} {p['unit']}) among {len(vals)} sources", Basis.INFERENCE, src))
            if ratios:
                r = statistics.fmean(ratios)
                pos = "budget" if r < 0.85 else "premium" if r > 1.15 else "mid"
                out.append(Competitor(c.name, c.url, c.prices, c.offers, pos, Basis.INFERENCE, tuple(strengths), tuple(weaknesses)))
            else:
                out.append(c)
        return out

    @staticmethod
    def _market_data(research: ResearchData) -> dict[str, Any]:
        figs = [f for f in research.figures if any(w in str(f["label"]).lower() for w in MARKET_WORDS)]
        if not figs:
            return {"market_size": {"status": "UNKNOWN", "reason": "no source stated a market size"}}
        return {"market_size": {"status": "FACT", "values": [{"label": f["label"], "value": f["value"], "unit": f["unit"], "source": f["source_url"]} for f in figs[:5]],
                                "conflict": len({f["value"] for f in figs}) > 1}}

    @staticmethod
    def _price_overview(research: ResearchData) -> tuple[dict[str, Any], list[Entry]]:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for f in research.figures:
            if f["unit"] in ("EUR", "USD"):
                groups[(label_key(str(f["label"])), f["unit"])].append(f)
        overview: dict[str, Any] = {}
        opp: list[Entry] = []
        conflicted = {(c.get("label"), c.get("unit")) for c in research.conflicts}
        for (label, unit), fs in list(groups.items())[:20]:
            srcs = tuple(dict.fromkeys(str(f["source_url"]) for f in fs))
            stats = K.price_stats([f["value"] for f in fs])
            overview[f"{label} ({unit})"] = {**stats, "sources": list(srcs[:5]), "basis": Basis.INFERENCE.value, "conflict": (label, unit) in conflicted,
                                             "note": "computed from the sourced figures" if len(srcs) >= 2 else "single source"}
            if len(srcs) >= 2 and (label, unit) not in conflicted and stats.get("spread_pct", 0) and stats["spread_pct"] >= 20:
                opp.append(Entry(f"prices for '{label}' vary by {stats['spread_pct']:.0f}% ({stats['min']:g}-{stats['max']:g} {unit}): room for positioning (inference from {len(srcs)} sources)",
                                 Basis.INFERENCE, srcs[:3]))
        return overview, opp

    # ---- task kinds ---------------------------------------------------------------------------------------------------------------------
    def _market_analysis(self, objective: str, data: Mapping[str, Any], research: ResearchData) -> BusinessResult:
        comps = self._competitors_from(data, research)
        overview, opp = self._price_overview(research)
        market = {**self._market_data(research), "price_overview": overview}
        findings = [Entry(f"{len(research.ok_sources)} source(s) read, {len(comps)} competitor(s) identified", Basis.FACT if research.ok_sources else Basis.UNKNOWN)]
        findings += [Entry(c.get("text", ""), Basis.FACT if c.get("kind") == "FACT" else Basis.INFERENCE, tuple(c.get("sources", [])[:3]))
                     for c in research.claims if c.get("kind") in ("FACT", "INFERENCE")][:8]
        risks, unknowns = [], []
        if len(comps) < 3:
            risks.append(Entry("fewer than 3 competitors found: the market picture is incomplete", Basis.INFERENCE))
        if research.conflicts:
            risks.append(Entry(f"{len(research.conflicts)} price/figure conflict(s) between sources: numbers must be verified before they are relied on", Basis.FACT))
        if market["market_size"]["status"] == "UNKNOWN":
            unknowns.append("market size: no source stated it")
        if not research.ok_sources:
            unknowns.append("no research data was available")
        recs = [Entry("verify the conflicting or single-source figures directly with the providers before deciding", Basis.INFERENCE)] if (research.conflicts or opp) else []
        if not recs and research.ok_sources:
            recs.append(Entry("the data shows no conflicts; widen the sample (more sources) to raise confidence", Basis.INFERENCE))
        return BusinessResult(objective, "market_analysis", f"market analysis from {len(research.ok_sources)} source(s): {len(comps)} competitor(s), {len(overview)} price group(s), "
                              f"{len(research.conflicts)} conflict(s); unknown: {len(unknowns)}", tuple(findings), market, tuple(comps), tuple(opp), tuple(risks),
                              tuple(self._given_assumptions(data)), tuple(recs), self._sources(research), self._confidence(research, len(unknowns)), {}, {}, tuple(unknowns))

    def _competitor_analysis(self, objective: str, data: Mapping[str, Any], research: ResearchData) -> BusinessResult:
        comps = self._competitors_from(data, research)
        overview, opp = self._price_overview(research)
        findings = [Entry(f"{c.name}: positioning {c.positioning}" + (f" ({len(c.prices)} price(s))" if c.prices else " (no prices found)"), c.positioning_basis, (c.url,))
                    for c in comps]
        unknowns = [f"{c.name}: positioning UNKNOWN (needs >= 3 competitors with comparable prices)" for c in comps if c.positioning == "UNKNOWN"]
        risks = [Entry("price comparison rests on very few competitors", Basis.INFERENCE)] if len(comps) < 3 else []
        if research.conflicts:
            risks.append(Entry(f"{len(research.conflicts)} conflicting figure(s): see the research conflicts", Basis.FACT))
        return BusinessResult(objective, "competitor_analysis", f"{len(comps)} competitor(s) compared on {len(overview)} price group(s)", tuple(findings), {"price_overview": overview},
                              tuple(comps), tuple(opp), tuple(risks), tuple(self._given_assumptions(data)), (), self._sources(research),
                              self._confidence(research, len(unknowns)), {}, {}, tuple(unknowns))

    def _business_plan(self, objective: str, data: Mapping[str, Any], research: ResearchData) -> BusinessResult:
        assumptions = self._given_assumptions(data)
        plan = data.get("plan") or {}
        if not isinstance(plan, Mapping):
            raise InvalidBusinessInput("plan is an object: offer, target_audience, price, variable_cost, fixed_costs, units, investment")
        unknowns: list[str] = []

        def val(name: str, *, positive: bool = False, non_negative: bool = True) -> float | None:
            v = plan.get(name)
            if v is None:
                unknowns.append(f"{name}: not given")
                return None
            n = number(v, name, positive=positive, non_negative=non_negative and not positive)
            assumptions.append(Assumption(name, n, Basis.GIVEN, "stated by the user"))
            return n

        price = val("price", positive=True) if plan.get("price") is not None else None
        fig = pick_figure(research, str(plan["price_label"])) if price is None and plan.get("price_label") else None
        if fig is not None and any(c.get("label") == label_key(str(fig["label"])) and c.get("unit") == fig["unit"] for c in research.conflicts):
            unknowns.append(f"price: the sources conflict on '{fig['label']}' - no number is taken from them; give a price or verify the sources")
            fig = None
        elif fig is not None:
            price = number(fig["value"], "price", positive=True)
            assumptions.append(Assumption("price", price, Basis.ESTIMATE, f"taken from a competitor figure ({fig['label']}) at {fig['source_url']}; not a recommendation"))
            unknowns = [u for u in unknowns if not u.startswith("price")]
        elif price is None and not any(u.startswith("price") for u in unknowns):
            unknowns.append("price: not given")
        var = val("variable_cost")
        fixed = val("fixed_costs")
        invest = val("investment")
        be = K.break_even(fixed, price, var)
        calcs: dict[str, Any] = {"break_even": be}
        units = plan.get("units")
        if units is not None and price is not None and var is not None and fixed is not None:
            calcs["scenarios"] = K.scenarios(price, var, fixed, units)
            base = calcs["scenarios"].get("base") or next(iter(calcs["scenarios"].values()))
            calcs["payback"] = K.payback_months(invest, base["profit"] if invest is not None else None)
        else:
            calcs["scenarios"] = K.unknown("price, variable_cost, fixed_costs and units are needed")
            unknowns.append("scenarios: needs price, variable_cost, fixed_costs and units")
        risks = [Entry("all revenue scenarios depend on the assumed unit volumes, which no source confirmed", Basis.INFERENCE)]
        if be.get("status") == "UNKNOWN":
            risks.append(Entry("break-even could not be computed: " + str(be.get("reason")), Basis.UNKNOWN))
        overview, opp = self._price_overview(research)
        model = {k: clip(str(plan[k]), MAX_TEXT) for k in ("offer", "target_audience", "pricing_strategy") if plan.get(k)}
        steps = [Entry(t, Basis.INFERENCE) for t in ("validate the price and volume assumptions with real customers", "obtain quotes to replace the cost estimates",
                                                     "re-run the plan with confirmed numbers")]
        return BusinessResult(objective, "business_plan", "business plan calculation: " + ("break-even computed" if be.get("status") == "COMPUTED" else "break-even UNKNOWN") +
                              f"; {len(unknowns)} item(s) missing", (Entry("business model as given by the user", Basis.GIVEN),), {"price_overview": overview}, (), tuple(opp),
                              tuple(risks), tuple(assumptions), tuple(steps), self._sources(research), self._confidence(research, len(unknowns)), calcs,
                              {"business_model": model}, tuple(unknowns))

    def _business_analysis(self, objective: str, data: Mapping[str, Any], research: ResearchData) -> BusinessResult:
        rows = self._cap(data.get("rows"), "rows")
        res = K.period_findings(rows)
        findings: list[Entry] = []
        risks: list[Entry] = []
        unknowns: list[str] = []
        if res.get("status") == "UNKNOWN":
            unknowns.append("no business data was given (rows with period, revenue, costs)")
        else:
            findings.append(Entry(f"{len(res['rows'])} period(s) analysed from the given data", Basis.GIVEN))
            if res["loss_periods"]:
                risks.append(Entry(f"loss-making period(s): {', '.join(res['loss_periods'][:6])}", Basis.INFERENCE))
            rc, cc = res.get("revenue_change"), res.get("cost_change")
            if rc is not None and rc < 0:
                risks.append(Entry(f"revenue fell {abs(rc) * 100:.1f}% between the first and the last period", Basis.INFERENCE))
            if rc is not None and cc is not None and cc > rc:
                risks.append(Entry(f"costs grew faster ({cc * 100:.1f}%) than revenue ({rc * 100:.1f}%)", Basis.INFERENCE))
            margins = [t["margin"] for t in res["rows"] if t["margin"] is not None]
            if margins and statistics.fmean(margins) < 0.05:
                risks.append(Entry(f"the average margin is low ({statistics.fmean(margins) * 100:.1f}%)", Basis.INFERENCE))
        return BusinessResult(objective, "business_analysis", f"{len(risks)} weak point(s) found in the given data" if not unknowns else "no data to analyse", tuple(findings), {},
                              (), (), tuple(risks), tuple(self._given_assumptions(data)), (), (), {"level": "medium" if not unknowns else "low", "score": 0.5 if not unknowns else 0.0,
                              "reasons": ["based on the numbers the user provided; no external verification"]}, {"periods": res}, {}, tuple(unknowns))

    def _marketing_draft(self, objective: str, data: Mapping[str, Any], research: ResearchData) -> BusinessResult:
        m = data.get("marketing") or {}
        if not isinstance(m, Mapping):
            raise InvalidBusinessInput("marketing is an object: audience, offer, usp (list), tone, channels")
        audience, offer = clip(str(m.get("audience", "")).strip(), 120), clip(str(m.get("offer", "")).strip(), 120)
        usps = [clip(str(u), 120) for u in (m.get("usp") or [])[:5]] if isinstance(m.get("usp"), list) else []
        unknowns = [n for n, v in (("audience", audience), ("offer", offer)) if not v]
        if unknowns:
            return BusinessResult(objective, "marketing_draft", "no draft: audience and offer are needed", unknowns=tuple(f"{n}: not given" for n in unknowns),
                                  confidence={"level": "low", "score": 0.0, "reasons": ["input missing"]})
        words: dict[str, int] = defaultdict(int)
        for c in research.claims:
            for w in re.findall(r"[a-zäöüß]{5,}", str(c.get("text", "")).lower()):
                words[w] += 1
        seo = [w for w, _ in sorted(words.items(), key=lambda t: (-t[1], t[0]))[:8]]
        usp_line = " · ".join(usps)
        drafts = {"status": "DRAFT - nothing was published or sent",
                  "headline_ideas": [f"{offer} für {audience}", f"{offer}: {usps[0]}" if usps else f"Jetzt {offer} entdecken"],
                  "ad_drafts": [f"{offer} – speziell für {audience}. {usp_line}".strip(" .") + ". Jetzt anfragen."],
                  "social_drafts": [f"{offer} für {audience}: {usp_line}".strip(": ")],
                  "landing_page_outline": ["Hero: " + offer, "Nutzen: " + (usp_line or "to be filled in by the user"), "Preise/Pakete (only confirmed numbers)", "Kontakt/Call-to-action"],
                  "content_ideas": [f"FAQ zu {offer}", f"Vorher/Nachher-Beispiele für {audience}", "Preisübersicht erklärt"],
                  "seo_keywords": {"values": seo, "basis": Basis.INFERENCE.value if seo else Basis.UNKNOWN.value, "note": "frequent terms of the researched pages" if seo else "no research text"}}
        return BusinessResult(objective, "marketing_draft", "marketing drafts prepared from the given audience/offer (nothing was published)", (), {}, (), (), (),
                              tuple(self._given_assumptions(data)), (Entry("review every draft and check claims before using them", Basis.INFERENCE),), self._sources(research),
                              self._confidence(research), {}, drafts, ())

    def _lead_list(self, objective: str, data: Mapping[str, Any], research: ResearchData) -> BusinessResult:
        """Public businesses found in the research - names and public URLs only. Contacting them is NOT done here."""
        leads = [{"name": clip(str(s.get("title") or s.get("source") or ""), 120), "url": s["url"], "source": s.get("source"), "retrieved_at": s.get("retrieved_at"),
                  "basis": Basis.FACT.value} for s in research.ok_sources[: self.max_steps]]
        notes = ("prepared only: no message, e-mail or offer was or will be sent by this agent; any outreach is a separate YELLOW action through the permission engine "
                 "and needs your explicit confirmation")
        return BusinessResult(objective, "lead_list", f"{len(leads)} public business page(s) listed" if leads else "no leads: no research data",
                              (Entry(notes, Basis.FACT),), {}, (), (), (), (), (), self._sources(research), self._confidence(research), {}, {"leads": leads, "outreach": "NOT SENT"},
                              () if leads else ("no research data",))
