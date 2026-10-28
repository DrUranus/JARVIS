"""Phase 14, sub-goal 4: session budget (tool calls and run time over all goals and agents). Deterministic: fake clock, no sleeping, no network."""
import ast
import threading
from pathlib import Path

import pytest

from jarvis.config import ConfigError, load_settings
from jarvis.errors import PermissionDeniedError
from jarvis.interface.cli import run_command
from jarvis.permissions import AuditEventType, ConfirmationChoice, DecisionStatus, ScriptedConfirmation
from jarvis.permissions.budget import SessionBudget
from secutil import G, Y, make_engine, req

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
ROOT = SRC.parents[1]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def budget(calls=3, seconds=60.0, clock=None):
    return SessionBudget(max_calls=calls, max_seconds=seconds, clock=clock or Clock())


# ---- the budget itself ---------------------------------------------------------------------------------------------------------------------
def test_books_up_to_the_limit_then_refuses_without_consuming():
    b = budget(calls=2)
    assert b.book() is None and b.book() is None
    assert "2/2" in b.book() and "2/2" in b.book()
    assert b.usage()["calls"] == 2                                           # refused calls consumed nothing


def test_check_never_books():
    b = budget(calls=1)
    assert all(b.denial() is None for _ in range(10)) and b.usage()["calls"] == 0


def test_runtime_starts_with_the_first_booked_action_and_expires():
    clock = Clock()
    b = budget(calls=100, seconds=60, clock=clock)
    clock.t += 5000                                                          # idle time before the first action does not count
    assert b.denial() is None and b.book() is None
    clock.t += 59
    assert b.denial() is None
    clock.t += 2
    assert "run time" in b.denial() and "run time" in b.book() and b.usage()["calls"] == 1


def test_runtime_only_check_does_not_count_calls():
    b = budget(calls=1)
    b.book()
    assert b.time_denial() is None                                           # the booked call itself may still execute


def test_exhaustion_is_announced_exactly_once():
    b = budget(calls=1)
    b.book()
    b.book()
    assert b.take_exhaustion_notice() is True and b.take_exhaustion_notice() is False


def test_concurrency_never_books_more_than_the_limit():
    b = budget(calls=10)
    wins, barrier = [], threading.Barrier(50)

    def hit():
        barrier.wait()
        wins.append(b.book() is None)
    threads = [threading.Thread(target=hit) for _ in range(50)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert wins.count(True) == 10 and b.usage()["calls"] == 10


def test_invalid_limits_are_rejected():
    for kw in ({"max_calls": 0, "max_seconds": 1}, {"max_calls": 1, "max_seconds": 0}, {"max_calls": -1, "max_seconds": 1}):
        with pytest.raises(ValueError):
            SessionBudget(**kw)


def test_no_public_way_to_reset_or_raise_the_budget():
    b = budget()
    public = {n for n in dir(b) if not n.startswith("_")}
    assert public == {"book", "denial", "time_denial", "usage", "take_exhaustion_notice", "max_calls", "max_seconds"}
    with pytest.raises(AttributeError):
        b.max_calls = 10 ** 6


# ---- engine integration -----------------------------------------------------------------------------------------------------------------------
def test_green_calls_count_and_the_next_one_is_denied_with_the_budget_rule(tmp_path):
    engine, sink, _ = make_engine(tmp_path, budget=budget(calls=3))
    assert [engine.authorize(req()).allowed for _ in range(3)] == [True, True, True]
    d = engine.authorize(req())
    assert d.status is DecisionStatus.DENIED and d.matched_rule == "invariant:budget" and "3/3" in d.reason


def test_evaluate_is_a_dry_run_and_books_nothing(tmp_path):
    b = budget(calls=2)
    engine, _, _ = make_engine(tmp_path, budget=b)
    for _ in range(10):
        assert engine.evaluate(req()).allowed
    assert b.usage()["calls"] == 0


def test_denied_and_declined_calls_consume_nothing(tmp_path):
    b = budget(calls=2)
    engine, _, _ = make_engine(tmp_path, budget=b, confirmation=ScriptedConfirmation([ConfirmationChoice.DENY]))
    assert not engine.authorize(req(level=Y)).allowed                          # the user declined
    from secutil import R
    assert not engine.authorize(req(level=R)).allowed                          # RED never
    assert b.usage()["calls"] == 0


def test_exhaustion_is_audited_once(tmp_path):
    engine, sink, _ = make_engine(tmp_path, budget=budget(calls=1))
    for _ in range(5):
        engine.authorize(req())
    assert [e.type for e in sink.events].count(AuditEventType.BUDGET_EXHAUSTED) == 1


def test_emergency_stop_has_priority_over_the_budget(tmp_path):
    engine, _, _ = make_engine(tmp_path, budget=budget(calls=1))
    engine.authorize(req())
    engine.emergency.engage("t", "t")
    d = engine.authorize(req())
    assert "emergency stop" in d.reason and d.matched_rule != "invariant:budget"


def test_execution_scope_rechecks_the_runtime(tmp_path):
    clock = Clock()
    engine, _, _ = make_engine(tmp_path, budget=SessionBudget(max_calls=5, max_seconds=60, clock=clock))
    r = req()
    d = engine.authorize(r)
    clock.t += 61                                                              # the time ran out between approval and execution
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(r, d):
            pass


def test_last_booked_call_can_still_execute(tmp_path):
    engine, _, _ = make_engine(tmp_path, budget=budget(calls=1))
    r = req()
    d = engine.authorize(r)
    with engine.execution_scope(r, d):
        pass


def test_no_budget_means_no_limit_and_describe_reports_usage(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    assert engine.budget is None and all(engine.authorize(req()).allowed for _ in range(50))
    engine2, _, _ = make_engine(tmp_path, budget=budget(calls=4))
    engine2.authorize(req())
    assert engine2.describe()["budget"]["calls"] == 1 and engine2.describe()["budget"]["max_calls"] == 4


def test_the_engine_exposes_the_budget_read_only(tmp_path):
    engine, _, _ = make_engine(tmp_path, budget=budget())
    with pytest.raises(AttributeError):
        engine.budget = None


def test_no_tool_agent_or_goal_module_touches_the_budget():
    for pkg in ("tools", "agents", "goals", "self_repair", "self_improvement", "computer", "browser", "coding", "research", "business", "finance", "llm",
                "planning", "memory", "voice", "tasks", "core"):
        for f in (SRC / pkg).rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            hits = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("budget", "book", "_budget")]
            assert not hits, f"{pkg}/{f.name} touches the session budget"


# ---- configuration ----------------------------------------------------------------------------------------------------------------------
def test_budget_is_off_by_default_in_code_and_in_the_shipped_toml():
    assert load_settings(env={}).budget.enabled is False
    assert load_settings(str(ROOT / "config" / "jarvis.toml"), env={}).budget.enabled is False


@pytest.mark.parametrize("env", [{"JARVIS_BUDGET_MAX_TOOL_CALLS": "0"}, {"JARVIS_BUDGET_MAX_TOOL_CALLS": "100001"},
                                 {"JARVIS_BUDGET_MAX_RUNTIME_SECONDS": "0"}, {"JARVIS_BUDGET_MAX_RUNTIME_SECONDS": "86401"}])
def test_config_enforces_hard_limits(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


def test_unknown_budget_keys_are_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[budget]\nenabled = true\nmax_tool_calls_unlimited = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(str(p), env={})


def test_factory_builds_the_budget_only_when_enabled(tmp_path):
    from jarvis.permissions.factory import build_permission_engine
    base = {"JARVIS_WORKSPACE": str(tmp_path / "ws"), "JARVIS_LOG_DIR": str(tmp_path / "logs")}
    assert build_permission_engine(load_settings(env=base)).budget is None
    on = build_permission_engine(load_settings(env={**base, "JARVIS_BUDGET_ENABLED": "true", "JARVIS_BUDGET_MAX_TOOL_CALLS": "7",
                                                    "JARVIS_BUDGET_MAX_RUNTIME_SECONDS": "90"}))
    assert (on.budget.max_calls, on.budget.max_seconds) == (7, 90.0)


# ---- CLI ----------------------------------------------------------------------------------------------------------------------------------
def test_cli_budget_is_read_only(tmp_path):
    from test_emergency_stop import build_core
    core, engine, _ = build_core(tmp_path)
    assert "nicht aktiviert" in run_command(core, "/budget")
    (tmp_path / "b").mkdir()
    core2, engine2, _ = build_core(tmp_path / "b")
    engine2._budget = budget(calls=5)                                          # the test wires it in; production builds it in the factory
    engine2.authorize(req())
    out = run_command(core2, "/budget")
    assert "1/5" in out
    assert run_command(core2, "/budget reset").startswith("Verwendung")       # there is no way to reset or raise it
    assert engine2.budget.usage()["calls"] == 1
