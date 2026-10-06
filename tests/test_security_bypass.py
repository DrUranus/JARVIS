"""Adversarial tests: each one is an attempt to get a protected action past the permission layer."""
import ast
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.core import JarvisCore
from jarvis.errors import PermissionDeniedError, ToolError
from jarvis.llm.mock import MockProvider
from jarvis.permissions import (ActionSpec, ConfirmationChoice, DecisionStatus, DenyAllConfirmation, GrantScope,
                                PermissionEngine, PermissionLevel, PermissionRequest, ResourceType, ScriptedConfirmation)
from jarvis.tools import Tool, ToolParameter, ToolRegistry, ToolResult
from jarvis.tools.base import ProtectedTool
from secutil import G, R, Y, make_engine, path_req, req, types

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
ONCE = ConfirmationChoice.ALLOW_ONCE


class Writer(ProtectedTool):
    name, description, permission = "writer", "pretend writer", Y
    parameters = (ToolParameter("path", "target"),)

    def __init__(self):
        self.performed = []

    def describe_action(self, **kw):
        return ActionSpec(action="write", resource=kw["path"], resource_type=ResourceType.PATH)

    def _perform(self, **kw):
        self.performed.append(kw["path"])
        return ToolResult.ok("written")


# ---- 1. an approval is worth exactly the request it was issued for -----------------------------------------------
def test_approval_cannot_be_reused_for_a_different_request_with_the_same_id(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    harmless = req(tool="echo", action="read")
    decision = engine.authorize(harmless)  # legitimately approved (GREEN)
    for evil in (replace(harmless, tool="writer", action="write", level=Y),
                 replace(harmless, action="delete_file"),
                 replace(harmless, resource="/etc/passwd", resource_type=ResourceType.OTHER),
                 replace(harmless, level=Y)):
        engine._approve(harmless, decision, None)  # re-arm the same legitimate approval for each attempt
        with pytest.raises(PermissionDeniedError):
            with engine.execution_scope(evil, decision):
                pass
    assert "security_error" in types(sink)


def test_a_failed_attempt_burns_the_approval(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    r = req()
    d = engine.authorize(r)
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(replace(r, action="delete"), d):
            pass
    with pytest.raises(PermissionDeniedError):  # probing costs the legitimate caller too: fail closed
        with engine.execution_scope(r, d):
            pass


def test_a_tampered_decision_object_is_not_accepted(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    r = req()
    d = engine.authorize(r)
    tampered = replace(d, reason="edited", level=G)
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(r, tampered):
            pass


# ---- 2. security switches cannot be flipped from outside --------------------------------------------------------
@pytest.mark.parametrize("attr,value", [
    ("mode", None), ("guard", None), ("confirmation", None), ("allow_session_grants", True),
    ("trust_caller_confirmation", True), ("undeclared_level", G), ("require_protected_tools", False),
    ("audit_strict", False), ("audit_green", True),
])
def test_engine_switches_are_read_only(tmp_path, attr, value):
    engine, _, _ = make_engine(tmp_path)
    with pytest.raises(AttributeError):
        setattr(engine, attr, value)


def test_registry_engine_cannot_be_replaced(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    reg = ToolRegistry(engine)
    with pytest.raises(AttributeError):
        reg.permissions = PermissionEngine.legacy()  # the classic "swap in a lenient engine"
    assert reg.permissions is engine


def test_confirmation_provider_changes_go_through_an_audited_method(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    engine.set_confirmation_provider(DenyAllConfirmation(), source="test")
    assert isinstance(engine.confirmation, DenyAllConfirmation)
    assert sink.events[-1].type.value == "policy_changed" and "DenyAllConfirmation" in sink.events[-1].detail
    engine.set_confirmation_provider(None)
    assert engine.confirmation is None and "none" in sink.events[-1].detail


# ---- 3. ProtectedTool.run cannot be replaced ---------------------------------------------------------------------------
def test_mixin_cannot_smuggle_a_run_override_into_a_protected_tool():
    class Mixin:
        def run(self, **kw):
            return ToolResult.ok("bypass")

    with pytest.raises(TypeError, match="_perform"):
        class Evil(Mixin, ProtectedTool):  # noqa: F841
            name, description, permission = "evil", "x", Y

            def _perform(self, **kw):
                return ToolResult.ok("")


def test_instance_level_run_replacement_is_refused(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    reg = ToolRegistry(engine)
    w = Writer()
    w.run = lambda **kw: ToolResult.ok("bypass")  # type: ignore[method-assign]
    with pytest.raises(ToolError, match="replaced"):
        reg.register(w)
    clean = Writer()
    reg.register(clean)
    clean.run = lambda **kw: ToolResult.ok("bypass")  # type: ignore[method-assign]  # tampered after registration
    r = reg.execute("writer", path="a.txt")
    assert not r.success and "replaced" in r.error and clean.performed == []


def test_renaming_a_registered_tool_does_not_borrow_a_grant(tmp_path):
    reg = ToolRegistry(make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE]))[0])
    w = Writer()
    reg.register(w)
    w.name = "other-name"  # the approval was issued for "writer"
    r = reg.execute("writer", path="a.txt")
    assert not r.success and "does not cover" in r.error and w.performed == []


# ---- 4. requests cannot be subclassed to tamper with validation -----------------------------------------------------------
def test_request_subclasses_are_rejected(tmp_path):
    class Lax(PermissionRequest):
        def validate(self):  # pretend everything is fine
            return None

    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE]))
    d = engine.authorize(Lax(tool="x y", action="write", level=G))
    assert d.status is DecisionStatus.INVALID_REQUEST and not d.allowed

    class Plain(PermissionRequest):  # not even a harmless subclass is accepted: type must be exactly PermissionRequest
        pass

    assert not engine.authorize(Plain(tool="t", action="read", level=G)).allowed


# ---- 5. case tricks cannot sneak past deny lists ----------------------------------------------------------------------------
def test_denied_and_protected_paths_ignore_case(tmp_path):
    ws = tmp_path / "ws"
    (ws / "private").mkdir(parents=True)
    engine, _, _ = make_engine(tmp_path, denied=[ws / "private"], protected=[ws / "Audit.jsonl"],
                               confirmation=ScriptedConfirmation([ONCE] * 4))
    for spelling in ("private/x", "PRIVATE/x", "Private/../PRIVATE/x"):
        assert engine.authorize(path_req(spelling, action="read", level=G)).matched_rule == "fs:denied_path", spelling
    assert engine.authorize(path_req("audit.JSONL")).matched_rule == "fs:protected_path"


def test_deny_rules_ignore_case_but_allow_rules_do_not(tmp_path):
    ws = tmp_path / "ws"
    rules = [{"id": "vault-off", "effect": "deny", "tool": "filesystem", "resource_type": "path", "resources": [str(ws / "vault")]},
             {"id": "notes-ok", "effect": "allow", "tool": "filesystem", "action": "write", "resource_type": "path",
              "resources": [str(ws / "notes")]}]
    engine, _, _ = make_engine(tmp_path, rules=rules)
    assert engine.authorize(path_req("VAULT/x")).matched_rule == "vault-off"  # over-matching is the safe direction
    assert engine.authorize(path_req("notes/x")).matched_rule == "notes-ok"
    assert engine.authorize(path_req("NOTES/x")).needs_confirmation  # a different spelling is NOT trusted


# ---- 6. no secrets in logs or error output -------------------------------------------------------------------------------------
def test_tool_crash_does_not_leak_secrets_into_the_log_file_or_result(tmp_path, caplog):
    class Boom(Tool):
        name, description, permission = "boom", "x", G

        def run(self, **kw):
            raise RuntimeError("connect failed: password=hunter22abc token=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123")

    reg = ToolRegistry(make_engine(tmp_path)[0])
    reg.register(Boom())
    with caplog.at_level(logging.DEBUG, logger="jarvis"):
        r = reg.execute("boom")
    assert "hunter22abc" not in r.error and "sk-ant" not in r.error and "RuntimeError" in r.error
    for rec in caplog.records:
        blob = rec.getMessage() + (rec.exc_text or "") + str(rec.exc_info)
        assert "hunter22abc" not in blob and "sk-ant-api03" not in blob


def test_a_tools_own_failure_message_is_redacted_too(tmp_path):
    class Leaky(Tool):
        name, description, permission = "leaky", "x", G

        def run(self, **kw):
            return ToolResult.fail("login failed for api_key=abcd1234efgh5678")

    reg = ToolRegistry(make_engine(tmp_path)[0])
    reg.register(Leaky())
    r = reg.execute("leaky")
    assert not r.success and "abcd1234efgh5678" not in r.error


# ---- 7. defaults are strict --------------------------------------------------------------------------------------------------------
def test_core_without_an_injected_registry_gets_a_strict_one():
    core = JarvisCore(MockProvider())
    engine = core.tools.permissions
    assert engine.require_protected_tools and not engine.trust_caller_confirmation and engine.undeclared_level is Y

    class Plain(Tool):
        name, description = "plain", "x"

        def run(self, **kw):
            return ToolResult.ok("x")

    with pytest.raises(ToolError):
        core.tools.register(Plain())  # undeclared = YELLOW = must be a ProtectedTool
    assert core.permissions is engine


def test_strict_registry_without_provider_or_roots_denies_everything_but_green():
    reg = ToolRegistry.strict()
    w = Writer()
    reg.register(w)
    assert not reg.execute("writer", path="/tmp/x").success  # no roots -> denied before anything else
    assert reg.permissions.evaluate(req(level=Y, action="send")).needs_confirmation  # nobody to ask


def test_src_never_builds_a_lenient_registry():
    offenders = []
    for f in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ToolRegistry"
                    and not node.args and not node.keywords):
                offenders.append(f.relative_to(SRC).as_posix())
    assert offenders == []


def test_no_assignment_to_engine_internals_outside_the_permissions_package():
    sensitive = {"_mode", "_guard", "_confirmation", "_trust_caller_confirmation", "_undeclared_level",
                 "_require_protected_tools", "_approved", "_permissions", "_session"}
    offenders = []
    for f in SRC.rglob("*.py"):
        if f.parent.name == "permissions" or f.name == "registry.py":
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    foreign = isinstance(t, ast.Attribute) and not (isinstance(t.value, ast.Name) and t.value.id == "self")
                    if foreign and t.attr in sensitive:  # `self._x = ...` is a class setting up its own state
                        offenders.append((f.name, t.attr))
    assert offenders == []
