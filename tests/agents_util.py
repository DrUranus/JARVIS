"""Deterministic building blocks for the agent tests: no wall-clock sleeps, no random timing."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentTask, TaskStatus
from jarvis.agents.fake import ConcurrencyProbe, FakeAgent

WAIT = 10.0  # upper bound for waiting on an event (a failure mode, never a synchronisation delay)


class FakeClock:
    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


class _Handle:
    def __init__(self, sched: "ManualScheduler", due: float, fn: Callable[[], None]) -> None:
        self.sched, self.due, self.fn, self.cancelled = sched, due, fn, False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler:
    """Timers fire only when the test calls advance(): timeouts without waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.handles: list[_Handle] = []

    def call_later(self, delay: float, fn: Callable[[], None]) -> _Handle:
        h = _Handle(self, self.now + delay, fn)
        self.handles.append(h)
        return h

    def pending(self) -> int:
        return sum(1 for h in self.handles if not h.cancelled and h.due >= self.now)

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for h in sorted(self.handles, key=lambda h: h.due):
            if not h.cancelled and h.due <= self.now:
                h.cancelled = True
                h.fn()


class InlineExecutor:
    """Runs the worker immediately on the calling thread: the whole orchestration becomes sequential and reproducible."""

    def submit(self, fn: Callable[[], None], name: str) -> None:
        fn()


class RecordingExecutor:
    """Collects workers; the test decides when (and on which thread) they run."""

    def __init__(self) -> None:
        self.jobs: list[Callable[[], None]] = []

    def submit(self, fn: Callable[[], None], name: str) -> None:
        self.jobs.append(fn)

    def run_next(self) -> None:
        self.jobs.pop(0)()


def make(agents: list[FakeAgent] | None = None, *, inline: bool = True, **kw: Any):
    reg = AgentRegistry()
    for a in agents if agents is not None else [FakeAgent("fake")]:
        reg.register(a)
    sched = ManualScheduler()
    kw.setdefault("clock", FakeClock())
    orch = AgentOrchestrator(reg, scheduler=sched, executor=InlineExecutor() if inline else None, **kw)
    return orch, reg, sched


def task(objective: str = "do it", agent_id: str | None = "fake", **kw: Any) -> AgentTask:
    return AgentTask(objective, agent_id=agent_id, **kw)


def wait_event(ev: threading.Event) -> None:
    assert ev.wait(WAIT), "timed out waiting for an event (deadlock?)"


__all__ = ["FakeClock", "ManualScheduler", "InlineExecutor", "RecordingExecutor", "make", "task", "wait_event", "ConcurrencyProbe", "FakeAgent",
           "TaskStatus"]


# ---- a real engine + real tool registry with the three existing subsystems on fake providers ---------------------------------------------------------------
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

ONCE_NO = None


@dataclass
class ToolRig:
    engine: Any
    sink: Any
    ws: Path
    prompts: Any
    registry: Any
    browser_provider: Any
    browser: Any
    coding_provider: Any
    coding: Any
    fb: Any
    computer: Any
    project: Path

    def agents(self, **kw: Any):
        from jarvis.agents.adapters import BrowserAgent, CodingAgent, ComputerAgent, ResearchAgent
        reg = AgentRegistry()
        for a in (ResearchAgent(), BrowserAgent(), CodingAgent(interrupt=lambda: self.coding.halt("agent task cancelled")), ComputerAgent()):
            reg.register(a)
        kw.setdefault("clock", FakeClock())
        kw.setdefault("scheduler", ManualScheduler())
        kw.setdefault("executor", InlineExecutor())
        return AgentOrchestrator(reg, tools=self.registry, **kw), reg

    def audit_blob(self) -> str:
        import json
        return json.dumps([e.to_dict() for e in self.sink.events])


def tool_rig(tmp_path: Path, answers=(), *, coding_provider: Any = None) -> ToolRig:
    import os

    from browser_util import make_web
    from coding_util import CALC, PYPROJECT, TEST_CALC
    from jarvis.browser import BrowserController
    from jarvis.browser.policy import baseline_rules as browser_rules
    from jarvis.browser.providers.fake import FakeBrowserProvider
    from jarvis.browser.tools import register_browser_tools
    from jarvis.coding import CodingController
    from jarvis.coding.policy import baseline_rules as coding_rules
    from jarvis.coding.providers.fake import FakeCodingProvider
    from jarvis.coding.tools import register_coding_tools
    from jarvis.computer import ComputerController
    from jarvis.computer.policy import baseline_rules as computer_rules
    from jarvis.computer.providers.fake import FakeBackend
    from jarvis.computer.tools import register_computer_tools
    from jarvis.config import BrowserSettings, CodingSettings, ComputerSettings
    from jarvis.permissions import Policy, ScriptedConfirmation
    from jarvis.tools import ToolRegistry
    from secutil import make_engine

    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = ScriptedConfirmation(answers)
    engine, sink, ws = make_engine(tmp_path, confirmation=prompts)
    ws = Path(os.path.realpath(ws))
    bs, cs, ps = BrowserSettings(enabled=True, provider="fake", headless=True), CodingSettings(enabled=True, provider="fake"), \
        ComputerSettings(enabled=True, backend="fake", use_default_apps=False, action_delay=0.0)
    bprov = FakeBrowserProvider(make_web())
    browser = BrowserController(bprov, bs)
    project = ws / "proj"
    cprov = coding_provider or FakeCodingProvider()
    cprov.dirs.update({str(ws), str(project)}) if hasattr(cprov, "dirs") else None
    for rel, text in {"pyproject.toml": PYPROJECT, "calc.py": CALC, "tests/test_calc.py": TEST_CALC}.items():
        cprov.put(str(project / rel), text)
    coding = CodingController(cprov, cs, workspace_roots=(str(ws),))
    fb = FakeBackend()
    fb.add_window("Untitled - Notepad", "notepad.exe", left=0, top=0, width=40, height=30, active=True)
    computer = ComputerController(fb.bundle(), ps, sleep=lambda s: None, own_pids=())
    engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(browser_rules(bs)) + tuple(coding_rules(cs)) + tuple(computer_rules(ps))))
    registry = ToolRegistry(engine)
    register_browser_tools(registry, browser)
    register_coding_tools(registry, coding)
    register_computer_tools(registry, computer)
    return ToolRig(engine, sink, ws, prompts, registry, bprov, browser, cprov, coding, fb, computer, project)
