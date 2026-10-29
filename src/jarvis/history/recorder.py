"""Copies FINISHED items from the in-memory sources into the store. It only reads (`list`, `result`); it never starts, creates, resumes or cancels anything."""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from jarvis.history.store import HistoryEntry, HistoryStore

log = logging.getLogger("jarvis.history")

FINISHED = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "TIMEOUT", "COMPLETED"})


def _status(obj: Any) -> str:
    return str(getattr(obj.status, "value", obj.status)).upper()


def _join(*parts: Any) -> str:
    return " – ".join(str(p) for p in parts if p)


class HistoryRecorder:
    def __init__(self, store: HistoryStore, *, goals: Any = None, repairs: Any = None, agents: Any = None, tasks: Any = None) -> None:
        self.store = store
        self._sources: tuple[tuple[str, Callable[[], Iterable[tuple]]], ...] = (
            ("Ziele", lambda: self._goals(goals)), ("Reparaturläufe", lambda: self._repairs(repairs)),
            ("Agenten-Tasks", lambda: self._agent_tasks(agents)), ("Pläne", lambda: self._tasks(tasks)))

    # -- sources ----------------------------------------------------------------------------------------
    @staticmethod
    def _goals(engine: Any) -> list[tuple]:
        out = []
        for g in (engine.list() if engine is not None else ()):
            st = _status(g)
            if st not in FINISHED:
                continue
            res = None
            try:
                res = engine.result(g.goal_id)
            except Exception:
                pass
            out.append(("goal", g.goal_id, st, _join(g.objective, getattr(res, "summary", "")),
                        None if st == "SUCCEEDED" else getattr(res, "reason_code", None), g.created_at, None, g.updated_at))
        return out

    @staticmethod
    def _repairs(engine: Any) -> list[tuple]:
        out = []
        for rv in (engine.list() if engine is not None else ()):
            st = _status(rv)
            if st not in FINISHED:
                continue
            res = None
            try:
                res = engine.result(rv.run_id)
            except Exception:
                pass
            out.append(("repair", rv.run_id, st, _join(rv.objective, rv.final_summary or rv.failure_summary),
                        None if st == "SUCCEEDED" else getattr(res, "reason_code", None), rv.created_at, rv.started_at, rv.finished_at))
        return out

    @staticmethod
    def _agent_tasks(orchestrator: Any) -> list[tuple]:
        out = []
        for r in (orchestrator.list() if orchestrator is not None else ()):
            st = _status(r)
            if st in FINISHED:
                out.append(("agent_task", r.task_id, st, _join(r.agent_id, r.summary), r.error_code or r.error, None, r.started_at, r.finished_at))
        return out

    @staticmethod
    def _tasks(manager: Any) -> list[tuple]:
        out = []
        for t in (manager.list() if manager is not None else ()):
            st = _status(t)
            if st in FINISHED:
                out.append(("task", t.id, st, _join(t.description, t.result), t.error, t.created_at, None, t.updated_at))
        return out

    # -- API --------------------------------------------------------------------------------------------
    def sync(self) -> int:
        """Store every finished item the sources show now. Never raises: a broken source or store is logged and skipped. Returns the number of items seen."""
        items: list[tuple] = []
        for label, read in self._sources:
            try:
                items.extend(read())
            except Exception as exc:
                log.warning("history: source %s not readable: %s", label, type(exc).__name__)
        if not items:
            return 0
        try:
            self.store.add_many(items)
        except Exception as exc:
            log.warning("history: not stored: %s", type(exc).__name__)
            return 0
        return len(items)

    def entries(self, limit: int = 20) -> list[HistoryEntry]:
        """The stored history, newest first (after taking over what finished meanwhile)."""
        self.sync()
        return self.store.list(limit)
