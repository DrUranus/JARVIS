"""Resume of interrupted tasks - ONLY on an explicit command, never automatically.

* `ResumeManager.interrupted()` reads the journal and lists goals / agent tasks that were last recorded as unfinished and are not alive in this process
  (so they were cut off by a crash or a restart). Reading only: nothing is created, started or asked.
* `ResumeManager.resume(ref_id)` is the single entry point that acts. It runs in the caller's thread (no thread, timer or scheduler in this module) and
  1. is blocked while the emergency stop is engaged (checked before asking, after asking and before starting; a failing probe counts as engaged),
  2. asks for a NEW confirmation for every still-open step marked `side_effect` (no callback = denied; a single "no" starts nothing),
  3. creates ONE new goal through the GoalEngine interface (`create` + `run`) - the engine plans, limits and runs it through the orchestrator exactly as for
     any other goal, so every tool action still passes `ToolRegistry.execute` -> `PermissionEngine`,
  4. keeps steps the journal reports as SUCCEEDED out of the new plan (`ResumeAwarePlanner`).
* Only goals are resumable: a journaled agent task carries no input, so it is listed but refused.
* The result is contract data: `ResumeResult.to_activity()` is an activity item with kind "resume" (`jarvis.ui_contract.schema.ACTIVITY_ITEM`).
Not wired into bootstrap yet; the caller (an explicit user command) decides when `resume` is called.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from jarvis.journal.store import JournalEntry, JournalStore

log = logging.getLogger("jarvis.journal")

OPEN_STATUSES = frozenset({"PENDING", "PLANNING", "RUNNING", "WAITING"})      # not finished when the process died
DONE = "SUCCEEDED"
RESUMED = "RESUMED"


def _norm(text: str) -> str:
    return " ".join(str(text).split())


class ResumeAwarePlanner:
    """Wraps the planner the GoalEngine is built with. For a goal registered with `skip()` it removes the plan steps that the journal reports as done
    (each done text is used at most once; evaluation steps are never removed) and drops dependencies on them. Other goals pass through unchanged."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self._skip: dict[str, tuple[list[str], int | None]] = {}

    @property
    def supports_replanning(self) -> bool:
        return bool(getattr(self.inner, "supports_replanning", False))

    def skip(self, goal_id: str, done_texts: Sequence[str], truncated_at: int | None = None) -> None:
        self._skip[goal_id] = ([_norm(t) for t in done_texts], truncated_at)

    def _filter(self, goal: Any, steps: Sequence[Any]) -> list[Any]:
        entry = self._skip.get(goal.goal_id)
        if entry is None:
            return list(steps)
        pool, cut = list(entry[0]), entry[1]
        removed: set[str] = set()
        for s in steps:
            if s.assigned_agent is None:
                continue
            text = _norm(s.objective)
            for d in pool:
                if text == d or (cut is not None and len(d) >= cut and text.startswith(d)):
                    pool.remove(d)
                    removed.add(s.step_id)
                    break
        return [dataclasses.replace(s, dependencies=tuple(d for d in s.dependencies if d not in removed)) for s in steps if s.step_id not in removed]

    def plan(self, goal: Any, ctx: Any, max_steps: int) -> list[Any]:
        return self._filter(goal, self.inner.plan(goal, ctx, max_steps))

    def replan(self, goal: Any, ctx: Any, max_steps: int, feedback: Any) -> list[Any]:
        return self._filter(goal, self.inner.replan(goal, ctx, max_steps, feedback))


@dataclass(frozen=True)
class InterruptedTask:
    kind: str
    ref_id: str
    text: str
    status: str
    done_steps: int
    open_steps: int
    needs_confirmation: int                 # open steps that may change something outside JARVIS
    resumable: bool


@dataclass(frozen=True)
class ResumeResult:
    ref_id: str
    status: str                             # SUCCEEDED | FAILED | ... (the new goal's status) | REFUSED | BLOCKED | DECLINED | NOTHING_TO_DO
    new_goal_id: str | None = None
    skipped_steps: int = 0
    confirmed_steps: int = 0
    reason: str = ""

    def to_activity(self) -> dict[str, Any]:
        """Contract data (`ACTIVITY_ITEM`): an activity item of kind "resume". Not cancellable: the call is synchronous."""
        note = self.reason or (f"goal {self.new_goal_id}" if self.new_goal_id else "")
        return {"kind": "resume", "id": f"resume-{self.ref_id}"[:64], "title": f"Wiederaufnahme {self.ref_id}"[:200], "status": self.status[:32],
                "note": f"{note}; ohne erneut: {self.skipped_steps}; bestaetigt: {self.confirmed_steps}"[:200], "cancellable": False}


class ResumeManager:
    def __init__(self, store: JournalStore, *, goals: Any, planner: ResumeAwarePlanner, emergency: Callable[[], bool],
                 confirm: Callable[[str], bool] | None = None) -> None:
        """`goals`: the GoalEngine (create/run/get/steps/list). `planner`: the ResumeAwarePlanner the engine was built with. `emergency`: returns True while
        the emergency stop is engaged. `confirm(text) -> bool`: asks the user (through the PermissionEngine's confirmation channel) - None means always no."""
        self._store, self._goals, self._planner, self._emergency, self._confirm = store, goals, planner, emergency, confirm

    # ---- reading ---------------------------------------------------------------------------------------------------------------------------
    def _alive(self, entry: JournalEntry) -> bool:
        if entry.kind != "goal":
            return False
        try:
            self._goals.get(entry.ref_id)
            return True
        except Exception:                                   # unknown to the engine -> not alive here
            return False

    def _is_interrupted(self, entry: JournalEntry) -> bool:
        return entry.status in OPEN_STATUSES and not self._alive(entry)

    def interrupted(self, limit: int = 20) -> list[InterruptedTask]:
        out = []
        for e in self._store.list(self._store.max_entries):
            if not self._is_interrupted(e):
                continue
            done = sum(1 for s in e.steps if s.status == DONE)
            open_ = [s for s in e.steps if s.status != DONE]
            out.append(InterruptedTask(e.kind, e.ref_id, e.text, e.status, done, len(open_), sum(1 for s in open_ if s.side_effect), e.kind == "goal"))
            if len(out) >= limit:
                break
        return out

    # ---- acting (explicit command only) ----------------------------------------------------------------------------------------------------
    def _stopped(self) -> bool:
        try:
            return bool(self._emergency())
        except Exception:                                   # unknown state -> treat as engaged
            return True

    def resume(self, ref_id: str, kind: str = "goal") -> ResumeResult:
        if self._stopped():
            return ResumeResult(ref_id, "BLOCKED", reason="emergency_stop")
        entry = self._store.get(kind, ref_id) if kind in ("goal", "agent_task") else None
        if entry is None:
            return ResumeResult(ref_id, "REFUSED", reason="unknown_task")
        if not self._is_interrupted(entry):
            return ResumeResult(ref_id, "REFUSED", reason="not_interrupted")
        if entry.kind != "goal":
            return ResumeResult(ref_id, "REFUSED", reason="not_resumable")
        done = [s for s in entry.steps if s.status == DONE]
        open_ = [s for s in entry.steps if s.status != DONE]
        if entry.steps and not open_:
            return ResumeResult(ref_id, "NOTHING_TO_DO", skipped_steps=len(done), reason="all_steps_done")
        confirmed = 0
        for s in open_:
            if not s.side_effect:
                continue
            try:
                ok = bool(self._confirm(f"Wiederaufnahme von {ref_id}: Schritt {s.step_id} mit moeglicher Aenderung ausserhalb von JARVIS erneut ausfuehren: {s.text}")) \
                    if self._confirm else False
            except Exception:
                ok = False
            if not ok:
                return ResumeResult(ref_id, "DECLINED", skipped_steps=len(done), confirmed_steps=confirmed, reason="confirmation_denied")
            confirmed += 1
        if self._stopped():                                 # the stop may have been triggered while a question was open
            return ResumeResult(ref_id, "BLOCKED", skipped_steps=len(done), confirmed_steps=confirmed, reason="emergency_stop")
        goal = self._goals.create(entry.text or ref_id, metadata={"resumed_from": ref_id})
        self._planner.skip(goal.goal_id, [s.text for s in done], self._store.max_text_length)
        self._store.record("goal", ref_id, RESUMED, entry.text, result=entry.result, evidence=entry.evidence, error=entry.error, created_at=entry.created_at,
                           started_at=entry.started_at, finished_at=entry.finished_at,
                           steps=[{"step_id": s.step_id, "status": s.status, "text": s.text, "side_effect": s.side_effect, "result": s.result,
                                   "evidence": s.evidence, "error": s.error, "started_at": s.started_at, "finished_at": s.finished_at} for s in entry.steps])
        res = self._goals.run(goal.goal_id)
        log.info("resume %s -> goal %s: %s", ref_id, goal.goal_id, res.goal.status.value)
        return ResumeResult(ref_id, res.goal.status.value, goal.goal_id, len(done), confirmed, res.reason_code or "")
