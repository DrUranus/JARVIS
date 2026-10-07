"""Building blocks for the self-repair tests: a real RepairEngine on a real AgentOrchestrator with the scripted FakeCodingAgent."""
from __future__ import annotations

from typing import Any

from agents_util import FakeClock, InlineExecutor, ManualScheduler, wait_event  # noqa: F401
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry
from jarvis.self_repair import RepairEngine
from jarvis.self_repair.fake import FakeCodingAgent, test_run  # noqa: F401

FAIL = ("tests/test_calc.py::test_add",)
FAIL_OUT = "E   AssertionError: assert -1 == 5\ncalc.py:2: AssertionError\nFAILED tests/test_calc.py::test_add - AssertionError\n"
EDIT = {"path": "calc.py", "mode": "replace", "old_text": "a - b", "new_text": "a + b"}


def failing(out: str = FAIL_OUT):
    return test_run(False, FAIL, out)


def rig(agent: FakeCodingAgent | None = None, *, inline: bool = True, orch_kw: dict | None = None, **engine_kw: Any):
    """-> (engine, orchestrator, agent, scheduler)."""
    agent = agent or FakeCodingAgent()
    reg = AgentRegistry()
    reg.register(agent)
    sched = ManualScheduler()
    kw = dict(orch_kw or {})
    kw.setdefault("clock", FakeClock())
    orch = AgentOrchestrator(reg, scheduler=sched, executor=InlineExecutor() if inline else None, **kw)
    engine_kw.setdefault("cancel_wait", 0.3)
    return RepairEngine(orch, AgentPlanner(reg), **engine_kw), orch, agent, sched


def candidates(*edits_each):
    return [{"edits": [dict(e) for e in (es if isinstance(es, list) else [es])]} for es in edits_each]
