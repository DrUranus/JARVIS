"""NEXUS Ultimate feed (V2 preparation, Area B): a PURE, read-only adapter from REAL backend data to the page structure of the NEXUS Ultimate front end.

Inputs are only (1) UI-contract events (validated again here with `ui_contract.schema.validate_event`) and (2) the already existing read-only views (`agents`, `mission`, `trace`,
`doctor` as returned by `ReadViews`). Nothing is simulated: without data a surface is `available = False` with a reason, a missing value is `None` (never a default such as "ready"),
an invalid event is counted (`rejected_events`) and never changes the state. Approvals are DISPLAY-ONLY: no choices are listed, answering happens in the existing V1 dialog. The module
imports no permission, tool, agent or goal layer, starts nothing and has no write path. It is wired nowhere yet (a route would extend the exact view-path pin: owner decision)."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from jarvis.redaction import SecretDetector
from jarvis.ui_contract.schema import ContractError, validate_event

VERSION = 1
PAGES = ("overview", "ai-core", "live-workspace", "agent-center", "creative-studio", "coding-studio", "business-center", "trading-center", "automations", "memory-settings")
NO_ENDPOINT = {"live-workspace": "Kein Dateiendpunkt im Backend-Vertrag (nur lokale Beispieldaten im Frontend).",
               "creative-studio": "Kein Endpunkt fuer Kreativprojekte im Backend.",
               "coding-studio": "Kein lesender Endpunkt fuer Coding-Sitzungen im Backend.",
               "trading-center": "Kein Endpunkt fuer Trading im Backend (Paper-Analyse nur ueber Aufgaben, kein Broker).",
               "automations": "Kein Endpunkt fuer Zeitplaene im Backend-Vertrag."}
MAX_ITEMS_DEFAULT = 50


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def build_feed(events: Iterable[Any], *, agents_view: Any = None, mission: Any = None, trace: Any = None, doctor: Any = None, max_items: int = MAX_ITEMS_DEFAULT,
               detector: SecretDetector | None = None) -> dict[str, Any]:
    det = detector or SecretDetector.from_environment()
    cap = max(1, min(200, int(max_items)))

    def txt(v: Any, n: int = 300) -> str:
        return " ".join(det.redact("" if v is None else v).split())[:n]

    hello: Mapping[str, Any] | None = None
    core = voice = emergency = None
    tasks: dict[str, dict[str, Any]] = {}
    pending: dict[str, dict[str, Any]] = {}
    recent: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    last_seq: int | None = None
    gap = False
    rejected = 0
    for raw in events:
        try:
            e = validate_event(raw)
        except (ContractError, Exception):                                    # noqa: BLE001 - any malformed event is counted, never applied
            rejected += 1
            continue
        seq, kind, d = e["seq"], e["type"], e["data"]
        if last_seq is not None and seq != last_seq + 1:
            gap = True
        last_seq = seq if last_seq is None else max(last_seq, seq)
        if kind == "hello":
            hello = d
            emergency = {"engaged": d["emergency"], "reason": "", "report": []} if emergency is None else emergency
        elif kind == "state":
            core = {"state": d["state"], "detail": txt(d.get("detail", ""), 200)}
        elif kind == "voice_level":
            voice = {"level": d["level"], "active": d["active"]}
        elif kind == "emergency":
            emergency = {"engaged": d["engaged"], "reason": txt(d["reason"], 200), "report": [txt(r, 200) for r in d["report"]]}
            timeline.append({"seq": seq, "kind": "emergency", "text": "Not-Aus aktiv" if d["engaged"] else "Not-Aus aufgehoben"})
        elif kind == "activity":
            for it in d["items"]:
                t = tasks.setdefault(it["id"], {"id": it["id"], "kind": it["kind"]})
                t.update(title=txt(it["title"], 120), status=it["status"], note=txt(it["note"], 200), cancellable=it["cancellable"])
        elif kind == "task_update":
            t = tasks.setdefault(d["id"], {"id": d["id"], "kind": d["kind"]})
            t.update(status=d["status"], note=txt(d.get("detail", ""), 200))
        elif kind == "routing":
            tasks.setdefault(d["task_id"], {"id": d["task_id"], "kind": "agent_task"}).update(agent=txt(d["agent"], 64), routing_source=d["source"], routing_reason=txt(d["reason"], 200))
        elif kind == "result":
            tasks.setdefault(d["task_id"], {"id": d["task_id"], "kind": "agent_task"}).update(summary=txt(d["summary"], 300), artifacts=[{"name": txt(a["name"], 120), "kind": a["kind"]} for a in d["artifacts"][:20]])
        elif kind == "confirmation_request":                                  # display only: NO choices are carried over
            pending[d["request_id"]] = {"request_id": d["request_id"], "tool": d["tool"], "action": d["action"], "resource": txt(d["resource"], 200), "level": d["level"],
                                        "reason": txt(d["reason"], 200), "timeout_s": d["timeout_s"]}
        elif kind == "confirmation_closed":
            pending.pop(d["request_id"], None)
            recent.append({"request_id": d["request_id"], "outcome": d["outcome"]})
        elif kind == "error":
            timeline.append({"seq": seq, "kind": "error", "text": txt(f"{d['code']}: {d['message']}", 300)})
    task_items = list(tasks.values())
    truncated = len(task_items) > cap
    attached = hello is not None or last_seq is not None
    feed: dict[str, Any] = {
        "v": VERSION,
        "connection": {"attached": attached, "backend": txt(hello["backend"], 64) if hello else None, "contract": hello["contract"] if hello else None, "last_seq": last_seq,
                       "seq_gap": gap, "rejected_events": rejected},
        "core": core, "voice": voice, "emergency": emergency,
        "tasks": {"items": task_items[-cap:], "truncated": truncated},
        "approvals": {"pending": list(pending.values())[:cap], "recent": recent[-cap:], "display_only": True, "answer_via": "v1_dialog"},
        "events": timeline[-cap:],
    }
    av, ms, doc = _map(agents_view), _map(mission), _map(doctor)
    feed["agents"] = ({"available": True, "items": sorted(({"id": txt(a.get("id"), 64), "status": txt(a.get("status"), 32), "reason": txt(a.get("reason"), 200),
                                                             "capabilities": [txt(c, 64) for c in _list(a.get("capabilities"))[:20]]} for a in _list(av.get("agents")) if isinstance(a, Mapping)),
                                                            key=lambda a: a["id"])[:cap]} if av.get("available") is True
                      else {"available": False, "items": [], "reason": txt(av.get("reason"), 200) or "Die Agentenuebersicht liegt nicht vor."})
    feed["mission"] = {"available": ms.get("available") is True, "reason": "" if ms.get("available") is True else (txt(ms.get("reason"), 200) or "Mission Control liegt nicht vor.")}
    feed["pages"] = _pages(feed, ms, doc, trace)
    return feed


def _section(m: Mapping[str, Any], key: str, why: str) -> tuple[bool, str]:
    s = _map(m.get(key))
    return (True, "") if s.get("available") is True else (False, str(s.get("reason") or why)[:200])


def _pages(feed: Mapping[str, Any], mission: Mapping[str, Any], doctor: Mapping[str, Any], trace: Any) -> dict[str, dict[str, Any]]:
    conn, attached = feed["connection"], feed["connection"]["attached"]
    pages: dict[str, dict[str, Any]] = {}
    nodata = "Keine Daten vom Backend empfangen."
    pages["overview"] = {"available": attached, "reason": "" if attached else nodata, "source": ["events"]}
    pages["ai-core"] = {"available": feed["core"] is not None or feed["voice"] is not None or feed["emergency"] is not None, "reason": "" if attached else nodata, "source": ["events"]}
    if not pages["ai-core"]["available"] and attached:
        pages["ai-core"]["reason"] = "Das Backend hat noch keinen Kernzustand gemeldet."
    agents_ok = feed["agents"]["available"] or bool(feed["tasks"]["items"])
    pages["agent-center"] = {"available": agents_ok, "reason": "" if agents_ok else (feed["agents"].get("reason") or nodata), "source": ["agents_view", "events"]}
    for page, key, why in (("business-center", "business", "Die Business-Ergebnisse liegen nicht vor."), ("memory-settings", "memory", "Das Projektgedaechtnis liegt nicht vor.")):
        ok, reason = _section(mission, key, why) if mission.get("available") is True else (False, feed["mission"]["reason"])
        pages[page] = {"available": ok, "reason": reason, "source": ["mission"]}
    if pages["memory-settings"]["available"] is False and doctor.get("available") is True:
        pages["memory-settings"] = {"available": True, "reason": "", "source": ["doctor"]}
    for page, why in NO_ENDPOINT.items():
        pages[page] = {"available": False, "reason": why, "source": []}
    return {p: pages[p] for p in PAGES}
