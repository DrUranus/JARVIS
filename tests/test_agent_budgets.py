"""WP02b: Budgets je Agent (Zeit, Werkzeugaufrufe je Aufgabe und je Sitzung, Artefaktgroesse). Nur senkend gegenueber den globalen Grenzen, Standard AUS, fail-closed.
Fakes only: kein Netzwerk, keine echten Modelle, keine Preise."""
from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

from agents_util import make, task
from jarvis.agents import AgentOrchestrator, AgentRegistry, TaskStatus
from jarvis.agents.agent import Agent
from jarvis.agents.artifacts import make_artifact, to_dict
from jarvis.agent_budgets import AgentBudget, AgentBudgets, BudgetError
from jarvis.agents.fake import FakeAgent
from jarvis.agents.recovery import FailureKind, classify
from jarvis.agents.result import AgentOutcome
from jarvis.config import AgentsSettings, ConfigError, Settings, load_settings
from jarvis.redaction import SecretDetector
from jarvis.tools.base import ToolResult

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
DET = SecretDetector()


class FakeTools:
    """A tool registry stand-in: every tool exists and succeeds; counts the real executions."""

    def __init__(self):
        self.executed = 0
        self._lock = threading.Lock()

    def __contains__(self, name):
        return True

    def execute(self, name, **kw):
        with self._lock:
            self.executed += 1
        return ToolResult.ok("x")


def caller(agent_id="fake", n=10, tool="browser"):
    a = FakeAgent(agent_id, tool_names=frozenset({tool}), tool_calls=[(tool, {})] * n)
    return a


class Caller(Agent):
    """Makes `n` tool calls and reports how many were allowed; catches ToolAccessError like the real agents do."""
    capabilities = frozenset({"research.web"})
    tool_names = frozenset({"browser"})

    def __init__(self, agent_id, n):
        super().__init__()
        self.id, self.name, self.description, self.n, self.allowed = agent_id, agent_id, "caller", n, 0

    def perform(self, task, ctx):
        from jarvis.agents.errors import ToolAccessError
        for _ in range(self.n):
            try:
                ctx.tools.call("browser")
                self.allowed += 1
            except ToolAccessError as exc:
                return AgentOutcome.failed(str(exc), code="tool_access_denied")
        return AgentOutcome.ok("done", {"calls": self.allowed})


def orch_with(agent, budgets=None, *, tools=None, inline=True, audit=None, **kw):
    reg = AgentRegistry()
    reg.register(agent)
    from agents_util import FakeClock, InlineExecutor, ManualScheduler
    sched = ManualScheduler()
    o = AgentOrchestrator(reg, tools=tools or FakeTools(), clock=FakeClock(), scheduler=sched, executor=InlineExecutor() if inline else None,
                          agent_budgets=budgets, audit=audit, **kw)
    return o, sched


def budgets(*entries, **kw):
    return AgentBudgets.from_entries(entries, global_timeout=kw.get("t", 300.0), global_tool_calls=kw.get("c", 200))


# ---- model ---------------------------------------------------------------------------------------------------------------------------------------
def test_defaults_are_off_and_empty():
    s = AgentsSettings()
    assert s.agent_budgets_enabled is False and s.agent_budgets == ()
    assert Settings().agents == s or Settings().agents.agent_budgets == ()
    cfg = Path(__file__).resolve().parent.parent / "config" / "jarvis.toml"
    assert load_settings(cfg, env={}).agents.agent_budgets_enabled is False


def test_entries_parse_into_frozen_budgets():
    b = budgets("research;60;20;100;5000", "browser;;10;;")
    r = b.get("research")
    assert (r.max_seconds, r.max_tool_calls, r.max_calls_session, r.max_artifact_chars) == (60.0, 20, 100, 5000)
    assert b.get("browser").max_seconds is None and b.get("browser").max_tool_calls == 10 and b.get("files") is None
    with pytest.raises(Exception):
        r.max_seconds = 999


@pytest.mark.parametrize("entry", [
    "research;301;20;;", "research;0;20;;", "research;-1;;;", "research;nan;;;", "research;inf;;;", "research;abc;;;",           # zeit: nur senkend (<= 300), positiv, endlich
    "research;;201;;", "research;;0;;", "research;;1.5;;", "research;;x;;",                                                      # aufrufe je Aufgabe: <= 200
    "research;;;0;", "research;;;1000001;", "research;;;2.5;",                                                                     # aufrufe je Sitzung
    "research;;;;0", "research;;;;100001", "research;;;;x",                                                                        # artefaktgroesse
    "", ";60;;;", "Bad Id;60;;;", "research;60", "research;60;1;1;1;1", "research;;;;", "research",                               # form; ein Eintrag ganz ohne Grenze ist sinnlos -> abgelehnt
])
def test_invalid_or_raising_entries_are_refused(entry):
    with pytest.raises(BudgetError):
        budgets(entry)


def test_duplicate_agent_entries_are_refused():
    with pytest.raises(BudgetError):
        budgets("research;60;;;", "research;30;;;")


def test_limits_cannot_be_raised_after_the_fact():
    b = budgets("research;60;20;;")
    assert not hasattr(b, "set") and not hasattr(b, "raise_limit")
    with pytest.raises(TypeError):
        b._by_agent["x"] = 1                        # mappingproxy / frozen
    with pytest.raises(Exception):
        AgentBudget(max_seconds=1).max_seconds = 5


def test_config_validation_rejects_bad_entries_at_startup():
    for bad in (("research;999;;;",), ("research;;9999;;",), ("nonsense",)):
        s = Settings()
        from dataclasses import replace
        s = replace(s, agents=replace(s.agents, agent_budgets_enabled=True, agent_budgets=bad))
        with pytest.raises(ConfigError, match="agents"):
            s.validate()
    from dataclasses import replace
    ok = replace(Settings(), agents=replace(Settings().agents, agent_budgets_enabled=True, agent_budgets=("research;60;20;;",)))
    ok.validate()
    # more generous than the global task timeout is refused (only lowering is allowed)
    gl = replace(Settings(), agents=replace(Settings().agents, task_timeout_seconds=30.0, agent_budgets_enabled=True, agent_budgets=("research;60;;;",)))
    with pytest.raises(ConfigError):
        gl.validate()


# ---- orchestrator: off = unchanged ---------------------------------------------------------------------------------------------------------------
def test_without_budgets_nothing_changes():
    a = caller(n=5)
    o, _ = orch_with(a, None)
    res = o.run(task())
    assert res.status is TaskStatus.SUCCEEDED and o.tool_call_limit == 200


# ---- tool calls per task ---------------------------------------------------------------------------------------------------------------------------
def test_tool_call_budget_per_task_blocks_with_the_agent_budget_code_even_if_the_agent_catches_the_error():
    a = Caller("fake", 10)
    o, _ = orch_with(a, budgets("fake;;3;;"))
    res = o.run(task())
    assert a.allowed == 3 and res.status is TaskStatus.BLOCKED and res.error_code == "agent_budget_exceeded"
    assert "agent_budget_exceeded" in (res.summary + (res.error or ""))


def test_a_global_limit_stricter_than_the_agent_budget_still_wins():
    a = Caller("fake", 10)
    o, _ = orch_with(a, budgets("fake;;50;;"), tool_call_limit=2)
    res = o.run(task())
    assert a.allowed == 2 and res.error_code == "tool_access_denied"          # the global limit (2) is stricter: unchanged behaviour


def test_other_agents_are_not_affected():
    a, b = Caller("a", 6), Caller("b", 6)
    reg = AgentRegistry(); reg.register(a); reg.register(b)
    from agents_util import FakeClock, InlineExecutor, ManualScheduler
    o = AgentOrchestrator(reg, tools=FakeTools(), clock=FakeClock(), scheduler=ManualScheduler(), executor=InlineExecutor(), agent_budgets=budgets("a;;2;;"))
    ra, rb = o.run(task(agent_id="a")), o.run(task(agent_id="b"))
    assert ra.status is TaskStatus.BLOCKED and rb.status is TaskStatus.SUCCEEDED and b.allowed == 6


def test_blocked_agent_budget_is_never_retried_or_replanned():
    c = classify(TaskStatus.BLOCKED, "agent_budget_exceeded")
    assert c.kind is FailureKind.FATAL
    c = classify(TaskStatus.FAILED, "agent_budget_exceeded")
    assert c.kind is FailureKind.FATAL


# ---- session total across tasks, atomic under parallel load -------------------------------------------------------------------------------------------
def test_session_total_binds_across_tasks():
    a = Caller("fake", 4)
    o, _ = orch_with(a, budgets("fake;;;6;"))
    r1, r2 = o.run(task()), o.run(task())
    assert r1.status is TaskStatus.SUCCEEDED and r2.status is TaskStatus.BLOCKED and a.allowed == 6        # 4 + 2


def test_parallel_tasks_cannot_exceed_the_session_total():
    tools = FakeTools()
    a = Caller("fake", 10)
    o, _ = orch_with(a, budgets("fake;;;25;"), tools=tools, inline=False, max_concurrent=8)
    ids = []
    for _ in range(8):
        t = task()
        o.submit(t)
        ids.append(t.task_id)
    for i in ids:
        o.start(i)
    for i in ids:
        o.wait(i, timeout=10)
    assert tools.executed == 25 and a.allowed == 25
    assert sum(1 for i in ids if o.get(i).status is TaskStatus.BLOCKED) >= 5


def test_replanned_retry_tasks_share_the_same_session_total():
    a = Caller("fake", 3)
    o, _ = orch_with(a, budgets("fake;;;7;"))
    results = [o.run(task()) for _ in range(4)]
    assert [r.status for r in results] == [TaskStatus.SUCCEEDED, TaskStatus.SUCCEEDED, TaskStatus.BLOCKED, TaskStatus.BLOCKED] and a.allowed == 7


# ---- time ------------------------------------------------------------------------------------------------------------------------------------------
def test_time_budget_shortens_the_timer_and_blocks_with_the_budget_code():
    a = FakeAgent("fake", behavior="wait")
    o, sched = orch_with(a, budgets("fake;10;;;"), inline=False)
    t = task(); o.submit(t); o.start(t.task_id)
    sched.advance(10.5)
    res = o.get(t.task_id)
    assert res.status is TaskStatus.BLOCKED and res.error_code == "agent_budget_exceeded"
    a.release.set()


def test_a_shorter_task_timeout_stays_a_plain_timeout():
    a = FakeAgent("fake", behavior="wait")
    o, sched = orch_with(a, budgets("fake;60;;;"), inline=False)
    t = task(timeout=5.0); o.submit(t); o.start(t.task_id)
    sched.advance(6)
    res = o.get(t.task_id)
    assert res.status is TaskStatus.FAILED and res.error_code == "timeout"
    a.release.set()


def test_a_longer_task_timeout_is_cut_down_to_the_budget():
    a = FakeAgent("fake", behavior="wait")
    o, sched = orch_with(a, budgets("fake;10;;;"), inline=False)
    t = task(timeout=200.0); o.submit(t); o.start(t.task_id)
    sched.advance(11)
    assert o.get(t.task_id).error_code == "agent_budget_exceeded"
    a.release.set()


# ---- artifact size ---------------------------------------------------------------------------------------------------------------------------------
def test_artifact_size_budget_drops_oversized_artifacts_but_keeps_the_task():
    small = to_dict(make_artifact("text", "kurz", source_agent="fake", source_task="at-1234567890ab", detector=DET))
    big = to_dict(make_artifact("text", "x" * 400, source_agent="fake", source_task="at-1234567890ab", detector=DET))
    a = FakeAgent("fake", output={"rows": [1], "artifacts": [small, big]})
    a.produces = frozenset({"text"})
    o, _ = orch_with(a, budgets("fake;;;;100"), artifacts=True)
    res = o.run(task())
    assert res.status is TaskStatus.SUCCEEDED and [x["content"] for x in res.output["artifacts"]] == ["kurz"] and res.output["rows"] == [1]
    assert res.output["artifact_rejections"] == [{"index": 1, "code": "agent_budget_exceeded", "kind": "text"}]


def test_artifact_budget_does_nothing_with_artifacts_off():
    big = to_dict(make_artifact("text", "x" * 400, source_agent="fake", source_task="at-1234567890ab", detector=DET))
    out = {"artifacts": [big]}
    a = FakeAgent("fake", output=dict(out))
    o, _ = orch_with(a, budgets("fake;;;;100"))
    assert o.run(task()).output == out


# ---- audit (numbers only) ---------------------------------------------------------------------------------------------------------------------------
def test_budget_exhaustion_is_audited_once_per_agent_with_numbers_and_no_content():
    events = []
    a = Caller("fake", 10)
    o, _ = orch_with(a, budgets("fake;;3;;"), audit=events.append)
    secret = "sk-SECRET-OBJECTIVE-TEXT-123456"
    o.run(task(objective=secret)); o.run(task(objective=secret))
    assert len(events) == 1
    e = events[0]
    assert e["agent"] == "fake" and e["limit"] == "tool_calls" and isinstance(e["used"], int) and isinstance(e["max"], int)
    assert secret not in repr(e) and set(e) <= {"agent", "limit", "used", "max", "task_id", "reason"}


def test_a_failing_audit_sink_never_turns_a_block_into_a_run():
    def boom(_e):
        raise RuntimeError("sink down")
    a = Caller("fake", 10)
    o, _ = orch_with(a, budgets("fake;;3;;"), audit=boom)
    assert o.run(task()).status is TaskStatus.BLOCKED and a.allowed == 3


# ---- fail-closed -----------------------------------------------------------------------------------------------------------------------------------
def test_an_unreadable_budget_lookup_blocks_the_task_instead_of_running_it_unbudgeted():
    class Broken:
        def get(self, agent_id):
            raise RuntimeError("table unreadable")
        def session_calls(self, *_a):
            return 0
    a = Caller("fake", 3)
    o, _ = orch_with(a, Broken())
    res = o.run(task())
    assert res.status is TaskStatus.BLOCKED and res.error_code == "agent_budget_unavailable" and a.allowed == 0


def test_the_factory_refuses_a_budget_for_an_unknown_agent(tmp_path):
    from dataclasses import replace
    from jarvis.bootstrap import build_core
    s = Settings()
    s = replace(s, agents=replace(s.agents, enabled=True, agent_budgets_enabled=True, agent_budgets=("no_such_agent;10;;;",)))
    core = build_core(s)
    assert core.subsystems["agents"].status == "disabled" and core.subsystems["agents"].orchestrator is None


def test_enabled_without_entries_changes_nothing(tmp_path):
    from dataclasses import replace
    from jarvis.bootstrap import build_core
    s = Settings()
    s = replace(s, agents=replace(s.agents, enabled=True, agent_budgets_enabled=True, agent_budgets=()))
    core = build_core(s)
    assert core.subsystems["agents"].orchestrator is not None


# ---- no prices, no autonomy, layering ------------------------------------------------------------------------------------------------------------------
def test_the_budget_module_is_pure_and_knows_no_prices_or_llm_cost_model():
    text = (SRC / "agent_budgets.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any((m or "").startswith(("jarvis.permissions", "jarvis.llm", "jarvis.tools", "jarvis.bootstrap")) for m in imported), imported
    for word in ("price", "Decimal", "cost"):
        assert word not in text.replace("llm_cost", ""), word


def test_the_neutral_module_keeps_the_agent_policy_constants_in_sync():
    from jarvis import agent_budgets
    from jarvis.agents import policy as AP
    assert agent_budgets.MAX_ARTIFACT_CHARS_HARD == AP.MAX_INPUT_BYTES and agent_budgets.AGENT_ID_RE.pattern == AP.AGENT_ID_RE.pattern
    assert agent_budgets.AgentBudgets is AgentBudgets and agent_budgets.BudgetError is BudgetError


def test_the_neutral_module_imports_nothing_from_the_agent_layer():
    tree = ast.parse((SRC / "agent_budgets.py").read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any((m or "").startswith("jarvis.") and m not in ("jarvis.errors",) for m in mods), mods


def test_no_agent_module_reaches_the_permission_engines_session_budget_in_any_spelling():
    """The permission engine's SessionBudget is a different thing from the agent budgets; the agent layer must not touch it however an import is spelled."""
    for f in (SRC / "agents").rglob("*.py"):
        found = set()
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                found.add(base)
                found.update(f"{base}.{a.name}" for a in node.names)
        assert not any(m == "jarvis.permissions.budget" or m.startswith("jarvis.permissions.budget.") for m in found), f.name
