"""V2.1 M7: typed evidence reports for the agents `business` and `strategist`, derived on the GATE side - never taken from the agent.

An agent's own claim (including any `quality_report` it carries) is not evidence. What counts is what can be checked independently of the agent:
  * sources     - a cited URL counts only if a SUCCEEDED parent task (the stored orchestrator record) really read it (status ok); anything else is claimed as FACT and fails the sources check
  * numbers     - the break-even calculation is recomputed by the caller's calculator (business.calc), the claimed value must match
  * actions     - a result that claims an action, or a blueprint step that is not a pure proposal, is an unapproved action unless the audit holds an accepted confirmation for it
  * result      - non-empty summary/result, required fields present
The audit side (approvals, budget exhaustion of THIS task) is added by the gate. This module imports nothing but the standard library; it runs nothing. Limits: scenarios and payback are not
recomputed (the engine knows break_even, sum and margin); a result shape this module does not know yields an EMPTY report, which the engine rejects."""
from __future__ import annotations

import re
from typing import Any, Mapping

TYPED_AGENTS = ("business", "strategist")
BASES = ("FACT", "GIVEN", "INFERENCE", "ESTIMATE", "UNKNOWN")
SECTIONS = ("findings", "opportunities", "risks", "recommendations")
_META = re.compile(r"^(\d+) source\(s\) read")
STEP_OK = ("proposed", "blocked_external")
NEEDS_RESEARCH = ("market_analysis", "competitor_analysis")      # analyses of the outside world need at least one source a parent task really read
MAX_ITEMS = 60


def read_sources(context: Mapping[str, Any] | None) -> set[str]:
    """URLs a SUCCEEDED research parent read (status ok), from the orchestrator's own record of the parent task."""
    urls: set[str] = set()
    parents = context.get("parents") if isinstance(context, Mapping) else None
    for p in parents if isinstance(parents, (list, tuple)) else ():
        out = p.get("output") if isinstance(p, Mapping) else None
        if isinstance(p, Mapping) and p.get("status") == "SUCCEEDED" and isinstance(out, Mapping) and out.get("kind") == "research_result":
            urls |= {s["url"] for s in (out.get("sources") or []) if isinstance(s, Mapping) and s.get("status") == "ok" and isinstance(s.get("url"), str)}
    return urls


def _urls(value: Any) -> list[str]:
    return [u for u in value if isinstance(u, str)][:10] if isinstance(value, (list, tuple)) else []


def _calc(out_calc: Any) -> list[dict[str, Any]]:
    be = out_calc.get("break_even") if isinstance(out_calc, Mapping) else None
    if isinstance(be, Mapping) and be.get("status") == "COMPUTED" and isinstance(be.get("inputs"), Mapping):
        return [{"id": "c_break_even", "op": "break_even", "inputs": dict(be["inputs"]), "claimed": be.get("units")}]
    return []


def _report(statements: list[dict[str, Any]], calculations: list[dict[str, Any]], read: set[str], required: dict[str, Any], actions: list[dict[str, Any]],
            needs_research: bool = False) -> dict[str, Any]:
    ids = [s["id"] for s in statements] + [c["id"] for c in calculations]
    requirements, coverage = [{"id": "result"}], {"result": ids}
    if needs_research:
        requirements.append({"id": "research"})
        coverage["research"] = ["research"] if read else []                 # no source read by a parent task = the requirement is uncovered
        if read:
            statements = statements + [{"id": "research", "basis": "FACT", "sources": sorted(read)[:20]}]
    return {"requirements": requirements, "coverage": coverage, "statements": statements, "calculations": calculations,
            "sources": [{"url": u, "status": "ok"} for u in sorted(read)[:200]], "required_fields": required, "actions": actions}


def _statement(sid: str, basis: Any, cited: list[str]) -> dict[str, Any]:
    b = basis if basis in BASES else "UNKNOWN"
    if cited and b != "FACT":
        b = "FACT"                                              # it claims to be sourced: the sources are checked like any FACT
    return {"id": sid, "basis": b, "sources": cited}


def business_report(output: Any, context: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(output, Mapping) or output.get("kind") != "business_result":
        return {}
    read = read_sources(context)
    statements: list[dict[str, Any]] = []
    summary = output.get("summary")
    if isinstance(summary, str) and summary.strip():
        statements.append({"id": "summary", "basis": "INFERENCE", "sources": []})
    for sec in SECTIONS:
        items = output.get(sec)
        for i, e in enumerate(items[:MAX_ITEMS] if isinstance(items, (list, tuple)) else ()):
            if not isinstance(e, Mapping):
                continue
            cited = _urls(e.get("sources"))
            st = _statement(f"{sec[0]}{i}", e.get("basis"), cited)
            m = _META.match(str(e.get("text", "")))
            if m and st["basis"] == "FACT" and not cited and int(m.group(1)) == len(read):      # "N source(s) read": checkable against the parent record
                st["sources"] = sorted(read)[:20]
            statements.append(st)
    conf = output.get("confidence")
    required = {"summary": summary if isinstance(summary, str) and summary.strip() else None, "confidence": conf.get("level") if isinstance(conf, Mapping) else None}
    actions = [{"id": f"a{i}", "side_effect": True, "request_id": a.get("request_id") if isinstance(a, Mapping) else None} for i, a in enumerate(_list(output.get("actions")))]
    return _report(statements, _calc(output.get("calculations")), read, required, actions, needs_research=output.get("task") in NEEDS_RESEARCH)


def _list(value: Any) -> list[Any]:
    return list(value)[:MAX_ITEMS] if isinstance(value, (list, tuple)) else []


def strategist_report(output: Any, context: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(output, Mapping) or output.get("kind") != "strategist_result" or not output.get("task") or output.get("result") in (None, "", [], {}):
        return {}
    read = read_sources(context)
    task, result = output["task"], output["result"]
    statements = [{"id": "result", "basis": "INFERENCE", "sources": []}]
    for i, s in enumerate(_list(output.get("sources"))):
        if isinstance(s, Mapping) and isinstance(s.get("url"), str):
            statements.append(_statement(f"src{i}", "FACT", [s["url"]]))                    # a carried-over source is a FACT claim: it must be in the parents' record
    rows: list[Any] = []
    if task == "rank" and isinstance(result, Mapping):
        rows = _list(result.get("ranking"))
    elif task == "discover":
        rows = _list(result)
    for i, r in enumerate(rows):
        if isinstance(r, Mapping):
            statements.append({"id": f"row{i}", "basis": "ESTIMATE" if r.get("basis") == "HYPOTHESIS" else "INFERENCE", "sources": []})
    calculations = _calc({"break_even": result.get("break_even")}) if task == "financial_model" and isinstance(result, Mapping) else []
    actions: list[dict[str, Any]] = []
    if task == "blueprint" and isinstance(result, Mapping):
        steps = [s for key in ("days_30", "days_90") for s in _list(result.get(key))]
        if not steps:
            return {}
        for i, s in enumerate(steps):
            if not isinstance(s, Mapping) or s.get("status") not in STEP_OK or s.get("requires_owner_approval") is not True:
                actions.append({"id": f"step{i}", "side_effect": True, "request_id": None})      # not a pure proposal: an unapproved action
    return _report(statements, calculations, read, {"task": task}, actions)


def build_report(agent_id: str | None, output: Any, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A report for the typed agents (possibly EMPTY = malformed, rejected by the engine), None for every other agent (their explicit report path is unchanged)."""
    if agent_id == "business":
        return business_report(output, context)
    if agent_id == "strategist":
        return strategist_report(output, context)
    return None
