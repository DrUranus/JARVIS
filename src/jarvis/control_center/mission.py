"""V2.1 M6 NEXUS Mission Control: ONE read-only overview for the control center (`/view/mission`).

It shows what already exists and invents nothing: the task dependency graph (waves), agent status, the session budget, project progress, quality verdicts, business results and
project memory. It only CALLS the read-only source functions it was given and keeps no state: it imports no agent, permission, tool, goal, business, memory or quality layer,
has no write path and no way to approve, start, cancel or run anything. Each optional section says WHY it is empty (source missing, not integrated yet, not readable) instead of
guessing. Every text is redacted again (`SecretDetector`) and clipped; every list is bounded; internals of a failing source are never shown."""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from jarvis.redaction import SecretDetector

log = logging.getLogger("jarvis.control_center")

MAX_NODES = 100
MAX_ITEMS = 20
MAX_AGENTS = 50
TERMINAL = ("SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED")
_OPEN = ("PENDING", "RUNNING")
_BUDGET_KEYS = ("calls", "max_calls", "elapsed", "max_seconds", "exhausted", "started")
REASONS = {"graph": "Die Agentenschicht ist nicht aktiv (agents.enabled = false).",
           "budget": "Kein Sitzungsbudget aktiv (security.session_budget).",
           "business": "Die Quelle der Business-Ergebnisse ist nicht angebunden.",
           "quality": "Die Qualitaetspruefung (V2.1 M7) ist noch nicht angebunden.",
           "memory": "Das Projektgedaechtnis (V2.1 M3) ist noch nicht angebunden."}


class MissionView:
    def __init__(self, agents_source: Callable[[int], Mapping[str, Any]] | None = None, *, budget_source: Callable[[], Mapping[str, Any]] | None = None,
                 business_source: Callable[[int], list[Mapping[str, Any]]] | None = None, quality_source: Callable[[int], list[Mapping[str, Any]]] | None = None,
                 memory_source: Callable[[], list[Mapping[str, Any]]] | None = None, detector: SecretDetector | None = None) -> None:
        self._agents_source, self._budget_source, self._business_source = agents_source, budget_source, business_source
        self._quality_source, self._memory_source = quality_source, memory_source
        self._detector = detector or SecretDetector.from_environment()

    # ---- helpers ------------------------------------------------------------------------------------------------------------------------
    def _t(self, value: Any, limit: int = 200) -> str:
        return " ".join(self._detector.redact("" if value is None else value).split())[:limit]

    @staticmethod
    def _list(value: Any) -> list[Any]:
        return list(value) if isinstance(value, (list, tuple)) else []

    @staticmethod
    def _int(value: Any, high: int = 10**9) -> int:
        return max(0, min(high, value)) if isinstance(value, int) and not isinstance(value, bool) else 0

    @staticmethod
    def _off(reason: str, **extra: Any) -> dict[str, Any]:
        return {"available": False, "reason": reason, **extra}

    def _read(self, name: str, call: Callable[[], Any]) -> Any:
        """The source's data, or None if it fails: the reason is generic, the internals stay in the log."""
        try:
            return call()
        except Exception:                                                               # noqa: BLE001 - no internals to the outside
            log.warning("mission %s source failed", name, exc_info=True)
            return None

    # ---- the view -----------------------------------------------------------------------------------------------------------------------
    def snapshot(self, limit: int) -> dict[str, Any]:
        limit = max(1, min(MAX_NODES * 2, int(limit)))
        raw = None if self._agents_source is None else self._read("agents", lambda: self._agents_source(limit))      # type: ignore[misc]
        if not isinstance(raw, Mapping):
            reason = REASONS["graph"] if self._agents_source is None else "Die Agentenuebersicht ist nicht lesbar."
            out = {"available": False, "reason": reason, "limit": limit, "graph": self._graph([], limit), "agents": self._off(reason, items=[]),
                   "progress": self._progress([])}
        else:
            tasks = [t for t in self._list(raw.get("tasks")) if isinstance(t, Mapping) and isinstance(t.get("task_id"), str)]
            out = {"available": True, "reason": "", "limit": limit, "graph": self._graph(tasks, limit), "agents": self._agents(raw.get("agents"), tasks),
                   "progress": self._progress(tasks[-limit:])}
        out.update(budget=self._budget(), quality=self._rows("quality", self._quality_source, self._quality_row),
                   business=self._rows("business", self._business_source, self._business_row), memory=self._memory())
        return out

    # ---- graph: waves = longest dependency chain, bounded, cycle-safe --------------------------------------------------------------------------
    def _graph(self, tasks: list[Mapping[str, Any]], limit: int) -> dict[str, Any]:
        window = tasks[-min(limit, MAX_NODES):]
        ids = {t["task_id"] for t in window}
        deps = {t["task_id"]: [self._t(d, 64) for d in self._list(t.get("dependencies"))[:20] if isinstance(d, str)] for t in window}
        external = sorted({d for ds in deps.values() for d in ds if d not in ids})
        wave: dict[str, int | None] = {}
        state: dict[str, int] = {}                                                       # 1 = being visited, 2 = done

        def depth(start: str) -> None:
            stack = [start]
            while stack:                                                                 # iterative: a deep chain cannot overflow the stack
                node = stack[-1]
                if state.get(node) == 2:
                    stack.pop()
                    continue
                state[node] = 1
                pending = [d for d in deps[node] if d in ids and state.get(d) != 2]
                loop = [d for d in pending if state.get(d) == 1]
                if loop:                                                                 # a back edge: part of a cycle
                    wave[node], state[node] = None, 2
                    stack.pop()
                    continue
                if pending:
                    stack.extend(pending)
                    continue
                inner = [wave[d] for d in deps[node] if d in ids]
                wave[node] = None if any(w is None for w in inner) else (max(inner) + 1 if inner else 0)      # type: ignore[type-var]
                state[node] = 2
                stack.pop()
        for t in window:
            depth(t["task_id"])
        nodes = [{"id": self._t(t["task_id"], 64), "agent": self._t(t.get("agent_id"), 64), "status": self._t(t.get("status"), 32).upper(), "wave": wave.get(t["task_id"]),
                  "deps": deps[t["task_id"]], "objective": self._t(t.get("objective"), 120)} for t in window]
        top = max((w for w in wave.values() if w is not None), default=-1)
        waves = [[n["id"] for n in nodes if n["wave"] == i] for i in range(top + 1)]
        return {"available": True, "truncated": len(tasks) >= min(limit, MAX_NODES),            # a full window: older tasks may exist that are not shown
                "nodes": nodes, "waves": waves, "external_deps": external[:MAX_ITEMS],
                "edges": [[d, n["id"]] for n in nodes for d in n["deps"] if d in ids], "cycle": [n["id"] for n in nodes if n["wave"] is None]}

    # ---- agents and progress ---------------------------------------------------------------------------------------------------------------
    def _agents(self, agents: Any, tasks: list[Mapping[str, Any]]) -> dict[str, Any]:
        def count(agent: str, status: str) -> int:
            return sum(1 for t in tasks if t.get("agent_id") == agent and str(t.get("status", "")).upper() == status)
        items = [{"id": self._t(a.get("id"), 64), "status": self._t(a.get("status"), 32), "reason": self._t(a.get("reason"), 200),
                  "capabilities": [self._t(c, 64) for c in self._list(a.get("capabilities"))[:MAX_ITEMS]], "pending": count(a.get("id"), "PENDING"), "running": count(a.get("id"), "RUNNING")}
                 for a in self._list(agents)[:MAX_AGENTS] if isinstance(a, Mapping)]
        return {"available": True, "items": sorted(items, key=lambda a: a["id"])}

    def _progress(self, tasks: list[Mapping[str, Any]]) -> dict[str, Any]:
        by: dict[str, int] = {}
        for t in tasks:
            s = self._t(t.get("status"), 32).upper() or "UNKNOWN"
            by[s] = by.get(s, 0) + 1
        total, finished = sum(by.values()), sum(n for s, n in by.items() if s in TERMINAL)
        return {"available": True, "total": total, "by_status": by, "finished": finished, "percent": round(100 * finished / total) if total else 0}

    # ---- optional sections ---------------------------------------------------------------------------------------------------------------
    def _budget(self) -> dict[str, Any]:
        if self._budget_source is None:
            return self._off(REASONS["budget"], session=None)
        usage = self._read("budget", self._budget_source)
        if not isinstance(usage, Mapping):
            return self._off("Das Budget ist nicht lesbar.", session=None)
        session = {k: usage.get(k) for k in _BUDGET_KEYS}
        for k in ("calls", "max_calls"):
            session[k] = self._int(session[k])
        for k in ("elapsed", "max_seconds"):
            v = session[k]
            session[k] = round(float(v), 1) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else 0.0
        session["exhausted"] = self._t(session["exhausted"], 200) if session["exhausted"] else None
        session["started"] = session["started"] is True
        return {"available": True, "reason": "", "session": session}

    def _rows(self, name: str, source: Callable[[int], list[Mapping[str, Any]]] | None, build: Callable[[Mapping[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        if source is None:
            return self._off(REASONS[name], items=[])
        rows = self._read(name, lambda: source(MAX_ITEMS))
        if not isinstance(rows, (list, tuple)):
            return self._off("Die Quelle ist nicht lesbar.", items=[])
        items = [build(r) for r in rows[:MAX_ITEMS] if isinstance(r, Mapping)]
        out: dict[str, Any] = {"available": True, "reason": "", "items": items}
        if name == "quality":
            out.update(accepted=sum(1 for i in items if i["accepted"]), rejected=sum(1 for i in items if not i["accepted"]))
        return out

    def _business_row(self, r: Mapping[str, Any]) -> dict[str, Any]:
        return {"task_id": self._t(r.get("task_id"), 64), "agent_id": self._t(r.get("agent_id"), 64), "kind": self._t(r.get("kind"), 64), "summary": self._t(r.get("summary"), 300),
                "confidence": self._t(r.get("confidence"), 16) or "UNKNOWN", "unknowns": self._int(r.get("unknowns"), 1000), "sources": self._int(r.get("sources"), 1000)}

    def _quality_row(self, r: Mapping[str, Any]) -> dict[str, Any]:
        return {"task_id": self._t(r.get("task_id"), 64), "accepted": r.get("accepted") is True, "self_reported": self._t(r.get("self_reported"), 32),
                "failed": [self._t(c, 40) for c in self._list(r.get("failed"))[:12]], "unknown": [self._t(c, 40) for c in self._list(r.get("unknown"))[:12]]}

    def _memory(self) -> dict[str, Any]:
        if self._memory_source is None:
            return self._off(REASONS["memory"], projects=[])
        rows = self._read("memory", self._memory_source)
        if not isinstance(rows, (list, tuple)):
            return self._off("Das Projektgedaechtnis ist nicht lesbar.", projects=[])
        projects = []
        for r in rows[:MAX_ITEMS]:
            if isinstance(r, Mapping):
                counts = r.get("counts") if isinstance(r.get("counts"), Mapping) else {}
                projects.append({"project": self._t(r.get("project"), 64), "counts": {self._t(k, 32): self._int(v, 100000) for k, v in list(counts.items())[:8]},
                                 "conflicts": self._int(r.get("conflicts"), 100000), "stale": self._int(r.get("stale"), 100000), "suggestions": self._int(r.get("suggestions"), 100000)})
        return {"available": True, "reason": "", "projects": projects}
