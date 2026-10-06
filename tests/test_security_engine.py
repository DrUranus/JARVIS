"""PermissionEngine: levels, rules, confirmation, scopes, audit, secrets, fail-closed behaviour, concurrency."""
import json
import os
import sys
import threading
import time
from dataclasses import replace

import pytest

from jarvis.errors import InvalidRequestError, PermissionDeniedError, PolicyError
from jarvis.permissions import (ActionSpec, AuditEventType, AuditLogger, ConfirmationChoice, ConfirmationProvider,
                                DecisionStatus, DenyAllConfirmation, ExecutionGrant, GrantScope, JsonlAuditSink,
                                MemoryAuditSink, NullAuditSink, PathGuard, PermissionDecision, PermissionEngine,
                                PermissionLevel, PermissionMode, PermissionRequest, Policy, ResourceType,
                                ScriptedConfirmation, action_floor)
from jarvis.permissions.audit import AuditSink
from jarvis.redaction import SecretDetector
from secutil import G, R, Y, make_engine, path_req, req, types

ONCE, SESSION, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.ALLOW_SESSION, ConfirmationChoice.DENY


# ---- GREEN / YELLOW / RED ------------------------------------------------------------------------------------
def test_green_is_automatic_and_quiet(tmp_path):
    prompts = ScriptedConfirmation()
    engine, sink, _ = make_engine(tmp_path, confirmation=prompts)
    d = engine.authorize(req())
    assert d.allowed and d.status is DecisionStatus.ALLOWED and d.scope is GrantScope.AUTOMATIC and d.level is G
    assert prompts.requests == [] and list(sink.events) == []  # no prompt, no log flooding


def test_green_can_be_logged_when_requested(tmp_path):
    engine, sink, _ = make_engine(tmp_path, audit_green=True)
    engine.authorize(req())
    assert types(sink) == ["permission_requested", "permission_granted"]


def test_yellow_requires_confirmation_without_a_provider(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    d = engine.authorize(req(level=Y, action="send"))
    assert d.needs_confirmation and not d.allowed and not d.denied and d.status is DecisionStatus.CONFIRMATION_REQUIRED
    assert "confirmation" in d.reason and d.level is Y
    assert types(sink)[-1] == "permission_denied"  # a non-grant is logged


def test_yellow_allowed_once_after_user_confirms(tmp_path):
    prompts = ScriptedConfirmation([ONCE, ONCE])
    engine, sink, _ = make_engine(tmp_path, confirmation=prompts)
    r = req(level=Y, action="send", reason="Mail an Anna")
    d = engine.authorize(r)
    assert d.allowed and d.scope is GrantScope.ONCE and d.matched_rule == "user:confirmed"
    assert types(sink) == ["permission_requested", "confirmation_requested", "confirmation_accepted", "permission_granted"]
    # one-time means one time: an identical later request asks again
    assert engine.authorize(req(level=Y, action="send")).scope is GrantScope.ONCE
    assert len(prompts.requests) == 2


def test_user_can_decline(tmp_path):
    engine, sink, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([NO]))
    d = engine.authorize(req(level=Y, action="send"))
    assert d.denied and d.status is DecisionStatus.DENIED and d.matched_rule == "user:declined"
    assert "confirmation_rejected" in types(sink) and "permission_denied" in types(sink)


def test_red_is_always_denied_and_never_asks(tmp_path):
    prompts = ScriptedConfirmation([ONCE, SESSION])
    engine, sink, _ = make_engine(tmp_path, confirmation=prompts, trust_caller_confirmation=True)
    d = engine.authorize(req(level=R, action="read"), caller_confirmed=True)
    assert d.denied and d.matched_rule == "invariant:red" and d.level is R
    assert prompts.requests == []


def test_red_cannot_be_unlocked_by_rules_sessions_or_modes(tmp_path):
    allow = {"id": "allow-all-t", "effect": "allow", "tool": "t", "action": "read"}
    engine, _, _ = make_engine(tmp_path, rules=[allow], confirmation=ScriptedConfirmation([SESSION] * 3),
                               trust_caller_confirmation=True, undeclared_level=G, require_protected_tools=False)
    for _ in range(3):
        assert engine.authorize(req(level=R), caller_confirmed=True).denied
    # a rule may not even be written for RED
    with pytest.raises(PolicyError):
        Policy.from_rules([{"id": "x", "effect": "allow", "tool": "t", "action": "read", "levels": ["red"]}])
    assert not engine.evaluate(req(level=R)).allowed


# ---- action-name safety net -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("action,expected", [
    ("read", G), ("list", G), ("search", G), ("run", G), ("analyze", G),
    ("write", Y), ("delete", Y), ("delete_file", Y), ("fs.write", Y), ("file:overwrite", Y), ("send-email", Y),
    ("Execute", Y), ("order", Y), ("pay", Y), ("kill", Y),
])
def test_action_floor(action, expected):
    assert action_floor(action) is expected


def test_a_tool_cannot_understate_a_consequential_action(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    d = engine.authorize(req(action="delete_file", level=G))  # tool claims GREEN
    assert d.needs_confirmation and d.level is Y
    assert "at least YELLOW" in d.reason


# ---- modes -------------------------------------------------------------------------------------------------------------
def test_lockdown_allows_only_green_and_never_asks(tmp_path):
    prompts = ScriptedConfirmation([ONCE])
    allow = {"id": "t", "effect": "allow", "tool": "t", "action": "send"}
    engine, _, _ = make_engine(tmp_path, rules=[allow], confirmation=prompts, mode=PermissionMode.LOCKDOWN)
    assert engine.authorize(req()).allowed
    d = engine.authorize(req(level=Y, action="send"))
    assert d.denied and d.matched_rule == "invariant:lockdown"  # not even an allow rule
    assert prompts.requests == []


def test_deny_all_confirmation_headless(tmp_path):
    engine, _, _ = make_engine(tmp_path, confirmation=DenyAllConfirmation())
    assert engine.authorize(req(level=Y, action="send")).denied


# ---- explicit rules -----------------------------------------------------------------------------------------------------
def test_allow_rule_is_a_persistent_permission(tmp_path):
    allow = {"id": "trust-send", "effect": "allow", "tool": "mail", "action": "send"}
    prompts = ScriptedConfirmation()
    engine, sink, _ = make_engine(tmp_path, rules=[allow], confirmation=prompts)
    d = engine.authorize(req(tool="mail", action="send", level=Y))
    assert d.allowed and d.scope is GrantScope.PERSISTENT and d.matched_rule == "trust-send"
    assert prompts.requests == []
    # narrow: another action or tool is not covered (it is put to the user, who - here - says nothing -> no)
    for other in (req(tool="mail", action="delete", level=Y), req(tool="chat", action="send", level=Y)):
        assert engine.authorize(other, interactive=False).needs_confirmation
        assert engine.authorize(other).denied
    assert len(prompts.requests) == 2


def test_deny_rule_blocks_even_green(tmp_path):
    deny = {"id": "no-terminal", "effect": "deny", "tool": "terminal"}
    engine, _, _ = make_engine(tmp_path, rules=[deny], confirmation=ScriptedConfirmation([ONCE]))
    d = engine.authorize(req(tool="terminal", action="list"))
    assert d.denied and d.matched_rule == "no-terminal" and d.considered_rules == ("no-terminal",)


def test_confirm_rule_forces_a_prompt_even_for_green(tmp_path):
    rule = {"id": "ask-reads", "effect": "confirm", "tool": "diary"}
    prompts = ScriptedConfirmation([ONCE, ONCE])
    engine, _, _ = make_engine(tmp_path, rules=[rule], confirmation=prompts)
    assert engine.authorize(req(tool="diary", action="read")).scope is GrantScope.ONCE
    assert len(prompts.requests) == 1
    assert engine.authorize(req(tool="diary", action="read")).allowed and len(prompts.requests) == 2


def test_confirm_rule_means_every_time_session_is_not_offered(tmp_path):
    rule = {"id": "ask", "effect": "confirm", "tool": "bank"}
    prompts = ScriptedConfirmation([SESSION, SESSION])
    engine, _, _ = make_engine(tmp_path, rules=[rule], confirmation=prompts)
    d1 = engine.authorize(req(tool="bank", action="pay", level=Y))
    assert d1.scope is GrantScope.ONCE and prompts.requests[0].session_allowed is False
    assert engine.authorize(req(tool="bank", action="pay", level=Y)).scope is GrantScope.ONCE
    assert len(prompts.requests) == 2  # asked again: "always ask" is respected


def test_conflicting_rules_resolve_to_the_safer_effect(tmp_path):
    rules = [{"id": "allow", "effect": "allow", "tool": "mail", "action": "send"},
             {"id": "confirm", "effect": "confirm", "tool": "mail"},
             {"id": "deny", "effect": "deny", "tool": "mail", "action": "send"}]
    engine, _, _ = make_engine(tmp_path, rules=rules, confirmation=ScriptedConfirmation([ONCE]))
    d = engine.authorize(req(tool="mail", action="send", level=Y))
    assert d.denied and d.matched_rule == "deny" and d.considered_rules == ("deny", "confirm", "allow")
    only_conflict = [rules[0], rules[1]]
    engine, _, _ = make_engine(tmp_path, rules=only_conflict)
    assert engine.authorize(req(tool="mail", action="send", level=Y)).needs_confirmation  # confirm beats allow


def test_rule_with_levels_only_applies_to_those_levels(tmp_path):
    rule = {"id": "r", "effect": "allow", "tool": "mail", "action": "send", "levels": ["green"]}
    engine, _, _ = make_engine(tmp_path, rules=[rule])
    assert engine.authorize(req(tool="mail", action="send", level=Y)).needs_confirmation  # YELLOW not covered


# ---- path rules and the filesystem envelope ----------------------------------------------------------------------------------
def notes_rule():
    return {"id": "notes", "effect": "allow", "tool": "filesystem", "action": "write", "resource_type": "path",
            "resources": ["{ws}/notes"]}


def engine_with_notes(tmp_path, **kw):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "other").mkdir(exist_ok=True)
    rule = {**notes_rule(), "resources": [str(ws / "notes")]}
    return make_engine(tmp_path, rules=[rule], **kw)


def test_path_allow_rule_applies_only_below_its_directory(tmp_path):
    engine, _, ws = engine_with_notes(tmp_path)
    assert engine.authorize(path_req(ws / "notes" / "a.md")).scope is GrantScope.PERSISTENT
    assert engine.authorize(path_req("notes/a.md")).scope is GrantScope.PERSISTENT  # relative spelling
    assert engine.authorize(path_req(ws / "other" / "a.md")).needs_confirmation


def test_traversal_cannot_borrow_a_path_allow_rule(tmp_path):
    engine, _, ws = engine_with_notes(tmp_path)
    for sneaky in ("notes/../other/a.md", f"{ws}/notes/../other/a.md", "notes/./../other/a.md"):
        d = engine.authorize(path_req(sneaky))
        assert d.needs_confirmation, sneaky  # normalised to other/a.md -> rule does not apply
    assert engine.authorize(path_req("other/../notes/a.md")).allowed  # but this one genuinely is in notes


def test_prefix_sibling_does_not_match_a_path_rule(tmp_path):
    engine, _, ws = engine_with_notes(tmp_path)
    (ws / "notes-archive").mkdir()
    assert engine.authorize(path_req(ws / "notes-archive" / "a.md")).needs_confirmation


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_symlink_inside_allowed_dir_cannot_launder_a_path_rule(tmp_path):
    engine, _, ws = engine_with_notes(tmp_path)
    (ws / "notes" / "alias").symlink_to(ws / "other", target_is_directory=True)
    d = engine.authorize(path_req("notes/alias/a.md"))
    assert d.needs_confirmation and d.resolved_resource == str(ws / "other" / "a.md")  # judged by its real location


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_symlink_escape_is_denied_by_the_envelope_even_for_green_reads(tmp_path):
    engine, _, ws = make_engine(tmp_path)
    (tmp_path / "secret").mkdir()
    (ws / "link").symlink_to(tmp_path / "secret", target_is_directory=True)
    d = engine.authorize(path_req("link/passwords.txt", action="read", level=G))
    assert d.denied and d.matched_rule == "fs:outside_roots" and d.resolved_resource == str(tmp_path / "secret" / "passwords.txt")


def test_rules_cannot_widen_the_allowed_roots(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    rule = {"id": "wide", "effect": "allow", "tool": "filesystem", "action": "write", "resource_type": "path",
            "resources": [str(outside)]}
    engine, _, _ = make_engine(tmp_path, rules=[rule], confirmation=ScriptedConfirmation([ONCE]))
    d = engine.authorize(path_req(outside / "x.txt"))
    assert d.denied and d.matched_rule == "fs:outside_roots"


@pytest.mark.parametrize("bad", ["../x", "../../etc/passwd", "/etc/passwd", "/", "sub/../../x"])
def test_traversal_and_absolute_escapes_are_denied_for_every_level(tmp_path, bad):
    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE] * 4))
    for level in (G, Y):
        assert engine.authorize(path_req(bad, action="read" if level is G else "write", level=level)).denied


def test_denied_paths_and_protected_paths(tmp_path):
    ws = tmp_path / "ws"
    (ws / "private").mkdir(parents=True)
    audit_file = ws / "audit.jsonl"
    engine, _, _ = make_engine(tmp_path, denied=[ws / "private"], protected=[audit_file],
                               confirmation=ScriptedConfirmation([ONCE] * 3))
    assert engine.authorize(path_req("private/x", action="read", level=G)).matched_rule == "fs:denied_path"
    assert engine.authorize(path_req("audit.jsonl", action="read", level=G)).allowed  # reading is fine
    d = engine.authorize(path_req("audit.jsonl", action="write"))
    assert d.denied and d.matched_rule == "fs:protected_path"  # the log cannot be edited by the tools it audits


def test_default_roots_are_empty_means_deny_everything(tmp_path):
    engine = PermissionEngine(confirmation=ScriptedConfirmation([ONCE]))
    assert engine.authorize(path_req(tmp_path / "x", action="read", level=G)).matched_rule == "fs:no_roots"


# ---- domain rules ----------------------------------------------------------------------------------------------------------------
def dom(host, **kw):
    return req(tool="browser", action="navigate", level=Y, resource=host, resource_type=ResourceType.DOMAIN, **kw)


def test_domain_allow_rule_and_lookalikes(tmp_path):
    rule = {"id": "docs", "effect": "allow", "tool": "browser", "action": "navigate", "resource_type": "domain",
            "resources": ["docs.python.org"]}
    engine, _, _ = make_engine(tmp_path, rules=[rule])
    assert engine.authorize(dom("docs.python.org")).scope is GrantScope.PERSISTENT
    assert engine.authorize(dom("HTTPS://DOCS.Python.ORG/3/")).scope is GrantScope.PERSISTENT
    for evil in ("docs.python.org.evil.com", "evil-docs.python.org", "python.org", "https://evil.com/docs.python.org"):
        assert engine.authorize(dom(evil)).needs_confirmation, evil


def test_invalid_domain_is_an_invalid_request(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    d = engine.authorize(dom("http://user:pw@host/"))
    assert d.status is DecisionStatus.INVALID_REQUEST and not d.allowed


# ---- sessions: scoped, expiring, revocable -----------------------------------------------------------------------------------------
def test_session_permission_is_scoped_to_the_exact_action_and_resource(tmp_path):
    prompts = ScriptedConfirmation([SESSION, ONCE, ONCE, ONCE, ONCE])
    engine, sink, ws = make_engine(tmp_path, confirmation=prompts)
    first = engine.authorize(path_req("a.txt"))
    assert first.scope is GrantScope.SESSION and "session_grant_created" in types(sink)
    assert len(prompts.requests) == 1
    again = engine.authorize(path_req(ws / "sub" / ".." / "a.txt"))  # equivalent spelling, same real path
    assert again.scope is GrantScope.SESSION and len(prompts.requests) == 1
    # NOT covered: other file, other action, other tool, other level
    assert engine.authorize(path_req("b.txt")).scope is GrantScope.ONCE
    assert engine.authorize(path_req("a.txt", action="delete")).scope is GrantScope.ONCE
    assert engine.authorize(path_req("a.txt", tool="other")).scope is GrantScope.ONCE
    assert len(prompts.requests) == 4


def test_session_permission_for_non_path_actions(tmp_path):
    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([SESSION, ONCE]))
    assert engine.authorize(req(tool="mail", action="send", level=Y)).scope is GrantScope.SESSION
    assert engine.authorize(req(tool="mail", action="send", level=Y)).scope is GrantScope.SESSION
    r = req(tool="mail", action="send", level=Y, resource="anna", resource_type=ResourceType.OTHER)
    assert engine.authorize(r).scope is GrantScope.ONCE  # different resource info -> asks


def test_session_permission_expires(tmp_path):
    now = [1000.0]
    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([SESSION, ONCE]), session_ttl=60,
                               clock=lambda: now[0])
    assert engine.authorize(req(level=Y, action="send")).scope is GrantScope.SESSION
    now[0] += 59
    assert engine.authorize(req(level=Y, action="send")).scope is GrantScope.SESSION
    now[0] += 2
    assert engine.authorize(req(level=Y, action="send")).scope is GrantScope.ONCE  # expired -> asked again


def test_session_permissions_can_be_revoked_and_listed(tmp_path):
    prompts = ScriptedConfirmation([SESSION, ONCE])
    engine, sink, _ = make_engine(tmp_path, confirmation=prompts)
    engine.authorize(req(tool="mail", action="send", level=Y))
    assert engine.session_grants() == [{"tool": "mail", "action": "send", "level": "yellow", "resource": ""}]
    assert engine.revoke_session_grants("test") == 1
    assert engine.session_grants() == [] and "session_grants_revoked" in types(sink)
    assert engine.authorize(req(tool="mail", action="send", level=Y)).scope is GrantScope.ONCE


def test_session_grants_can_be_disabled(tmp_path):
    prompts = ScriptedConfirmation([SESSION, SESSION])
    engine, _, _ = make_engine(tmp_path, confirmation=prompts, allow_session_grants=False)
    assert engine.authorize(req(level=Y, action="send")).scope is GrantScope.ONCE  # downgraded
    assert prompts.requests[0].session_allowed is False
    engine.authorize(req(level=Y, action="send"))
    assert len(prompts.requests) == 2


def test_session_grant_never_overrides_a_later_deny_rule(tmp_path):
    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([SESSION]))
    assert engine.authorize(req(tool="mail", action="send", level=Y)).allowed
    engine.update_policy(Policy.from_rules([{"id": "stop", "effect": "deny", "tool": "mail"}]))
    d = engine.authorize(req(tool="mail", action="send", level=Y))
    assert d.denied and d.matched_rule == "stop"


def test_session_grant_store_is_bounded(tmp_path):
    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([SESSION] * 105 + [ONCE]))
    scopes = [engine.authorize(req(tool="mail", action="send", level=Y, resource=f"r{i}",
                                   resource_type=ResourceType.OTHER)).scope for i in range(105)]
    assert scopes.count(GrantScope.SESSION) == 100 and scopes.count(GrantScope.ONCE) == 5  # overflow -> one-time


# ---- request validation / malformed input -----------------------------------------------------------------------------------------------
BAD = [
    dict(tool="", action="read", level=G), dict(tool="has space", action="read", level=G),
    dict(tool="x" * 65, action="read", level=G), dict(tool="t", action=None, level=G),
    dict(tool="t", action="a;b", level=G), dict(tool="t", action="read", level="green"),
    dict(tool="t", action="read", level=None), dict(tool=5, action="read", level=G),
    dict(tool="t", action="read", level=G, resource="x"),                                   # resource without type
    dict(tool="t", action="read", level=G, resource_type=ResourceType.PATH),                # type without resource
    dict(tool="t", action="read", level=G, resource_type=ResourceType.PATH, resource="  "),
    dict(tool="t", action="read", level=G, resource_type="path", resource="x"),             # type not an enum
    dict(tool="t", action="read", level=G, resource_type=ResourceType.OTHER, resource="a\x00b"),
    dict(tool="t", action="read", level=G, resource_type=ResourceType.OTHER, resource="a\nb"),
    dict(tool="t", action="read", level=G, resource_type=ResourceType.OTHER, resource="x" * 5000),
    dict(tool="t", action="read", level=G, reason="x" * 501), dict(tool="t", action="read", level=G, reason=7),
    dict(tool="t", action="read", level=G, context={"a": 1}), dict(tool="t", action="read", level=G, context="x"),
    dict(tool="t", action="read", level=G, context={str(i): "v" for i in range(21)}),
    dict(tool="t", action="read", level=G, id=""), dict(tool="t", action="read", level=G, id=None),
    dict(tool="t", action="read", level=G, timestamp="now"),
    dict(tool="t", action="read", level=G, args_fingerprint=5),
]


@pytest.mark.parametrize("fields", BAD)
def test_malformed_requests_are_invalid_not_crashes(tmp_path, fields):
    engine, sink, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE]))
    d = engine.authorize(PermissionRequest(**fields))
    assert d.status is DecisionStatus.INVALID_REQUEST and d.denied and d.is_error and not d.allowed
    assert engine.evaluate(PermissionRequest(**fields)).status is DecisionStatus.INVALID_REQUEST
    assert "permission_denied" in types(sink)
    with pytest.raises(InvalidRequestError):
        PermissionRequest.create(**fields)


@pytest.mark.parametrize("junk", [None, {}, "read file", 42, object(), {"tool": "t", "action": "read"}, ["t"]])
def test_non_request_objects_are_invalid(tmp_path, junk):
    engine, _, _ = make_engine(tmp_path)
    d = engine.authorize(junk)
    assert d.status is DecisionStatus.INVALID_REQUEST and not d.allowed and d.request_id is None


def test_create_rejects_unknown_fields_and_accepts_valid():
    with pytest.raises(InvalidRequestError):
        PermissionRequest.create(tool="t", action="read", level=G, bogus=1)
    with pytest.raises(InvalidRequestError):
        PermissionRequest.create(tool="t", action="read")  # level missing
    r = PermissionRequest.create(tool="fs", action="read", level=G, resource="x", resource_type=ResourceType.PATH,
                                 reason="why", context={"k": "v"})
    assert r.id and r.timestamp.tzinfo is not None and len({PermissionRequest.create(tool="t", action="a", level=G).id
                                                              for _ in range(50)}) == 50


def test_path_request_with_unresolvable_path_is_invalid(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    d = engine.authorize(PermissionRequest(tool="fs", action="read", level=G, resource="a\x00b",
                                           resource_type=ResourceType.PATH))
    assert d.status is DecisionStatus.INVALID_REQUEST


# ---- fail closed ---------------------------------------------------------------------------------------------------------------------------
def test_unexpected_exception_becomes_internal_error_denial(tmp_path, monkeypatch):
    engine, sink, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE]))
    monkeypatch.setattr(engine, "_evaluate", lambda r: (_ for _ in ()).throw(RuntimeError("boom api_key=hunter22abc")))
    for call in (engine.authorize, engine.evaluate):
        d = call(req(level=Y, action="send"))
        assert d.status is DecisionStatus.INTERNAL_ERROR and d.is_error and not d.allowed
        assert "hunter22abc" not in d.reason and "boom" not in d.reason
    assert "security_error" in types(sink)
    assert all("hunter22abc" not in json.dumps(e.to_dict()) for e in sink.events)


def test_broken_policy_evaluation_is_a_policy_error_denial(tmp_path, monkeypatch):
    engine, _, _ = make_engine(tmp_path, rules=[{"id": "x", "effect": "deny", "tool": "zzz"}])
    monkeypatch.setattr(Policy, "verdict", lambda *a: (_ for _ in ()).throw(ValueError("bad rule")))
    d = engine.authorize(req())  # even a GREEN request: unknown policy state -> deny
    assert d.status is DecisionStatus.POLICY_ERROR and d.is_error and not d.allowed


def test_invalid_policy_cannot_be_installed_and_old_policy_stays(tmp_path):
    engine, sink, ws = make_engine(tmp_path, rules=[{"id": "keep", "effect": "deny", "tool": "bad"}])
    with pytest.raises(PolicyError):
        Policy.from_rules([{"id": "p", "effect": "allow"}])
    nul_rule = Policy(rules=Policy.from_rules([{"id": "n", "effect": "deny", "resource_type": "path",
                                                "resources": ["bad\x00path"]}]).rules)
    with pytest.raises(PolicyError):
        engine.update_policy(nul_rule)
    assert [r.id for r in engine.policy.rules] == ["keep"]
    assert engine.authorize(req(tool="bad")).denied


def test_engine_construction_validates_policy_paths(tmp_path):
    p = Policy.from_rules([{"id": "n", "effect": "deny", "resource_type": "path", "resources": ["a\x00b"]}])
    with pytest.raises(PolicyError):
        PermissionEngine(policy=p)


class Exploding(ConfirmationProvider):
    def confirm(self, request):
        raise RuntimeError("provider crashed token=abcd1234efgh")


@pytest.mark.parametrize("provider", [
    Exploding(),
    type("Bool", (ConfirmationProvider,), {"confirm": lambda s, r: True})(),
    type("None", (ConfirmationProvider,), {"confirm": lambda s, r: None})(),
    type("Str", (ConfirmationProvider,), {"confirm": lambda s, r: "allow_once"})(),
    type("Yes", (ConfirmationProvider,), {"confirm": lambda s, r: 1})(),
])
def test_confirmation_provider_misbehaviour_is_a_denial(tmp_path, provider):
    engine, sink, _ = make_engine(tmp_path, confirmation=provider)
    d = engine.authorize(req(level=Y, action="send"))
    assert d.denied and not d.allowed
    assert "security_error" in types(sink) or "confirmation_rejected" in types(sink)
    assert all("abcd1234efgh" not in json.dumps(e.to_dict()) for e in sink.events)


def test_non_interactive_authorize_never_prompts(tmp_path):
    prompts = ScriptedConfirmation([ONCE])
    engine, _, _ = make_engine(tmp_path, confirmation=prompts)
    d = engine.authorize(req(level=Y, action="send"), interactive=False)
    assert d.needs_confirmation and prompts.requests == []


# ---- caller-asserted confirmation (legacy flag) ---------------------------------------------------------------------------------------------
def test_strict_engine_ignores_caller_confirmation_and_audits_it(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    d = engine.authorize(req(level=Y, action="send"), caller_confirmed=True)
    assert d.needs_confirmation and not d.allowed
    assert "caller_confirmation_ignored" in types(sink)


def test_legacy_engine_honours_caller_confirmation_but_not_against_confirm_rules():
    engine = PermissionEngine.legacy()
    d = engine.authorize(req(level=Y, action="send"), caller_confirmed=True)
    assert d.allowed and d.scope is GrantScope.ASSERTED
    assert engine.authorize(req(level=Y, action="send")).needs_confirmation
    assert engine.authorize(req(level=R), caller_confirmed=True).denied
    engine.update_policy(Policy.from_rules([{"id": "ask", "effect": "confirm", "tool": "t"}]))
    assert engine.authorize(req(level=Y, action="send"), caller_confirmed=True).needs_confirmation


# ---- single-use approvals and execution scopes ---------------------------------------------------------------------------------------------------
def test_approval_is_single_use(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    r = req()
    d = engine.authorize(r)
    with engine.execution_scope(r, d) as grant:
        assert isinstance(grant, ExecutionGrant) and grant.request_id == r.id
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(r, d):
            pass


def test_a_forged_or_foreign_decision_gets_no_scope(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    r = req(level=Y, action="send")
    forged = PermissionDecision(DecisionStatus.ALLOWED, "trust me", r.id, Y, scope=GrantScope.ONCE)
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(r, forged):
            pass
    assert "security_error" in types(sink)
    # a real approval for ANOTHER request cannot be reused
    other = req()
    d_other = engine.authorize(other)
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(r, d_other):
            pass
    # a denied decision never yields a scope
    denied = engine.authorize(req(level=R))
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(req(level=R), denied):
            pass


def test_approval_is_bound_to_the_arguments(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    approved = replace(req(), args_fingerprint="aaa")
    d = engine.authorize(approved)
    swapped = replace(approved, args_fingerprint="bbb")  # same id, different arguments
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(swapped, d):
            pass


def test_approval_expires(tmp_path):
    now = [0.0]
    engine, _, _ = make_engine(tmp_path, clock=lambda: now[0])
    r = req()
    d = engine.authorize(r)
    now[0] += 61
    with pytest.raises(PermissionDeniedError):
        with engine.execution_scope(r, d):
            pass


def test_execution_grants_cannot_be_constructed_by_hand():
    with pytest.raises(PermissionDeniedError):
        ExecutionGrant("t", "read", None, "id")
    with pytest.raises(PermissionDeniedError):
        ExecutionGrant("t", "read", None, "id", _seal=object())


# ---- audit ------------------------------------------------------------------------------------------------------------------------------------------
def test_denial_flow_is_audited(tmp_path):
    engine, sink, _ = make_engine(tmp_path, rules=[{"id": "no", "effect": "deny", "tool": "t"}])
    engine.authorize(req(reason="because"))
    assert types(sink) == ["permission_requested", "permission_denied"]
    e = sink.events[-1]
    assert (e.tool, e.action, e.status, e.rule) == ("t", "read", "denied", "no") and e.request_id


def test_policy_events_and_session_revocation(tmp_path):
    engine, sink, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([SESSION]),
                                  rules=[{"id": "old", "effect": "deny", "tool": "x"}])
    engine.authorize(req(level=Y, action="send"))
    engine.update_policy(Policy.from_rules([{"id": "new", "effect": "deny", "tool": "y"}]), source="test")
    ev = sink.events[-1]
    assert ev.type is AuditEventType.POLICY_CHANGED and ev.extra["added"] == "new" and ev.extra["removed"] == "old"
    assert "test" in ev.detail and ev.extra["fingerprint"]
    assert engine.session_grants() == []  # policy change revokes session permissions
    engine.note_policy_loaded("config/policy.toml")
    assert sink.events[-1].type is AuditEventType.POLICY_LOADED


def test_tool_registration_and_execution_are_audited_only_when_consequential(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    engine.note_tool_registered("echo", G)
    assert list(sink.events) == []
    engine.note_tool_registered("shell", Y)
    engine.note_tool_registered("mystery", None)  # undeclared counts as YELLOW
    assert [e.type.value for e in sink.events] == ["tool_registered"] * 2
    d = engine.authorize(req(level=Y, action="send"), caller_confirmed=False, interactive=False)
    engine.record_execution(req(), PermissionDecision(DecisionStatus.ALLOWED, "x", level=G), True)
    assert types(sink)[-1] != "execution_result"  # GREEN outcome is not logged
    engine.record_execution(req(), PermissionDecision(DecisionStatus.ALLOWED, "x", level=Y), False, "oops")
    assert sink.events[-1].type is AuditEventType.EXECUTION_RESULT and "failed: oops" in sink.events[-1].detail


class BrokenSink(AuditSink):
    def record(self, event):
        raise OSError("disk full")


def test_audit_failure_fails_closed_for_non_green(tmp_path):
    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE]), audit_green=True)
    engine.audit.sinks.append(BrokenSink())
    assert engine.authorize(req(level=Y, action="send")).status is DecisionStatus.INTERNAL_ERROR
    # GREEN actions keep working when the log is down (a dead log must not paralyse harmless reads)
    quiet, _, _ = make_engine(tmp_path)
    quiet.audit.sinks.append(BrokenSink())
    assert quiet.authorize(req()).allowed


def test_audit_failure_policy_is_configurable(tmp_path):
    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE]), audit_strict=False)
    engine.audit.sinks.append(BrokenSink())
    assert engine.authorize(req(level=Y, action="send")).allowed


def test_audit_logger_survives_sink_errors_and_reports_them():
    logger = AuditLogger([BrokenSink(), MemoryAuditSink()])
    from jarvis.permissions import AuditEvent
    assert logger.record(AuditEvent(AuditEventType.SECURITY_ERROR)) is False
    assert AuditLogger([NullAuditSink()]).record(AuditEvent(AuditEventType.SECURITY_ERROR)) is True
    assert AuditLogger().record(AuditEvent(AuditEventType.SECURITY_ERROR)) is True


def test_jsonl_sink_writes_owner_only_json_lines_lazily(tmp_path):
    path = tmp_path / "logs" / "audit.jsonl"
    sink = JsonlAuditSink(path)
    assert not path.exists() and sink.tail() == []
    engine, _, _ = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE]))
    engine.audit.sinks.append(sink)
    engine.authorize(req(level=Y, action="send", reason="Mail an Anna"))
    lines = path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(ln) for ln in lines]
    assert [e["type"] for e in events] == ["permission_requested", "confirmation_requested", "confirmation_accepted",
                                           "permission_granted"]
    assert all(e["id"] and e["timestamp"] for e in events) and events[-1]["scope"] == "once"
    assert [e["type"] for e in sink.tail(2)] == ["confirmation_accepted", "permission_granted"]
    if os.name == "posix":
        assert (path.stat().st_mode & 0o077) == 0  # not readable by others
    path.write_text(path.read_text() + "not json\n")
    assert sink.tail(1) == [{"type": "unreadable_line"}]


def test_audit_log_has_no_conversation_content(tmp_path):
    engine, sink, _ = make_engine(tmp_path)
    engine.authorize(req())
    engine.authorize(req(tool="chat", action="reply"))
    assert list(sink.events) == []


# ---- secrets never leak ----------------------------------------------------------------------------------------------------------------------------------------
SECRETS = ["sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123", "password=hunter22abc", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"]


@pytest.mark.parametrize("secret", SECRETS + ["plain-known-secret-4711"])
def test_secrets_never_appear_in_decisions_prompts_or_audit(tmp_path, secret):
    prompts = ScriptedConfirmation([ONCE, NO, ONCE])
    red = SecretDetector(known_secrets=["plain-known-secret-4711"])
    engine, sink, ws = make_engine(tmp_path, confirmation=prompts, redactor=red)
    r = PermissionRequest(tool="mail", action="send", level=Y, resource=f"anna {secret}",
                          resource_type=ResourceType.OTHER, reason=f"use {secret} to log in",
                          context={"note": f"token is {secret}", "api_key": "whatever-value", "ok": "fine"})
    for d in (engine.authorize(r), engine.authorize(replace(r, id="second")), engine.evaluate(r)):
        blob = json.dumps(d.to_dict())
        assert secret not in blob and secret not in d.reason
    shown = prompts.requests[0]
    text = shown.to_text() + shown.summary + json.dumps(dict(shown.context))
    assert secret not in text and "whatever-value" not in text and "[REDACTED]" in text and "fine" in text
    audit_blob = json.dumps([e.to_dict() for e in sink.events])
    assert secret not in audit_blob and "whatever-value" not in audit_blob
    assert secret not in repr(r) and secret not in str(engine.describe())
    assert secret not in repr(engine.authorize(replace(r, id="third")))


def test_audit_file_contains_no_secrets(tmp_path):
    path = tmp_path / "audit.jsonl"
    red = SecretDetector(known_secrets=["plain-known-secret-4711"])
    engine, _, _ = make_engine(tmp_path, redactor=red, confirmation=ScriptedConfirmation([ONCE]))
    engine.audit.sinks[:] = [JsonlAuditSink(path)]
    engine.authorize(PermissionRequest(tool="mail", action="send", level=Y, reason="login plain-known-secret-4711 and "
                                       "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123", context={"password": "pw12345678"}))
    raw = path.read_text()
    assert "plain-known-secret-4711" not in raw and "sk-ant-api03" not in raw and "pw12345678" not in raw


def test_engine_redact_helper(tmp_path):
    engine, _, _ = make_engine(tmp_path, redactor=SecretDetector(known_secrets=["my-known-secret-xyz"]))
    assert engine.redact("a my-known-secret-xyz b password=abcdefg c") == "a [REDACTED] b [REDACTED] c"
    assert engine.redact(None) == "None" and engine.redact(123) == "123"


# ---- confirmation request content ----------------------------------------------------------------------------------------------------------------------------------
def test_confirmation_request_shows_what_the_user_needs_to_decide(tmp_path):
    prompts = ScriptedConfirmation([NO])
    engine, _, ws = make_engine(tmp_path, confirmation=prompts)
    engine.authorize(path_req("notes.md", reason="Notiz aktualisieren", context={"zeilen": "3"}))
    c = prompts.requests[0]
    assert (c.tool, c.action, c.level, c.session_allowed) == ("filesystem", "write", Y, True)
    assert c.resource == str(ws / "notes.md") and c.context["angefragter Pfad"] == "notes.md"
    text = c.to_text()
    for expected in ("JARVIS möchte", "Aktion: write", "Werkzeug: filesystem", "Risiko: YELLOW", "Grund: Notiz aktualisieren",
                     "zeilen: 3", "Erlauben?"):
        assert expected in text


def test_confirmation_shows_the_real_path_behind_a_symlink(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX symlinks")
    prompts = ScriptedConfirmation([NO])
    engine, _, ws = make_engine(tmp_path, confirmation=prompts)
    (ws / "sub").mkdir()
    (ws / "alias").symlink_to(ws / "sub", target_is_directory=True)
    engine.authorize(path_req("alias/f.txt"))
    assert prompts.requests[0].resource == str(ws / "sub" / "f.txt")


# ---- concurrency ---------------------------------------------------------------------------------------------------------------------------------------------------------
class Slow(ConfirmationProvider):
    def __init__(self, choice):
        self.choice, self.calls, self.active, self.max_active = choice, 0, 0, 0
        self._lock = threading.Lock()

    def confirm(self, request):
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        with self._lock:
            self.active -= 1
        return self.choice


def run_threads(n, fn):
    results, errors = [None] * n, []

    def work(i):
        try:
            results[i] = fn(i)
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    return results


def test_concurrent_requests_with_session_answer_prompt_once(tmp_path):
    provider = Slow(SESSION)
    engine, _, _ = make_engine(tmp_path, confirmation=provider)
    res = run_threads(20, lambda i: engine.authorize(req(level=Y, action="send")))
    assert all(d.allowed for d in res) and provider.calls == 1  # the others re-checked inside the lock
    assert {d.scope for d in res} == {GrantScope.SESSION}


def test_concurrent_one_time_confirmations_are_serialised_and_independent(tmp_path):
    provider = Slow(ONCE)
    engine, _, _ = make_engine(tmp_path, confirmation=provider)
    reqs = [req(level=Y, action="send") for _ in range(15)]
    res = run_threads(15, lambda i: engine.authorize(reqs[i]))
    assert all(d.allowed and d.scope is GrantScope.ONCE for d in res)
    assert provider.calls == 15 and provider.max_active == 1  # never two prompts at once
    for r, d in zip(reqs, res):  # every approval is usable exactly once, by its own request
        with engine.execution_scope(r, d):
            pass
        with pytest.raises(PermissionDeniedError):
            with engine.execution_scope(r, d):
                pass


def test_concurrent_denials_stay_denied(tmp_path):
    provider = Slow(NO)
    engine, _, _ = make_engine(tmp_path, confirmation=provider)
    assert not any(d.allowed for d in run_threads(10, lambda i: engine.authorize(req(level=Y, action="send"))))


def test_concurrent_mixed_requests_and_policy_updates(tmp_path):
    engine, _, _ = make_engine(tmp_path, confirmation=Slow(ONCE))
    deny = Policy.from_rules([{"id": "d", "effect": "deny", "tool": "x"}])

    def work(i):
        if i % 5 == 0:
            engine.update_policy(deny if i % 10 == 0 else Policy())
        return engine.authorize(req(level=G if i % 2 else Y, action="read" if i % 2 else "send"))

    res = run_threads(40, work)
    assert all(d.status in (DecisionStatus.ALLOWED, DecisionStatus.DENIED) for d in res)


# ---- misc API ------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_describe_reports_configuration(tmp_path):
    engine, _, ws = make_engine(tmp_path, rules=[{"id": "r", "effect": "deny", "tool": "x"}],
                                confirmation=DenyAllConfirmation())
    d = engine.describe()
    assert d["mode"] == "standard" and d["roots"] == [str(ws)] and d["rules"][0]["id"] == "r"
    assert d["confirmation"] == "DenyAllConfirmation" and d["policy_fingerprint"]


def test_decision_helpers():
    ok = PermissionDecision(DecisionStatus.ALLOWED, "x", scope=GrantScope.ONCE)
    assert ok.allowed and not ok.denied and not ok.needs_confirmation and not ok.is_error
    assert PermissionDecision(DecisionStatus.CONFIRMATION_REQUIRED, "x").needs_confirmation
    assert not PermissionDecision(DecisionStatus.CONFIRMATION_REQUIRED, "x").denied
    for s in (DecisionStatus.INVALID_REQUEST, DecisionStatus.POLICY_ERROR, DecisionStatus.INTERNAL_ERROR):
        d = PermissionDecision(s, "x")
        assert d.is_error and d.denied and not d.allowed
    assert ok.to_dict()["scope"] == "once"


def test_levels():
    assert G.rank < Y.rank < R.rank
    from jarvis.permissions import is_allowed, max_level
    assert max_level(G, Y) is Y and max_level(R, G, Y) is R and max_level(G) is G
    assert is_allowed(G) and not is_allowed(Y) and is_allowed(Y, True) and not is_allowed(R, True)
