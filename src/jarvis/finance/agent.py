"""FinanceAgent: analysis and PAPER trading on the numbers it is given (user input, or sourced figures from research results). It has NO tools: it cannot
reach a broker, an account, the browser or the file system, and it contains no order, transfer or withdrawal code. Requests for any of those end BLOCKED.
Metrics are COMPUTED or UNKNOWN - never guessed. Output is analysis, not advice."""
from __future__ import annotations

import json
from dataclasses import asdict
import time
from typing import Any, Callable, Mapping

from jarvis.agents import policy as AP
from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentOutcome
from jarvis.finance import calc as C
from jarvis.finance import paper as PP
from jarvis.finance.errors import InvalidFinanceInput
from jarvis.finance.models import Direction, Metric, Position, RiskLimits, TradeIdea, number, symbol
from jarvis.research.handoff import ResearchData, collect, pick_figure

LIVE_KINDS = frozenset({"live_order", "place_order", "order", "order_execute", "execute_order", "buy", "sell", "trade", "transfer", "withdraw", "withdrawal",
                        "deposit", "payment", "broker_login", "leverage_trade", "open_position", "close_position", "margin"})
KINDS = ("financial_analysis", "company_analysis", "risk_analysis", "scenario_analysis", "portfolio_analysis", "paper_trade_analysis")
DISCLAIMER = "analysis only - not financial advice; nothing was ordered, transferred or withdrawn; figures are only as good as the data supplied"
FIELDS = ("price", "eps", "market_cap", "revenue", "revenue_previous", "net_income", "ebitda", "debt", "cash", "equity", "operating_cash_flow", "capex")


class FinanceAgent(Agent):
    id = "finance"
    name = "Finance Agent"
    description = ("Computes ratios, risk figures, scenarios and paper-trade simulations from supplied numbers (UNKNOWN when data is missing). "
                   "Analysis and paper trading only: no orders, no transfers, no broker.")
    capabilities = frozenset({AP.FINANCE_ANALYZE})
    tool_names = frozenset()

    def __init__(self, *, max_steps: int = 50, timeout: float = 120.0, max_result_chars: int = 20_000, limits: RiskLimits | None = None,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self.max_steps, self.timeout, self.max_result_chars = max_steps, timeout, max_result_chars
        self.limits = limits or RiskLimits()
        self._mono = monotonic

    def perform(self, task: AgentTask, ctx: AgentContext) -> AgentOutcome:
        if AP.FINANCE_ANALYZE not in ctx.allowed_capabilities:
            return AgentOutcome.blocked("this task does not allow the capability finance.analyze", code="capability_not_allowed")
        data = dict(task.input)
        kind = str(data.get("kind", "")).lower().strip()
        if kind in LIVE_KINDS or any(w in kind for w in ("order", "transfer", "withdraw", "broker")):
            return AgentOutcome.blocked("live trading, orders, transfers and withdrawals do not exist in this version; only analysis and paper trading are supported",
                                        code="live_trading_not_supported")
        if kind not in KINDS:
            return AgentOutcome.failed(f"unknown finance task kind {kind[:30]!r}; known: {', '.join(KINDS)}", code="invalid_input")
        deadline = self._mono() + self.timeout
        research = collect(ctx.parent_results, data.get("research"))
        try:
            result = getattr(self, "_" + kind)(data, research, ctx, deadline)
        except InvalidFinanceInput as exc:
            return AgentOutcome.failed(str(exc), code="invalid_input")
        if self._mono() > deadline:
            return AgentOutcome.failed("the finance task exceeded its time limit", code="timeout")
        out = {"kind": "finance_result", "task": kind, "objective": task.objective[:300], **result, "sources": [dict(s) for s in research.ok_sources[:20]],
               "disclaimer": DISCLAIMER, "paper": True}
        out = self._bound(out)
        return AgentOutcome.ok(str(result.get("summary", kind))[:400], out)

    # ---- helpers -------------------------------------------------------------------------------------------------------------------
    def _bound(self, out: dict[str, Any]) -> dict[str, Any]:
        while len(json.dumps(out)) > self.max_result_chars:
            out["truncated"] = True
            biggest = max((k for k, v in out.items() if isinstance(v, list) and v), key=lambda k: len(json.dumps(out[k])), default=None)
            if biggest is None:
                out = {k: v for k, v in out.items() if k in ("kind", "task", "summary", "disclaimer", "paper", "truncated")}
                break
            out[biggest] = out[biggest][: max(0, len(out[biggest]) // 2)]
        return out

    def _cap(self, items: Any, what: str) -> list[Any]:
        if not isinstance(items, (list, tuple)) or not items:
            raise InvalidFinanceInput(f"{what} must be a non-empty list")
        if len(items) > self.max_steps:
            raise InvalidFinanceInput(f"{what} has {len(items)} entries; at most {self.max_steps} are processed")
        return list(items)

    def _company(self, raw: Any, research: ResearchData) -> tuple[dict[str, Any], list[Metric], dict[str, str]]:
        if not isinstance(raw, Mapping):
            raise InvalidFinanceInput("a company is an object with the fields price, eps, revenue ...")
        unknown = set(raw) - set(FIELDS) - {"name", "symbol", "from_research"}
        if unknown:
            raise InvalidFinanceInput(f"unknown company fields {sorted(str(k)[:30] for k in unknown)}")
        vals: dict[str, float | None] = {}
        used: dict[str, str] = {}
        mapping = raw.get("from_research") or {}
        if not isinstance(mapping, Mapping):
            raise InvalidFinanceInput("from_research maps a field to a label keyword")
        for f in FIELDS:
            v = raw.get(f)
            if v is None and f in mapping and isinstance(mapping[f], str):
                fig = pick_figure(research, mapping[f])
                if fig is not None:
                    v, used[f] = fig["value"], str(fig.get("source_url"))[:200]
            vals[f] = None if v is None else number(v, f)
        name = str(raw.get("name") or raw.get("symbol") or "company")[:80]
        m = [C.pe_ratio(vals["price"], vals["eps"]), C.ps_ratio(vals["market_cap"], vals["revenue"]),
             C.ev_ebitda(vals["market_cap"], vals["debt"], vals["cash"], vals["ebitda"]), C.growth("Revenue growth", vals["revenue"], vals["revenue_previous"]),
             C.margin("Net margin", vals["net_income"], vals["revenue"]), C.margin("EBITDA margin", vals["ebitda"], vals["revenue"]),
             C.debt_to_equity(vals["debt"], vals["equity"]), C.free_cash_flow(vals["operating_cash_flow"], vals["capex"])]
        return {"name": name, "symbol": symbol(raw["symbol"]) if raw.get("symbol") else None}, m, used

    # ---- task kinds --------------------------------------------------------------------------------------------------------------------
    def _financial_analysis(self, data: Mapping[str, Any], research: ResearchData, ctx: AgentContext, deadline: float) -> dict[str, Any]:
        ident, metrics, used = self._company(data.get("company"), research)
        known = [m for m in metrics if m.value is not None]
        return {"summary": f"{ident['name']}: {len(known)} of {len(metrics)} metrics computed, {len(metrics) - len(known)} UNKNOWN (data missing or not meaningful)",
                "company": ident, "metrics": [m.to_dict() for m in metrics], "data_from_research": used}

    def _company_analysis(self, data: Mapping[str, Any], research: ResearchData, ctx: AgentContext, deadline: float) -> dict[str, Any]:
        companies = self._cap(data.get("companies"), "companies")
        rows, table = [], {}
        for c in companies:
            ident, metrics, used = self._company(c, research)
            rows.append({**ident, "metrics": [m.to_dict() for m in metrics], "data_from_research": used})
            for m in metrics:
                table.setdefault(m.name, []).append((ident["name"], m.value))
        ranking = {name: [{"company": n, "value": None if v is None else round(v, 6), "status": "UNKNOWN" if v is None else "COMPUTED"}
                          for n, v in sorted(vals, key=lambda t: (t[1] is None, t[1] if t[1] is not None else 0))] for name, vals in table.items()}
        return {"summary": f"{len(rows)} companies compared on {len(table)} metrics (ascending; UNKNOWN last; which direction is 'better' depends on the metric)",
                "companies": rows, "comparison": ranking}

    def _risk_analysis(self, data: Mapping[str, Any], research: ResearchData, ctx: AgentContext, deadline: float) -> dict[str, Any]:
        prices = self._cap(data.get("prices"), "prices")
        ppy = data.get("periods_per_year")
        dd, vol = C.max_drawdown(prices), C.volatility(prices, ppy if ppy is not None else None)
        first, last = number(prices[0], "price", positive=True), number(prices[-1], "price", positive=True)
        ret = Metric("Total return", last / first - 1, "last / first - 1", {"first": first, "last": last})
        return {"summary": f"{len(prices)} prices analysed", "symbol": symbol(data["symbol"]) if data.get("symbol") else None,
                "metrics": [m.to_dict() for m in (ret, dd, vol)]}

    def _scenario_analysis(self, data: Mapping[str, Any], research: ResearchData, ctx: AgentContext, deadline: float) -> dict[str, Any]:
        base_rev = number(data.get("revenue"), "revenue", positive=True)
        years = data.get("years", 3)
        if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 20:
            raise InvalidFinanceInput("years must be an integer within 1..20")
        scen = data.get("scenarios")
        if not isinstance(scen, Mapping) or not 1 <= len(scen) <= 6:
            raise InvalidFinanceInput("scenarios is an object with 1..6 named scenarios, e.g. {'bear': {'growth': 0, 'margin': 0.05}}")
        multiple = data.get("multiple")
        out = []
        for name, s in scen.items():
            if not isinstance(s, Mapping):
                raise InvalidFinanceInput("a scenario is an object with growth and margin")
            g, m = number(s.get("growth"), "growth"), number(s.get("margin"), "margin")
            if not -1 < g <= 5 or not -1 <= m <= 1:
                raise InvalidFinanceInput("growth must be within -100%..500% and margin within -100%..100%")
            rev = base_rev * (1 + g) ** years
            row: dict[str, Any] = {"scenario": str(name)[:30], "assumptions": {"growth": g, "margin": m, "years": years, "kind": "GIVEN"},
                                   "revenue_end": round(rev, 2), "profit_end": round(rev * m, 2)}
            if multiple is not None:
                mult = number(multiple, "multiple", positive=True)
                row["value_estimate"] = {"value": round(rev * m * mult, 2), "status": "ESTIMATE", "basis": f"profit x {mult:g} (the multiple is an assumption)"}
            out.append(row)
        return {"summary": f"{len(out)} scenario(s) over {years} year(s); all inputs are the given assumptions", "scenarios": out}

    def _portfolio_analysis(self, data: Mapping[str, Any], research: ResearchData, ctx: AgentContext, deadline: float) -> dict[str, Any]:
        raws = self._cap(data.get("positions"), "positions")
        positions = [Position(r.get("symbol"), r.get("quantity"), r.get("average_price")) if isinstance(r, Mapping) else _bad() for r in raws]
        marks = data.get("marks") or {}
        if not isinstance(marks, Mapping):
            raise InvalidFinanceInput("marks maps a symbol to its current price")
        snap = PP.snapshot(data.get("cash", 0), positions, {symbol(k): v for k, v in marks.items()})
        d = snap.to_dict()
        weights = []
        mv = snap.market_value
        if mv:
            weights = [{"symbol": p.symbol, "weight": round(p.quantity * pr / mv, 6)} for p, pr in snap.positions if pr is not None]
        unknown = [p.symbol for p, pr in snap.positions if pr is None]
        return {"summary": f"{len(positions)} position(s); " + (f"mark price UNKNOWN for {', '.join(unknown)}" if unknown else "all positions valued"),
                "portfolio": d, "weights": weights, "largest_weight": max((w["weight"] for w in weights), default=None)}

    def _paper_trade_analysis(self, data: Mapping[str, Any], research: ResearchData, ctx: AgentContext, deadline: float) -> dict[str, Any]:
        ideas = self._cap(data.get("ideas"), "ideas")
        account = data.get("account")
        account = None if account is None else number(account, "account", positive=True)
        results, closed = [], []
        exposure = 0.0
        for raw in ideas:
            if not isinstance(raw, Mapping):
                raise InvalidFinanceInput("an idea is an object")
            if self._mono() > deadline:
                raise InvalidFinanceInput("time limit reached while simulating")
            idea = TradeIdea(raw.get("symbol"), raw.get("direction"), raw.get("entry"), raw.get("stop"), raw.get("target"), raw.get("position_size"),
                             raw.get("confidence", 0.5), raw.get("thesis", ""), tuple(raw.get("invalidations") or ()))
            risk = PP.assess(idea, account, self.limits, exposure)
            row: dict[str, Any] = {"idea": idea.to_dict(), "risk": risk.to_dict()}
            if risk.ok:
                exposure += idea.entry * idea.position_size
                if raw.get("prices"):
                    trade = PP.simulate(idea, self._cap(raw["prices"], "prices"))
                    row["paper_trade"] = trade.to_dict()
                    closed.append(trade)
            else:
                row["paper_trade"] = None
                row["note"] = "not simulated: the risk limits are violated (or cannot be checked)"
            results.append(row)
        pnl = sum(t.pnl for t in closed)
        out: dict[str, Any] = {"summary": f"{len(results)} idea(s): {sum(1 for r in results if r['risk']['ok'])} within the risk limits, {len(closed)} simulated, paper P&L {pnl:.2f}",
                               "trades": results, "paper_pnl": round(pnl, 4), "limits": asdict(self.limits)}
        if account is not None and closed:
            out["daily_loss_limit_reached"] = PP.daily_loss_exceeded(closed, account, self.limits)
        return out


def _bad() -> Any:
    raise InvalidFinanceInput("a position is an object with symbol, quantity and average_price")
