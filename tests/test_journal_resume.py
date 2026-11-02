"""Wiederaufnahme unterbrochener Aufgaben (Strang A3): nur auf ausdruecklichen Befehl, nichts startet von selbst.

Echte GoalEngine auf echtem Orchestrator mit FakeAgents, JournalStore in tmp_path, ohne Netzwerk."""
import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from goals_util import HookAgent, rig
from jarvis.goals.fake import StaticPlanner, step
from jarvis.journal import JournalStore
from jarvis.journal.resume import InterruptedTask, ResumeAwarePlanner, ResumeManager, ResumeResult
from jarvis.ui_contract.schema import ACTIVITY_ITEM

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def jstep(n, text, status="SUCCEEDED", side=False):
    return {"step_id": f"s{n}", "status": status, "text": text, "side_effect": side}


class Rig:
    def __init__(self, tmp_path, *, engaged=False, answer=True):
        self.store = JournalStore(tmp_path / "j.db")
        self.planner = None
        self.asked: list[str] = []
        self.engaged = engaged
        self.answer = answer

        def make(goal):
            return [step(goal, "s1", objective="lese Datei"), step(goal, "s2", deps=("s1",), objective="schreibe Datei"),
                    step(goal, "ev", None, deps=("s2",))]
        self.agent = HookAgent("fake")
        engine, self.orch, _, _, inner = rig([self.agent], make)
        self.inner = inner
        self.planner = ResumeAwarePlanner(inner)
        engine._planner = self.planner                      # der Planer, mit dem die Engine gebaut waere
        self.engine = engine

    def manager(self):
        def confirm(text):
            self.asked.append(text)
            return self.answer
        return ResumeManager(self.store, goals=self.engine, planner=self.planner, emergency=lambda: self.engaged, confirm=confirm)


def crash(store, ref="g-old", steps=None, status="RUNNING"):
    store.record("goal", ref, status, "mein Ziel", created_at=T0,
                 steps=steps if steps is not None else [jstep(1, "lese Datei"), jstep(2, "schreibe Datei", "PENDING", True)])


# ------------------------------------------------ Absturz mitten im Ziel
def test_crashed_goal_is_listed_as_interrupted_and_nothing_starts(tmp_path):
    r = Rig(tmp_path)
    crash(r.store)
    r.store.record("goal", "g-done", "SUCCEEDED", "fertig", steps=[jstep(1, "x")])
    mgr = r.manager()                                       # "Neustart": die Engine kennt das Ziel nicht
    pending = mgr.interrupted()
    assert [p.ref_id for p in pending] == ["g-old"] and isinstance(pending[0], InterruptedTask)
    assert pending[0].resumable and pending[0].done_steps == 1 and pending[0].open_steps == 1 and pending[0].needs_confirmation == 1
    assert r.engine.list() == [] and r.agent.calls == 0 and r.asked == []


def test_listing_twice_never_creates_goals_or_runs_agents(tmp_path):
    r = Rig(tmp_path)
    crash(r.store)
    mgr = r.manager()
    mgr.interrupted(); mgr.interrupted()
    assert r.engine.list() == [] and r.orch.list() == [] and r.agent.calls == 0


def test_live_goal_in_this_process_is_not_interrupted(tmp_path):
    r = Rig(tmp_path)
    g = r.engine.create("live", goal_id="g-live")
    r.store.record("goal", "g-live", "RUNNING", "live", steps=[jstep(1, "a", "RUNNING")])
    assert r.manager().interrupted() == []
    assert g.goal_id == "g-live"


def test_agent_tasks_are_listed_but_not_resumable(tmp_path):
    r = Rig(tmp_path)
    r.store.record("agent_task", "t1", "RUNNING", "agent")
    p = r.manager().interrupted()
    assert [(x.kind, x.resumable) for x in p] == [("agent_task", False)]
    res = r.manager().resume("t1", kind="agent_task")
    assert res.status == "REFUSED" and res.reason == "not_resumable" and r.engine.list() == []


def test_unknown_or_finished_entries_are_refused(tmp_path):
    r = Rig(tmp_path)
    r.store.record("goal", "g-done", "SUCCEEDED", "fertig", steps=[jstep(1, "x")])
    mgr = r.manager()
    assert mgr.resume("nope").reason == "unknown_task"
    assert mgr.resume("g-done").reason == "not_interrupted" and r.engine.list() == []


# ------------------------------------------------ erledigt / side_effect
def test_completed_steps_are_not_repeated_and_side_effect_needs_new_confirmation(tmp_path):
    r = Rig(tmp_path)
    crash(r.store)
    res = r.manager().resume("g-old")
    assert len(r.asked) == 1 and "schreibe Datei" in r.asked[0]            # nur der offene side_effect-Schritt wird gefragt
    assert res.status == "SUCCEEDED" and res.skipped_steps == 1 and res.confirmed_steps == 1
    ran = [s.objective for s in r.engine.steps(res.new_goal_id)]
    assert "lese Datei" not in ran and "schreibe Datei" in ran               # der erledigte Schritt kommt im neuen Plan nicht vor
    assert r.agent.calls == 1


def test_declined_side_effect_starts_nothing(tmp_path):
    r = Rig(tmp_path, answer=False)
    crash(r.store)
    res = r.manager().resume("g-old")
    assert res.status == "DECLINED" and res.new_goal_id is None
    assert r.engine.list() == [] and r.agent.calls == 0
    assert [p.ref_id for p in r.manager().interrupted()] == ["g-old"]       # bleibt unterbrochen und wiederaufnehmbar


def test_without_confirmation_callback_side_effects_are_denied(tmp_path):
    r = Rig(tmp_path)
    crash(r.store)
    mgr = ResumeManager(r.store, goals=r.engine, planner=r.planner, emergency=lambda: False)
    assert mgr.resume("g-old").status == "DECLINED" and r.agent.calls == 0


def test_confirmation_is_asked_again_on_every_resume(tmp_path):
    r = Rig(tmp_path, answer=False)
    crash(r.store)
    mgr = r.manager()
    mgr.resume("g-old"); mgr.resume("g-old")
    assert len(r.asked) == 2


def test_read_only_remainder_needs_no_confirmation(tmp_path):
    r = Rig(tmp_path)
    crash(r.store, steps=[jstep(1, "lese Datei", "PENDING", False)])
    res = r.manager().resume("g-old")
    assert r.asked == [] and res.status == "SUCCEEDED"


def test_resumed_entry_is_marked_and_not_offered_again(tmp_path):
    r = Rig(tmp_path)
    crash(r.store)
    mgr = r.manager()
    mgr.resume("g-old")
    assert r.store.get("goal", "g-old").status == "RESUMED" and mgr.interrupted() == []
    assert mgr.resume("g-old").reason == "not_interrupted"


def test_all_steps_done_means_nothing_to_resume(tmp_path):
    r = Rig(tmp_path)
    crash(r.store, steps=[jstep(1, "lese Datei"), jstep(2, "schreibe Datei", side=True)])
    res = r.manager().resume("g-old")
    assert res.status == "NOTHING_TO_DO" and r.engine.list() == [] and r.asked == []


# ------------------------------------------------ Notaus
def test_emergency_stop_blocks_resume_and_listing_still_works(tmp_path):
    r = Rig(tmp_path, engaged=True)
    crash(r.store)
    mgr = r.manager()
    assert [p.ref_id for p in mgr.interrupted()] == ["g-old"]
    res = mgr.resume("g-old")
    assert res.status == "BLOCKED" and res.reason == "emergency_stop"
    assert r.asked == [] and r.engine.list() == [] and r.agent.calls == 0
    assert r.store.get("goal", "g-old").status == "RUNNING"                  # unveraendert


def test_emergency_stop_during_confirmation_blocks_the_start(tmp_path):
    r = Rig(tmp_path)
    crash(r.store)

    def confirm(text):
        r.engaged = True                                                       # Notaus waehrend die Frage offen ist
        return True
    mgr = ResumeManager(r.store, goals=r.engine, planner=r.planner, emergency=lambda: r.engaged, confirm=confirm)
    res = mgr.resume("g-old")
    assert res.status == "BLOCKED" and r.engine.list() == [] and r.agent.calls == 0


def test_emergency_probe_failure_blocks(tmp_path):
    r = Rig(tmp_path)
    crash(r.store)

    def boom():
        raise RuntimeError("x")
    mgr = ResumeManager(r.store, goals=r.engine, planner=r.planner, emergency=boom, confirm=lambda t: True)
    assert mgr.resume("g-old").status == "BLOCKED" and r.agent.calls == 0


# ------------------------------------------------ Vertragsdaten
def test_result_is_an_activity_item_of_kind_resume(tmp_path):
    r = Rig(tmp_path)
    crash(r.store)
    item = r.manager().resume("g-old").to_activity()
    assert item["kind"] == "resume" and item["cancellable"] is False
    ACTIVITY_ITEM.check(item, "item")                                          # gueltig nach dem UI-Vertrag
    blocked = ResumeResult("g-x", "BLOCKED", reason="emergency_stop").to_activity()
    ACTIVITY_ITEM.check(blocked, "item")


# ------------------------------------------------ Struktur
def test_planner_keeps_evaluation_steps_and_unrelated_steps(tmp_path):
    inner = StaticPlanner(lambda g: [step(g, "a", objective="x"), step(g, "b", objective="y", deps=("a",)), step(g, "ev", None, deps=("b",))])
    p = ResumeAwarePlanner(inner)
    p.skip("g1", ["x"])
    from jarvis.goals.models import Goal
    g = Goal("o", goal_id="g1")
    steps = p.plan(g, None, 10)
    assert [s.step_id for s in steps] == ["b", "ev"] and steps[0].dependencies == ()
    again = p.plan(Goal("o", goal_id="g2"), None, 10)                          # andere Ziele bleiben unberuehrt
    assert [s.step_id for s in again] == ["a", "b", "ev"]


def test_resume_module_has_no_threads_timers_or_autostart():
    src = (ROOT / "src/jarvis/journal/resume.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"threading", "asyncio", "sched", "multiprocessing", "subprocess", "atexit", "concurrent", "signal"}
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"start", "submit", "cancel", "Thread", "Timer"}
    # __init__ ruft nie resume auf; Aufruf von resume() steht nur in der Klasse als Methode
    init = ast.parse((ROOT / "src/jarvis/journal/__init__.py").read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(init) if isinstance(n, ast.Call)]


def test_nothing_in_bootstrap_or_core_resumes_on_startup():
    for rel in ("src/jarvis/bootstrap.py", "src/jarvis/core/core.py", "src/jarvis/journal/factory.py", "src/jarvis/journal/recorder.py"):
        assert "ResumeManager" not in (ROOT / rel).read_text(encoding="utf-8"), rel
