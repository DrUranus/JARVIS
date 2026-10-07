"""AgentOrchestrator: coordinates agents, contains no browser, coding or computer logic.

submit -> start -> (dependencies / free slot / free agent) -> RUNNING on a worker -> terminal result.
Everything is bounded: at most `max_concurrent` agents work at the same time (the rest stays PENDING), the queue and the history
have limits, every task has a timeout, and nothing polls in a loop - waiting uses a Condition, timeouts use a scheduler.

Honesty rules: a task is never reported finished while its work is still running. Cancelling a RUNNING task only *requests*
cancellation (cooperative); the task becomes CANCELLED when the agent actually returns. A timeout marks the task FAILED
(`timeout`, `still_running`) but the agent stays BUSY and the slot stays taken until the work really stops; an agent that does
not stop within the grace period is marked FAILED so nothing new is sent to it.
"""
from __future__ import annotations

import copy
import json
import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, Sequence

from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext, ParentResult, ToolGateway
from jarvis.agents.errors import DuplicateError, InvalidTaskError, TaskCancelled, ToolAccessError, UnknownAgentError
from jarvis.agents.models import AgentTask
from jarvis.agents.registry import AgentRegistry
from jarvis.agents.result import AgentOutcome, AgentResult
from jarvis.agents.state import TERMINAL, AgentStatus, TaskStatus, check_task_transition
from jarvis.redaction import SecretDetector
from jarvis.tasks import Task, TaskManager
from jarvis.tasks import TaskStatus as CoreStatus

log = logging.getLogger("jarvis.agents")


# ---- injectable time and execution (so tests are deterministic) -----------------------------------------------------------------------------
class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


class Scheduler(Protocol):
    def call_later(self, delay: float, fn: Callable[[], None]) -> TimerHandle: ...


class ThreadScheduler:
    def call_later(self, delay: float, fn: Callable[[], None]) -> TimerHandle:
        t = threading.Timer(delay, fn)
        t.daemon = True
        t.start()
        return t


class Executor(Protocol):
    def submit(self, fn: Callable[[], None], name: str) -> None: ...


class ThreadExecutor:
    """One daemon thread per started task. The orchestrator itself limits how many run at once."""

    def submit(self, fn: Callable[[], None], name: str) -> None:
        threading.Thread(target=fn, name=name, daemon=True).start()


MemoryLookup = Callable[[str, int], Sequence[str]]


@dataclass
class _Rec:
    task: AgentTask
    seq: int
    agent_id: str | None
    result: AgentResult
    requested: bool = False
    cancel_requested: bool = False
    timed_out: bool = False
    worker_alive: bool = False
    stuck: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)
    timer: TimerHandle | None = None
    grace_timer: TimerHandle | None = None
    core_task: Task | None = None

    @property
    def status(self) -> TaskStatus:
        return self.result.status


@dataclass(frozen=True)
class CancelReport:
    task_id: str
    accepted: bool
    status: TaskStatus
    message: str


class AgentOrchestrator:
    def __init__(self, registry: AgentRegistry, *, tools: Any = None, max_concurrent: int = 3, default_timeout: float = 300.0,
                 max_queue: int = 50, max_history: int = 200, cancel_grace: float = 5.0, tool_call_limit: int = 200,
                 max_output_chars: int = 20_000, task_manager: TaskManager | None = None, memory_lookup: MemoryLookup | None = None,
                 clock: Clock | None = None, scheduler: Scheduler | None = None, executor: Executor | None = None,
                 detector: SecretDetector | None = None) -> None:
        if max_concurrent < 1 or default_timeout <= 0 or max_queue < 1 or max_history < 1 or cancel_grace < 0:
            raise InvalidTaskError("orchestrator limits must be positive")
        self.registry = registry
        self._tools = tools                       # a ToolRegistry: the ONLY way agents act (through ToolGateway)
        self.max_concurrent = max_concurrent
        self.default_timeout, self.max_queue, self.max_history = default_timeout, max_queue, max_history
        self.cancel_grace, self.tool_call_limit, self.max_output_chars = cancel_grace, tool_call_limit, max_output_chars
        self._task_manager, self._memory_lookup = task_manager, memory_lookup
        self._clock: Clock = clock or SystemClock()
        self._scheduler: Scheduler = scheduler or ThreadScheduler()
        self._executor: Executor = executor or ThreadExecutor()
        self._detector = detector or SecretDetector.from_environment()
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._records: dict[str, _Rec] = {}
        self._seq = 0
        self._running = 0
        self.peak_running = 0

    # ---- views ------------------------------------------------------------------------------------------------------------------------
    @property
    def active_agents(self) -> int:
        """Workers that are executing right now (also ones whose task already timed out but whose work has not stopped yet)."""
        with self._lock:
            return self._running

    @property
    def queued(self) -> int:
        with self._lock:
            return sum(1 for r in self._records.values() if r.status is TaskStatus.PENDING)

    def get(self, task_id: str) -> AgentResult:
        with self._lock:
            return self._rec(task_id).result

    def list(self, status: TaskStatus | None = None, limit: int | None = None) -> list[AgentResult]:
        with self._lock:
            recs = sorted(self._records.values(), key=lambda r: r.seq)
            out = [r.result for r in recs if status is None or r.status is status]
            return out[-limit:] if limit else out

    def describe(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            r = self._rec(task_id)
            res = r.result
            return {"task_id": r.task.task_id, "agent_id": res.agent_id, "status": res.status.value, "priority": r.task.priority,
                    "objective": self._detector.redact(r.task.objective)[:200], "dependencies": list(r.task.dependencies),
                    "requested": r.requested, "cancel_requested": r.cancel_requested, "timed_out": r.timed_out,
                    "still_running": r.worker_alive and res.is_terminal, "summary": res.summary[:200], "error_code": res.error_code,
                    "started_at": res.started_at.isoformat() if res.started_at else None,
                    "finished_at": res.finished_at.isoformat() if res.finished_at else None}

    def _rec(self, task_id: str) -> _Rec:
        try:
            return self._records[task_id]
        except (KeyError, TypeError):
            raise UnknownAgentError(f"unknown task {str(task_id)[:40]!r}") from None

    # ---- submit -----------------------------------------------------------------------------------------------------------------------
    def submit(self, task: AgentTask) -> AgentResult:
        """Register a task (status PENDING, not started). Conditions that make it impossible (unknown/disabled agent, missing capability,
        unknown dependency, full queue) are reported as a BLOCKED result - not raised. Raises only for programmer errors."""
        if not isinstance(task, AgentTask):
            raise InvalidTaskError("submit() needs an AgentTask")
        with self._lock:
            if task.task_id in self._records:
                raise DuplicateError(f"task id {task.task_id!r} is already in use")
            self._seq += 1
            rec = _Rec(task, self._seq, None, AgentResult(task.task_id, task.agent_id, TaskStatus.PENDING))
            self._records[task.task_id] = rec
            problem = self._admission(rec)
            if problem is None and sum(1 for r in self._records.values() if r.status is TaskStatus.PENDING) > self.max_queue:
                problem = ("queue_full", f"more than {self.max_queue} tasks are waiting")
            self._mirror_new(rec)
            if problem is not None:
                self._finalize(rec, TaskStatus.BLOCKED, problem[1], None, problem[1], problem[0])
            self._trim()
            log.info("agent task %s submitted (%s)", task.task_id, rec.status.value)
            return rec.result

    def _admission(self, rec: _Rec) -> tuple[str, str] | None:
        task = rec.task
        agent: Agent | None
        if task.agent_id is not None:
            agent = self.registry.get(task.agent_id) if self.registry.has(task.agent_id) else None
            if agent is None:
                return "unknown_agent", f"no agent {task.agent_id!r} is registered"
        else:
            found = self.registry.find(task.required_capabilities)
            if not task.required_capabilities or not found:
                return "no_suitable_agent", "no available agent offers the required capabilities"
            agent = next((a for a in found if a.status is AgentStatus.AVAILABLE), found[0])
        rec.agent_id = agent.id
        rec.result = replace(rec.result, agent_id=agent.id)
        missing = task.required_capabilities - agent.capabilities
        if missing:
            return "capability_missing", f"agent {agent.id!r} does not offer {sorted(missing)}"
        if agent.status is AgentStatus.DISABLED:
            return "agent_disabled", f"agent {agent.id!r} is disabled"
        if agent.status is AgentStatus.FAILED:
            return "agent_failed", f"agent {agent.id!r} is in the FAILED state and must be reset first"
        for dep in task.dependencies:
            if dep not in self._records:
                return "unknown_dependency", f"dependency {dep!r} is not a known task"
        return None

    # ---- start / dispatch ---------------------------------------------------------------------------------------------------------------
    def start(self, task_id: str) -> AgentResult:
        """Ask for execution. The task runs as soon as its dependencies succeeded, its agent is free and a slot is free; until then it is
        PENDING. Starting a task that is not PENDING changes nothing (a task never runs twice)."""
        with self._lock:
            rec = self._rec(task_id)
            if rec.status is TaskStatus.PENDING:
                rec.requested = True
                self._dispatch()
            return rec.result

    def _dispatch(self) -> None:
        progress = True
        while progress:
            progress = False
            for rec in sorted((r for r in self._records.values() if r.status is TaskStatus.PENDING), key=lambda r: (r.task.priority, r.seq)):
                if rec.status is not TaskStatus.PENDING:
                    continue
                dep = self._dependency_state(rec)
                if isinstance(dep, tuple):
                    self._finalize(rec, TaskStatus.BLOCKED, dep[1], None, dep[1], dep[0])
                    progress = True
                    continue
                if dep == "wait" or not rec.requested:
                    continue
                agent = self.registry.get(rec.agent_id) if rec.agent_id and self.registry.has(rec.agent_id) else None
                if agent is None or agent.status in (AgentStatus.DISABLED, AgentStatus.FAILED):
                    self._finalize(rec, TaskStatus.BLOCKED, "the agent is not available any more", None, "the agent is not available any more",
                                   "agent_unavailable")
                    progress = True
                    continue
                if self._running >= self.max_concurrent or not agent.state.claim():
                    continue
                if self._launch(rec, agent):
                    progress = True

    def _dependency_state(self, rec: _Rec) -> str | tuple[str, str]:
        waiting = False
        for dep in rec.task.dependencies:
            d = self._records.get(dep)
            if d is None:
                return "unknown_dependency", f"dependency {dep!r} is gone"
            if d.status is TaskStatus.SUCCEEDED:
                continue
            if d.status in TERMINAL:
                return "dependency_failed", f"dependency {dep!r} ended {d.status.value}; this task was not run"
            waiting = True
        return "wait" if waiting else "ready"

    def _launch(self, rec: _Rec, agent: Agent) -> bool:
        task = rec.task
        check_task_transition(rec.status, TaskStatus.RUNNING)
        now = self._clock.now()
        rec.result = replace(rec.result, status=TaskStatus.RUNNING, started_at=now)
        ctx = self._context(rec, agent)
        rec.worker_alive = True
        self._running += 1
        self.peak_running = max(self.peak_running, self._running)
        timeout = task.timeout if task.timeout is not None else self.default_timeout
        rec.timer = self._scheduler.call_later(timeout, lambda: self._on_timeout(task.task_id, timeout))
        self._mirror_running(rec)
        try:
            self._executor.submit(lambda: self._worker(rec, agent, ctx), f"agent-{agent.id}-{task.task_id}")
        except Exception as exc:  # could not even start the work: undo, report
            rec.worker_alive = False
            self._running -= 1
            self._cancel_timers(rec)
            agent.state.try_transition(AgentStatus.AVAILABLE)
            self._finalize(rec, TaskStatus.FAILED, "the task could not be started", None, f"executor failed ({type(exc).__name__})", "executor_failed")
            return False
        log.info("agent task %s started on %s", task.task_id, agent.id)
        return True

    def _context(self, rec: _Rec, agent: Agent) -> AgentContext:
        task = rec.task
        parents: dict[str, ParentResult] = {}
        for ref in (*task.dependencies, *(() if task.parent_task_id is None else (task.parent_task_id,))):
            p = self._records.get(ref)
            if p is not None and p.status is TaskStatus.SUCCEEDED and ref not in parents:
                parents[ref] = ParentResult(ref, p.result.agent_id, p.status, p.result.summary, copy.deepcopy(p.result.output))
        memory: tuple[str, ...] = ()
        if task.memory_query and self._memory_lookup is not None:
            try:
                memory = tuple(self._detector.redact(str(m))[:500] for m in list(self._memory_lookup(task.memory_query, 5))[:5])
            except Exception:  # noqa: BLE001 - memory trouble never blocks a task
                memory = ()
        allowed = task.required_capabilities or frozenset(agent.capabilities)
        gateway = ToolGateway(self._tools, agent.tool_names, rec.cancel_event, self.tool_call_limit)
        return AgentContext(task.task_id, task.objective, copy.deepcopy(dict(task.input)), allowed, memory, parents, dict(task.metadata),
                            gateway, rec.cancel_event)

    # ---- the worker -----------------------------------------------------------------------------------------------------------------------
    def _worker(self, rec: _Rec, agent: Agent, ctx: AgentContext) -> None:
        outcome: AgentOutcome | None = None
        crash: str | None = None
        try:
            outcome = agent.perform(rec.task, ctx)
            if not isinstance(outcome, AgentOutcome):
                outcome, crash = None, "InvalidOutcome"
        except TaskCancelled:
            outcome = AgentOutcome.cancelled()
        except ToolAccessError as exc:
            outcome = AgentOutcome.failed(str(exc), code="tool_access_denied")
        except Exception as exc:  # noqa: BLE001 - isolation: whatever an agent does, the orchestrator and the other agents go on
            crash = type(exc).__name__
        with self._lock:
            self._complete(rec, agent, outcome, crash)

    def _complete(self, rec: _Rec, agent: Agent, outcome: AgentOutcome | None, crash: str | None) -> None:
        rec.worker_alive = False
        self._running -= 1
        if rec.status is TaskStatus.RUNNING:
            if crash is not None:
                self._finalize(rec, TaskStatus.FAILED, "the agent crashed", None, f"agent crashed ({crash})", "agent_crashed")
            else:
                assert outcome is not None
                status = outcome.status
                if rec.cancel_requested and status is not TaskStatus.SUCCEEDED:
                    status = TaskStatus.CANCELLED
                self._finalize(rec, status, outcome.summary, outcome.output, outcome.error, outcome.error_code)
        else:
            log.info("agent task %s: late result discarded (task is already %s)", rec.task.task_id, rec.status.value)
        st = agent.status
        if crash is not None and st is AgentStatus.BUSY:
            agent.state.try_transition(AgentStatus.FAILED, f"crashed ({crash})")
        elif st is AgentStatus.BUSY:
            agent.state.try_transition(AgentStatus.AVAILABLE)
        elif st is AgentStatus.FAILED and rec.stuck and crash is None:
            agent.state.try_transition(AgentStatus.AVAILABLE)  # the stuck work finally returned: the agent is usable again
        rec.stuck = False
        self._cond.notify_all()
        self._dispatch()

    # ---- finishing ----------------------------------------------------------------------------------------------------------------------------
    def _finalize(self, rec: _Rec, status: TaskStatus, summary: str, output: Any, error: str | None, code: str | None) -> None:
        check_task_transition(rec.status, status)
        self._cancel_timers(rec, grace=False)
        red = self._detector.redact
        out = self._limit_output(self._redact_data(output))
        rec.result = AgentResult(rec.task.task_id, rec.agent_id, status, red(summary or "")[:2000], out,
                                 red(error)[:2000] if error else None, code, rec.result.started_at, self._clock.now())
        self._mirror_final(rec)
        self._cond.notify_all()
        log.info("agent task %s -> %s%s", rec.task.task_id, status.value, f" ({code})" if code else "")

    def _redact_data(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._detector.redact(value)
        if isinstance(value, dict):
            return {k: self._redact_data(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact_data(v) for v in value]
        return value

    def _limit_output(self, value: Any) -> Any:
        try:
            blob = json.dumps(value)
        except (TypeError, ValueError):
            return {"unserialisable": True}
        if len(blob) <= self.max_output_chars:
            return value
        return {"truncated": True, "preview": blob[: self.max_output_chars // 4]}

    def _cancel_timers(self, rec: _Rec, grace: bool = True) -> None:
        if rec.timer is not None:
            rec.timer.cancel()
            rec.timer = None
        if grace and rec.grace_timer is not None:
            rec.grace_timer.cancel()
            rec.grace_timer = None

    def _trim(self) -> None:
        terminal = [r for r in sorted(self._records.values(), key=lambda r: r.seq) if r.status in TERMINAL and not r.worker_alive]
        for r in terminal[: max(0, len(self._records) - self.max_history)]:
            del self._records[r.task.task_id]

    # ---- timeout / cancel -----------------------------------------------------------------------------------------------------------------------
    def _on_timeout(self, task_id: str, timeout: float) -> None:
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None or rec.status is not TaskStatus.RUNNING:
                return
            rec.timed_out = True
            rec.cancel_event.set()
            agent = self.registry.get(rec.agent_id) if rec.agent_id and self.registry.has(rec.agent_id) else None
            self._finalize(rec, TaskStatus.FAILED, "timeout", {"still_running": True}, f"the task did not finish within {timeout:g} seconds", "timeout")
            rec.grace_timer = self._scheduler.call_later(self.cancel_grace, lambda: self._on_grace(task_id))
        self._tell_agent(agent, task_id)

    def _on_grace(self, task_id: str) -> None:
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None or not rec.worker_alive:
                return
            rec.stuck = True
            agent = self.registry.get(rec.agent_id) if rec.agent_id and self.registry.has(rec.agent_id) else None
            if agent is not None:
                agent.state.try_transition(AgentStatus.FAILED, "did not stop after cancel/timeout")
            log.warning("agent task %s: the agent did not stop within the grace period", task_id)

    @staticmethod
    def _tell_agent(agent: Agent | None, task_id: str) -> None:
        if agent is None:
            return
        try:
            agent.cancel(task_id)
        except Exception:  # noqa: BLE001 - a failing cancel hook must not break the orchestrator
            log.warning("agent %s: cancel hook failed", agent.id)

    def cancel(self, task_id: str, wait: float = 0.0) -> CancelReport:
        """PENDING: cancelled at once. RUNNING: cancellation is REQUESTED (the agent must support it) and the task turns CANCELLED when the
        agent really returns; with `wait` seconds the call waits for that. Terminal tasks are left alone."""
        with self._lock:
            rec = self._rec(task_id)
            if rec.status in TERMINAL:
                return CancelReport(task_id, False, rec.status, f"the task is already {rec.status.value}")
            if rec.status is TaskStatus.PENDING:
                self._finalize(rec, TaskStatus.CANCELLED, "cancelled before it started", None, None, "cancelled")
                self._dispatch()
                return CancelReport(task_id, True, rec.status, "cancelled before it started")
            agent = self.registry.get(rec.agent_id) if rec.agent_id and self.registry.has(rec.agent_id) else None
            if agent is None or not agent.supports_cancellation:
                return CancelReport(task_id, False, rec.status, "this agent does not support cancellation; the task keeps running until it ends or times out")
            first = not rec.cancel_requested
            rec.cancel_requested = True
            rec.cancel_event.set()
            if first:
                rec.grace_timer = self._scheduler.call_later(self.cancel_grace, lambda: self._on_grace(task_id))
        if first:
            self._tell_agent(agent, task_id)
        with self._cond:
            if wait > 0:
                self._cond.wait_for(lambda: rec.status in TERMINAL, timeout=wait)
            return CancelReport(task_id, True, rec.status, "cancellation requested" if rec.status is TaskStatus.RUNNING else f"task is {rec.status.value}")

    def wait(self, task_id: str, timeout: float | None = None) -> AgentResult:
        """Wait (without polling) until the task is terminal or `timeout` seconds passed; returns the current result either way."""
        with self._cond:
            rec = self._rec(task_id)
            self._cond.wait_for(lambda: rec.status in TERMINAL, timeout=timeout)
            return rec.result

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Wait (without polling) until no worker is executing any more - including work of tasks that already timed out."""
        with self._cond:
            return self._cond.wait_for(lambda: self._running == 0, timeout=timeout)

    def run(self, task: AgentTask, timeout: float | None = None) -> AgentResult:
        """submit + start + wait. Never waits forever: at most the task's timeout plus the cancel grace plus a margin (or `timeout`)."""
        result = self.submit(task)
        if result.is_terminal:
            return result
        self.start(task.task_id)
        limit = timeout if timeout is not None else (task.timeout or self.default_timeout) + self.cancel_grace + 5.0
        return self.wait(task.task_id, limit)

    # ---- agents -----------------------------------------------------------------------------------------------------------------------------
    def set_enabled(self, agent_id: str, enabled: bool) -> AgentStatus:
        with self._lock:
            agent = self.registry.get(agent_id)
            if enabled:
                if agent.status in (AgentStatus.DISABLED, AgentStatus.FAILED) and not any(r.worker_alive and r.agent_id == agent_id for r in self._records.values()):
                    agent.state.transition(AgentStatus.AVAILABLE, "enabled")
            elif agent.status is not AgentStatus.DISABLED:
                agent.state.transition(AgentStatus.DISABLED, "disabled by the user")
            self._dispatch()
            return agent.status

    def reset_agent(self, agent_id: str) -> AgentStatus:
        """FAILED -> AVAILABLE (only if no work of that agent is still running)."""
        agent = self.registry.get(agent_id)
        return self.set_enabled(agent_id, True) if agent.status is AgentStatus.FAILED else agent.status

    def shutdown(self, wait: float = 2.0) -> None:
        """Cancel everything that is open and release timers (program exit)."""
        for res in self.list():
            if not res.is_terminal:
                try:
                    self.cancel(res.task_id)
                except UnknownAgentError:
                    pass
        deadline_ids = [r.task.task_id for r in list(self._records.values()) if r.worker_alive]
        for tid in deadline_ids:
            self.wait(tid, wait)
        with self._lock:
            for rec in self._records.values():
                self._cancel_timers(rec)

    # ---- mirror into the Core's task manager (clear separation: AgentTask stays AgentTask) ---------------------------------------------------
    def _mirror_new(self, rec: _Rec) -> None:
        if self._task_manager is None:
            return
        try:
            core = Task(description=self._detector.redact(rec.task.objective).strip()[:300] or "agent task", priority=rec.task.priority,
                        required_agents=[rec.agent_id] if rec.agent_id else [])
            self._task_manager.add(core)
            rec.core_task = core
        except Exception:  # noqa: BLE001
            rec.core_task = None

    def _mirror_running(self, rec: _Rec) -> None:
        if rec.core_task is not None:
            try:
                rec.core_task.transition(CoreStatus.RUNNING)
            except Exception:  # noqa: BLE001
                pass

    def _mirror_final(self, rec: _Rec) -> None:
        core = rec.core_task
        if core is None:
            return
        try:
            s = rec.status
            if s is TaskStatus.SUCCEEDED:
                core.complete(rec.result.summary)
            elif s is TaskStatus.CANCELLED:
                core.transition(CoreStatus.CANCELLED)
            elif s in (TaskStatus.FAILED, TaskStatus.BLOCKED):
                core.fail(rec.result.error or s.value)
        except Exception:  # noqa: BLE001 - mirroring is informational
            pass
