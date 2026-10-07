"""`/run` front-ends of the analysis capabilities: small, side-effect-free calculation tools (GREEN). They compute on the numbers passed in and report status;
they open no connection, read and write no file and cannot move money - there is no action here for that. They go through ToolRegistry -> PermissionEngine
like every tool."""
from __future__ import annotations

from typing import Any, Callable

from jarvis.business import calc as BK
from jarvis.finance import calc as FK
from jarvis.finance.errors import FinanceError
from jarvis.business.errors import BusinessError
from jarvis.permissions import PermissionLevel
from jarvis.research.urls import ResearchUrlPolicy
from jarvis.tools.base import Tool, ToolParameter, ToolResult
from jarvis.tools.registry import ToolRegistry


def _f(kw: dict[str, Any], name: str, required: bool = True) -> float | None:
    v = kw.get(name)
    if v in (None, ""):
        if required:
            raise ValueError(f"{name} is required")
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        raise ValueError(f"{name} must be a number") from None


def _list(kw: dict[str, Any], name: str) -> list[float]:
    raw = str(kw.get(name, "")).replace(";", ",")
    try:
        vals = [float(x.replace(" ", "")) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise ValueError(f"{name} must be a comma-separated list of numbers") from None
    if not vals or len(vals) > 1000:
        raise ValueError(f"{name} needs 1..1000 numbers")
    return vals


class _Calc(Tool):
    permission = PermissionLevel.GREEN
    actions: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def __init__(self, status: Callable[[], dict[str, Any]]) -> None:
        self._status = status

    def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action", "status")).lower()
        if action == "status":
            return ToolResult.ok(self._status())
        fn = self.actions.get(action)
        if fn is None:
            return ToolResult.fail(f"unknown action {action[:30]!r}; known: status, {', '.join(self.actions)}")
        try:
            return ToolResult.ok(fn(dict(kwargs)))
        except (ValueError, BusinessError, FinanceError) as exc:
            return ToolResult.fail(str(exc)[:300])


class ResearchTool(_Calc):
    name = "research"
    description = "Research helpers: status | check_url url=... (would the research agent read this address?). Reading pages is done by the research agent via the browser."
    parameters = (ToolParameter("action", "status | check_url", required=False), ToolParameter("url", "address to check", required=False))

    def __init__(self, status: Callable[[], dict[str, Any]], private_hosts_allowed: tuple[str, ...] = ()) -> None:
        super().__init__(status)
        self._policy = ResearchUrlPolicy(private_hosts_allowed=private_hosts_allowed)
        self.actions = {"check_url": self._check}

    def _check(self, kw: dict[str, Any]) -> dict[str, Any]:
        d = self._policy.check(kw.get("url"))
        return {"allowed": d.ok, "canonical_url": d.url if d.ok else None, "reason": d.reason}


class BusinessTool(_Calc):
    name = "business"
    description = "Business calculations: status | break_even fixed_costs= price= variable_cost= | price_stats values=1,2,3"
    parameters = (ToolParameter("action", "status | break_even | price_stats", required=False), ToolParameter("fixed_costs", "fixed costs", required=False),
                  ToolParameter("price", "price per unit", required=False), ToolParameter("variable_cost", "variable cost per unit", required=False),
                  ToolParameter("values", "comma-separated prices", required=False))

    def __init__(self, status: Callable[[], dict[str, Any]]) -> None:
        super().__init__(status)
        self.actions = {"break_even": lambda kw: BK.break_even(_f(kw, "fixed_costs", False), _f(kw, "price", False), _f(kw, "variable_cost", False)),
                        "price_stats": lambda kw: BK.price_stats(_list(kw, "values"))}


class FinanceTool(_Calc):
    name = "finance"
    description = ("Finance calculations (analysis / paper only; no orders, no transfers): status | risk_reward direction= entry= stop= target= | "
                   "position_size account= risk_pct= entry= stop= | pe price= eps= | drawdown prices=1,2,3")
    parameters = (ToolParameter("action", "status | risk_reward | position_size | pe | drawdown", required=False),
                  *(ToolParameter(n, n, required=False) for n in ("direction", "entry", "stop", "target", "account", "risk_pct", "price", "eps", "prices")))

    def __init__(self, status: Callable[[], dict[str, Any]]) -> None:
        super().__init__(status)
        self.actions = {
            "risk_reward": lambda kw: FK.risk_reward(str(kw.get("direction", "long")), _f(kw, "entry"), _f(kw, "stop"), _f(kw, "target")).to_dict(),
            "position_size": lambda kw: FK.position_size(_f(kw, "account"), _f(kw, "risk_pct"), _f(kw, "entry"), _f(kw, "stop")).to_dict(),
            "pe": lambda kw: FK.pe_ratio(_f(kw, "price", False), _f(kw, "eps", False)).to_dict(),
            "drawdown": lambda kw: FK.max_drawdown(_list(kw, "prices")).to_dict()}


def register_analysis_tools(registry: ToolRegistry, subsystems: dict[str, Any], private_hosts_allowed: tuple[str, ...] = ()) -> None:
    """Register the front-ends of the ENABLED capabilities only."""
    for name, factory in (("research", lambda s: ResearchTool(s, private_hosts_allowed)), ("business", BusinessTool), ("finance", FinanceTool)):
        sub = subsystems.get(name)
        if sub is not None and getattr(sub, "available", False):
            registry.register(factory(sub.describe))
