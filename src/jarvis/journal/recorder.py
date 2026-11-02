"""Copies goals / agent tasks (with steps) from the in-memory sources into the store. It only reads (`list`, `result`); it never starts, creates,
resumes or cancels anything. Not wired into bootstrap yet."""
from __future__ import annotations

import logging
from typing import Any

from jarvis.journal.store import JournalEntry, JournalStore

log = logging.getLogger("jarvis.journal")

# Capabilities ending like this only observe; everything else (and anything unknown) is treated as a possible side effect.
_READ_ONLY_SUFFIXES = (".read", ".screen", ".plan")


def _status(obj: Any) -> str:
    return str(getattr(obj.status, "value", obj.status)).upper()


def _join(*parts: Any) -> str:
    return " – ".join(str(p) for p in parts if p)


def side_effect(capabilities: Any, agent_id: str | None = None) -> bool:
    """Conservative marking: no capabilities and no agent (an evaluation step) -> False; otherwise True unless every capability is read-only."""
    caps = sorted(str(c) for c in (capabilities or ()))
    if not caps:
        return agent_id is not None
    return not all(c.endswith(_READ_ONLY_SUFFIXES) for c in caps)


class JournalRecorder:
    def __init__(self, store: JournalStore, *, goals: Any = None, agents: Any = None) -> None:
        self.store = store
        self._goals, self._agents = goals, agents

    def _goal_items(self) -> list[dict]:
        out = []
        for g in (self._goals.list() if self._goals is not None else ()):
            res = None
            try:
                res = self._goals.result(g.goal_id)
            except Exception:
                pass
            steps = []
            for s in getattr(res, "steps", ()):
                r = s.result
                steps.append({"step_id": s.step_id, "status": _status(s), "text": s.objective, "side_effect": side_effect(s.required_capabilities, s.assigned_agent),
                              "result": getattr(r, "summary", ""), "error": getattr(r, "error_code", None),
                              "evidence": [x for x in (f"agent={r.agent_id}" if r and r.agent_id else "", f"task={r.task_id}" if r and r.task_id else "",
                                                        f"attempts={r.attempts}" if r else "") if x],
                              "finished_at": s.updated_at if r else None})
            st = _status(g)
            out.append(dict(kind="goal", ref_id=g.goal_id, status=st, text=g.objective, result=getattr(res, "summary", ""),
                            error=None if st == "SUCCEEDED" else getattr(res, "reason_code", None), created_at=g.created_at, finished_at=g.updated_at,
                            evidence=list(getattr(res, "warnings", ())), steps=steps))
        return out

    def _task_items(self) -> list[dict]:
        out = []
        for r in (self._agents.list() if self._agents is not None else ()):
            out.append(dict(kind="agent_task", ref_id=r.task_id, status=_status(r), text=r.agent_id or "", result=r.summary or "",
                            error=r.error_code or r.error, started_at=r.started_at, finished_at=r.finished_at))
        return out

    def sync(self) -> int:
        """Store what the sources show now. Never raises: a broken source or store is logged and skipped. Returns the number of items stored."""
        items: list[dict] = []
        for label, read in (("goals", self._goal_items), ("agent tasks", self._task_items)):
            try:
                items.extend(read())
            except Exception as exc:
                log.warning("journal: source %s not readable: %s", label, type(exc).__name__)
        stored = 0
        for it in items:
            try:
                self.store.record(**it)
                stored += 1
            except Exception as exc:
                log.warning("journal: not stored: %s", type(exc).__name__)
        return stored

    def entries(self, limit: int = 20) -> list[JournalEntry]:
        self.sync()
        return self.store.list(limit)
