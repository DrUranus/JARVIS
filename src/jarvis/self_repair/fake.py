"""Test doubles for the self-repair layer: a scripted coding agent (no files, no processes) that lets the engine tests exercise success,
transient/permanent failure, permission denial, timeout, cancellation, crashes and unexpected file changes deterministically."""
from __future__ import annotations

import threading
from typing import Any

from jarvis.agents import policy as P
from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentOutcome
from jarvis.agents.state import TaskStatus
from jarvis.self_repair.engine import RepairCancelReport
from jarvis.self_repair.errors import UnknownRepairError
from jarvis.self_repair.models import RepairResult, RepairRun
from jarvis.self_repair.state import RepairStatus


def test_run(passed: bool, failures: tuple[str, ...] = (), stdout: str = "", summary: str = "", *, timed_out: bool = False) -> dict[str, Any]:
    """The `output` of a coding-tool `test` step."""
    return {"command": "pytest", "exit_code": 0 if passed else 1, "passed": passed, "timed_out": timed_out, "aborted": False, "duration": 0.01,
            "summary": summary or ("2 passed" if passed else f"{len(failures)} failed"), "failures": list(failures), "stdout": stdout, "stderr": ""}


test_run.__test__ = False  # type: ignore[attr-defined]


class FakeCodingAgent(Agent):
    """Behaves like the CodingAgent (id 'coding') towards the engine. `tests` is the queue of results for successive `test` steps.
    `script` holds one behaviour per perform() call (consumed in order, then 'ok'):
       ok | failure (FAILED step_failed) | permanent (FAILED invalid_input) | denied (BLOCKED permission_denied) | timeout (FAILED timeout) |
       crash (raises) | cancel (waits until cancelled) | hang (waits, ignores cancel)
    `extra_change`: a path that shows up in `changes` after a write although no plan named it. `noop_write`: writes change nothing."""
    id = "coding"
    name = "Fake coding agent"
    description = "scripted coding agent for tests"
    capabilities = frozenset({P.CODING_READ, P.CODING_WRITE, P.CODING_TEST})
    tool_names = frozenset()

    def __init__(self, tests: list[dict[str, Any]] | None = None, *, script: list[str] | None = None, extra_change: str | None = None,
                 noop_write: bool = False, jarvis_repo: bool = False) -> None:
        super().__init__()
        self.tests = list(tests or [])
        self.script = list(script or [])
        self.extra_change, self.noop_write, self.jarvis_repo = extra_change, noop_write, jarvis_repo
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancel_calls: list[str] = []
        self.tasks: list[AgentTask] = []
        self.actions: list[str] = []
        self.written: list[dict[str, Any]] = []
        self.changes: list[str] = []
        self.session = False
        self.hanging = False

    def cancel(self, task_id: str) -> None:
        self.cancel_calls.append(task_id)
        if not self.hanging:                      # a hanging agent ignores cancellation (it only ends when the test releases it)
            self.release.set()

    def perform(self, task: AgentTask, ctx: AgentContext) -> AgentOutcome:
        self.tasks.append(task)
        self.started.set()
        mode = self.script.pop(0) if self.script else "ok"
        if mode == "crash":
            raise RuntimeError("fake coding agent exploded with token=abc123456789")
        if mode == "failure":
            return AgentOutcome.failed("transient problem", code="step_failed")
        if mode == "permanent":
            return AgentOutcome.failed("invalid input", code="invalid_input")
        if mode == "denied":
            return AgentOutcome.blocked("step 1 was refused by the permission system", code="permission_denied")
        if mode == "timeout":
            return AgentOutcome.failed("timeout", code="timeout")
        if mode in ("cancel", "hang"):
            self.hanging = mode == "hang"
            self.release.wait()
            if mode == "cancel":
                return AgentOutcome.cancelled()
        results: list[dict[str, Any]] = []
        for i, step in enumerate(task.input.get("steps", []), 1):
            action = step.get("action")
            self.actions.append(action)
            out: Any = {}
            if action == "start":
                self.session = True
            elif action == "info":
                out = {"is_jarvis_workspace": self.jarvis_repo, "language": "Python"}
            elif action == "test":
                out = dict(self.tests.pop(0)) if self.tests else test_run(True)
                for k in ("stdout", "stderr"):             # the real ToolStepAgent clips every string of a step output to 4000 characters
                    out[k] = str(out.get(k, ""))[:4000]
            elif action == "write":
                self.written.append(dict(step))
                if not self.noop_write:
                    self.changes = [c for c in self.changes if not c.startswith(step["path"] + ":")] + [f"{step['path']}: modify +{len(self.written)}/-{len(self.written)}"]
                if self.extra_change:
                    self.changes = [c for c in self.changes if not c.startswith(self.extra_change + ":")] + [f"{self.extra_change}: modify +1/-0"]
            elif action == "changes":
                out = {"changes": list(self.changes)}
            elif action == "stop":
                self.session = False
            results.append({"step": i, "tool": "coding", "action": action, "ok": True, "output": out})
        return AgentOutcome.ok(f"{len(results)} step(s) done", {"steps": results})


class FakeRepairEngine:
    """Same surface as RepairEngine for Core/CLI tests; a run simply ends as scripted."""

    def __init__(self, final: RepairStatus = RepairStatus.SUCCEEDED) -> None:
        self.final = final
        self._runs: dict[str, RepairResult] = {}
        self.created: list[tuple[str, dict[str, Any]]] = []

    def create(self, objective: str, *, workspace: str, **kw: Any) -> RepairRun:
        run = RepairRun(objective, workspace)
        self._runs[run.run_id] = RepairResult(run)
        self.created.append((run.run_id, dict(kw)))
        return run

    def _rec(self, run_id: str) -> RepairResult:
        try:
            return self._runs[run_id]
        except KeyError:
            raise UnknownRepairError("unknown run") from None

    def run(self, run_id: str) -> RepairResult:
        r = self._rec(run_id)
        if r.run.is_terminal:
            return r
        run = r.run.with_status(RepairStatus.TESTING).with_status(self.final).evolve(final_summary="fake run finished", current_phase="done")
        self._runs[run_id] = RepairResult(run)
        return self._runs[run_id]

    def start(self, run_id: str) -> RepairRun:
        return FakeRepairEngine.run(self, run_id).run

    def wait(self, run_id: str, timeout: float | None = None) -> RepairResult:
        return self._rec(run_id)

    def cancel(self, run_id: str) -> RepairCancelReport:
        r = self._rec(run_id)
        if r.run.is_terminal:
            return RepairCancelReport(run_id, False, r.run.status, f"the run is already {r.run.status.value}")
        run = r.run.with_status(RepairStatus.CANCELLED)
        self._runs[run_id] = RepairResult(run)
        return RepairCancelReport(run_id, True, run.status, "cancelled")

    def get(self, run_id: str) -> RepairRun:
        return self._rec(run_id).run

    def attempts(self, run_id: str) -> tuple[Any, ...]:
        return self._rec(run_id).attempts

    def result(self, run_id: str) -> RepairResult:
        return self._rec(run_id)

    def list(self, status: RepairStatus | None = None, limit: int | None = None) -> list[RepairRun]:
        out = [r.run for r in reversed(list(self._runs.values())) if status is None or r.run.status is status]
        return out[:limit] if limit else out

    def describe(self) -> dict[str, Any]:
        return {"runs": len(self._runs), "active": 0, "max_active": 1}

    def shutdown(self, wait: float = 0.0) -> None:
        pass
