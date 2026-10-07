"""Models, lifecycle, registry, planner, context/gateway and configuration of the multi-agent layer."""
import json
import threading

import pytest

from agents_util import FakeAgent, make, task
from jarvis.agents import (Agent, AgentContext, AgentOutcome, AgentPlanner, AgentRegistry, AgentResult, AgentState, AgentStatus, AgentTask,
                           DuplicateError, InvalidAgentError, InvalidTaskError, StateError, TaskCancelled, TaskStatus, ToolAccessError, ToolGateway,
                           UnknownAgentError, validate_agent)
from jarvis.agents import policy as P
from jarvis.agents.state import AGENT_TRANSITIONS, TASK_TRANSITIONS, TERMINAL, check_agent_transition, check_task_transition
from jarvis.config import AgentsSettings, load_settings
from jarvis.errors import ConfigError
from jarvis.tools import ToolRegistry, ToolResult


# ---- AgentTask -------------------------------------------------------------------------------------------------------------------------------
def test_task_defaults_and_unique_ids():
    a, b = AgentTask("read the page"), AgentTask("read the page")
    assert a.task_id != b.task_id and a.task_id.startswith("at-") and P.valid_id(a.task_id)
    assert (a.agent_id, a.priority, a.parent_task_id, a.dependencies, a.timeout, a.required_capabilities) == (None, 5, None, (), None, frozenset())
    assert len({AgentTask("x").task_id for _ in range(500)}) == 500


@pytest.mark.parametrize("bad", ["", " ", "a b", "-x", "x" * 65, "a/b", "a\nb", "ä", None, 5, "a;b"])
def test_invalid_task_ids(bad):
    with pytest.raises(InvalidTaskError):
        AgentTask("x", task_id=bad)


@pytest.mark.parametrize("good", ["a", "A1", "t-1", "task_2.3", "x" * 64])
def test_valid_task_ids(good):
    assert AgentTask("x", task_id=good).task_id == good


@pytest.mark.parametrize("kw", [dict(objective=""), dict(objective="  "), dict(objective="x" * 2001), dict(objective="a\x00b"), dict(objective=5),
                                dict(agent_id="Browser"), dict(agent_id="a b"), dict(agent_id=""), dict(priority=0), dict(priority=11), dict(priority=True),
                                dict(priority="5"), dict(timeout=0), dict(timeout=-1), dict(timeout=4000), dict(timeout=True), dict(timeout="5"),
                                dict(required_capabilities=frozenset({"browser"})), dict(required_capabilities=frozenset({"Browser.Read"})),
                                dict(required_capabilities=frozenset({5})), dict(dependencies=("a", "a")), dict(dependencies=("bad id",)),
                                dict(dependencies=tuple(f"d{i}" for i in range(11))), dict(parent_task_id="bad id"), dict(input=[1]),
                                dict(input={"a": object()}), dict(input={1: 2}), dict(input={"a": float("nan")}), dict(input={"a": {1, 2}}),
                                dict(input={"k": "v" * 200_000}), dict(metadata={"a": 1}), dict(metadata={f"k{i}": "v" for i in range(30)}),
                                dict(memory_query=""), dict(memory_query="x" * 300), dict(memory_query=5)])
def test_invalid_tasks_are_rejected(kw):
    base = dict(objective="do it")
    with pytest.raises(InvalidTaskError):
        AgentTask(**{**base, **kw})


def test_self_dependency_is_rejected():
    with pytest.raises(InvalidTaskError):
        AgentTask("x", task_id="t1", dependencies=("t1",))


def test_deep_nesting_is_rejected_and_inputs_are_copied():
    deep: dict = {}
    cur = deep
    for _ in range(12):
        cur["n"] = {}
        cur = cur["n"]
    with pytest.raises(InvalidTaskError):
        AgentTask("x", input=deep)
    src = {"steps": [{"a": 1}], "t": (1, 2)}
    t = AgentTask("x", input=src)
    src["steps"][0]["a"] = 99
    src["new"] = 1
    assert t.input == {"steps": [{"a": 1}], "t": [1, 2]}  # a private deep copy: later edits of the caller's data do not reach the task


def test_task_serialisation_and_repr_do_not_leak():
    t = AgentTask("open my bank at https://x.test password=hunter22abc", agent_id="browser", input={"text": "secret-typed-text"},
                  required_capabilities=frozenset({"browser.read"}), dependencies=("d1",), timeout=5, metadata={"k": "v"}, task_id="t1")
    d = t.to_dict()
    assert json.loads(json.dumps(d)) == d and d["task_id"] == "t1" and d["required_capabilities"] == ["browser.read"] and d["dependencies"] == ["d1"]
    d["input"]["text"] = "changed"
    assert t.input["text"] == "secret-typed-text"
    assert "hunter22abc" not in repr(t) and "secret-typed-text" not in repr(t) and "t1" in repr(t)


# ---- AgentOutcome / AgentResult ----------------------------------------------------------------------------------------------------------------
def test_outcome_rules_and_result_serialisation():
    ok = AgentOutcome.ok("done", {"a": [1, 2]})
    assert ok.status is TaskStatus.SUCCEEDED and ok.output == {"a": [1, 2]}
    assert AgentOutcome.failed("boom", code="x").error == "boom" and AgentOutcome.blocked("no").status is TaskStatus.BLOCKED
    assert AgentOutcome.cancelled().status is TaskStatus.CANCELLED
    for st in (TaskStatus.PENDING, TaskStatus.RUNNING, "OK", None):
        with pytest.raises(InvalidTaskError):
            AgentOutcome(st)
    with pytest.raises(InvalidTaskError):
        AgentOutcome.ok("x", {"f": lambda: 1})
    r = AgentResult("t1", "a", TaskStatus.FAILED, "sum secret=abc12345", {"o": 1}, "err secret=abc12345", "code")
    assert r.is_terminal and not r.succeeded and json.loads(json.dumps(r.to_dict()))["status"] == "FAILED"
    assert "abc12345" not in repr(r) and AgentResult("t", "a", TaskStatus.RUNNING).is_terminal is False
    assert {s.value for s in TaskStatus} == {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}


# ---- lifecycles ------------------------------------------------------------------------------------------------------------------------------------
A = AgentStatus


@pytest.mark.parametrize("old,new", [(A.AVAILABLE, A.BUSY), (A.BUSY, A.AVAILABLE), (A.BUSY, A.FAILED), (A.FAILED, A.AVAILABLE),
                                     (A.AVAILABLE, A.DISABLED), (A.DISABLED, A.AVAILABLE), (A.BUSY, A.DISABLED), (A.FAILED, A.DISABLED)])
def test_valid_agent_transitions(old, new):
    s = AgentState(old)
    s.transition(new, "why")
    assert s.status is new and s.reason == "why"


@pytest.mark.parametrize("old,new", [(A.AVAILABLE, A.FAILED), (A.AVAILABLE, A.AVAILABLE), (A.BUSY, A.BUSY), (A.DISABLED, A.BUSY), (A.DISABLED, A.FAILED),
                                     (A.FAILED, A.BUSY), (A.FAILED, A.FAILED), (A.DISABLED, A.DISABLED)])
def test_illegal_agent_transitions(old, new):
    s = AgentState(old)
    with pytest.raises(StateError):
        s.transition(new)
    assert s.status is old and s.try_transition(new) is False


def test_transition_tables_are_complete_and_terminal_states_are_final():
    assert set(AGENT_TRANSITIONS) == set(AgentStatus) and set(TASK_TRANSITIONS) == set(TaskStatus)
    assert all(not TASK_TRANSITIONS[t] for t in TERMINAL) and TERMINAL == {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
    for t in TERMINAL:
        for n in TaskStatus:
            with pytest.raises(StateError):
                check_task_transition(t, n)
    check_task_transition(TaskStatus.PENDING, TaskStatus.RUNNING)
    with pytest.raises(StateError):
        check_task_transition(TaskStatus.PENDING, TaskStatus.SUCCEEDED)  # a task cannot succeed without having run
    with pytest.raises(StateError):
        check_agent_transition(A.DISABLED, A.BUSY)


def test_claim_is_atomic_under_contention():
    s = AgentState()
    wins, barrier = [], threading.Barrier(8)

    def go():
        barrier.wait()
        wins.append(s.claim())

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert wins.count(True) == 1 and s.status is A.BUSY
    assert AgentState(A.DISABLED).claim() is False and AgentState(A.FAILED).claim() is False


# ---- registry ------------------------------------------------------------------------------------------------------------------------------------------
def test_registry_register_get_list_has_unregister():
    reg = AgentRegistry()
    a, b = FakeAgent("beta"), FakeAgent("alpha")
    assert reg.register(a) is a and reg.register(b) is b
    assert reg.has("alpha") and "beta" in reg and not reg.has("zeta") and len(reg) == 2
    assert [x.id for x in reg.list()] == ["alpha", "beta"] and reg.get("beta") is a
    assert reg.unregister("beta") is a and not reg.has("beta")
    for bad in ("beta", "", None, 5):
        with pytest.raises(UnknownAgentError):
            reg.get(bad)
    assert reg.has(None) is False and reg.has([]) is False
    with pytest.raises(UnknownAgentError):
        reg.unregister("beta")


def test_duplicate_and_invalid_agents_are_rejected():
    reg = AgentRegistry()
    reg.register(FakeAgent("a"))
    with pytest.raises(DuplicateError):
        reg.register(FakeAgent("a"))
    assert len(reg) == 1

    class Bare:
        id, name, description, capabilities, tool_names = "x", "x", "x", frozenset({"a.b"}), frozenset()

    class NoState(FakeAgent):
        def __init__(self):
            self.id, self.name, self.description = "ns", "n", "d"
            self.capabilities, self.tool_names = frozenset({"a.b"}), frozenset()

    for bad in (object(), None, "agent", Bare(), NoState(), FakeAgent("Bad Id"), FakeAgent("a" * 40), FakeAgent("x", capabilities=frozenset()),
                FakeAgent("y", capabilities=frozenset({"nodot"})), FakeAgent("z", capabilities=frozenset({"A.B"})), FakeAgent("w", tool_names=frozenset({5}))):
        with pytest.raises(InvalidAgentError):
            reg.register(bad)
    blank = FakeAgent("v")
    blank.name = " "
    with pytest.raises(InvalidAgentError):
        validate_agent(blank)
    assert len(reg) == 1


def test_agent_subclasses_must_implement_perform():
    class Incomplete(Agent):
        id = "inc"

    with pytest.raises(TypeError):
        Incomplete()


def test_busy_agents_cannot_be_unregistered_and_disabled_agents_are_excluded_from_find():
    reg = AgentRegistry()
    a, b = FakeAgent("a", {"x.one", "x.two"}), FakeAgent("b", {"x.one"})
    reg.register(a), reg.register(b)
    assert [x.id for x in reg.find(frozenset({"x.one"}))] == ["a", "b"] and [x.id for x in reg.find(frozenset({"x.one", "x.two"}))] == ["a"]
    assert reg.find(frozenset({"x.three"})) == []
    b.state.transition(A.DISABLED)
    assert [x.id for x in reg.find(frozenset({"x.one"}))] == ["a"] and [x.id for x in reg.find(frozenset({"x.one"}), include_unavailable=True)] == ["a", "b"]
    a.state.claim()
    with pytest.raises(StateError):
        reg.unregister("a")


def test_registries_are_independent_and_thread_safe():
    r1, r2 = AgentRegistry(), AgentRegistry()
    r1.register(FakeAgent("same")), r2.register(FakeAgent("same"))      # no hidden global state
    reg, errors, barrier = AgentRegistry(), [], threading.Barrier(12)

    def go(i):
        barrier.wait()
        try:
            reg.register(FakeAgent("shared"))
        except DuplicateError:
            errors.append(i)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(reg) == 1 and len(errors) == 11
    for _ in range(3):  # repeated registration/removal
        reg.unregister("shared")
        reg.register(FakeAgent("shared"))
    assert len(reg) == 1


# ---- planner ---------------------------------------------------------------------------------------------------------------------------------------------
def full_registry():
    reg = AgentRegistry()
    for i, caps in (("research", {P.RESEARCH_WEB}), ("browser", {P.BROWSER_READ, P.BROWSER_INTERACT}),
                    ("coding", {P.CODING_READ, P.CODING_WRITE, P.CODING_TEST, P.CODING_PLAN}), ("computer", {P.COMPUTER_SCREEN, P.COMPUTER_INPUT})):
        reg.register(FakeAgent(i, caps))
    return reg


@pytest.mark.parametrize("text,agent,caps", [
    ("Öffne die Webseite https://example.com", "browser", {P.BROWSER_READ, P.BROWSER_INTERACT}),   # navigating is an interaction (goto)
    ("Open the website example.com and read the opening hours", "browser", {P.BROWSER_READ, P.BROWSER_INTERACT}),
    ("Klicke im Browser auf den Link und fülle das Formular aus", "browser", {P.BROWSER_READ, P.BROWSER_INTERACT}),
    ("Ändere die Datei calc.py und führe die Tests aus", "coding", {P.CODING_READ, P.CODING_WRITE, P.CODING_TEST}),
    ("Führe die Tests dieses Projekts aus", "coding", {P.CODING_READ, P.CODING_TEST}),
    ("Analysiere den Code in src/main.py", "coding", {P.CODING_READ}),
    ("Fix the bug in the function parse() and run pytest", "coding", {P.CODING_READ, P.CODING_WRITE, P.CODING_TEST}),
    ("Klicke auf den Button im Fenster", "computer", {P.COMPUTER_SCREEN, P.COMPUTER_INPUT}),
    ("Mach einen Screenshot vom Bildschirm", "computer", {P.COMPUTER_SCREEN}),
    ("Tippe Hallo in Notepad", "computer", {P.COMPUTER_SCREEN, P.COMPUTER_INPUT}),
    ("Recherchiere Informationen über Solarzellen", "research", {P.RESEARCH_WEB}),
    ("Find out what the sources say about solar cells", "research", {P.RESEARCH_WEB})])
def test_planner_selects_the_suitable_agent(text, agent, caps):
    sel = AgentPlanner(full_registry()).select(text)
    assert sel.found and sel.agent_id == agent and sel.capabilities == frozenset(caps), (text, sel)
    assert sel.score >= 3 and sel.reason


@pytest.mark.parametrize("text", ["", "   ", "Hallo, wie geht es dir?", "Was ist die Hauptstadt von Frankreich?", "ok"])
def test_planner_finds_nothing_for_unrelated_text(text):
    sel = AgentPlanner(full_registry()).select(text)
    assert not sel.found and sel.agent_id is None and sel.reason


def test_planner_only_considers_usable_agents_and_required_capabilities():
    reg = full_registry()
    planner = AgentPlanner(reg)
    reg.get("browser").state.transition(A.DISABLED)
    sel = planner.select("Öffne die Webseite https://example.com")
    assert not sel.found
    reg.get("browser").state.transition(A.AVAILABLE)
    assert planner.select("Öffne die Webseite https://example.com").agent_id == "browser"
    assert not planner.select("Öffne die Webseite https://example.com", frozenset({P.CODING_WRITE})).found       # the browser cannot satisfy it
    assert planner.select("Mach das irgendwie", frozenset({P.RESEARCH_WEB})).agent_id == "research"             # pure capability match
    assert planner.select("Öffne die Webseite https://example.com", frozenset({P.BROWSER_INTERACT})).capabilities >= {P.BROWSER_INTERACT}
    assert not AgentPlanner(AgentRegistry()).select("Öffne die Webseite https://example.com").found


def test_planner_reports_ambiguity_instead_of_guessing():
    sel = AgentPlanner(full_registry()).select("Öffne die Webseite und ändere die Datei calc.py")
    assert sel.candidates and (sel.found or "ambiguous" in sel.reason)
    tie = AgentPlanner(full_registry()).select("Klicke auf die Webseite")  # browser keyword vs computer keyword
    assert tie.found or "ambiguous" in tie.reason


def test_the_planner_grants_nothing_it_only_names_capabilities():
    sel = AgentPlanner(full_registry()).select("Ändere die Datei x.py")
    assert isinstance(sel.capabilities, frozenset) and all(P.valid_capability(c) for c in sel.capabilities)


# ---- context and gateway ----------------------------------------------------------------------------------------------------------------------------------
class RecordingTool:
    name = "echo_tool"
    description = "d"
    parameters = ()
    permission = None


def real_registry():
    from secutil import make_engine
    from pathlib import Path
    import tempfile
    from jarvis.permissions import ConfirmationChoice, ScriptedConfirmation
    from jarvis.tools.builtin import EchoTool

    engine, sink, ws = make_engine(Path(tempfile.mkdtemp()), confirmation=ScriptedConfirmation([ConfirmationChoice.ALLOW_ONCE] * 10))
    reg = ToolRegistry(engine)
    reg.register(EchoTool())
    return reg


def test_gateway_forwards_only_declared_tools_and_never_bypass_arguments():
    ev = threading.Event()
    gw = ToolGateway(real_registry(), frozenset({"echo"}), ev, max_calls=3)
    assert gw.available("echo") and not gw.available("other") and gw.allowed_tools == frozenset({"echo"})
    res = gw.call("echo", text="hi")
    assert isinstance(res, ToolResult) and res.success and gw.calls == 1
    with pytest.raises(ToolAccessError):
        gw.call("filesystem", path="x")                         # not declared for this agent
    for bad in ("confirmed", "force", "bypass", "confirm", "skip_permissions", "unsafe", "grant", "approval"):
        with pytest.raises(ToolAccessError):
            gw.call("echo", text="x", **{bad: True})
    assert gw.call("echo", text="x").success and gw.call("echo", text="y").success
    with pytest.raises(ToolAccessError):
        gw.call("echo", text="over budget")                     # at most 3 calls per task
    ev.set()
    with pytest.raises(TaskCancelled):
        ToolGateway(real_registry(), frozenset({"echo"}), ev).call("echo", text="x")


def test_gateway_without_registry_or_tool_reports_instead_of_crashing():
    gw = ToolGateway(None, frozenset({"browser"}), threading.Event())
    assert not gw.available("browser") and gw.call("browser", action="status").success is False
    gw2 = ToolGateway(real_registry(), frozenset({"browser"}), threading.Event())
    res = gw2.call("browser", action="status")
    assert not res.success and "not available" in res.error


def test_context_is_explicit_isolated_and_cancellable():
    ev = threading.Event()
    ctx = AgentContext("t1", "obj secret=abc12345", {"a": 1}, frozenset({"x.y"}), ("memo",), {}, {"k": "v"}, None, ev)
    assert not ctx.is_cancelled() and "abc12345" not in repr(ctx) and ctx.relevant_memory == ("memo",)
    ctx.check_cancelled()
    ev.set()
    with pytest.raises(TaskCancelled):
        ctx.check_cancelled()
    fields = set(AgentContext.__dataclass_fields__)
    assert fields == {"task_id", "objective", "input", "allowed_capabilities", "relevant_memory", "parent_results", "metadata", "tools", "cancel_event"}
    assert not fields & {"core", "memory", "memory_store", "registry", "engine", "permissions", "controller", "provider", "settings"}


# ---- configuration ----------------------------------------------------------------------------------------------------------------------------------------
def test_defaults_are_safe_and_validation_works(tmp_path):
    a = load_settings(env={}).agents
    assert a == AgentsSettings() and a.enabled is False and a.max_concurrent == 3 and a.task_timeout_seconds == 300.0 and a.max_queue == 50
    f = tmp_path / "c.toml"
    f.write_text("[agents]\nenabled = true\nmax_concurrent = 2\ntask_timeout_seconds = 30\n", encoding="utf-8")
    b = load_settings(f, env={"JARVIS_AGENTS_MAX_QUEUE": "7"}).agents
    assert (b.enabled, b.max_concurrent, b.task_timeout_seconds, b.max_queue) == (True, 2, 30.0, 7)
    for bad in ("max_concurrent = 0", "max_concurrent = 99", "task_timeout_seconds = 0", "task_timeout_seconds = 99999", "max_queue = 0", "max_history = 0",
                "cancel_grace_seconds = -1", "tool_call_limit = 0", "max_output_chars = 5", "bogus = 1", "skip_permissions = true", "allow_shell = true"):
        f.write_text(f"[agents]\n{bad}\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_settings(f, env={})
