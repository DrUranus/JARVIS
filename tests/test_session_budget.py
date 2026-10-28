"""Phase 14, Teilziel 4: Gesamtbudget pro Sitzung (Tool-Aufrufe und Laufzeit ueber alle Ziele und Agenten).

Deterministisch mit Fake-Uhr; keine echten Wartezeiten, kein Netzwerk, keine Plattformabhaengigkeit."""
import ast
import threading
from pathlib import Path

import pytest

from jarvis.config import BudgetSettings, Settings, load_settings
from jarvis.core import JarvisCore
from jarvis.errors import ConfigError, PermissionDeniedError
from jarvis.interface.cli import run_command
from jarvis.llm.mock import MockProvider
from jarvis.permissions import AuditEventType, ConfirmationChoice, ScriptedConfirmation
from jarvis.permissions.budget import SessionBudget
from jarvis.permissions.factory import build_permission_engine
from jarvis.tools.registry import ToolRegistry
from secutil import G, Y, make_engine, req, types

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def engine_with(tmp_path, calls=3, seconds=60.0, **kw):
    clock = FakeClock()
    budget = SessionBudget(calls, seconds, clock)
    engine, sink, ws = make_engine(tmp_path, budget=budget, **kw)
    return engine, budget, clock, sink


# ---- SessionBudget selbst ------------------------------------------------------------------------------------------------------------------
def test_budget_books_up_to_the_limit_and_refuses_after():
    b = SessionBudget(2, 60.0, FakeClock())
    assert b.refusal() is None and b.try_book() is None and b.try_book() is None
    reason = b.try_book()
    assert reason and "2/2" in reason and b.usage().calls == 2          # the refused call consumed nothing
    assert b.refusal() == reason


def test_refusal_and_usage_book_nothing():
    b = SessionBudget(5, 60.0, FakeClock())
    for _ in range(10):
        b.refusal()
        b.usage()
    assert b.usage().calls == 0 and not b.usage().started


def test_runtime_starts_with_the_first_booked_action_not_before():
    clock = FakeClock()
    b = SessionBudget(10, 30.0, clock)
    clock.advance(10_000)                          # waiting before the first action costs nothing
    assert b.refusal() is None and b.usage().elapsed == 0.0
    b.try_book()
    clock.advance(29.9)
    assert b.refusal() is None
    clock.advance(0.1)
    reason = b.refusal()
    assert reason and "30" in reason and b.try_book() == reason and b.usage().calls == 1


def test_runtime_overrun_is_reported_for_a_running_scope_only_when_exceeded():
    clock = FakeClock()
    b = SessionBudget(1, 30.0, clock)
    assert b.try_book() is None and b.refusal()                     # last call booked: next one is refused ...
    assert b.overrun() is None                                      # ... but the booked one may still run
    clock.advance(31)
    assert b.overrun()


def test_exhaustion_is_reported_exactly_once():
    b = SessionBudget(1, 60.0, FakeClock())
    assert not b.claim_report()                                    # nothing exhausted yet
    b.try_book()
    b.try_book()
    assert b.claim_report() and not b.claim_report()


@pytest.mark.parametrize("calls,seconds", [(0, 10.0), (-1, 10.0), (1, 0.0), (1, -5.0)])
def test_budget_rejects_nonsense_limits(calls, seconds):
    with pytest.raises(ValueError):
        SessionBudget(calls, seconds, FakeClock())


def test_concurrent_bookings_never_exceed_the_limit():
    b = SessionBudget(50, 60.0, FakeClock())
    ok, barrier = [], threading.Barrier(16)

    def work():
        barrier.wait()
        for _ in range(20):
            ok.append(b.try_book() is None)

    threads = [threading.Thread(target=work) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(ok) == 50 and b.usage().calls == 50 and len(ok) == 320


# ---- Engine: Pruefung nach dem Notaus, Buchung bei der Genehmigung ------------------------------------------------------------------------
def test_green_calls_count_and_the_next_one_is_denied_with_a_clear_message(tmp_path):
    engine, budget, _, sink = engine_with(tmp_path, calls=3)
    assert [engine.authorize(req()).allowed for _ in range(3)] == [True, True, True]
    d = engine.authorize(req())
    assert d.denied and d.matched_rule == "invariant:budget" and "3/3" in d.reason and "Sitzungsbudget" in d.reason
    assert budget.usage().calls == 3 and types(sink).count("budget_exhausted") == 1


def test_denied_calls_consume_nothing(tmp_path):
    engine, budget, _, _ = engine_with(tmp_path, calls=2)
    assert not engine.authorize(req(level=Y, action="write")).allowed           # no provider: YELLOW is not granted
    assert budget.usage().calls == 0
    assert engine.authorize(req(action="read", level=G)).allowed and budget.usage().calls == 1


def test_confirmation_declined_consumes_nothing_and_confirmed_consumes_one(tmp_path):
    engine, budget, _, _ = engine_with(tmp_path, calls=5, confirmation=ScriptedConfirmation([ConfirmationChoice.DENY, ConfirmationChoice.ALLOW_ONCE]))
    assert engine.authorize(req(action="delete", level=Y)).denied and budget.usage().calls == 0
    assert engine.authorize(req(action="delete", level=Y)).allowed and budget.usage().calls == 1


def test_evaluate_books_nothing_but_reports_the_exhausted_budget(tmp_path):
    engine, budget, _, _ = engine_with(tmp_path, calls=1)
    for _ in range(5):
        assert engine.evaluate(req()).allowed
    assert budget.usage().calls == 0
    assert engine.authorize(req()).allowed
    assert engine.evaluate(req()).matched_rule == "invariant:budget"


def test_runtime_limit_denies_further_actions_without_cancelling_anything(tmp_path):
    engine, budget, clock, _ = engine_with(tmp_path, calls=100, seconds=60.0)
    assert engine.authorize(req()).allowed
    clock.advance(61)
    d = engine.authorize(req())
    assert d.denied and d.matched_rule == "invariant:budget" and "60" in d.reason


def test_execution_scope_rechecks_the_runtime_but_lets_a_booked_last_call_run(tmp_path):
    engine, budget, clock, _ = engine_with(tmp_path, calls=1, seconds=60.0)
    r = req()
    d = engine.authorize(r)
    assert d.allowed and budget.refusal()                           # the last call is booked, the budget is full
    with engine.execution_scope(r, d):
        pass                                                         # still runs: it was booked before
    r2 = req()
    engine2, budget2, clock2, sink2 = engine_with(tmp_path, calls=5, seconds=60.0)
    d2 = engine2.authorize(r2)
    clock2.advance(61)                                               # approved, but the time ran out before it started
    with pytest.raises(PermissionDeniedError, match="budget"):
        with engine2.execution_scope(r2, d2):
            raise AssertionError("must not run")
    assert "security_error" in types(sink2)


def test_emergency_stop_has_precedence_and_the_exhaustion_is_not_reported_meanwhile(tmp_path):
    engine, budget, _, sink = engine_with(tmp_path, calls=1)
    engine.authorize(req())
    engine.emergency.engage("test", "t")
    d = engine.authorize(req())
    assert d.denied and "emergency stop active" in d.reason and d.matched_rule != "invariant:budget"
    assert "budget_exhausted" not in types(sink)


def test_budget_denial_beats_confirmation_and_session_grants(tmp_path):
    engine, budget, _, _ = engine_with(tmp_path, calls=1, confirmation=ScriptedConfirmation([ConfirmationChoice.ALLOW_SESSION] * 3))
    assert engine.authorize(req(action="delete", level=Y)).allowed
    d = engine.authorize(req(action="delete", level=Y))            # a session grant exists, the budget still says no
    assert d.denied and d.matched_rule == "invariant:budget"


def test_no_budget_means_unchanged_behaviour(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    assert engine.budget is None and all(engine.authorize(req()).allowed for _ in range(200))
    assert engine.describe()["budget"] is None


def test_describe_shows_usage_read_only(tmp_path):
    engine, budget, _, _ = engine_with(tmp_path, calls=4)
    engine.authorize(req())
    info = engine.describe()["budget"]
    assert info["calls"] == 1 and info["max_calls"] == 4 and info["exhausted"] is False


def test_engine_budget_property_is_read_only(tmp_path):
    engine, *_ = engine_with(tmp_path)
    with pytest.raises(AttributeError):
        engine.budget = None


def test_concurrent_authorizations_never_grant_more_than_the_limit(tmp_path):
    engine, budget, _, _ = engine_with(tmp_path, calls=25)
    granted, barrier = [], threading.Barrier(8)

    def work():
        barrier.wait()
        for _ in range(10):
            granted.append(engine.authorize(req()).allowed)

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(granted) == 25 and budget.usage().calls == 25


def test_registry_calls_from_all_callers_share_one_budget(tmp_path):
    from jarvis.tools.builtin import register_builtin_tools
    engine, budget, _, _ = engine_with(tmp_path, calls=2)
    reg = register_builtin_tools(ToolRegistry(permissions=engine))
    results = [reg.execute("echo", text="x").success for _ in range(4)]
    assert results == [True, True, False, False]


# ---- Konfiguration -----------------------------------------------------------------------------------------------------------------------
def test_budget_is_off_by_default_in_code_and_in_the_shipped_toml():
    assert Settings().budget.enabled is False
    assert load_settings("config/jarvis.toml", env={}).budget.enabled is False
    assert build_permission_engine(Settings()).budget is None


def test_enabled_budget_is_built_into_the_engine(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[budget]\nenabled = true\nmax_tool_calls = 7\nmax_runtime_seconds = 90\n', encoding="utf-8")
    engine = build_permission_engine(load_settings(p, env={}))
    assert engine.budget is not None and engine.budget.max_tool_calls == 7 and engine.budget.max_runtime_seconds == 90


@pytest.mark.parametrize("kv", ["max_tool_calls = 0", "max_tool_calls = 100001", "max_runtime_seconds = 0", "max_runtime_seconds = 86401", "max_tool_calls = -3"])
def test_budget_limits_outside_the_hard_limits_are_rejected(tmp_path, kv):
    p = tmp_path / "c.toml"
    p.write_text(f"[budget]\nenabled = true\n{kv}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(p, env={})


def test_budget_hard_limits_are_accepted_at_the_boundary(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[budget]\nenabled = true\nmax_tool_calls = 100000\nmax_runtime_seconds = 86400\n", encoding="utf-8")
    assert load_settings(p, env={}).budget.max_tool_calls == 100_000


def test_unknown_budget_keys_are_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[budget]\nunlimited = true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown config key"):
        load_settings(p, env={})


def test_shipped_toml_defaults_are_within_the_hard_limits():
    b = load_settings("config/jarvis.toml", env={}).budget
    assert isinstance(b, BudgetSettings) and 1 <= b.max_tool_calls <= 100_000 and 0 < b.max_runtime_seconds <= 86_400


# ---- Strukturtest: nur die Engine und die Oberflaechen beruehren das Budget -------------------------------------------------------------
def test_no_tool_agent_or_goal_module_can_touch_the_budget():
    for pkg in ("tools", "agents", "goals", "self_repair", "self_improvement", "computer", "browser", "coding", "research", "business", "finance", "llm", "planning"):
        for f in (SRC / pkg).rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            hits = [n for n in ast.walk(tree) if (isinstance(n, ast.Attribute) and n.attr in ("budget", "try_book")) or (isinstance(n, ast.ImportFrom) and (n.module or "").endswith("budget"))]
            assert not hits, f"{pkg}/{f.name} touches the session budget"


def test_the_budget_has_no_reset_or_raise_api():
    public = {n for n in dir(SessionBudget) if not n.startswith("_")}
    assert not {n for n in public if any(w in n for w in ("reset", "raise", "extend", "increase", "set_", "clear", "grant"))}
    for p in ("max_tool_calls", "max_runtime_seconds"):
        with pytest.raises(AttributeError):
            setattr(SessionBudget(1, 1.0, FakeClock()), p, 99)


def test_only_the_engine_books_and_only_the_factory_builds_the_budget():
    users = sorted(f.relative_to(SRC).as_posix() for f in SRC.rglob("*.py")
                   if any(isinstance(n, ast.Attribute) and n.attr == "try_book" for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))))
    assert users == ["permissions/engine.py"]


# ---- CLI: /budget nur lesend ---------------------------------------------------------------------------------------------------------------
def build_core(tmp_path, budget):
    engine, *_ = make_engine(tmp_path, budget=budget)
    return JarvisCore(provider=MockProvider(), tools=ToolRegistry(permissions=engine)), engine


def test_cli_budget_shows_usage_and_changes_nothing(tmp_path):
    clock = FakeClock()
    core, engine = build_core(tmp_path, SessionBudget(5, 60.0, clock))
    engine.authorize(req())
    out = run_command(core, "/budget")
    assert "1/5" in out and "60" in out
    for arg in ("reset", "5000", "set 99", "off"):
        run_command(core, "/budget " + arg)
    assert engine.budget.usage().calls == 1 and engine.budget.max_tool_calls == 5


def test_cli_budget_without_a_budget_says_so(tmp_path):
    core, _ = build_core(tmp_path, None)
    assert "kein" in run_command(core, "/budget").lower()


def test_audit_event_type_exists():
    assert AuditEventType.BUDGET_EXHAUSTED.value == "budget_exhausted"
