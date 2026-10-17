"""Central emergency stop (Phase 14, sub-goal 1): latch, stoppers, report honesty, reset, engine/core/tool/CLI integration. Fakes only - nothing real is stopped.

Platform-neutral: the same code runs on Windows and Linux; the real-process parts (a running test run, a started program) are NOT exercised here and
are listed as limits in docs/PHASE14_AUTONOMY.md."""
import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.core import JarvisCore, ResponseKind
from jarvis.errors import JarvisError, PermissionDeniedError
from jarvis.interface.cli import run_command
from jarvis.llm.mock import MockProvider
from jarvis.permissions import (AuditEventType, ConfirmationChoice, ConfirmationProvider, DenyAllConfirmation, EmergencyStop, ReportStatus,
                                ScriptedConfirmation, StopOutcome, StopResult)
from jarvis.tools.base import ToolResult
from jarvis.tools.registry import ToolRegistry
from secutil import G, make_engine, req, types

ONCE, SESSION, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.ALLOW_SESSION, ConfirmationChoice.DENY
SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"


def names(rep):
    return {c.name: c.outcome for c in rep.components}


# ---- the latch -------------------------------------------------------------------------------------------------------------------------------
def test_engage_is_immediate_idempotent_and_thread_safe():
    events = []
    em = EmergencyStop(on_event=lambda k, d: events.append(k))
    results, barrier = [], threading.Barrier(20)

    def hit():
        barrier.wait()
        results.append(em.engage("x", "t"))
    threads = [threading.Thread(target=hit) for _ in range(20)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert em.engaged and results.count(True) == 1 and results.count(False) == 19
    assert events == ["engage"]                           # audited once, not 20 times


def test_engage_never_waits_for_a_component():
    em = EmergencyStop()
    gate = threading.Event()
    em.register("stuck", lambda r: gate.wait(10))
    em.engage("first", "t")
    t = threading.Thread(target=lambda: em.run_stoppers(timeout=0.3), daemon=True)
    t.start()
    time.sleep(0.05)
    start = time.monotonic()
    assert em.engage("again", "t") is False and em.engaged
    assert time.monotonic() - start < 0.2                 # the latch is independent of a running stop
    t.join(3)
    gate.set()


# ---- stoppers and the report -----------------------------------------------------------------------------------------------------------------
def test_all_stopped_is_complete_and_says_what_it_does_not_do():
    em = EmergencyStop()
    em.register("a", lambda r: None)
    em.register("b", lambda r: StopResult(StopOutcome.NOTHING, "idle"))
    rep = em.trigger("test", "t")
    assert rep.status is ReportStatus.COMPLETE and rep.complete and names(rep) == {"a": StopOutcome.STOPPED, "b": StopOutcome.NOTHING}
    assert "weder rückgängig gemacht" in rep.summary()


def test_cooperative_components_are_reported_as_requested_not_stopped():
    em = EmergencyStop()
    em.register("a", lambda r: None)
    em.register("goals", lambda r: StopResult(StopOutcome.REQUESTED, "1 running"))
    rep = em.trigger("test", "t")
    assert rep.status is ReportStatus.REQUESTED and not rep.complete and "angefordert" in rep.summary()


def test_one_failing_stopper_makes_the_report_incomplete_and_does_not_block_the_others():
    em = EmergencyStop()
    ran = []
    em.register("bad", lambda r: 1 / 0)
    em.register("good", lambda r: ran.append("good"))
    rep = em.trigger("test", "t")
    assert ran == ["good"] and names(rep) == {"bad": StopOutcome.FAILED, "good": StopOutcome.STOPPED}
    assert rep.status is ReportStatus.INCOMPLETE and "UNVOLLSTÄNDIG" in rep.summary() and "ZeroDivisionError" in rep.summary()
    assert em.engaged                                     # a failed component never lifts or weakens the stop


def test_an_invalid_stopper_result_counts_as_failed():
    em = EmergencyStop()
    em.register("odd", lambda r: "stopped")
    assert names(em.trigger("t", "t"))["odd"] is StopOutcome.FAILED


def test_a_stuck_stopper_times_out_within_the_deadline_and_is_reported_unknown():
    em = EmergencyStop()
    gate = threading.Event()
    em.register("stuck", lambda r: gate.wait(10))
    em.register("fast", lambda r: None)
    start = time.monotonic()
    rep = em.trigger("t", "t", timeout=0.3)
    assert time.monotonic() - start < 2.0                 # bounded: never waits for the stuck component
    assert names(rep) == {"stuck": StopOutcome.TIMEOUT, "fast": StopOutcome.STOPPED} and rep.status is ReportStatus.INCOMPLETE
    assert "state is unknown" in rep.summary()
    # asking again does not pile up another thread behind the stuck one
    calls = []
    em.unregister("fast")
    rep2 = em.run_stoppers(timeout=0.2)
    assert names(rep2)["stuck"] is StopOutcome.TIMEOUT and "earlier stop attempt" in rep2.summary()
    gate.set()


def test_repeated_activation_retries_only_what_is_not_stopped():
    em = EmergencyStop()
    counts = {"ok": 0, "flaky": 0}
    state = {"fail": True}

    def ok(r):
        counts["ok"] += 1

    def flaky(r):
        counts["flaky"] += 1
        if state["fail"]:
            raise OSError("not yet")
    em.register("ok", ok)
    em.register("flaky", flaky)
    assert em.trigger("t", "t").status is ReportStatus.INCOMPLETE
    state["fail"] = False
    rep = em.trigger("t", "t")
    assert rep.status is ReportStatus.COMPLETE and counts == {"ok": 1, "flaky": 2}


def test_a_component_registered_after_activation_is_stopped_on_the_next_run():
    em = EmergencyStop()
    em.trigger("t", "t")
    em.register("late", lambda r: None)
    assert names(em.run_stoppers())["late"] is StopOutcome.STOPPED


def test_a_second_concurrent_run_returns_the_partial_report_at_once():
    em = EmergencyStop()
    gate = threading.Event()
    em.register("slow", lambda r: gate.wait(5))
    em.engage("t", "t")
    first = threading.Thread(target=lambda: em.run_stoppers(timeout=2), daemon=True)
    first.start()
    time.sleep(0.1)
    rep = em.run_stoppers(timeout=2)
    assert rep.in_progress and rep.status is ReportStatus.INCOMPLETE
    gate.set()
    first.join(3)


def test_a_stop_report_that_outlives_a_reset_is_dropped():
    """Race found by the flaky GUI test: the slow stopper run finished AFTER the reset and told the listeners 'engaged' again."""
    em = EmergencyStop()
    gate = threading.Event()
    seen = []
    em.add_listener(lambda engaged, rep: seen.append(engaged))
    em.register("slow", lambda r: gate.wait(5))
    em.engage("t", "t")
    run = threading.Thread(target=lambda: em.run_stoppers(timeout=4), daemon=True)
    run.start()
    time.sleep(0.1)
    assert em.reset(lambda: True).ok
    gate.set()
    run.join(5)
    assert seen == [True, False] and not em.engaged and em.report().components == ()


def test_run_stoppers_without_an_engaged_stop_does_nothing():
    em = EmergencyStop()
    called = []
    em.register("a", lambda r: called.append(1))
    em.run_stoppers()
    assert called == [] and not em.engaged


def test_a_broken_audit_hook_never_prevents_the_stop():
    em = EmergencyStop(on_event=lambda k, d: 1 / 0)
    em.register("a", lambda r: None)
    assert em.trigger("t", "t").complete and em.engaged


# ---- reset -------------------------------------------------------------------------------------------------------------------------------------------
def test_reset_needs_an_authoriser_that_says_yes():
    em = EmergencyStop()
    em.engage("t", "t")
    assert not em.reset(lambda: False).ok and em.engaged
    assert not em.reset(lambda: 1 / 0).ok and em.engaged         # an authoriser that crashes is a "no"
    assert em.reset(lambda: True).ok and not em.engaged


def test_reset_when_not_engaged_does_nothing():
    asked = []
    assert not EmergencyStop().reset(lambda: asked.append(1) or True).ok and asked == []


def test_a_new_request_or_a_new_trigger_never_resets():
    em = EmergencyStop()
    em.trigger("t", "t")
    for _ in range(3):
        em.trigger("t2", "t")
        em.run_stoppers()
    assert em.engaged


def test_reset_resumes_stopped_components_and_lists_the_ones_that_cannot_be_resumed():
    em = EmergencyStop()
    resumed = []
    em.register("a", lambda r: None, resumer=lambda: resumed.append("a"))
    em.register("b", lambda r: None, resumer=lambda: 1 / 0)
    em.register("idle", lambda r: StopResult(StopOutcome.NOTHING), resumer=lambda: resumed.append("idle"))
    em.trigger("t", "t")
    res = em.reset(lambda: True)
    assert res.ok and resumed == ["a"] and any("b: could not be resumed" in p for p in res.problems) and not em.engaged


def test_listeners_see_engage_report_and_reset_and_a_broken_listener_is_harmless():
    em = EmergencyStop()
    seen = []
    em.add_listener(lambda engaged, rep: seen.append((engaged, rep.status.value if rep else None)))
    em.add_listener(lambda e, r: 1 / 0)
    em.register("a", lambda r: None)
    em.trigger("t", "t")
    em.reset(lambda: True)
    assert seen == [(True, "incomplete"), (True, "complete"), (False, None)]      # engage (in progress) -> final report -> reset


# ---- the permission engine ------------------------------------------------------------------------------------------------------------------------
def test_while_engaged_every_request_is_denied_even_green_and_audited(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    assert engine.authorize(req()).allowed
    engine.emergency.engage("test", "t")
    d = engine.authorize(req())
    assert d.denied and "emergency stop active" in d.reason and not engine.evaluate(req()).allowed
    assert "emergency_stop" in types(sink) and types(sink)[-1] == "permission_denied"
    assert engine.describe()["emergency_stop"] == {"engaged": True, "reason": "test"}


def test_an_approval_issued_just_before_the_stop_can_not_be_executed(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    r = req()
    d = engine.authorize(r)
    assert d.allowed
    engine.emergency.engage("late", "t")
    with pytest.raises(PermissionDeniedError, match="emergency stop active"):
        with engine.execution_scope(r, d):
            pytest.fail("must not run")


def test_reset_through_the_engine_asks_the_user_and_accepts_only_allow_once(tmp_path):
    for answer, ok in ((ONCE, True), (SESSION, False), (NO, False)):
        prompts = ScriptedConfirmation([answer])
        engine, sink, _ = make_engine(tmp_path, confirmation=prompts)
        engine.emergency.engage("t", "t")
        assert engine.reset_emergency_stop("test").ok is ok and engine.emergency.engaged is (not ok)
        (asked,) = prompts.requests
        assert asked.tool == "jarvis" and asked.action == "emergency_reset" and asked.session_allowed is False


def test_reset_is_impossible_without_a_human_channel(tmp_path):
    for provider in (None, DenyAllConfirmation()):
        engine, _, _ = make_engine(tmp_path, confirmation=provider)
        engine.emergency.engage("t", "t")
        res = engine.reset_emergency_stop("test")
        assert not res.ok and engine.emergency.engaged
    class Boom(ConfirmationProvider):
        def confirm(self, request):
            raise RuntimeError("dialog crashed")
    engine, _, _ = make_engine(tmp_path, confirmation=Boom())
    engine.emergency.engage("t", "t")
    assert not engine.reset_emergency_stop("test").ok and engine.emergency.engaged


def test_reset_is_audited(tmp_path):
    engine, sink, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE]))
    engine.emergency.engage("t", "t")
    engine.reset_emergency_stop("test")
    details = [e.detail for e in sink.events if e.type is AuditEventType.EMERGENCY_STOP]
    assert [d.split(":")[0] for d in details] == ["engage", "reset_requested", "reset_ok"]


def test_the_engine_stays_stopped_when_the_audit_log_is_broken(tmp_path):
    from jarvis.permissions import PermissionEngine
    from jarvis.permissions.audit import AuditSink

    class Broken(AuditSink):
        def record(self, event):
            raise OSError("disk full")
    engine = PermissionEngine(audit=Broken())
    assert engine.emergency.trigger("t", "t").complete and engine.emergency.engaged and engine.authorize(req()).denied


# ---- tools, core, CLI -----------------------------------------------------------------------------------------------------------------------------
def build_core(tmp_path, confirmation=None):
    engine, sink, _ = make_engine(tmp_path, confirmation=confirmation)
    registry = ToolRegistry(engine)
    from jarvis.tools.builtin import register_builtin_tools
    register_builtin_tools(registry, include_demo=True)
    return JarvisCore(MockProvider(), tools=registry), engine, sink


def test_tool_calls_fail_while_engaged_and_work_again_after_an_authorised_reset(tmp_path):
    core, engine, _ = build_core(tmp_path, ScriptedConfirmation([ONCE]))
    assert core.tools.execute("echo", text="hi").success
    engine.emergency.engage("t", "t")
    res = core.tools.execute("echo", text="hi")
    assert not res.success and "emergency stop active" in res.error
    assert engine.reset_emergency_stop("t").ok
    assert core.tools.execute("echo", text="hi").success


def test_core_refuses_new_work_while_engaged_and_a_new_request_does_not_reset(tmp_path):
    core, engine, _ = build_core(tmp_path)
    assert core.handle("hallo").ok
    engine.emergency.engage("t", "t")
    for text in ("hallo", "erstelle einen plan für x", "/notaus"):
        r = core.handle(text)
        assert r.kind is ResponseKind.ERROR and r.error == "emergency_stop" and "Notaus aktiv" in r.text
    for call in (lambda: core.create_goal("x"), lambda: core.run_goal("x"), lambda: core.create_repair("x"), lambda: core.run_repair("x")):
        with pytest.raises(JarvisError, match="Notaus aktiv"):
            call()
    assert core.emergency_stopped and engine.emergency.engaged


def test_cli_notaus_engages_reports_and_resets_only_with_confirmation(tmp_path):
    core, engine, _ = build_core(tmp_path, ScriptedConfirmation([NO, ONCE]))
    engine.emergency.register("fake", lambda r: StopResult(StopOutcome.REQUESTED, "cooperative"))
    assert run_command(core, "/notaus status") == "Notaus nicht aktiv."
    out = run_command(core, "/notaus")
    assert "NOTAUS aktiv" in out and "fake: requested" in out and engine.emergency.engaged
    assert "NOTAUS aktiv" in run_command(core, "/notaus status")
    assert "stays engaged" in run_command(core, "/notaus reset") and engine.emergency.engaged      # answered NO
    assert "was reset" in run_command(core, "/notaus reset") and not engine.emergency.engaged      # answered ONCE
    assert "Verwendung" in run_command(core, "/notaus quatsch")


# ---- component wiring (bootstrap) ---------------------------------------------------------------------------------------------------------------
class FakeSub:
    def __init__(self, available=True, raises=False):
        self.available, self.raises, self.halted, self.resumed = available, raises, [], 0

    def halt(self, reason="x"):
        if self.raises:
            raise RuntimeError("controller broke")
        self.halted.append(reason)
        return True

    def resume(self):
        self.resumed += 1
        return True


class Rep:
    def __init__(self, accepted, status):
        self.accepted, self.status, self.message = accepted, status, "msg"


class FakeEngine:
    """list()/cancel() like the goal engine, agent orchestrator and repair engine."""
    def __init__(self, items, cancel):
        self.items, self._cancel, self.cancelled = items, cancel, []

    def list(self):
        return [SimpleNamespace(goal_id=i, task_id=i, run_id=i, status=s) for i, s in self.items]

    def cancel(self, ident):
        self.cancelled.append(ident)
        return self._cancel(ident)


def wired_core(tmp_path, **subs):
    from jarvis.bootstrap import register_emergency_components
    core, engine, sink = build_core(tmp_path)
    core.subsystems.update(subs)
    register_emergency_components(core)
    return core, engine


def test_wiring_halts_the_controllers_and_a_reset_resumes_them(tmp_path):
    comp, br, cod = FakeSub(), FakeSub(available=False), FakeSub()
    core, engine = wired_core(tmp_path, computer=comp, browser=br, coding=cod)
    rep = engine.emergency.trigger("t", "t")
    assert names(rep)["computer"] is StopOutcome.STOPPED and names(rep)["browser"] is StopOutcome.NOTHING and names(rep)["coding"] is StopOutcome.STOPPED
    assert comp.halted == ["Notaus: t"] and br.halted == [] and "weder rückgängig gemacht" in rep.summary()
    engine.set_confirmation_provider(ScriptedConfirmation([ONCE]))
    assert engine.reset_emergency_stop("t").ok and comp.resumed == 1 and cod.resumed == 1


def test_wiring_a_controller_that_breaks_is_an_incomplete_stop(tmp_path):
    core, engine = wired_core(tmp_path, computer=FakeSub(raises=True), coding=FakeSub())
    rep = engine.emergency.trigger("t", "t")
    assert names(rep)["computer"] is StopOutcome.FAILED and names(rep)["coding"] is StopOutcome.STOPPED and rep.status is ReportStatus.INCOMPLETE


def test_wiring_cancels_non_terminal_work_and_is_honest_about_what_only_got_a_request(tmp_path):
    from jarvis.agents.state import TaskStatus
    from jarvis.goals.state import GoalStatus
    pend, run = GoalStatus.PENDING, GoalStatus.RUNNING
    goals = SimpleNamespace(engine=FakeEngine([("g1", pend), ("g2", run), ("g3", GoalStatus.SUCCEEDED)],
                                              lambda i: Rep(True, GoalStatus.CANCELLED if i == "g1" else GoalStatus.RUNNING)))
    core, engine = wired_core(tmp_path, goals=goals)
    rep = engine.emergency.trigger("t", "t")
    assert names(rep)["goals"] is StopOutcome.REQUESTED and goals.engine.cancelled == ["g1", "g2"]      # the finished goal is left alone
    agents = SimpleNamespace(orchestrator=FakeEngine([("t1", TaskStatus.RUNNING)], lambda i: Rep(False, TaskStatus.RUNNING)))
    core, engine = wired_core(tmp_path, agents=agents)
    rep = engine.emergency.trigger("t", "t")
    assert names(rep)["agents"] is StopOutcome.FAILED and rep.status is ReportStatus.INCOMPLETE and "could NOT be cancelled" in rep.summary()


def test_wiring_with_nothing_running_or_disabled_subsystems_reports_nothing_to_stop(tmp_path):
    from jarvis.goals.state import GoalStatus
    goals = SimpleNamespace(engine=FakeEngine([("g", GoalStatus.SUCCEEDED)], lambda i: Rep(False, GoalStatus.SUCCEEDED)))
    off = SimpleNamespace(engine=None)
    core, engine = wired_core(tmp_path, goals=goals, self_repair=off)
    rep = engine.emergency.trigger("t", "t")
    assert names(rep)["goals"] is StopOutcome.NOTHING and names(rep)["self_repair"] is StopOutcome.NOTHING and goals.engine.cancelled == []


def test_wiring_a_real_build_core_registers_the_components(tmp_path):
    from jarvis.bootstrap import build_core as real_build
    from jarvis.config import load_settings
    core = real_build(load_settings(env={"JARVIS_WORKSPACE": str(tmp_path / "ws"), "JARVIS_LOG_DIR": str(tmp_path / "logs"),
                                         "JARVIS_MEMORY_PATH": str(tmp_path / "m.db")}))
    (tmp_path / "ws").mkdir(exist_ok=True)
    assert {"computer", "browser", "coding", "goals", "agents", "self_repair"} <= set(core.permissions.emergency.names())
    rep = core.permissions.emergency.trigger("test", "t")
    assert rep.complete and all(c.outcome is StopOutcome.NOTHING for c in rep.components)          # everything is off by default -> nothing to stop
    assert core.handle("hallo").error == "emergency_stop"


# ---- structure: who may stop and who may reset ---------------------------------------------------------------------------------------------
def attribute_users(name):
    out = []
    for f in SRC.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Attribute) and n.attr == name for n in ast.walk(tree)) or any(isinstance(n, ast.FunctionDef) and n.name == name for n in ast.walk(tree)):
            out.append(f.relative_to(SRC).as_posix())
    return sorted(out)


def test_only_the_user_interfaces_and_the_engine_can_lift_the_emergency_stop():
    assert attribute_users("reset_emergency_stop") == ["interface/cli.py", "interface/gui_model.py", "permissions/engine.py"]
    assert attribute_users("reset") and "tools/registry.py" not in attribute_users("reset_emergency_stop")


def test_no_tool_agent_or_goal_module_can_engage_or_reset_the_emergency_stop():
    forbidden = ("emergency", "reset_emergency_stop")
    for pkg in ("tools", "agents", "goals", "self_repair", "self_improvement", "computer", "browser", "coding", "research", "business", "finance", "llm", "planning"):
        for f in (SRC / pkg).rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            hits = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in forbidden]
            assert not hits, f"{pkg}/{f.name} touches the emergency stop"
