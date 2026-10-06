"""Rules: validation, matching, deterministic conflict resolution, policy files."""
import itertools
from pathlib import Path

import pytest

from jarvis.errors import PolicyError
from jarvis.permissions import Effect, PathGuard, PermissionLevel, Policy, ResourceType, Rule
from secutil import G, R, Y, path_req, req

REPO = Path(__file__).resolve().parent.parent


def rule(**kw):
    kw.setdefault("id", "r")
    kw.setdefault("effect", "deny")
    return Rule.from_dict(kw)


@pytest.fixture
def guard(tmp_path):
    (tmp_path / "ws").mkdir()
    return PathGuard([tmp_path / "ws"], base_dir=tmp_path / "ws")


# ---- validation: no unrestricted allow --------------------------------------------------------------------
@pytest.mark.parametrize("data", [
    {"effect": "allow"},                                                    # no tool, no action
    {"effect": "allow", "tool": "*", "action": "write"},                     # wildcard tool
    {"effect": "allow", "tool": "fs*", "action": "write"},                   # glob tool
    {"effect": "allow", "tool": "filesystem"},                               # no action
    {"effect": "allow", "tool": "filesystem", "action": "*"},                # bare wildcard action
    {"effect": "allow", "tool": "filesystem", "action": "write", "levels": ["red"]},   # RED can never be allowed
    {"effect": "allow", "tool": "filesystem", "action": "write", "resource_type": "path", "resources": ["*"]},
    {"effect": "allow", "tool": "filesystem", "action": "write", "resource_type": "path", "resources": ["/"]},
    {"effect": "allow", "tool": "browser", "action": "navigate", "resource_type": "domain", "resources": ["*.com"]},
    {"effect": "deny", "resource_type": "path"} | {"resources": ["a"], "resource_type": None},   # resources w/o type
    {"effect": "deny", "resources": ["x"]},                                  # resources without resource_type
    {"effect": "bogus"}, {"effect": ""}, {},                                 # bad effect
    {"effect": "deny", "bogus_key": 1}, {"effect": "deny", "levels": ["purple"]},
    {"effect": "deny", "resource_type": "nonsense"}, {"effect": "deny", "tool": 5},
    {"effect": "deny", "resource_type": "path", "resources": "not-a-list"},
    {"effect": "deny", "resource_type": "path", "resources": [""]},
])
def test_invalid_rules_are_rejected(data):
    with pytest.raises(PolicyError):
        Rule.from_dict({"id": "x", **data})


def test_rule_needs_an_id():
    with pytest.raises(PolicyError):
        Rule.from_dict({"effect": "deny"})
    with pytest.raises(PolicyError):
        Rule.from_dict({"id": " ", "effect": "deny"})


def test_non_table_rule_rejected():
    with pytest.raises(PolicyError):
        Rule.from_dict("deny everything")  # type: ignore[arg-type]


def test_duplicate_ids_rejected():
    with pytest.raises(PolicyError, match="duplicate"):
        Policy.from_rules([{"id": "a", "effect": "deny"}, {"id": "a", "effect": "confirm"}])


def test_deny_and_confirm_may_be_broad_but_allow_may_not():
    assert Policy.from_rules([{"id": "d", "effect": "deny"}, {"id": "c", "effect": "confirm", "tool": "*"}])


# ---- matching ----------------------------------------------------------------------------------------------------
def test_tool_and_action_exact_and_glob(guard):
    r = rule(tool="filesystem", action="delete*")
    assert r.matches(req(tool="filesystem", action="delete_file"), G, None, guard)
    assert r.matches(req(tool="filesystem", action="delete"), G, None, guard)
    assert not r.matches(req(tool="filesystem", action="write"), G, None, guard)
    assert not r.matches(req(tool="terminal", action="delete"), G, None, guard)
    assert not r.matches(req(tool="filesystem2", action="delete"), G, None, guard)  # exact means exact


def test_matching_is_case_sensitive(guard):
    assert not rule(tool="Filesystem").matches(req(tool="filesystem"), G, None, guard)


def test_levels_filter(guard):
    r = rule(effect="confirm", levels=["green"])
    assert r.matches(req(), G, None, guard) and not r.matches(req(level=Y), Y, None, guard)


def test_path_rule_uses_real_containment(guard, tmp_path):
    ws = tmp_path / "ws"
    r = rule(resource_type="path", resources=[str(ws / "notes")])
    rq = path_req(ws / "notes" / "a.txt")
    assert r.matches(rq, Y, str(ws / "notes" / "a.txt"), guard)
    assert r.matches(rq, Y, str(ws / "notes"), guard)  # the directory itself
    assert not r.matches(rq, Y, str(ws / "notes-evil" / "a"), guard)  # prefix trap
    assert not r.matches(rq, Y, str(ws / "other"), guard)


def test_relative_rule_path_is_relative_to_project_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "workspace").mkdir()
    g = PathGuard(["workspace"])
    r = rule(resource_type="path", resources=["workspace/notes"])
    assert r.matches(path_req("x"), Y, str(tmp_path / "workspace" / "notes" / "a"), g)


def test_domain_rule(guard):
    r = rule(resource_type="domain", resources=["docs.python.org", "*.example.com"])
    dom = lambda h: req(tool="browser", action="navigate", level=Y, resource=h, resource_type=ResourceType.DOMAIN)  # noqa: E731
    assert r.matches(dom("docs.python.org"), Y, "docs.python.org", guard)
    assert r.matches(dom("a.example.com"), Y, "a.example.com", guard)
    assert not r.matches(dom("example.com"), Y, "example.com", guard)
    assert not r.matches(dom("docs.python.org.evil.org"), Y, "docs.python.org.evil.org", guard)


def test_other_resource_glob(guard):
    r = rule(resource_type="other", resources=["order-*"])
    o = lambda v: req(resource=v, resource_type=ResourceType.OTHER)  # noqa: E731
    assert r.matches(o("order-7"), G, "order-7", guard) and not r.matches(o("invoice-7"), G, "invoice-7", guard)


def test_resource_type_mismatch_does_not_match(guard):
    r = rule(resource_type="path", resources=["x"])
    other = req(resource="docs.python.org", resource_type=ResourceType.DOMAIN)
    assert not r.matches(other, G, "docs.python.org", guard)


def test_missing_resource_info_is_conservative(guard):
    """No resource on the request: deny/confirm rules with resource constraints still apply; allow rules never do."""
    no_resource = req(tool="filesystem", action="write", level=Y)
    path_rule = dict(resource_type="path", resources=["/tmp/x"], tool="filesystem")
    assert rule(effect="deny", **path_rule).matches(no_resource, Y, None, guard)
    assert rule(effect="confirm", **path_rule).matches(no_resource, Y, None, guard)
    assert not rule(effect="allow", action="write", **path_rule).matches(no_resource, Y, None, guard)
    typed_but_unresolved = path_req("whatever")
    assert not rule(effect="allow", action="write", **path_rule).matches(typed_but_unresolved, Y, None, guard)
    assert rule(effect="deny", **path_rule).matches(typed_but_unresolved, Y, None, guard)


# ---- conflict resolution: safest effect wins, order never matters ---------------------------------------------------
RULES = [
    {"id": "a-allow", "effect": "allow", "tool": "filesystem", "action": "write"},
    {"id": "b-confirm", "effect": "confirm", "tool": "filesystem"},
    {"id": "c-deny", "effect": "deny", "tool": "filesystem", "action": "wr*"},
    {"id": "d-deny", "effect": "deny", "action": "write"},
]


def test_deny_beats_confirm_beats_allow(guard):
    rq = req(tool="filesystem", action="write", level=Y)
    v = Policy.from_rules(RULES).verdict(rq, Y, None, guard)
    assert v.effect is Effect.DENY and v.rule == "c-deny"  # ties on effect: lowest id, deterministic
    assert v.considered == ("c-deny", "d-deny", "b-confirm", "a-allow")
    v = Policy.from_rules(RULES[:2]).verdict(rq, Y, None, guard)
    assert v.effect is Effect.CONFIRM and v.rule == "b-confirm"
    v = Policy.from_rules(RULES[:1]).verdict(rq, Y, None, guard)
    assert v.effect is Effect.ALLOW


def test_rule_order_never_changes_the_outcome(guard):
    rq = req(tool="filesystem", action="write", level=Y)
    results = {(v.effect, v.rule, v.considered) for perm in itertools.permutations(RULES)
               for v in [Policy.from_rules(perm).verdict(rq, Y, None, guard)]}
    assert len(results) == 1


def test_no_matching_rule_is_a_neutral_verdict(guard):
    v = Policy.from_rules(RULES).verdict(req(tool="other"), G, None, guard)
    assert v.effect is None and v.rule is None and v.considered == ()
    assert Policy().verdict(req(), G, None, guard).effect is None


def test_policy_fingerprint_is_order_independent_and_content_sensitive():
    a, b = Policy.from_rules(RULES), Policy.from_rules(list(reversed(RULES)))
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != Policy.from_rules(RULES[:3]).fingerprint


# ---- policy files ------------------------------------------------------------------------------------------------------
def test_example_policy_file_is_valid_and_safe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    policy = Policy.from_file(REPO / "config" / "policy.example.toml")
    assert {r.id for r in policy.rules} == {"never-touch-ssh", "confirm-deletes", "trust-notes-edits", "trust-docs-site"}
    allow = [r for r in policy.rules if r.is_allow]
    assert all(r.tool and r.action and r.resources for r in allow)  # nothing unrestricted
    policy.validate_paths(PathGuard([tmp_path / "workspace"]))


def test_policy_file_errors(tmp_path):
    with pytest.raises(PolicyError, match="not found"):
        Policy.from_file(tmp_path / "missing.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("[[rule]\nid = ")
    with pytest.raises(PolicyError, match="cannot read"):
        Policy.from_file(bad)
    bad.write_text('[[rule]]\nid = "x"\neffect = "allow"\n')  # unrestricted allow
    with pytest.raises(PolicyError):
        Policy.from_file(bad)
    bad.write_text('rules = []\n')
    with pytest.raises(PolicyError, match="top-level"):
        Policy.from_file(bad)
    bad.write_text('rule = "oops"\n')
    with pytest.raises(PolicyError):
        Policy.from_file(bad)
    bad.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(PolicyError):
        Policy.from_file(bad)


def test_empty_policy_file_is_valid(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text("")
    assert Policy.from_file(f).rules == ()
