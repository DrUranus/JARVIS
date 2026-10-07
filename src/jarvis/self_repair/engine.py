"""RepairEngine: test -> diagnose -> plan -> repair -> targeted re-test -> regression -> evaluate, within hard limits.

It does NOT touch files, run commands or decide permissions. Every action is a task for the existing Coding Agent, run through the existing
AgentOrchestrator (-> ToolGateway -> ToolRegistry -> PermissionEngine -> CodingController). A refused action ends the run BLOCKED - without
retry and without any attempt to get around the refusal. One driver per run (the caller's thread for run(), one daemon thread for start());
it blocks on the orchestrator's own Condition: no polling, no scheduler, no concurrency logic of its own.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from jarvis.agents import policy as AP
from jarvis.agents.errors import AgentError
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentResult
from jarvis.agents.state import TaskStatus
from jarvis.redaction import SecretDetector
from jarvis.self_repair import policy as P
from jarvis.self_repair import tester as T
from jarvis.self_repair.context import RepairContext, check_context
from jarvis.self_repair.diagnostics import DiagnosisEngine
from jarvis.self_repair.errors import InvalidRepairError, PlanBlocked, RepairError, RepairStateError, UnknownRepairError
from jarvis.self_repair.evaluator import RepairEvaluator, Verdict
from jarvis.self_repair.models import Diagnosis, ErrorCategory, RepairAttempt, RepairPlan, RepairResult, RepairRun, TestResult
from jarvis.self_repair.planner import RepairPlanner, targeted_args
from jarvis.self_repair.state import RUN_TERMINAL, AttemptStatus, RepairStatus

log = logging.getLogger("jarvis.self_repair")
_RETRYABLE = frozenset({"timeout", "agent_crashed", "executor_failed", "step_failed"})     # transient: ONE more try for read/test tasks


class Clock(Protocol):
    def monotonic(self) -> float: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class RepairCancelReport:
    run_id: str
    accepted: bool
    status: RepairStatus
    message: str


class _End(Exception):
    """Internal: the run ends now with this status."""

    def __init__(self, status: RepairStatus, reason: str, code: str) -> None:
        super().__init__(reason)
        self.status, self.reason, self.code = status, reason, code


@dataclass
class _Rec:
    run: RepairRun
    ctx: RepairContext
    seq: int
    attempts: list[RepairAttempt] = field(default_factory=list)
    baseline: TestResult | None = None
    changed: tuple[str, ...] = ()
    summaries: tuple[str, ...] = ()
    allowed: list[str] = field(default_factory=list)
    digests: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    reason_code: str | None = None
    cancel_requested: bool = False
    started: bool = False
    opened: bool = False                    # this run started the coding session (and must close it)
    inflight: str | None = None
    thread: threading.Thread | None = None
    deadline: float | None = None
    began: float = 0.0
    counter: int = 0


class RepairEngine:
    def __init__(self, orchestrator: Any, agent_planner: Any, *, repair_planner: RepairPlanner | None = None, diagnostics: DiagnosisEngine | None = None,
                 evaluator: RepairEvaluator | None = None, max_attempts: int = P.MAX_ATTEMPTS_DEFAULT, repair_timeout: float = 900.0,
                 step_timeout: float = 300.0, max_active: int = 1, max_history: int = 50, cancel_wait: float | None = None,
                 clock: Clock | None = None, detector: SecretDetector | None = None) -> None:
        if not 1 <= max_attempts <= P.MAX_ATTEMPTS_HARD or not 0 < repair_timeout <= P.MAX_TIMEOUT or not 0 < step_timeout <= P.MAX_STEP_TIMEOUT \
                or max_active < 1 or max_history < 1:
            raise InvalidRepairError("the self-repair limits must be positive and within the hard limits")
        self._orch, self._agents = orchestrator, agent_planner
        self._planner = repair_planner or RepairPlanner()
        self._diag = diagnostics or DiagnosisEngine()
        self._eval = evaluator or RepairEvaluator()
        self.max_attempts, self.repair_timeout, self.step_timeout = max_attempts, repair_timeout, step_timeout
        self.max_active, self.max_history = max_active, max_history
        self._cancel_wait = cancel_wait if cancel_wait is not None else float(getattr(orchestrator, "cancel_grace", 5.0)) + 1.0
        self._clock: Clock = clock or SystemClock()
        self._detector = detector or SecretDetector.from_environment()
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._recs: dict[str, _Rec] = {}
        self._seq = 0

    # ---- public --------------------------------------------------------------------------------------------------------------------------
    def create(self, objective: str, *, workspace: str, context: Mapping[str, Any] | None = None, max_attempts: int | None = None,
               timeout: float | None = None, run_id: str | None = None) -> RepairRun:
        """Register a run (PENDING). Nothing is tested or changed yet. The workspace must be given explicitly."""
        ctx = check_context(workspace, objective, context)
        kw: dict[str, Any] = {"max_attempts": min(max_attempts or self.max_attempts, self.max_attempts), "timeout": timeout}
        if run_id is not None:
            kw["run_id"] = run_id
        run = RepairRun(self._red(objective, P.MAX_OBJECTIVE), workspace, **kw)
        with self._lock:
            if run.run_id in self._recs:
                raise RepairError(f"run id {run.run_id!r} is already in use")
            self._trim()
            if len(self._recs) >= self.max_history * 2:
                raise RepairError("too many repair runs are registered; finish or cancel some first")
            self._seq += 1
            self._recs[run.run_id] = _Rec(run, ctx, self._seq)
        log.info("repair run %s created", run.run_id)
        return run

    def run(self, run_id: str) -> RepairResult:
        rec = self._claim(run_id)
        if rec is not None:
            self._drive(rec)
        return self.result(run_id)

    def start(self, run_id: str) -> RepairRun:
        rec = self._claim(run_id)
        if rec is not None:
            t = threading.Thread(target=self._drive, args=(rec,), name=f"jarvis-repair-{run_id[:20]}", daemon=True)
            with self._lock:
                rec.thread = t
            t.start()
        return self.get(run_id)

    def wait(self, run_id: str, timeout: float | None = None) -> RepairResult:
        with self._cond:
            rec = self._rec(run_id)
            self._cond.wait_for(lambda: rec.run.status in RUN_TERMINAL, timeout=timeout)
        return self.result(run_id)

    def cancel(self, run_id: str) -> RepairCancelReport:
        """PENDING: cancelled at once. Running: the agents' own cancellation is requested (the coding tool halts a running test process); the
        run turns CANCELLED once the driver has dealt with it. A process that did not stop is reported as a warning, never as stopped."""
        with self._lock:
            rec = self._rec(run_id)
            if rec.run.status in RUN_TERMINAL:
                return RepairCancelReport(run_id, False, rec.run.status, f"the run is already {rec.run.status.value}")
            if not rec.started:
                rec.run = rec.run.with_status(RepairStatus.CANCELLED).evolve(current_phase="done", final_summary="cancelled before it started")
                rec.reason_code = "cancelled"
                self._cond.notify_all()
                return RepairCancelReport(run_id, True, rec.run.status, "cancelled before it started")
            rec.cancel_requested = True
            tid = rec.inflight
        if tid:
            try:
                self._orch.cancel(tid)
            except AgentError:
                pass
        self._orch.notify_waiters()
        with self._cond:
            self._cond.notify_all()
        return RepairCancelReport(run_id, True, rec.run.status, "cancellation requested; the run ends CANCELLED once the agent has been dealt with")

    def get(self, run_id: str) -> RepairRun:
        with self._lock:
            return self._rec(run_id).run

    def attempts(self, run_id: str) -> tuple[RepairAttempt, ...]:
        with self._lock:
            return tuple(self._rec(run_id).attempts)

    def result(self, run_id: str) -> RepairResult:
        with self._lock:
            r = self._rec(run_id)
            return RepairResult(r.run, tuple(r.attempts), r.baseline, r.changed, tuple(r.warnings), r.reason_code)

    def list(self, status: RepairStatus | None = None, limit: int | None = None) -> list[RepairRun]:
        with self._lock:
            runs = [r.run for r in sorted(self._recs.values(), key=lambda r: r.seq, reverse=True) if status is None or r.run.status is status]
            return runs[:limit] if limit else runs

    def describe(self) -> dict[str, Any]:
        with self._lock:
            return {"runs": len(self._recs), "active": self._active(), "max_active": self.max_active, "max_attempts": self.max_attempts,
                    "repair_timeout": self.repair_timeout, "step_timeout": self.step_timeout}

    def shutdown(self, wait: float = 2.0) -> None:
        with self._lock:
            active = [r for r in self._recs.values() if r.started and r.run.status not in RUN_TERMINAL]
        for r in active:
            self.cancel(r.run.run_id)
        end = time.monotonic() + max(0.0, wait)
        for r in active:
            if r.thread is not None:
                r.thread.join(max(0.0, end - time.monotonic()))

    # ---- bookkeeping ------------------------------------------------------------------------------------------------------------------------
    def _rec(self, run_id: str) -> _Rec:
        try:
            return self._recs[run_id]
        except (KeyError, TypeError):
            raise UnknownRepairError(f"unknown repair run {str(run_id)[:40]!r}") from None

    def _active(self) -> int:
        return sum(1 for r in self._recs.values() if r.started and r.run.status not in RUN_TERMINAL)

    def _trim(self) -> None:
        done = sorted((r for r in self._recs.values() if r.run.status in RUN_TERMINAL and (r.thread is None or not r.thread.is_alive())), key=lambda r: r.seq)
        for r in done[: max(0, len(self._recs) - self.max_history)]:
            del self._recs[r.run.run_id]

    def _claim(self, run_id: str) -> _Rec | None:
        with self._lock:
            rec = self._rec(run_id)
            if rec.run.status in RUN_TERMINAL:
                return None
            if rec.started:
                raise RepairStateError("this run is already running")
            if self._active() >= self.max_active:
                raise RepairError(f"at most {self.max_active} repair run(s) can run at the same time")
            rec.started = True
            rec.began = self._clock.monotonic()
            rec.deadline = rec.began + min(rec.run.timeout or self.repair_timeout, self.repair_timeout)
            return rec

    def _set(self, rec: _Rec, status: RepairStatus, phase: str) -> None:
        with self._lock:
            if rec.run.status in RUN_TERMINAL:
                return
            if rec.run.status is not status:
                rec.run = rec.run.with_status(status)
            rec.run = rec.run.evolve(current_phase=phase)

    def _red(self, text: Any, limit: int = P.MAX_SUMMARY) -> str:
        return P.clip(self._detector.redact(text if isinstance(text, str) else str(text)), limit)

    def _remaining(self, rec: _Rec) -> float | None:
        return None if rec.deadline is None else rec.deadline - self._clock.monotonic()

    def _checkpoint(self, rec: _Rec) -> None:
        if rec.cancel_requested:
            raise _End(RepairStatus.CANCELLED, "the run was cancelled", "cancelled")
        rem = self._remaining(rec)
        if rem is not None and rem <= 0:
            raise _End(RepairStatus.TIMEOUT, "the repair timeout was reached", "timeout")

    def _warn(self, rec: _Rec, text: str) -> None:
        with self._lock:
            if len(rec.warnings) < 20 and text not in rec.warnings:
                rec.warnings.append(self._red(text, 300))

    # ---- driver -----------------------------------------------------------------------------------------------------------------------------
    def _drive(self, rec: _Rec) -> None:
        try:
            self._execute(rec)
        except _End as end:
            self._finish(rec, end.status, end.reason, end.code)
        except Exception as exc:  # noqa: BLE001 - a bug here must end the run honestly, never leave it hanging
            log.warning("repair run %s: internal error (%s)", rec.run.run_id, type(exc).__name__)
            self._abandon(rec)
            self._finish(rec, RepairStatus.FAILED, f"internal error ({type(exc).__name__})", "internal_error")

    def _abandon(self, rec: _Rec) -> None:
        tid = rec.inflight
        if tid:
            try:
                self._orch.cancel(tid)
            except AgentError:
                pass

    def _finish(self, rec: _Rec, status: RepairStatus, reason: str, code: str) -> None:
        stopped_by_user = status in (RepairStatus.CANCELLED, RepairStatus.TIMEOUT)
        if rec.opened and not stopped_by_user:
            self._close_session(rec)
        elif rec.opened:
            self._warn(rec, "the coding session was left open (the run was stopped); close it with /run coding action=stop")
        with self._lock:
            if rec.run.status in RUN_TERMINAL:
                return
            if rec.run.status is RepairStatus.PENDING:
                rec.run = rec.run.with_status(RepairStatus.TESTING)
            for i, a in enumerate(rec.attempts):
                if a.status not in (AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.BLOCKED, AttemptStatus.CANCELLED):
                    to = {RepairStatus.SUCCEEDED: AttemptStatus.SUCCEEDED, RepairStatus.CANCELLED: AttemptStatus.CANCELLED,
                          RepairStatus.BLOCKED: AttemptStatus.BLOCKED}.get(status, AttemptStatus.FAILED)
                    rec.attempts[i] = a.with_status(to, self._red(reason))
            rec.run = rec.run.with_status(status).evolve(current_phase="done", final_summary=self._red(reason))
            rec.reason_code = code
            self._cond.notify_all()
        log.info("repair run %s -> %s (%s)", rec.run.run_id, status.value, code)

    def _close_session(self, rec: _Rec) -> None:
        try:
            self._task(rec, "cleanup", "Beende die Projekt-Sitzung (Code, Projekt)", [{"action": "stop"}], {AP.CODING_READ}, retry=False, checkpoint=False)
        except _End:
            self._warn(rec, "the coding session could not be closed; close it with /run coding action=stop")
        except Exception:  # noqa: BLE001
            self._warn(rec, "the coding session could not be closed; close it with /run coding action=stop")

    # ---- one agent task ---------------------------------------------------------------------------------------------------------------------
    def _task(self, rec: _Rec, phase: str, objective: str, steps: list[dict[str, Any]], caps: set[str], *, retry: bool = True,
              checkpoint: bool = True) -> AgentResult:
        """Run ONE coding-agent task through the orchestrator and return its final result (raises _End for cancel/timeout/no agent)."""
        capset = frozenset(caps)
        for tries in (1, 2):
            if checkpoint:
                self._checkpoint(rec)
            sel = self._agents.select(objective, capset)
            if not sel.found:
                raise _End(RepairStatus.BLOCKED, f"no agent can do this step: {sel.reason}", "no_agent")
            rem = self._remaining(rec)
            timeout = self.step_timeout if rem is None or not checkpoint else max(0.1, min(self.step_timeout, rem))
            with self._lock:
                rec.counter += 1
                tid = f"{rec.run.run_id[:34]}-{phase[:10]}-{rec.counter}"
            try:
                task = AgentTask(objective, agent_id=sel.agent_id, input={"steps": steps}, required_capabilities=capset, priority=3, timeout=timeout,
                                 task_id=tid, metadata={"repair_id": rec.run.run_id, "phase": phase})
                res = self._orch.submit(task)
                if not res.is_terminal:
                    with self._lock:
                        rec.inflight = tid
                    self._orch.start(tid)
                    got = self._orch.wait_any([tid], rem if checkpoint else timeout + self._cancel_wait + 5.0, lambda: rec.cancel_requested)
                    if not got:
                        self._stop_task(rec, tid)
                    res = got[0]
            except AgentError as exc:
                raise _End(RepairStatus.FAILED, f"the agent task was refused: {self._red(exc)}", "task_refused") from None
            finally:
                with self._lock:
                    rec.inflight = None
            if not isinstance(res.status, TaskStatus) or res.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                raise _End(RepairStatus.FAILED, "the agent returned an invalid status", "invalid_status")
            if res.status is TaskStatus.CANCELLED and rec.cancel_requested:
                raise _End(RepairStatus.CANCELLED, "the run was cancelled", "cancelled")
            if res.status is TaskStatus.FAILED and retry and tries == 1 and res.error_code in _RETRYABLE:
                self._warn(rec, f"{phase}: transient failure ({res.error_code}); trying once more")
                continue
            return res
        raise _End(RepairStatus.FAILED, "unreachable", "internal_error")      # pragma: no cover

    def _stop_task(self, rec: _Rec, tid: str) -> None:
        """Cancel or timeout while a task runs: ask the agent to stop, wait a bounded time, say honestly what happened."""
        try:
            self._orch.cancel(tid)
            res = self._orch.wait(tid, self._cancel_wait)
            if not res.is_terminal:
                self._warn(rec, "the agent has not stopped yet and may still be working")
        except AgentError:
            pass
        if rec.cancel_requested:
            raise _End(RepairStatus.CANCELLED, "the run was cancelled", "cancelled")
        raise _End(RepairStatus.TIMEOUT, "the repair timeout was reached", "timeout")

    def _need_ok(self, res: AgentResult, what: str) -> None:
        """A task that did not succeed ends the run: BLOCKED when the permission system (or a halt) refused it, else FAILED."""
        if res.status is TaskStatus.SUCCEEDED:
            return
        detail = self._red(res.error or res.summary or res.status.value, 300)
        if res.status is TaskStatus.BLOCKED:
            raise _End(RepairStatus.BLOCKED, f"{what} was blocked: {detail}", res.error_code or "blocked")
        raise _End(RepairStatus.FAILED, f"{what} failed: {detail}", res.error_code or "failed")

    def _test(self, rec: _Rec, phase: str, what: str, args: list[str]) -> TestResult:
        res = self._task(rec, phase, "Führe die Tests des Projekts aus (Code, Tests, pytest)", [T.test_step(rec.ctx.runner, args)], {AP.CODING_TEST})
        self._need_ok(res, what)
        out = T.parse_test_result(res.output, self._detector.redact)
        if out is None:
            raise _End(RepairStatus.FAILED, f"{what} produced no test result", "no_test_result")
        return out

    # ---- the repair loop ----------------------------------------------------------------------------------------------------------------------
    def _execute(self, rec: _Rec) -> None:
        ctx = rec.ctx
        self._checkpoint(rec)
        try:
            self._planner.preflight(ctx)        # unacceptable candidates (traversal, secrets, tests ...) stop the run before ANY test or write
        except PlanBlocked as exc:
            raise _End(RepairStatus.BLOCKED, self._red(str(exc)), "candidate_refused") from None
        self._set(rec, RepairStatus.TESTING, "baseline")
        res = self._task(rec, "baseline", "Starte das Projekt und führe die Tests aus (Code, Tests, Projekt)",
                         T.start_steps(ctx.workspace) + [T.test_step(ctx.runner)], {AP.CODING_READ, AP.CODING_TEST})
        started = T.last_step(res.output, "start")
        rec.opened = bool(started and started.get("ok") is True)
        info = T.last_step(res.output, "info")
        if info and info.get("ok") is True and isinstance(info.get("output"), Mapping) and info["output"].get("is_jarvis_workspace"):
            raise _End(RepairStatus.BLOCKED, "JARVIS's own repository is not a repair target in this version", "jarvis_repo")
        self._need_ok(res, "the baseline test run")
        base = T.parse_test_result(res.output, self._detector.redact)
        if base is None:
            raise _End(RepairStatus.FAILED, "the baseline test run produced no test result", "no_test_result")
        base = self._categorise(base)
        with self._lock:
            rec.baseline = base
            rec.run = rec.run.evolve(failure_summary="" if base.passed else self._red(base.summary or "tests failed"))
        if base.passed:
            raise _End(RepairStatus.SUCCEEDED, "the tests pass" + ("; nothing was changed" if ctx.repair else ""), "tests_pass")
        if not ctx.repair:
            raise _End(RepairStatus.FAILED, f"the tests fail: {base.summary or len(base.failed_tests)} (no repair was requested)", "tests_fail")
        failing = base
        for n in range(1, rec.run.max_attempts + 1):
            self._checkpoint(rec)
            self._set(rec, RepairStatus.DIAGNOSING, "diagnose")
            diag = self._diag.diagnose(failing)
            self._set(rec, RepairStatus.PLANNING, "plan")
            try:
                plan = self._planner.plan(failing, diag, ctx, n)
            except PlanBlocked as exc:
                status = RepairStatus.BLOCKED if n == 1 else RepairStatus.FAILED
                raise _End(status, self._red(str(exc)) + ("" if n == 1 else f" (after {n - 1} attempt(s))"), "no_plan" if n == 1 else "exhausted") from None
            digest = plan.digest()
            attempt = RepairAttempt(f"{rec.run.run_id[:40]}-a{n}", rec.run.run_id, n, diag, plan.objective, (), None, None, AttemptStatus.PENDING, "", plan)
            with self._lock:
                rec.attempts.append(attempt)
                rec.run = rec.run.evolve(attempt_count=n)
            if digest in rec.digests:
                raise _End(RepairStatus.FAILED, "the same repair was proposed again; stopping instead of repeating it", "repeated_plan")
            rec.digests.add(digest)
            with self._lock:
                rec.allowed.extend(plan.target_files)
            self._attempt(rec, n, AttemptStatus.REPAIRING)
            self._set(rec, RepairStatus.REPAIRING, "repair")
            steps = [{"action": "write", **e} for e in plan.edits] + [{"action": "changes"}]
            res = self._task(rec, "repair", plan.objective, steps, {AP.CODING_READ, AP.CODING_WRITE}, retry=False)
            if res.status is TaskStatus.BLOCKED:
                self._need_ok(res, "the repair")                      # permission refused: BLOCKED, no retry, no second try
            changed = T.changed_paths(res.output)
            summaries = T.change_summaries(res.output)
            if changed is not None:
                with self._lock:
                    rec.changed = changed
            stray = self._eval.unexpected_files(rec.changed, rec.allowed)
            if stray:
                self._attempt(rec, n, AttemptStatus.BLOCKED, f"unexpected file change: {', '.join(stray[:3])}", changed=rec.changed)
                raise _End(RepairStatus.BLOCKED, f"files outside the repair plan were changed: {', '.join(stray[:3])}; nothing was accepted (not rolled back)", "unexpected_change")
            if res.status is not TaskStatus.SUCCEEDED:
                self._attempt(rec, n, AttemptStatus.FAILED, self._red(res.error or res.summary or "the repair could not be applied", 300), changed=rec.changed)
                if res.status is TaskStatus.FAILED and n < rec.run.max_attempts:
                    self._set(rec, RepairStatus.DIAGNOSING, "diagnose")
                    continue                                           # an edit that did not apply: the next candidate gets its attempt
                self._need_ok(res, "the repair")
            if summaries is not None and summaries == rec.summaries:
                self._attempt(rec, n, AttemptStatus.FAILED, "the repair changed nothing relevant", changed=rec.changed)
                raise _End(RepairStatus.FAILED, "the repair did not change any file; stopping instead of repeating it", "no_change")
            rec.summaries = summaries or rec.summaries
            self._attempt(rec, n, AttemptStatus.RETESTING, changed=rec.changed)
            self._set(rec, RepairStatus.RETESTING, "targeted test")
            targeted = self._categorise(self._test(rec, "retest", "the targeted test run", targeted_args(plan, ctx, failing.failed_tests)))
            self._attempt(rec, n, None, targeted=targeted)
            if not targeted.passed:
                self._attempt(rec, n, AttemptStatus.FAILED, "the targeted test still fails")
                failing = targeted
                self._set(rec, RepairStatus.DIAGNOSING, "diagnose")
                with self._lock:
                    rec.run = rec.run.evolve(failure_summary=self._red(targeted.summary or "targeted test failed"))
                continue
            self._attempt(rec, n, AttemptStatus.REGRESSION)
            self._set(rec, RepairStatus.REGRESSION, "regression")
            regression = self._categorise(self._test(rec, "regress", "the regression run", []))
            self._attempt(rec, n, None, regression=regression)
            verdict = self._eval.golden(targeted, regression, rec.changed, rec.allowed)
            if verdict.verdict is Verdict.SUCCESS:
                self._attempt(rec, n, AttemptStatus.SUCCEEDED)
                raise _End(RepairStatus.SUCCEEDED, f"repaired in attempt {n}: {verdict.reason}; changed: {', '.join(rec.changed)}", "repaired")
            same, total = self._eval.preexisting(base, regression)
            note = f" ({same} of {total} failing test(s) already failed before the repair)" if total else ""
            self._attempt(rec, n, AttemptStatus.BLOCKED if verdict.verdict is Verdict.BLOCKED else AttemptStatus.FAILED, verdict.reason + note)
            status = RepairStatus.BLOCKED if verdict.verdict is Verdict.BLOCKED else RepairStatus.FAILED
            raise _End(status, verdict.reason + note + "; the repair is NOT reported as successful", "regression_failed" if status is RepairStatus.FAILED else "unexpected_change")
        raise _End(RepairStatus.FAILED, f"the tests still fail after {rec.run.max_attempts} attempt(s)", "max_attempts")

    def _categorise(self, result: TestResult) -> TestResult:
        if result.passed:
            return result
        from dataclasses import replace
        return replace(result, error_category=self._diag.diagnose(result).category)

    def _attempt(self, rec: _Rec, n: int, status: AttemptStatus | None, reason: str = "", *, changed: tuple[str, ...] | None = None,
                 targeted: TestResult | None = None, regression: TestResult | None = None) -> None:
        with self._lock:
            a = rec.attempts[n - 1]
            kw: dict[str, Any] = {}
            if changed is not None:
                kw["changed_files"] = tuple(changed)
            if targeted is not None:
                kw["targeted_test_result"] = targeted
            if regression is not None:
                kw["regression_result"] = regression
            if kw:
                a = a.evolve(**kw)
            if status is not None and status is not a.status:
                a = a.with_status(status, reason)
            rec.attempts[n - 1] = a
