"""Building blocks for the goal tests: a real GoalEngine on a real AgentOrchestrator with FakeAgents (no tools, no providers)."""
from __future__ import annotations

import threading
from typing import Any

from agents_util import FakeAgent, FakeClock, InlineExecutor, ManualScheduler, wait_event  # noqa: F401
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry
from jarvis.goals import GoalEngine
from jarvis.goals.fake import StaticPlanner, step  # noqa: F401


def rig(agents: list[FakeAgent] | None = None, make=None, *, inline: bool = True, blocked_reason: str | None = None, orch_kw: dict | None = None,
        **engine_kw: Any):
    """-> (engine, orchestrator, registry, scheduler, planner). `make(goal)` returns the plan (see StaticPlanner)."""
    reg = AgentRegistry()
    for a in agents if agents is not None else [FakeAgent("fake")]:
        reg.register(a)
    sched = ManualScheduler()
    kw = dict(orch_kw or {})
    kw.setdefault("clock", FakeClock())
    orch = AgentOrchestrator(reg, scheduler=sched, executor=InlineExecutor() if inline else None, **kw)
    planner = StaticPlanner(make, blocked_reason=blocked_reason)
    engine_kw.setdefault("cancel_wait", 0.3)
    return GoalEngine(orch, planner, **engine_kw), orch, reg, sched, planner


def chain(*sids: str, agent: str = "fake", attempts: int = 1):
    """A plan factory: a linear chain s1 -> s2 -> ... of fake-agent steps followed by an evaluation step."""
    def make(goal):
        out, prev = [], ()
        for sid in sids:
            out.append(step(goal, sid, agent, deps=prev, attempts=attempts))
            prev = (sid,)
        out.append(step(goal, "ev", None, deps=prev))
        return out
    return make


def started_in_thread(fn, *a) -> threading.Thread:
    t = threading.Thread(target=fn, args=a, daemon=True)
    t.start()
    return t


class HookAgent(FakeAgent):
    """A FakeAgent that runs `hook(call_number)` at the start of every perform() - to change the world while a step runs."""

    def __init__(self, *a: Any, hook=None, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.hook, self.calls = hook, 0

    def perform(self, task, ctx):
        self.calls += 1
        if self.hook:
            self.hook(self.calls)
        return super().perform(task, ctx)


class MonoClock:
    """Engine clock under test control."""

    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t
