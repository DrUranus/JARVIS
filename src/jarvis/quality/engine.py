"""V2.1 (Mission 7): did a task really do what was asked? Pure checks on a structured result - not wired, nothing is executed.

An agent's own "SUCCEEDED" decides nothing (in either direction). A result is ACCEPTED only if every mandatory check passes:
  requirements  every requirement is covered by evidence that exists in the result (a statement, a calculation or a declared file)
  sources       every FACT names sources that were really read (listed with status ok); assumptions must be marked as such
  calculations  claimed numbers are recomputed. Simple arithmetic is checked here; domain formulas (e.g. break-even) are recomputed with the calculator the caller passes in
                (`calculators`, e.g. business.calc - this module imports no other layer); a calculation that cannot be checked is UNKNOWN, not passed
  consistency   the same figure with different values is a conflict unless the result shows it as one
  completeness  required fields are filled
  approvals     every action with a side effect or an external effect has its own recorded, accepted confirmation (one approval covers one action)
  budgets       no budget exceeded; unknown use of a binding budget fails closed
  files         declared files really exist (the caller passes the check; without it the result is UNKNOWN, i.e. not accepted)
`reproducibility` is reported and only blocks when the caller requires it. Codes carry ids and indices only - never texts, values of statements or file contents."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

MANDATORY = ("requirements", "sources", "calculations", "consistency", "completeness", "approvals", "budgets", "files")
BASES = ("FACT", "GIVEN", "INFERENCE", "ESTIMATE", "UNKNOWN")
CONFLICT_TOLERANCE = 0.01          # relative difference above which two values of the same figure contradict each other


@dataclass(frozen=True)
class Check:
    name: str
    status: str                    # PASS | FAIL | UNKNOWN
    codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    checks: tuple[Check, ...]
    failed: tuple[str, ...]
    unknown: tuple[str, ...]
    self_reported: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "failed": list(self.failed), "unknown": list(self.unknown), "self_reported": self.self_reported,
                "checks": [{"name": c.name, "status": c.status, "codes": list(c.codes)} for c in self.checks]}


def _maps(value: Any) -> list[Mapping[str, Any]]:
    return [x for x in value if isinstance(x, Mapping)] if isinstance(value, (list, tuple)) else []


def _id(item: Mapping[str, Any], i: int) -> str:
    v = item.get("id")
    return v if isinstance(v, str) and 0 < len(v) <= 64 and v.replace("_", "").replace("-", "").replace(".", "").isalnum() else f"#{i}"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _check(name: str, fails: Iterable[str], unknowns: Iterable[str] = ()) -> Check:
    f, u = tuple(fails), tuple(unknowns)
    return Check(name, "FAIL" if f else "UNKNOWN" if u else "PASS", f + u)


def conflicts(figures: Any) -> list[dict[str, Any]]:
    """The same figure (label + unit) reported with different values, e.g. by two agents. Values within 1 % count as equal."""
    groups: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for f in _maps(figures):
        value = _num(f.get("value"))
        if value is None or not isinstance(f.get("label"), str):
            continue
        groups.setdefault((f["label"], str(f.get("unit", ""))), []).append((value, str(f.get("source", ""))[:200]))
    out = []
    for (label, unit), rows in sorted(groups.items()):
        lo, hi = min(v for v, _ in rows), max(v for v, _ in rows)
        if hi - lo > CONFLICT_TOLERANCE * max(abs(hi), abs(lo), 1e-12):
            out.append({"label": label, "unit": unit, "values": sorted({v for v, _ in rows}), "sources": sorted({s for _, s in rows})})
    return out


def _recompute(op: Any, inputs: Any, calculators: Mapping[str, Callable[[Any], Any]]) -> float | None | str:
    """The recomputed value; None if the operation has no result for these inputs; "?" if it cannot be checked here."""
    try:
        if isinstance(op, str) and op in calculators:
            return _num(calculators[op](inputs))                          # None = this operation has no result for these inputs
        if op in ("sum", "product") and isinstance(inputs, (list, tuple)) and inputs:
            nums = [_num(x) for x in inputs]
            if any(n is None for n in nums):
                return None
            return math.fsum(nums) if op == "sum" else math.prod(nums)
        if isinstance(inputs, Mapping):
            g = lambda k: _num(inputs.get(k))                              # noqa: E731
            if op == "difference" and g("a") is not None and g("b") is not None:
                return g("a") - g("b")
            if op == "ratio" and g("a") is not None and g("b"):
                return g("a") / g("b")
            if op == "margin" and g("revenue") and g("costs") is not None:
                return (g("revenue") - g("costs")) / g("revenue")
            if op in ("difference", "ratio", "margin"):
                return None
    except Exception:  # noqa: BLE001 - a calculator that fails has not confirmed the number
        return None
    return "?"


def _plain_path(path: Any) -> bool:
    if not isinstance(path, str) or not path.strip() or len(path) > 300 or any(ord(c) < 32 for c in path):
        return False
    p = path.replace("\\", "/")
    return not (p.startswith(("/", "~")) or (len(p) > 1 and p[1] == ":") or ".." in p.split("/"))


def evaluate(report: Any, *, file_exists: Callable[[str], bool] | None, audit_events: Sequence[Any] = (), require_reproduction: bool = False,
             calculators: Mapping[str, Callable[[Any], Any]] | None = None) -> Verdict:
    r: Mapping[str, Any] = report if isinstance(report, Mapping) else {}
    statements, calcs = _maps(r.get("statements")), _maps(r.get("calculations"))
    files = [f for f in r.get("files", [])] if isinstance(r.get("files"), (list, tuple)) else []
    checks: list[Check] = []

    # requirements
    reqs = _maps(r.get("requirements"))
    coverage = r.get("coverage") if isinstance(r.get("coverage"), Mapping) else {}
    known = {_id(s, i) for i, s in enumerate(statements)} | {_id(c, i) for i, c in enumerate(calcs)} | {f"file:{f}" for f in files if isinstance(f, str)}
    fails = [] if reqs else ["no_requirements"]
    for i, q in enumerate(reqs):
        ev = coverage.get(_id(q, i))
        ev = [e for e in ev if isinstance(e, str)] if isinstance(ev, (list, tuple)) else []
        if not ev:
            fails.append(f"requirement_uncovered:{_id(q, i)}")
        elif any(e not in known for e in ev):
            fails.append(f"evidence_unknown:{_id(q, i)}")
    checks.append(_check("requirements", fails))

    # sources
    read = {s.get("url") for s in _maps(r.get("sources")) if s.get("status") == "ok" and isinstance(s.get("url"), str)}
    fails = []
    for i, s in enumerate(statements):
        sid, basis, src = _id(s, i), s.get("basis"), s.get("sources")
        if basis is None:
            fails.append(f"basis_missing:{sid}")
        elif basis not in BASES:
            fails.append(f"basis_unknown:{sid}")
        elif basis == "FACT" and not (isinstance(src, (list, tuple)) and src):
            fails.append(f"fact_without_source:{sid}")
        elif basis == "FACT" and not all(isinstance(u, str) and u in read for u in src):
            fails.append(f"source_not_read:{sid}")
    checks.append(_check("sources", fails))

    # calculations
    fails, unknowns = [], []
    for i, c in enumerate(calcs):
        cid, claimed = _id(c, i), _num(c.get("claimed"))
        if claimed is None:
            fails.append(f"calculation_invalid:{cid}")
            continue
        value = _recompute(c.get("op"), c.get("inputs"), calculators or {})
        if value == "?":
            unknowns.append(f"calculation_unverifiable:{cid}")
        elif value is None or not math.isclose(claimed, value, rel_tol=1e-6, abs_tol=1e-6):
            fails.append(f"calculation_wrong:{cid}")
    if isinstance(r.get("calculations"), Mapping):
        fails.append("calculations_malformed")
    checks.append(_check("calculations", fails, unknowns))

    # consistency
    shown = set(r.get("acknowledged_conflicts")) if isinstance(r.get("acknowledged_conflicts"), (list, tuple)) and all(isinstance(x, str) for x in r["acknowledged_conflicts"]) else set()
    checks.append(_check("consistency", [f"conflict:{c['label'][:64]}" for c in conflicts(r.get("figures")) if c["label"] not in shown]))

    # completeness
    need = r.get("required_fields") if isinstance(r.get("required_fields"), Mapping) else {}
    checks.append(_check("completeness", sorted(f"missing:{str(k)[:64]}" for k, v in need.items() if v is None or (isinstance(v, str) and not v.strip()))))

    # approvals
    events = _maps(list(audit_events) if isinstance(audit_events, (list, tuple)) else [])
    rejected = {e.get("request_id") for e in events if e.get("type") == "confirmation_rejected"}
    free = {e.get("request_id") for e in events if e.get("type") == "confirmation_accepted" and isinstance(e.get("request_id"), str)} - rejected
    fails = ["actions_malformed"] if r.get("actions") is not None and not isinstance(r.get("actions"), (list, tuple)) else []
    for i, a in enumerate(_maps(r.get("actions"))):
        if not (a.get("side_effect") is True or a.get("external") is True):
            continue
        rid = a.get("request_id")
        if rid in free:
            free.discard(rid)
        elif any(e.get("request_id") == rid and e.get("type") == "confirmation_accepted" for e in events) and rid not in rejected:
            fails.append(f"approval_reused:{_id(a, i)}")
        else:
            fails.append(f"unapproved_action:{_id(a, i)}")
    checks.append(_check("approvals", fails))

    # budgets
    fails = []
    for i, b in enumerate(r.get("budgets") if isinstance(r.get("budgets"), (list, tuple)) else []):
        if not isinstance(b, Mapping):
            fails.append(f"budget_malformed:{i}")
            continue
        name, limit, used = str(b.get("name", f"#{i}"))[:64], _num(b.get("limit")), _num(b.get("used"))
        if used is None or limit is None:
            if b.get("binding") is not False:
                fails.append(f"budget_unknown:{name}")
        elif used > limit:
            fails.append(f"budget_exceeded:{name}")
    checks.append(_check("budgets", fails))

    # files
    fails, unknowns = ([], []) if isinstance(r.get("files", []), (list, tuple)) else (["files_malformed"], [])
    for i, path in enumerate(files):
        if not _plain_path(path):
            fails.append(f"file_path_invalid:{i}")
        elif file_exists is None:
            unknowns.append(f"file_unverified:{i}")
        else:
            try:
                ok = file_exists(path) is True
            except Exception:  # noqa: BLE001 - a check that cannot run is not a pass
                ok = False
            if not ok:
                fails.append(f"file_missing:{i}")
    checks.append(_check("files", fails, unknowns))

    # reproducibility
    rep = r.get("reproduction")
    if isinstance(rep, Mapping) and isinstance(rep.get("first"), str) and isinstance(rep.get("second"), str) and rep["first"]:
        checks.append(_check("reproducibility", [] if rep["first"] == rep["second"] else ["not_reproducible"]))
    else:
        checks.append(_check("reproducibility", [], ["not_reproduced"]))

    failed = tuple(c.name for c in checks if c.status == "FAIL")
    unknown = tuple(c.name for c in checks if c.status == "UNKNOWN")
    blocking = set(MANDATORY) | ({"reproducibility"} if require_reproduction else set())
    status = r.get("status")
    return Verdict(not failed and not (set(unknown) & blocking), tuple(checks), failed, unknown, status if isinstance(status, str) and len(status) <= 20 else None)
