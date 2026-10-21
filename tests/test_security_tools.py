"""ToolRegistry integration: no protected action without the permission layer; bypass attempts must fail."""
import ast
import sys
import threading
from pathlib import Path

import pytest

from jarvis.errors import PermissionDeniedError, ToolError
from jarvis.permissions import (ActionSpec, ConfirmationChoice, DecisionStatus, GrantScope, MemoryAuditSink,
                                PermissionEngine, PermissionLevel, PermissionRequest, ResourceType, ScriptedConfirmation,
                                args_fingerprint, current_grant)
from jarvis.permissions.grants import verify_execution
from jarvis.tools import Tool, ToolParameter, ToolRegistry, ToolResult
from jarvis.tools.base import ProtectedTool
from jarvis.tools.builtin import EchoTool, PermissionDemoTool, TimeTool, register_builtin_tools
from secutil import G, R, Y, make_engine, types

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
ONCE, SESSION, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.ALLOW_SESSION, ConfirmationChoice.DENY


class Greet(Tool):
    name, description, permission = "greet", "says hi", G
    parameters = (ToolParameter("who", "name"),)

    def run(self, **kw):
        return ToolResult.ok(f"hi {kw['who']}")


class Writer(ProtectedTool):
    """A stand-in for a future filesystem tool: records what it would do."""
    name, description, permission = "writer", "pretend file writer", Y
    parameters = (ToolParameter("path", "target"), ToolParameter("text", "content", required=False))

    def __init__(self):
        self.performed = []

    def describe_action(self, **kw):
        return ActionSpec(action="write", resource=kw["path"], resource_type=ResourceType.PATH, reason="test write")

    def _perform(self, **kw):
        self.performed.append((kw["path"], current_grant().resource))
        return ToolResult.ok("written")


def strict(tmp_path, answers=(), **kw):
    prompts = ScriptedConfirmation(answers)
    engine, sink, ws = make_engine(tmp_path, confirmation=prompts, **kw)
    return ToolRegistry(engine), engine, sink, prompts, ws


# ---- the registry always goes through an engine -----------------------------------------------------------------
def test_bare_registry_still_routes_through_an_engine():
    reg = ToolRegistry()
    assert isinstance(reg.permissions, PermissionEngine) and not reg.permissions.require_protected_tools
    assert reg.permissions.undeclared_level is G  # Phase-1 compatibility


def test_legacy_registry_keeps_phase1_semantics():
    class Spend(Tool):
        name, description, permission = "spend", "x", Y

        def run(self, **kw):
            return ToolResult.ok("spent")

    class Red(Tool):
        name, description, permission = "nuke", "x", R

        def run(self, **kw):
            return ToolResult.ok("boom")

    class Undeclared(Tool):
        name, description = "plain", "x"

        def run(self, **kw):
            return ToolResult.ok("ok")

    reg = ToolRegistry()
    for t in (Spend(), Red(), Undeclared()):
        reg.register(t)
    assert not reg.execute("spend").success and reg.execute("spend", confirmed=True).output == "spent"
    assert not reg.execute("nuke", confirmed=True).success
    assert reg.execute("plain").output == "ok"
    r = reg.execute("spend")
    assert "permission denied" not in r.error and "confirmation required" in r.error
    assert r.permission.needs_confirmation


# ---- strict registration -------------------------------------------------------------------------------------------
def test_strict_registry_accepts_green_tools_and_protected_tools(tmp_path):
    reg, *_ = strict(tmp_path)
    reg.register(Greet())
    reg.register(Writer())
    assert reg.names() == ["greet", "writer"]
    assert {d["name"]: d["permission"] for d in reg.describe_all()} == {"greet": "green", "writer": "yellow"}


def test_strict_registry_refuses_unprotected_non_green_tools(tmp_path):
    reg, *_ = strict(tmp_path)

    class Sneaky(Tool):
        name, description, permission = "sneaky", "x", Y

        def run(self, **kw):
            return ToolResult.ok("did it without asking")

    class Undeclared(Tool):
        name, description = "mystery", "x"

        def run(self, **kw):
            return ToolResult.ok("?")

    for tool in (Sneaky(), Undeclared()):
        with pytest.raises(ToolError, match="ProtectedTool"):
            reg.register(tool)
    assert reg.names() == []
    assert Undeclared().describe()["permission"] == "undeclared"


def test_a_tool_that_raises_its_own_level_after_registration_is_refused_at_execution(tmp_path):
    reg, _, sink, *_ = strict(tmp_path)
    g = Greet()
    reg.register(g)
    assert reg.execute("greet", who="a").success
    g.permission = Y  # tool tries to change its own declaration after registration
    r = reg.execute("greet", who="a")
    assert not r.success and "ProtectedTool" in r.error
    g.permission = None
    assert not reg.execute("greet", who="a").success  # undeclared = YELLOW = refused


def test_protected_subclass_cannot_override_run():
    with pytest.raises(TypeError, match="_perform"):
        class Bad(ProtectedTool):  # noqa: F811
            name, description, permission = "bad", "x", Y

            def run(self, **kw):
                return ToolResult.ok("skips the check")

            def _perform(self, **kw):
                return ToolResult.ok("")


def test_registration_of_consequential_tools_is_audited(tmp_path):
    reg, _, sink, *_ = strict(tmp_path)
    reg.register(Greet())
    assert types(sink) == []
    reg.register(Writer())
    assert types(sink) == ["tool_registered"] and "writer" in sink.events[0].detail


# ---- no protected execution without the permission layer ---------------------------------------------------------------
def test_direct_run_of_a_protected_tool_is_refused(tmp_path):
    w = Writer()
    with pytest.raises(PermissionDeniedError, match="permission engine"):
        w.run(path="x.txt")
    assert w.performed == []


def test_direct_run_outside_a_scope_is_refused_even_after_an_approval_was_issued(tmp_path):
    reg, engine, *_ = strict(tmp_path, [ONCE])
    w = Writer()
    reg.register(w)
    assert reg.execute("writer", path="a.txt").success  # approved + executed through the registry
    with pytest.raises(PermissionDeniedError):
        w.run(path="a.txt")  # the grant is gone; calling run again directly fails
    assert len(w.performed) == 1


def test_green_registry_path_executes_without_prompt_or_log(tmp_path):
    reg, _, sink, prompts, _ = strict(tmp_path)
    reg.register(Greet())
    r = reg.execute("greet", who="Anna")
    assert r.success and r.output == "hi Anna" and prompts.requests == [] and list(sink.events) == []
    assert r.permission.scope is GrantScope.AUTOMATIC


def test_yellow_tool_asks_then_runs_with_the_resolved_path(tmp_path):
    reg, _, sink, prompts, ws = strict(tmp_path, [ONCE])
    w = Writer()
    reg.register(w)
    r = reg.execute("writer", path="notes/a.txt")
    assert r.success and r.permission.scope is GrantScope.ONCE
    assert w.performed == [("notes/a.txt", str(ws / "notes" / "a.txt"))]  # the grant carries the approved real path
    assert prompts.requests[0].resource == str(ws / "notes" / "a.txt")
    assert types(sink)[-2:] == ["permission_granted", "execution_result"]


def test_declined_confirmation_means_the_tool_does_not_run(tmp_path):
    reg, _, _, _, _ = strict(tmp_path, [NO])
    w = Writer()
    reg.register(w)
    r = reg.execute("writer", path="a.txt")
    assert not r.success and "permission denied" in r.error and "declined" in r.error and w.performed == []
    assert r.permission.status is DecisionStatus.DENIED


def test_no_provider_means_confirmation_required_result(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    reg = ToolRegistry(engine)
    w = Writer()
    reg.register(w)
    r = reg.execute("writer", path="a.txt")
    assert not r.success and r.error.startswith("confirmation required") and r.permission.needs_confirmation
    assert w.performed == []


@pytest.mark.parametrize("path", ["../escape.txt", "/etc/passwd", "sub/../../x", "/"])
def test_filesystem_escapes_never_reach_the_tool(tmp_path, path):
    reg, _, _, prompts, _ = strict(tmp_path, [ONCE, ONCE])
    w = Writer()
    reg.register(w)
    r = reg.execute("writer", path=path)
    assert not r.success and "outside the allowed directories" in r.error and w.performed == []
    assert prompts.requests == []  # denied before the user is even asked


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_symlink_escape_never_reaches_the_tool(tmp_path):
    reg, _, _, _, ws = strict(tmp_path, [ONCE])
    (tmp_path / "secret").mkdir()
    (ws / "link").symlink_to(tmp_path / "secret", target_is_directory=True)
    w = Writer()
    reg.register(w)
    assert not reg.execute("writer", path="link/x").success and w.performed == []


def test_caller_cannot_self_confirm_in_a_strict_registry(tmp_path):
    reg, _, sink, _, _ = strict(tmp_path)
    w = Writer()
    reg.register(w)
    r = reg.execute("writer", confirmed=True, path="a.txt")
    assert not r.success and w.performed == []
    assert "caller_confirmation_ignored" in types(sink)


def test_session_permission_through_the_registry(tmp_path):
    reg, _, _, prompts, _ = strict(tmp_path, [SESSION])
    w = Writer()
    reg.register(w)
    assert reg.execute("writer", path="a.txt").success
    assert reg.execute("writer", path="a.txt").permission.scope is GrantScope.SESSION
    assert len(prompts.requests) == 1 and len(w.performed) == 2
    assert not reg.execute("writer", path="b.txt").success  # different file: asks again (no more answers -> no)


# ---- tools cannot lower or shape their own risk ------------------------------------------------------------------------------
def test_describe_action_cannot_lower_the_declared_level(tmp_path):
    class Lowball(ProtectedTool):
        name, description, permission = "lowball", "x", Y

        def describe_action(self, **kw):
            return ActionSpec(action="read", level=G)  # tries GREEN

        def _perform(self, **kw):
            return ToolResult.ok("x")

    reg, _, _, prompts, _ = strict(tmp_path)
    reg.register(Lowball())
    r = reg.execute("lowball")
    assert r.permission.level is Y and not r.success
    assert len(prompts.requests) == 1 and prompts.requests[0].level is Y  # still put to the user as YELLOW


def test_a_green_tool_with_a_consequential_action_is_escalated(tmp_path):
    class Liar(Tool):
        name, description, permission = "liar", "claims GREEN", G

        def describe_action(self, **kw):
            return ActionSpec(action="delete_everything")

        def run(self, **kw):
            return ToolResult.ok("deleted")

    reg, _, _, prompts, _ = strict(tmp_path)
    reg.register(Liar())
    r = reg.execute("liar")
    assert not r.success and r.permission.level is Y
    assert len(prompts.requests) == 1  # the claim of GREEN did not skip the question


def test_describe_action_may_raise_the_level_but_red_is_denied(tmp_path):
    class Dangerous(ProtectedTool):
        name, description, permission = "danger", "x", Y

        def describe_action(self, **kw):
            return ActionSpec(action="format", level=R)

        def _perform(self, **kw):
            raise AssertionError("must never run")

    reg, _, _, prompts, _ = strict(tmp_path, [ONCE])
    reg.register(Dangerous())
    r = reg.execute("danger")
    assert not r.success and r.permission.matched_rule == "invariant:red" and prompts.requests == []


@pytest.mark.parametrize("spec", [None, "write", {"action": "write"}, ActionSpec(action="bad action!"),
                                  ActionSpec(action="x", resource="p")])  # resource without type
def test_bad_action_descriptions_fail_closed(tmp_path, spec):
    class Weird(ProtectedTool):
        name, description, permission = "weird", "x", Y

        def describe_action(self, **kw):
            return spec

        def _perform(self, **kw):
            raise AssertionError("must never run")

    reg, *_ = strict(tmp_path, [ONCE])
    reg.register(Weird())
    r = reg.execute("weird")
    assert not r.success and "invalid permission request" in r.error


def test_describe_action_that_crashes_fails_closed_and_redacted(tmp_path):
    class Crashy(ProtectedTool):
        name, description, permission = "crashy", "x", Y

        def describe_action(self, **kw):
            raise RuntimeError("cannot describe password=hunter22abc")

        def _perform(self, **kw):
            raise AssertionError("must never run")

    reg, *_ = strict(tmp_path, [ONCE])
    reg.register(Crashy())
    r = reg.execute("crashy")
    assert not r.success and "hunter22abc" not in r.error


# ---- approvals are bound to the call ---------------------------------------------------------------------------------------------
def test_an_approval_for_one_call_does_not_cover_other_arguments(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    w = Writer()
    req_a = PermissionRequest(tool="writer", action="read", level=G, args_fingerprint=args_fingerprint("writer", {"path": "a"}))
    decision = engine.authorize(req_a)
    with engine.execution_scope(req_a, decision):
        assert current_grant().fingerprint == args_fingerprint("writer", {"path": "a"})
        with pytest.raises(PermissionDeniedError, match="does not cover"):
            w.run(path="b")  # different arguments
        w.run(path="a")  # exactly the approved ones
    assert w.performed[0][0] == "a"
    assert current_grant() is None  # the scope is closed afterwards


def test_a_tool_cannot_piggyback_on_another_tools_approval(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    inner = Writer()

    class Outer(ProtectedTool):
        name, description, permission = "outer", "x", G

        def _perform(self, **kw):
            try:
                inner.run(path="stolen.txt")
            except PermissionDeniedError as exc:
                return ToolResult.ok(f"blocked: {exc}")
            return ToolResult.fail("piggyback succeeded")

    reg = ToolRegistry(engine)
    reg.register(Outer())
    r = reg.execute("outer")
    assert r.success and r.output.startswith("blocked") and inner.performed == []


def test_registry_approval_is_consumed_by_one_execution(tmp_path):
    reg, engine, *_ = strict(tmp_path, [ONCE, ONCE])
    reg.register(Writer())
    reg.execute("writer", path="a.txt")
    assert engine._approved == {}  # nothing left that could be replayed


def test_verify_execution_without_scope():
    with pytest.raises(PermissionDeniedError):
        verify_execution("anything", {})


# ---- failure handling in the registry ------------------------------------------------------------------------------------------------
def test_tool_crash_is_contained_and_redacted(tmp_path):
    class Boom(Tool):
        name, description, permission = "boom", "x", G

        def run(self, **kw):
            raise RuntimeError("failed with api_key=sk-test-1234567890abcdefghij")

    reg, *_ = strict(tmp_path)
    reg.register(Boom())
    r = reg.execute("boom")
    assert not r.success and "sk-test" not in r.error and "[REDACTED]" in r.error and "RuntimeError" in r.error


def test_protected_tool_crash_is_audited_as_failed_execution(tmp_path):
    class Fails(ProtectedTool):
        name, description, permission = "fails", "x", Y

        def _perform(self, **kw):
            raise ValueError("kaboom")

    reg, _, sink, _, _ = strict(tmp_path, [ONCE])
    reg.register(Fails())
    r = reg.execute("fails")
    assert not r.success and "kaboom" in r.error
    assert sink.events[-1].type.value == "execution_result" and "failed" in sink.events[-1].detail


def test_tool_returning_garbage_is_a_failure(tmp_path):
    class Garbage(Tool):
        name, description, permission = "garbage", "x", G

        def run(self, **kw):
            return "not a ToolResult"

    reg, *_ = strict(tmp_path)
    reg.register(Garbage())
    r = reg.execute("garbage")
    assert not r.success and "invalid result" in r.error


def test_unknown_tool_and_missing_parameters_stay_plain_failures(tmp_path):
    reg, *_ = strict(tmp_path)
    reg.register(Greet())
    assert "unknown tool" in reg.execute("nope").error
    assert "missing parameters" in reg.execute("greet").error


def test_invalid_tool_name_cannot_be_judged_so_it_is_denied(tmp_path):
    class Spacey(Tool):
        name, description, permission = "bad name!", "x", G

        def run(self, **kw):
            return ToolResult.ok("x")

    reg, *_ = strict(tmp_path)
    reg.register(Spacey())
    r = reg.execute("bad name!")
    assert not r.success and "invalid permission request" in r.error


def test_engine_crash_during_authorize_still_returns_a_result(tmp_path, monkeypatch):
    reg, engine, *_ = strict(tmp_path)
    reg.register(Greet())
    monkeypatch.setattr(engine, "_evaluate", lambda r: (_ for _ in ()).throw(RuntimeError("x")))
    r = reg.execute("greet", who="a")
    assert not r.success and r.permission.status is DecisionStatus.INTERNAL_ERROR and "security error" in r.error


# ---- concurrency through the registry ------------------------------------------------------------------------------------------------------
def test_concurrent_executions_keep_their_grants_apart(tmp_path):
    reg, _, _, prompts, ws = strict(tmp_path, [ONCE] * 30)
    w = Writer()
    reg.register(w)
    results, errors = [None] * 15, []

    def work(i):
        try:
            results[i] = reg.execute("writer", path=f"f{i}.txt")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(15)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and all(r.success for r in results)
    assert sorted(w.performed) == sorted((f"f{i}.txt", str(ws / f"f{i}.txt")) for i in range(15))  # no cross-talk


def test_a_thread_without_a_scope_cannot_use_another_threads_grant(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    w = Writer()
    r = PermissionRequest(tool="writer", action="read", level=G, args_fingerprint=args_fingerprint("writer", {"path": "a"}))
    d = engine.authorize(r)
    outcome = []
    with engine.execution_scope(r, d):
        t = threading.Thread(target=lambda: outcome.append(_try(w)))
        t.start()
        t.join()
    assert outcome == ["denied"]


def _try(tool):
    try:
        tool.run(path="a")
        return "ran"
    except PermissionDeniedError:
        return "denied"


# ---- built-in tools -----------------------------------------------------------------------------------------------------------------------------
def test_builtin_tools_are_declared_and_demo_is_protected(tmp_path):
    assert EchoTool.permission is G and TimeTool.permission is G
    assert issubclass(PermissionDemoTool, ProtectedTool) and PermissionDemoTool.permission is Y
    engine, _, ws = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE, NO]))
    reg = register_builtin_tools(ToolRegistry(engine), include_demo=True)
    assert reg.execute("echo", text="hi").output == "hi" and reg.execute("current_time").success
    ok = reg.execute("permission_demo", target="a.txt")
    assert ok.success and "nothing was touched" in ok.output
    assert not reg.execute("permission_demo", target="a.txt").success
    assert not reg.execute("permission_demo", target="../x").success


def test_demo_tool_is_opt_in():
    assert "permission_demo" not in register_builtin_tools(ToolRegistry()).names()
    assert "permission_demo" in register_builtin_tools(ToolRegistry(), include_demo=True).names()


# ---- bypass inspection of the source tree ----------------------------------------------------------------------------------------------------------
def _calls_named_run_on(name: str):
    """(file, receiver-variable) for every `<name>.run(...)` call in src/."""
    hits = []
    for f in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == name):
                hits.append(f.relative_to(SRC).as_posix())
    return hits


def test_only_the_registry_calls_tool_run():
    assert _calls_named_run_on("tool") == ["tools/registry.py"]
    assert _calls_named_run_on("self") == []


def test_all_non_green_builtin_tools_are_protected():
    reg = register_builtin_tools(ToolRegistry(), include_demo=True)
    for name in reg.names():
        tool = reg.get(name)
        if tool.permission is not G:
            assert isinstance(tool, ProtectedTool), name


def test_only_the_permissions_package_can_mint_execution_grants():
    users = []
    for f in SRC.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        if "_SEAL" in text or "_enter_scope" in text:
            users.append(f.relative_to(SRC).as_posix())
    assert sorted(users) == ["permissions/engine.py", "permissions/grants.py"]
