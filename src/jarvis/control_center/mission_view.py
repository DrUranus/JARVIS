"""NEXUS Advanced Mission Control (V2.1 M6) - reines, nur lesendes Ansichtsmodell. Isolierter Prototyp: nicht in Server, Webseite oder bootstrap verdrahtet.

`build(snapshot)` formt bereits vorliegende Daten (Plan, Agenten, Kosten, Fehler, Quellen, Projektgedaechtnis, Business-Ergebnisse, Qualitaetsurteil, Freigaben)
in neun begrenzte, geschwaerzte, JSON-faehige Abschnitte. Es liest nichts selbst, fuehrt nichts aus und hat keinen Schreib- oder Antwortweg: Freigaben sind
reine Anzeige (die Antwort bleibt im bestehenden modalen Dialog). Fehlendes wird als nicht vorhanden gemeldet, Unbekanntes bleibt UNKNOWN - nichts wird
geschaetzt, insbesondere keine Kosten."""
from __future__ import annotations

import re
from typing import Any, Mapping

from jarvis.redaction import SecretDetector

PANELS = ("graph", "agents", "costs", "progress", "errors", "sources", "memory", "business", "approvals")
MAX_NODES, MAX_ITEMS, MAX_TEXT, MAX_DEPS = 50, 20, 200, 20
UNKNOWN = "UNKNOWN"
NODE_STATES = ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED", "BLOCKED")
AGENT_STATES = ("idle", "running", "failed", "stopped", "timeout")
APPROVAL_STATES = ("pending", "approved", "denied", "expired")
_ID = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
_HTTP = re.compile(r"https?://[^\s<>\"']{1,500}")
_MISSING = {"available": False, "reason": "not_provided"}
_INVALID = {"available": False, "reason": "invalid"}


class _Fmt:
    def __init__(self, detector: SecretDetector | None) -> None:
        self._d = detector or SecretDetector.from_environment()

    def text(self, value: Any) -> str:
        return "" if value is None else self._d.redact(str(value))[:MAX_TEXT]

    def ident(self, value: Any) -> str | None:
        return value if isinstance(value, str) and _ID.fullmatch(value) else None

    @staticmethod
    def number(value: Any) -> Any:
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else UNKNOWN

    @staticmethod
    def choice(value: Any, allowed: tuple[str, ...]) -> str:
        return value if isinstance(value, str) and value in allowed else UNKNOWN


def _items(raw: Any, row) -> dict[str, Any]:
    if not isinstance(raw, (list, tuple)):
        return dict(_INVALID)
    rows = [row(r) for r in raw[:MAX_ITEMS] if isinstance(r, Mapping)]
    return {"available": True, "items": rows, "total": len(raw), "truncated": len(raw) > MAX_ITEMS}


def _graph(raw: Any, f: _Fmt) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("nodes"), (list, tuple)):
        return dict(_INVALID)
    problems: set[str] = set()
    nodes: dict[str, dict[str, Any]] = {}
    for n in raw["nodes"][:MAX_NODES]:
        nid = f.ident(n.get("id")) if isinstance(n, Mapping) else None
        if nid is None:
            problems.add("invalid_id")
        elif nid in nodes:
            problems.add("duplicate_id")
        else:
            deps = [d for d in (n.get("deps") or ())][:MAX_DEPS] if isinstance(n.get("deps") or (), (list, tuple)) else []
            nodes[nid] = {"id": nid, "label": f.text(n.get("label") or nid), "status": f.choice(n.get("status"), NODE_STATES), "deps": deps, "wave": None}
    for n in nodes.values():
        known = [d for d in n["deps"] if isinstance(d, str) and d in nodes]
        if len(known) != len(n["deps"]):
            problems.add("unknown_dependency")
        n["deps"] = known
    left = set(nodes)
    wave = 0
    while left:  # Wellen: ein Knoten liegt eine Welle hinter seiner spaetesten Abhaengigkeit
        ready = sorted(i for i in left if all(nodes[d]["wave"] is not None for d in nodes[i]["deps"]))
        if not ready:
            problems.add("cycle")
            break
        for i in ready:
            nodes[i]["wave"] = max((nodes[d]["wave"] + 1 for d in nodes[i]["deps"]), default=0)
        left -= set(ready)
        wave += 1
    bad = {i for i, n in nodes.items() if n["status"] in ("FAILED", "CANCELLED")}
    blocked: set[str] = set()
    changed = True
    while changed:
        changed = False
        for i, n in nodes.items():
            if i not in bad and i not in blocked and n["status"] in ("PENDING", "BLOCKED", UNKNOWN) and any(d in bad or d in blocked for d in n["deps"]):
                blocked.add(i)
                changed = True
    counts: dict[str, int] = {}
    for n in nodes.values():
        counts[n["status"]] = counts.get(n["status"], 0) + 1
    total = len(nodes)
    return {"available": True, "nodes": list(nodes.values()), "edges": [{"from": d, "to": i} for i, n in nodes.items() for d in n["deps"]], "counts": counts,
            "progress_percent": round(100 * counts.get("SUCCEEDED", 0) / total) if total else 0, "blocked_by_failure": sorted(blocked), "problems": sorted(problems),
            "truncated": len(raw["nodes"]) > MAX_NODES}


def build(snapshot: Any, *, detector: SecretDetector | None = None) -> dict[str, Any]:
    f = _Fmt(detector)
    s = snapshot if isinstance(snapshot, Mapping) else {}
    out: dict[str, Any] = {p: dict(_MISSING) for p in PANELS}
    if "graph" in s:
        out["graph"] = _graph(s["graph"], f)
        g = out["graph"]
        if g["available"]:
            out["progress"] = {"available": True, "percent": g["progress_percent"], "done": g["counts"].get("SUCCEEDED", 0), "total": len(g["nodes"]),
                               "failed": g["counts"].get("FAILED", 0), "blocked": len(g["blocked_by_failure"]), "quality": dict(_MISSING)}
        else:
            out["progress"] = dict(_INVALID)
    if "quality" in s:
        q = s["quality"]
        if isinstance(q, Mapping):
            failed = [f.text(x) for x in (q.get("failed") or ())][:MAX_ITEMS] if isinstance(q.get("failed") or (), (list, tuple)) else [UNKNOWN]
            unknown = [f.text(x) for x in (q.get("unknown") or ())][:MAX_ITEMS] if isinstance(q.get("unknown") or (), (list, tuple)) else [UNKNOWN]
            quality = {"available": True, "accepted": q.get("accepted") is True and not failed and not unknown, "failed": failed, "unknown": unknown}
        else:
            quality = dict(_INVALID)
        if not out["progress"]["available"]:
            out["progress"] = {"available": True, "percent": UNKNOWN, "done": UNKNOWN, "total": UNKNOWN, "failed": UNKNOWN, "blocked": UNKNOWN}
        out["progress"]["quality"] = quality
    if "agents" in s:
        out["agents"] = _items(s["agents"], lambda a: {"name": f.text(a.get("name")), "state": f.choice(a.get("state"), AGENT_STATES), "task": f.text(a.get("task"))})
    if "costs" in s:
        c = s["costs"]
        out["costs"] = ({"available": True, **{k: f.number(c.get(k)) for k in ("llm_calls", "tokens", "cost", "limit_calls", "limit_tokens", "limit_cost")}}
                        if isinstance(c, Mapping) else dict(_INVALID))
    if "errors" in s:
        out["errors"] = _items(s["errors"], lambda e: {"code": f.text(e.get("code")), "where": f.text(e.get("where")), "text": f.text(e.get("text"))})
    if "sources" in s:
        out["sources"] = _items(s["sources"], lambda x: {"title": f.text(x.get("title")), "url": x["url"] if isinstance(x.get("url"), str) and _HTTP.fullmatch(x["url"])
                                                         and f.text(x["url"]) == x["url"] else None, "retrieved_at": f.text(x.get("retrieved_at")), "quality": f.text(x.get("quality"))})
    if "memory" in s:
        m = s["memory"]
        if isinstance(m, Mapping):
            conf = _items(m.get("conflicts") or [], lambda x: {"key": f.text(x.get("key")), "values": f.number(x.get("values"))})
            out["memory"] = {"available": True, "project": f.text(m.get("project")), "records": f.number(m.get("records")), "stale": f.number(m.get("stale")),
                             "conflicts": conf.get("items", [])}
        else:
            out["memory"] = dict(_INVALID)
    if "business" in s:
        out["business"] = _items(s["business"], lambda b: {"name": f.text(b.get("name")), "score": f.number(b.get("score")), "rank": f.number(b.get("rank")), "why": f.text(b.get("why"))})
    if "approvals" in s:
        a = _items(s["approvals"], lambda x: {"id": f.text(x.get("id")), "what": f.text(x.get("what")), "level": f.text(x.get("level")), "state": f.choice(x.get("state"), APPROVAL_STATES)})
        if a["available"]:
            a.update(display_only=True, pending=sum(1 for i in a["items"] if i["state"] == "pending"))
        out["approvals"] = a
    return out
