"""V2.1 (Mission 8): reproducible micro-benchmarks of existing components. Read-only measurement: Fake agents, mock LLM, temporary files; no network, no real tools, nothing is changed.

Each case runs `--runs` times; reported are the median and the spread (min/max) of the wall time, plus the peak Python memory (tracemalloc) of ONE extra run - tracing slows the code, so
it is never mixed with the timing runs. Numbers describe THIS machine at THIS moment (see `environment` in the output); they are measurements, not targets, and say nothing about
the owner's PC.   python scripts/bench/v21_bench.py [--runs 5] [--scale 1.0] [--out reports/bench/v21.json]"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


def case_orchestrator(n: int) -> dict[str, Any]:
    from agents_util import FakeClock, InlineExecutor, ManualScheduler
    from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentTask
    from jarvis.agents.fake import FakeAgent
    reg = AgentRegistry()
    reg.register(FakeAgent("fake"))
    orch = AgentOrchestrator(reg, clock=FakeClock(), scheduler=ManualScheduler(), executor=InlineExecutor(), max_history=n + 10, max_queue=n + 10)
    for i in range(n):
        orch.run(AgentTask("bench", agent_id="fake", task_id=f"t{i}"))
    return {"tasks": n}


def case_orchestrator_threads(n: int) -> dict[str, Any]:
    from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentTask
    from jarvis.agents.fake import FakeAgent
    workers = 10
    reg = AgentRegistry()
    for w in range(workers):
        reg.register(FakeAgent(f"a{w}"))
    orch = AgentOrchestrator(reg, max_concurrent=workers, max_history=n + 10, max_queue=n + 10)
    ids = []
    for i in range(n):
        t = AgentTask("bench", agent_id=f"a{i % workers}", task_id=f"t{i}")
        orch.submit(t)
        ids.append(t.task_id)
    for i in ids:
        orch.start(i)
    for i in ids:
        orch.wait(i, timeout=60)
    orch.shutdown(wait=1.0)
    return {"tasks": n, "agents": workers, "peak_running": orch.peak_running}


def case_goals(n: int) -> dict[str, Any]:
    from agents_util import FakeAgent
    from goals_util import chain, rig
    engine, _orch, *_ = rig([FakeAgent("fake")], chain("s1", "s2", "s3"))
    for i in range(n):
        engine.run(engine.create(f"Ziel {i}").goal_id)
    return {"goals": n, "steps_per_goal": 4}


def case_journal(n: int) -> dict[str, Any]:
    from jarvis.journal.store import JournalStore
    with tempfile.TemporaryDirectory() as tmp:
        store = JournalStore(Path(tmp) / "j.db", max_entries=n + 10)
        for i in range(n):
            store.record("goal", f"g-{i:06d}", "RUNNING", "bench")
            store.record("goal", f"g-{i:06d}", "SUCCEEDED", "bench", result="ok")
        listed = len(store.list(limit=50))
        store.close()
    return {"entries": n, "writes": 2 * n, "listed": listed}


def case_memory(n: int) -> dict[str, Any]:
    from jarvis.memory.sqlite_store import SqliteMemoryStore
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteMemoryStore(Path(tmp) / "m.db")
        for i in range(n):
            store.add(f"Eintrag {i} zur Fahrzeugaufbereitung in Region {i % 17}")
        hits = sum(len(store.search(f"Region {i % 17}", limit=5)) for i in range(max(1, n // 10)))
        store.close()
    return {"adds": n, "searches": max(1, n // 10), "hits": hits}


def _release_log_files(tmp: str) -> None:
    import logging
    for logger in [logging.getLogger(), *(logging.getLogger(n) for n in list(logging.root.manager.loggerDict))]:
        for h in list(getattr(logger, "handlers", ())):
            if str(getattr(h, "baseFilename", "")).startswith(str(Path(tmp).resolve())) or str(getattr(h, "baseFilename", "")).startswith(tmp):
                logger.removeHandler(h)
                h.close()


def case_build_core(n: int) -> dict[str, Any]:
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    # Windows: der Kern haelt Log- und Datenbankdateien offen; ein Aufraeumfehler des Temp-Ordners ist kein Messfehler.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        env = {"JARVIS_WORKSPACE": str(Path(tmp) / "ws"), "JARVIS_LOG_DIR": str(Path(tmp) / "logs"), "JARVIS_MEMORY_PATH": str(Path(tmp) / "m.db"), "JARVIS_AGENTS_ENABLED": "true",
               "JARVIS_GOALS_ENABLED": "true"}
        (Path(tmp) / "ws").mkdir()
        for _ in range(n):
            core = build_core(load_settings(env=env))
            close = getattr(getattr(core, "memory", None), "close", None)
            if callable(close):
                close()
        _release_log_files(tmp)
    return {"starts": n, "note": "mock LLM, agents and goals on, everything else default (off)"}


CASES: dict[str, tuple[Callable[[int], dict[str, Any]], int]] = {
    "orchestrator_inline_tasks": (case_orchestrator, 500), "orchestrator_10_agents_threads": (case_orchestrator_threads, 200), "goal_engine_goals": (case_goals, 100),
    "journal_sqlite_writes": (case_journal, 200), "memory_sqlite_add_search": (case_memory, 200), "build_core_starts": (case_build_core, 5)}


def measure(fn: Callable[[int], dict[str, Any]], n: int, runs: int) -> dict[str, Any]:
    times, info = [], {}
    for _ in range(runs):
        t0 = time.perf_counter()
        info = fn(n)
        times.append(time.perf_counter() - t0)
    tracemalloc.start()
    fn(n)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    med = statistics.median(times)
    return {"n": n, "runs": runs, "median_s": round(med, 4), "min_s": round(min(times), 4), "max_s": round(max(times), 4), "per_item_ms": round(med / n * 1000, 4),
            "peak_python_mb": round(peak / 1e6, 2), "info": info}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    if not 1 <= a.runs <= 50 or not 0.001 <= a.scale <= 100:
        print("runs 1..50, scale 0.001..100", file=sys.stderr)
        return 2
    wanted = [c for c in a.only.split(",") if c] or list(CASES)
    result = {"environment": {"python": platform.python_version(), "platform": platform.platform(), "cpus": os.cpu_count(), "machine": platform.machine()},
              "conditions": {"runs": a.runs, "scale": a.scale, "timer": "time.perf_counter", "memory": "tracemalloc peak of one separate run", "agents": "FakeAgent", "llm": "mock"},
              "cases": {name: measure(CASES[name][0], max(1, int(CASES[name][1] * a.scale)), a.runs) for name in wanted if name in CASES}}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
