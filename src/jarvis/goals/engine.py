"""GoalEngine: owns goals and their progress. It does NOT choose agents (GoalPlanner + AgentPlanner do), does NOT run agents
(AgentOrchestrator does), does NOT use tools and does NOT decide permissions (the PermissionEngine does). It only
  plans -> validates -> starts ready steps through the orchestrator -> waits -> evaluates -> repeats, within hard limits.

One goal is driven by ONE driver (the caller's thread for run(), one daemon thread for start()); it blocks on the orchestrator's own
Condition (wait_any) - no polling, no scheduler of its own, no own parallelisation: independent ready steps are submitted together and
the orchestrator decides how many run at once.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence

from jarvis.agents.errors import AgentError
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentResult
from jarvis.agents.state import TaskStatus
from jarvis.goals import policy as P
from jarvis.goals.context import GoalContext, check_user_context
from jarvis.goals.errors import GoalError, GoalStateError, InvalidGoalError, InvalidPlanError, PlanningError, UnknownGoalError
from jarvis.goals.evaluator import TERMINAL_DECISIONS, Decision, GoalEvaluator, Verdict, is_cleanup
from jarvis.goals.models import Goal, GoalResult, GoalStep, GoalStepResult, utcnow
from jarvis.goals.planner import Planner
from jarvis.goals.state import GOAL_TERMINAL, STEP_TERMINAL, GoalStatus, StepStatus
from jarvis.goals.validation import validate_plan
from jarvis.redaction import SecretDetector

log = logging.getLogger("jarvis.goals")


class Clock(Protocol):
    def monotonic(self) -> float: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class GoalCancelReport:
    goal_id: str
    accepted: bool
    status: GoalStatus
    message: str


@dataclass
class _Rec:
    goal: Goal
    user_ctx: dict[str, Any]
    seq: int
    steps: dict[str, GoalStep] = field(default_factory=dict)
    inflight: dict[str, tuple[str, float]] = field(default_factory=dict)      # step_id -> (task_id, monotonic start of the attempt)
    logs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)       # step_id -> one entry per attempt
    warnings: list[str] = field(default_factory=list)
    summary: str = ""
    reason_code: str | None = None
    cancel_requested: bool = False
    started: bool = False
    thread: threading.Thread | None = None
    began: float = 0.0
    ended: float | None = None
    deadline: float | None = None
    max_steps: int = 0
    cancelled_tasks: bool = False

    @property
    def status(self) -> GoalStatus:
        return self.goal.status


class GoalEngine:
    def __init__(self, orchestrator: Any, planner: Planner, *, evaluator: GoalEvaluator | None = None, max_steps: int = 20,
                 max_attempts: int = 2, goal_timeout: float = 1800.0, step_timeout: float = 300.0, max_active: int = 3,
                 max_history: int = 100, cancel_wait: float | None = None, cleanup_timeout: float = 30.0, clock: Clock | None = None,
                 detector: SecretDetector | None = None) -> None:
        if not 1 <= max_steps <= P.MAX_STEPS_HARD or not 1 <= max_attempts <= P.MAX_ATTEMPTS_HARD or not 0 < goal_timeout <= P.MAX_TIMEOUT \
                or not 0 < step_timeout <= P.MAX_STEP_TIMEOUT or max_active < 1 or max_history < 1:
            raise InvalidGoalError("the goal engine limits must be positive and within the hard limits")
        self._orch, self._planner = orchestrator, planner
        self._eval = evaluator or GoalEvaluator()
        self.max_steps, self.max_attempts, self.goal_timeout, self.step_timeout = max_steps, max_attempts, goal_timeout, step_timeout
        self.max_active, self.max_history, self.cleanup_timeout = max_active, max_history, cleanup_timeout
        self._cancel_wait = cancel_wait if cancel_wait is not None else float(getattr(orchestrator, "cancel_grace", 5.0)) + 1.0
        self._clock: Clock = clock or SystemClock()
        self._detector = detector or SecretDetector.from_environment()
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._recs: dict[str, _Rec] = {}
        self._seq = 0

    # ---- public: goals ----------------------------------------------------------------------------------------------------------------------
    def create(self, objective: str, *, priority: int = 5, timeout: float | None = None, max_steps: int | None = None,
               context: dict[str, Any] | None = None, metadata: dict[str, str] | None = None, goal_id: str | None = None) -> Goal:
        """Register a goal (PENDING). Nothing is planned or executed yet. `context` is the information the user explicitly releases."""
        user = check_user_context(context)
        kw: dict[str, Any] = {"priority": priority, "timeout": timeout, "max_steps": max_steps, "metadata": metadata or {}}
        if goal_id is not None:
            kw["goal_id"] = goal_id
        goal = Goal(objective, **kw)
        with self._lock:
            if goal.goal_id in self._recs:
                raise GoalError(f"goal id {goal.goal_id!r} is already in use")
            self._trim()
            if len(self._recs) >= self.max_history * 2:
                raise GoalError("too many goals are registered; finish or cancel some first")
            self._seq += 1
            self._recs[goal.goal_id] = _Rec(goal, user, self._seq)
        log.info("goal %s created", goal.goal_id)
        return goal

    def run(self, goal_id: str) -> GoalResult:
        """Drive the goal in the calling thread until it is finished. A goal never runs twice."""
        rec = self._claim(goal_id)
        if rec is not None:
            self._drive(rec)
        return self.result(goal_id)

    def start(self, goal_id: str) -> Goal:
        """Drive the goal in one background (daemon) thread; use wait() / get() / cancel()."""
        rec = self._claim(goal_id)
        if rec is not None:
            t = threading.Thread(target=self._drive, args=(rec,), name=f"jarvis-goal-{goal_id[:20]}", daemon=True)
            with self._lock:
                rec.thread = t
            t.start()
        return self.get(goal_id)

    def wait(self, goal_id: str, timeout: float | None = None) -> GoalResult:
        with self._cond:
            rec = self._rec(goal_id)
            self._cond.wait_for(lambda: rec.status in GOAL_TERMINAL, timeout=timeout)
        return self.result(goal_id)

    def cancel(self, goal_id: str) -> GoalCancelReport:
        """PENDING: cancelled at once. Running: cancellation is REQUESTED from the agents (their own cancel mechanism); the goal turns
        CANCELLED when the driver has dealt with them. Finished goals are left as they are. Never says an agent stopped that did not."""
        with self._lock:
            rec = self._rec(goal_id)
            if rec.status in GOAL_TERMINAL:
                return GoalCancelReport(goal_id, False, rec.status, f"the goal is already {rec.status.value}")
            if not rec.started:
                rec.goal = rec.goal.with_status(GoalStatus.CANCELLED)
                rec.summary, rec.reason_code, rec.ended = "cancelled before it started", "cancelled", self._clock.monotonic()
                self._cond.notify_all()
                log.info("goal %s cancelled before start", goal_id)
                return GoalCancelReport(goal_id, True, rec.status, "cancelled before it started")
            rec.cancel_requested = True
            tasks = [tid for tid, _ in rec.inflight.values()]
        for tid in tasks:
            try:
                self._orch.cancel(tid)
            except AgentError:
                pass
        self._orch.notify_waiters()
        with self._cond:
            self._cond.notify_all()
        return GoalCancelReport(goal_id, True, rec.status, "cancellation requested; the goal ends CANCELLED once its agents have been dealt with")

    # ---- public: views -------------------------------------------------------------------------------------------------------------------------
    def get(self, goal_id: str) -> Goal:
        with self._lock:
            return self._rec(goal_id).goal

    def steps(self, goal_id: str) -> tuple[GoalStep, ...]:
        with self._lock:
            return tuple(self._rec(goal_id).steps.values())

    def result(self, goal_id: str) -> GoalResult:
        with self._lock:
            rec = self._rec(goal_id)
            end = rec.ended if rec.ended is not None else self._clock.monotonic()
            return GoalResult(rec.goal, tuple(rec.steps.values()), rec.summary, rec.reason_code, tuple(rec.warnings),
                              max(0.0, end - rec.began) if rec.started else 0.0)

    def list(self, status: GoalStatus | None = None, limit: int | None = None) -> list[Goal]:
        with self._lock:
            recs = sorted(self._recs.values(), key=lambda r: r.seq, reverse=True)
            out = [r.goal for r in recs if status is None or r.status is status]
            return out[:limit] if limit else out

    def describe(self) -> dict[str, Any]:
        with self._lock:
            return {"goals": len(self._recs), "active": self._active(), "max_active": self.max_active, "max_steps": self.max_steps,
                    "max_attempts_per_step": self.max_attempts, "goal_timeout": self.goal_timeout, "step_timeout": self.step_timeout}

    def shutdown(self, wait: float = 2.0) -> None:
        with self._lock:
            active = [r for r in self._recs.values() if r.started and r.status not in GOAL_TERMINAL]
            for r in active:
                r.cancel_requested = True
        for r in active:
            self.cancel(r.goal.goal_id)
        deadline = time.monotonic() + max(0.0, wait)
        for r in active:
            if r.thread is not None:
                r.thread.join(max(0.0, deadline - time.monotonic()))

    # ---- internals: bookkeeping -------------------------------------------------------------------------------------------------------------
    def _rec(self, goal_id: str) -> _Rec:
        try:
            return self._recs[goal_id]
        except (KeyError, TypeError):
            raise UnknownGoalError(f"unknown goal {str(goal_id)[:40]!r}") from None

    def _active(self) -> int:
        return sum(1 for r in self._recs.values() if r.started and r.status not in GOAL_TERMINAL)

    def _trim(self) -> None:
        done = sorted((r for r in self._recs.values() if r.status in GOAL_TERMINAL and (r.thread is None or not r.thread.is_alive())),
                      key=lambda r: r.seq)
        for r in done[: max(0, len(self._recs) - self.max_history)]:
            del self._recs[r.goal.goal_id]

    def _claim(self, goal_id: str) -> _Rec | None:
        with self._lock:
            rec = self._rec(goal_id)
            if rec.status in GOAL_TERMINAL:
                return None
            if rec.started:
                raise GoalStateError("this goal is already running")
            if self._active() >= self.max_active:
                raise GoalError(f"at most {self.max_active} goals can run at the same time")
            rec.started = True
            rec.began = self._clock.monotonic()
            rec.max_steps = min(rec.goal.max_steps or self.max_steps, self.max_steps)
            rec.deadline = rec.began + min(rec.goal.timeout or self.goal_timeout, self.goal_timeout)
            return rec

    def _set_goal(self, rec: _Rec, status: GoalStatus) -> None:
        with self._lock:
            if rec.status is not status and rec.status not in GOAL_TERMINAL:
                rec.goal = rec.goal.with_status(status)

    def _remaining(self, rec: _Rec) -> float | None:
        return None if rec.deadline is None else rec.deadline - self._clock.monotonic()

    # ---- internals: the driver ---------------------------------------------------------------------------------------------------------------
    def _drive(self, rec: _Rec) -> None:
        try:
            if self._plan(rec):
                self._loop(rec)
        except Exception as exc:  # noqa: BLE001 - a bug here must end the goal honestly, never leave it hanging
            log.warning("goal %s: internal error (%s)", rec.goal.goal_id, type(exc).__name__)
            self._abandon(rec)
            self._finalize(rec, GoalStatus.FAILED, f"internal error ({type(exc).__name__})", "internal_error")

    def _abandon(self, rec: _Rec) -> None:
        try:
            self._stop_inflight(rec, StepStatus.CANCELLED, "the goal engine stopped")
        except Exception:  # noqa: BLE001
            pass

    def _plan(self, rec: _Rec) -> bool:
        with self._lock:
            if rec.cancel_requested:
                self._finalize(rec, GoalStatus.CANCELLED, "cancelled before planning", "cancelled")
                return False
            rec.goal = rec.goal.with_status(GoalStatus.PLANNING)
            ctx = GoalContext(rec.goal.goal_id, rec.goal.objective, None, (), dict(rec.user_ctx))
        try:
            steps = self._planner.plan(rec.goal, ctx, rec.max_steps)
            steps = validate_plan(rec.goal, steps, max_steps=rec.max_steps, max_attempts=self.max_attempts, max_step_timeout=self.step_timeout,
                                  agent_exists=getattr(getattr(self._orch, "registry", None), "has", None))
        except PlanningError as exc:
            self._finalize(rec, GoalStatus.BLOCKED, f"no plan: {P.clip(self._detector.redact(str(exc)), 300)}", "no_plan")
            return False
        except InvalidPlanError as exc:
            self._finalize(rec, GoalStatus.BLOCKED, f"invalid plan: {P.clip(self._detector.redact(str(exc)), 300)}", "invalid_plan")
            return False
        except GoalError as exc:
            self._finalize(rec, GoalStatus.FAILED, f"planning failed: {P.clip(self._detector.redact(str(exc)), 300)}", "planning_failed")
            return False
        with self._lock:
            if rec.cancel_requested:
                self._finalize(rec, GoalStatus.CANCELLED, "cancelled while planning", "cancelled")
                return False
            rec.steps = {s.step_id: s for s in steps}
            rec.goal = rec.goal.with_status(GoalStatus.RUNNING)
        log.info("goal %s planned: %d step(s)", rec.goal.goal_id, len(steps))
        return True

    def _loop(self, rec: _Rec) -> None:
        guard = rec.max_steps * (self.max_attempts + 2) * 3 + 50     # every pass starts a step, handles a result or ends: this is only a net
        while guard > 0:
            guard -= 1
            with self._lock:
                remaining = self._remaining(rec)
                timed_out = remaining is not None and remaining <= 0
                if not rec.cancel_requested and not timed_out:      # a stopped goal ends its open steps as CANCELLED, not as "dependency failed"
                    self._block_dependents(rec)
                decision = self._eval.decide(list(rec.steps.values()), cancelled=rec.cancel_requested, timed_out=timed_out)
            if decision.kind in TERMINAL_DECISIONS:
                self._conclude(rec, decision.kind, decision.reason)
                return
            if decision.kind is Decision.NEXT:
                self._set_goal(rec, GoalStatus.RUNNING)
                for sid in decision.ready:
                    if rec.cancel_requested:
                        break
                    self._launch(rec, sid)
                continue
            self._await(rec)
        self._abandon(rec)
        self._finalize(rec, GoalStatus.FAILED, "the goal engine stopped after too many iterations", "loop_guard")

    def _block_dependents(self, rec: _Rec) -> None:
        for sid in self._eval.blocked_by_dependencies(list(rec.steps.values())):
            step = rec.steps[sid]
            res = GoalStepResult(sid, StepStatus.BLOCKED, "not run: a step it depends on did not succeed", None, step.assigned_agent,
                                 None, 0.0, 1, "dependency_failed")
            rec.steps[sid] = step.with_result(res)

    def _await(self, rec: _Rec) -> None:
        with self._lock:
            by_task = {tid: sid for sid, (tid, _) in rec.inflight.items()}
            remaining = self._remaining(rec)
        if not by_task:
            self._abandon(rec)
            self._finalize(rec, GoalStatus.BLOCKED, "no step is running and none can start", "stalled")
            return
        if remaining is not None and remaining <= 0:
            return
        self._set_goal(rec, GoalStatus.WAITING)
        try:
            results = self._orch.wait_any(list(by_task), remaining, lambda: rec.cancel_requested)
        except AgentError:
            results = []
            for tid, sid in by_task.items():     # a task record vanished from the orchestrator: the step cannot be followed any more
                self._lost(rec, sid)
        for res in results:
            sid = by_task.get(getattr(res, "task_id", None))
            if sid is not None and sid in rec.inflight:
                self._handle(rec, sid, res)

    def _lost(self, rec: _Rec, sid: str) -> None:
        with self._lock:
            tid, _ = rec.inflight.pop(sid, ("", 0.0))
        self._settle_step(rec, sid, StepStatus.FAILED, "the agent task is no longer known to the orchestrator", "task_lost", None, tid)

    # ---- internals: steps ---------------------------------------------------------------------------------------------------------------------
    def _launch(self, rec: _Rec, sid: str) -> None:
        with self._lock:
            step = rec.steps[sid]
        if step.is_evaluation:
            self._evaluate_step(rec, sid)
            return
        remaining = self._remaining(rec)
        if rec.cancel_requested or (remaining is not None and remaining <= 0):
            self._settle_step(rec, sid, StepStatus.CANCELLED if rec.cancel_requested else StepStatus.TIMEOUT,
                              "not started: the goal was cancelled or ran out of time", "goal_stopped", None, None)
            return
        with self._lock:
            if step.status is StepStatus.PENDING:
                step = step.with_status(StepStatus.RUNNING)
            step = step.with_attempt()
            rec.steps[sid] = step
        agent_input = {k: v for k, v in step.input.items() if k != "cleanup"}
        timeout = min(step.timeout or self.step_timeout, self.step_timeout)
        if remaining is not None:
            timeout = max(0.1, min(timeout, remaining))
        task_id = f"{rec.goal.goal_id[:36]}-{sid[:12]}-a{step.attempts}"
        # results of finished dependency steps travel through the orchestrator's own parent-result mechanism (AgentTask.dependencies), not through the engine
        parents = tuple(dict.fromkeys(rec.steps[d].result.task_id for d in step.dependencies if d in rec.steps and rec.steps[d].result is not None
                                      and rec.steps[d].status is StepStatus.SUCCEEDED and rec.steps[d].result.task_id and not rec.steps[d].is_evaluation
                                      and not is_cleanup(step)))[:10]
        try:
            task = AgentTask(step.objective, agent_id=step.assigned_agent, input=agent_input, required_capabilities=step.required_capabilities,
                             priority=rec.goal.priority, timeout=timeout, task_id=task_id, dependencies=parents, metadata={"goal_id": rec.goal.goal_id, "step_id": sid},
                             memory_query=rec.user_ctx.get("memory_query") if isinstance(rec.user_ctx.get("memory_query"), str) else None)
            res = self._orch.submit(task)
            with self._lock:
                rec.inflight[sid] = (task.task_id, self._clock.monotonic())
            if res.is_terminal:           # refused at admission (unknown/disabled agent, queue full ...)
                self._handle(rec, sid, res)
                return
            self._orch.start(task.task_id)
        except AgentError as exc:
            with self._lock:
                rec.inflight.pop(sid, None)
            self._settle_step(rec, sid, StepStatus.FAILED, f"the task was refused: {exc}", "invalid_input", None, task_id)

    def _handle(self, rec: _Rec, sid: str, res: AgentResult) -> None:
        with self._lock:
            step = rec.steps[sid]
            _, started = rec.inflight.pop(sid, (res.task_id, self._clock.monotonic()))
            elapsed = max(0.0, self._clock.monotonic() - started)
            status = res.status if isinstance(res.status, TaskStatus) and res.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED,
                                                                                         TaskStatus.BLOCKED, TaskStatus.CANCELLED) else None
            code = res.error_code if isinstance(res.error_code, str) else None
            rec.logs.setdefault(sid, []).append({"attempt": step.attempts, "status": status.value if status else "INVALID", "code": code,
                                                 "duration": round(elapsed, 3), "task_id": str(res.task_id)[:64]})
        if isinstance(res.output, dict) and res.output.get("still_running"):
            self._warn(rec, f"step {sid}: the agent may still be working on its task after the timeout")
        verdict = self._eval.judge(step, status, code) if status else None
        if verdict is None:
            self._settle_step(rec, sid, StepStatus.FAILED, "the agent returned an invalid status", "invalid_status", res, res.task_id)
            return
        if verdict.kind is Verdict.RETRY:
            remaining = self._remaining(rec)
            if rec.cancel_requested or (remaining is not None and remaining <= 0):
                self._settle_step(rec, sid, StepStatus.CANCELLED if rec.cancel_requested else StepStatus.TIMEOUT,
                                  "no retry: the goal was cancelled or ran out of time", code, res, res.task_id)
            else:
                self._launch(rec, sid)
            return
        if verdict.kind is Verdict.DONE:
            self._settle_step(rec, sid, StepStatus.SUCCEEDED, res.summary, code, res, res.task_id)
        else:
            self._settle_step(rec, sid, verdict.status, (res.error or res.summary or verdict.reason), code, res, res.task_id)

    def _settle_step(self, rec: _Rec, sid: str, status: StepStatus, summary: str, code: str | None, res: AgentResult | None,
                     task_id: str | None) -> None:
        red = self._detector.redact
        with self._lock:
            step = rec.steps[sid]
            if step.status in STEP_TERMINAL:
                return
            if step.status is StepStatus.PENDING and status in (StepStatus.SUCCEEDED, StepStatus.TIMEOUT):
                step = step.with_status(StepStatus.RUNNING)
            log_ = rec.logs.get(sid, [])
            res_out = self._clean(res.output) if res is not None else None
            result = GoalStepResult(sid, status, red(summary or "")[:P.MAX_SUMMARY], res_out, (res.agent_id if res is not None else step.assigned_agent),
                                    task_id, round(sum(a.get("duration", 0.0) for a in log_), 3), max(1, step.attempts), code,
                                    tuple(log_))
            rec.steps[sid] = step.with_result(result)
            self._cond.notify_all()

    def _clean(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._detector.redact(value)
        if isinstance(value, dict):
            return {str(k): self._clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean(v) for v in value]
        return value

    def _evaluate_step(self, rec: _Rec, sid: str) -> None:
        with self._lock:
            step = rec.steps[sid].with_status(StepStatus.RUNNING)
            rec.steps[sid] = step
            results = [rec.steps[d].result for d in step.dependencies]
        ok, msg = self._eval.check_evaluation(step, [r for r in results if r is not None] if all(results) else [])
        self._settle_step(rec, sid, StepStatus.SUCCEEDED if ok else StepStatus.FAILED, msg, None if ok else "evaluation_failed", None, None)

    def _warn(self, rec: _Rec, text: str) -> None:
        with self._lock:
            if len(rec.warnings) < 20 and text not in rec.warnings:
                rec.warnings.append(self._detector.redact(text)[:300])

    # ---- internals: finishing --------------------------------------------------------------------------------------------------------------------
    def _stop_inflight(self, rec: _Rec, final: StepStatus, why: str) -> None:
        """Ask every running task to stop (their own cancel mechanism), wait a bounded time, and record what REALLY happened."""
        with self._lock:
            flying = dict(rec.inflight)
        if not flying:
            return
        for tid, _ in flying.values():
            try:
                self._orch.cancel(tid)
            except AgentError:
                pass
        end = self._clock.monotonic() + self._cancel_wait
        for sid, (tid, _) in flying.items():
            try:
                res = self._orch.wait(tid, max(0.0, end - self._clock.monotonic()))
            except AgentError:
                res = None
            with self._lock:
                rec.inflight.pop(sid, None)
            if res is not None and res.is_terminal and res.status is TaskStatus.SUCCEEDED:
                self._settle_step(rec, sid, StepStatus.SUCCEEDED, res.summary, None, res, tid)
            elif res is not None and res.is_terminal:
                self._settle_step(rec, sid, final, why, res.error_code, res, tid)
            else:
                self._warn(rec, f"step {sid}: the agent has not stopped yet and may still be working")
                self._settle_step(rec, sid, final, why + " (the agent had not stopped yet)", "agent_not_stopped", None, tid)

    def _conclude(self, rec: _Rec, kind: Decision, reason: str) -> None:
        if kind in (Decision.CANCELLED, Decision.TIMEOUT):
            self._stop_inflight(rec, StepStatus.CANCELLED if kind is Decision.CANCELLED else StepStatus.TIMEOUT, reason)
        else:
            self._cleanup(rec)
        names = {Decision.REACHED: GoalStatus.SUCCEEDED, Decision.FAILED: GoalStatus.FAILED, Decision.BLOCKED: GoalStatus.BLOCKED,
                 Decision.TIMEOUT: GoalStatus.TIMEOUT, Decision.CANCELLED: GoalStatus.CANCELLED}
        with self._lock:
            ok = sum(1 for s in rec.steps.values() if s.status is StepStatus.SUCCEEDED and not is_cleanup(s))
            total = sum(1 for s in rec.steps.values() if not is_cleanup(s))
            bad = next((s for s in rec.steps.values() if s.status in (StepStatus.FAILED, StepStatus.BLOCKED, StepStatus.TIMEOUT, StepStatus.CANCELLED)
                        and not is_cleanup(s) and not (s.result and (s.result.error_code or "").startswith("dependency_"))), None)
        text = f"{reason} ({ok}/{total} steps succeeded)"
        if bad is not None and bad.result is not None and kind in (Decision.FAILED, Decision.BLOCKED):
            text = f"step {bad.step_id} {bad.status.value}: {bad.result.summary} ({ok}/{total} steps succeeded)"
        self._finalize(rec, names[kind], text, kind.value if kind is not Decision.REACHED else None)

    def _cleanup(self, rec: _Rec) -> None:
        """Steps that only close what an earlier step opened (e.g. a coding session). Run after the goal's own steps, only if the opening
        step succeeded, never after a cancel/timeout, and they never change the goal's result."""
        with self._lock:
            todo = [s.step_id for s in rec.steps.values() if is_cleanup(s) and s.status is StepStatus.PENDING]
        for sid in todo:
            with self._lock:
                step = rec.steps[sid]
                opener = rec.steps.get(step.input["cleanup"])
            remaining = self._remaining(rec)
            if rec.cancel_requested or (remaining is not None and remaining <= 0) or opener is None or opener.status is not StepStatus.SUCCEEDED:
                self._settle_step(rec, sid, StepStatus.CANCELLED, "not needed: nothing was opened or the goal was stopped", "not_needed", None, None)
                continue
            self._launch(rec, sid)
            while sid in rec.inflight:
                tid = rec.inflight[sid][0]
                try:
                    results = self._orch.wait_any([tid], self.cleanup_timeout, lambda: rec.cancel_requested)
                except AgentError:
                    self._lost(rec, sid)
                    break
                if not results:
                    self._stop_inflight(rec, StepStatus.TIMEOUT, "the cleanup did not finish in time")
                    break
                self._handle(rec, sid, results[0])
            with self._lock:
                final = rec.steps[sid]
            if final.status is not StepStatus.SUCCEEDED:
                self._warn(rec, f"cleanup step {sid} ended {final.status.value}: a session may still be open")

    def _finalize(self, rec: _Rec, status: GoalStatus, summary: str, code: str | None) -> None:
        with self._lock:
            if rec.status in GOAL_TERMINAL:
                return
            for sid, step in list(rec.steps.items()):          # nothing stays half-finished
                if step.status is StepStatus.PENDING:
                    gone = status in (GoalStatus.CANCELLED, GoalStatus.TIMEOUT)
                    rec.steps[sid] = step.with_result(GoalStepResult(sid, StepStatus.CANCELLED if gone else StepStatus.BLOCKED,
                                                                      "not run: the goal ended first", None, step.assigned_agent, None, 0.0, 1,
                                                                      "goal_" + status.value.lower()))
                elif step.status is StepStatus.RUNNING:
                    rec.steps[sid] = step.with_result(GoalStepResult(sid, StepStatus.FAILED, "the goal ended while this step was running",
                                                                      None, step.assigned_agent, None, 0.0, max(1, step.attempts), "goal_ended"))
            if rec.status is GoalStatus.PENDING:
                rec.goal = rec.goal.with_status(GoalStatus.PLANNING)
            rec.goal = rec.goal.with_status(status)
            rec.summary = self._detector.redact(summary)[:P.MAX_SUMMARY]
            rec.reason_code = code
            rec.ended = self._clock.monotonic()
            self._cond.notify_all()
        log.info("goal %s -> %s%s", rec.goal.goal_id, status.value, f" ({code})" if code else "")
