"""[security] configuration, engine factory/bootstrap, CLI confirmation + commands, architectural independence."""
import ast
import json
import os
from pathlib import Path

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import SecuritySettings, Settings, load_settings
from jarvis.errors import ConfigError, PolicyError, ToolError
from jarvis.interface.cli import main, repl, run_command
from jarvis.permissions import (CliConfirmation, ConfirmationChoice, ConfirmationRequest, DenyAllConfirmation,
                                PermissionLevel, PermissionMode, ScriptedConfirmation)
from jarvis.permissions.factory import build_permission_engine
from jarvis.redaction import SecretDetector
from jarvis.tools import Tool, ToolResult
from secutil import G, Y

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
REPO = SRC.parent.parent


def settings_for(tmp_path, **env):
    base = {"JARVIS_WORKSPACE": str(tmp_path / "ws"), "JARVIS_LOG_DIR": str(tmp_path / "logs"),
            "JARVIS_MEMORY_PATH": str(tmp_path / "m.db")}
    (tmp_path / "ws").mkdir(exist_ok=True)
    return load_settings(env={**base, **{k: str(v) for k, v in env.items()}})


# ---- configuration -----------------------------------------------------------------------------------------------
def test_security_defaults_are_restrictive():
    s = load_settings(env={})
    sec = s.security
    assert sec == SecuritySettings()
    assert (sec.mode, sec.confirmation, sec.policy_file, sec.allowed_roots, sec.denied_paths) == \
           ("standard", "cli", None, (), ())
    assert sec.allow_session_grants and sec.audit_enabled and sec.audit_strict and not sec.audit_green
    assert s.effective_fs_roots == (s.workspace,)  # nothing but the workspace; no manual setup needed
    assert s.effective_audit_path == str(Path(s.log_dir) / "audit.jsonl")


def q(path):
    """TOML basic-string literal for a path (Windows backslashes must be escaped)."""
    return json.dumps(str(path))


def test_security_config_from_file_and_env(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[security]\nmode = "lockdown"\nallowed_roots = ["a", "b"]\ndenied_paths = ["a/private"]\n'
                 'session_ttl_seconds = 60\naudit_path = "x/audit.jsonl"\n')
    s = load_settings(f, env={"JARVIS_SECURITY_CONFIRMATION": "deny",
                              "JARVIS_SECURITY_DENIED_PATHS": os.pathsep.join(["p", "q"]),
                              "JARVIS_SECURITY_AUDIT_STRICT": "false"})
    sec = s.security
    assert (sec.mode, sec.allowed_roots, sec.confirmation, sec.session_ttl_seconds) == ("lockdown", ("a", "b"), "deny", 60)
    assert sec.denied_paths == ("p", "q") and sec.audit_strict is False and s.effective_audit_path == "x/audit.jsonl"
    assert s.effective_fs_roots == ("a", "b")


@pytest.mark.parametrize("env", [
    {"JARVIS_SECURITY_MODE": "permissive"}, {"JARVIS_SECURITY_MODE": "off"}, {"JARVIS_SECURITY_MODE": ""},
    {"JARVIS_SECURITY_CONFIRMATION": "auto"}, {"JARVIS_SECURITY_CONFIRMATION": "always-yes"},
    {"JARVIS_SECURITY_SESSION_TTL_SECONDS": "0"}, {"JARVIS_SECURITY_SESSION_TTL_SECONDS": "-5"},
    {"JARVIS_SECURITY_SESSION_TTL_SECONDS": "soon"},
])
def test_invalid_security_config_is_rejected(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


@pytest.mark.parametrize("toml", ['[security]\nallowed_roots = ["ok", ""]\n', '[security]\nallowed_roots = 5\n',
                                  '[security]\ndenied_paths = [1]\n', '[security]\nallow_red = true\n',
                                  '[security]\nunrestricted = true\n', '[security]\nbypass_confirmation = true\n'])
def test_invalid_security_file_is_rejected_and_has_no_bypass_switches(tmp_path, toml):
    f = tmp_path / "c.toml"
    f.write_text(toml)
    with pytest.raises(ConfigError):
        load_settings(f, env={})


def test_repo_config_and_example_policy_match_the_defaults():
    assert load_settings(REPO / "config" / "jarvis.toml", env={}).security == SecuritySettings()


# ---- engine factory ----------------------------------------------------------------------------------------------------
def test_factory_builds_a_strict_engine_from_defaults(tmp_path):
    s = settings_for(tmp_path)
    e = build_permission_engine(s)
    assert e.mode is PermissionMode.STANDARD and e.require_protected_tools and not e.trust_caller_confirmation
    assert e.undeclared_level is PermissionLevel.YELLOW and e.audit_strict and e.allow_session_grants
    assert isinstance(e.confirmation, CliConfirmation)
    assert e.guard.allowed_roots == [str((tmp_path / "ws").resolve())]
    assert e.guard.base_dir == e.guard.allowed_roots[0]


def test_factory_honours_mode_and_confirmation(tmp_path):
    e = build_permission_engine(settings_for(tmp_path, JARVIS_SECURITY_MODE="lockdown", JARVIS_SECURITY_CONFIRMATION="deny"))
    assert e.mode is PermissionMode.LOCKDOWN and isinstance(e.confirmation, DenyAllConfirmation)


def test_factory_refuses_the_filesystem_root(tmp_path):
    with pytest.raises(PolicyError, match="filesystem root"):
        build_permission_engine(settings_for(tmp_path, JARVIS_SECURITY_ALLOWED_ROOTS="/"))


def test_missing_or_broken_policy_file_is_a_startup_error_not_a_fallback(tmp_path):
    with pytest.raises(PolicyError, match="not found"):
        build_permission_engine(settings_for(tmp_path, JARVIS_SECURITY_POLICY_FILE=tmp_path / "nope.toml"))
    bad = tmp_path / "policy.toml"
    bad.write_text('[[rule]]\nid = "x"\neffect = "allow"\n')
    with pytest.raises(PolicyError):
        build_permission_engine(settings_for(tmp_path, JARVIS_SECURITY_POLICY_FILE=bad))
    with pytest.raises(PolicyError):
        build_core(settings_for(tmp_path, JARVIS_SECURITY_POLICY_FILE=bad))


def test_main_refuses_to_start_with_a_broken_policy(tmp_path, capsys):
    bad = tmp_path / "policy.toml"
    bad.write_text("[[rule]\n")
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'workspace = {q(tmp_path / "ws")}\nlog_dir = {q(tmp_path / "logs")}\n[security]\npolicy_file = {q(bad)}\n'
                   f'[memory]\npath = {q(tmp_path / "m.db")}\n')
    assert main(["-c", str(cfg)]) == 2
    assert "Startfehler" in capsys.readouterr().err


def test_policy_file_is_applied_and_its_load_is_audited(tmp_path):
    policy = tmp_path / "policy.toml"
    ws = tmp_path / "ws"
    policy.write_text(f'[[rule]]\nid = "trust"\neffect = "allow"\ntool = "permission_demo"\naction = "write"\n'
                      f'resource_type = "path"\nresources = [{q(ws / "notes")}]\n'
                      f'[[rule]]\nid = "never"\neffect = "deny"\ntool = "permission_demo"\nresource_type = "path"\n'
                      f'resources = [{q(ws / "vault")}]\n')
    core = build_core(settings_for(tmp_path, JARVIS_SECURITY_POLICY_FILE=policy, JARVIS_SECURITY_CONFIRMATION="deny"))
    r = core.tools.execute("permission_demo", target="notes/a.txt")
    assert r.success and r.permission.matched_rule == "trust"  # explicit persistent permission: no question
    assert not core.tools.execute("permission_demo", target="other/a.txt").success  # headless: YELLOW denied
    d = core.tools.execute("permission_demo", target="vault/a.txt").permission
    assert d.matched_rule == "never"
    events = [json.loads(ln) for ln in (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[0]["type"] == "policy_loaded" and events[0]["extra"]["rules"] == "2"


def test_policy_and_audit_files_inside_the_workspace_cannot_be_modified_by_tools(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    policy = ws / "policy.toml"
    policy.write_text('[[rule]]\nid = "trust-all-writes-here"\neffect = "allow"\ntool = "permission_demo"\naction = "write"\n'
                      'resource_type = "path"\nresources = [' + q(ws) + ']\n')
    core = build_core(settings_for(tmp_path, JARVIS_SECURITY_POLICY_FILE=policy, JARVIS_LOG_DIR=ws / "logs"))
    assert core.tools.execute("permission_demo", target="a.txt").success  # the allow rule covers the workspace...
    for protected in ("policy.toml", "logs/audit.jsonl", "sub/../policy.toml"):
        d = core.tools.execute("permission_demo", target=protected).permission
        assert d.denied and d.matched_rule == "fs:protected_path", protected  # ...but not the files that govern it


def test_audit_can_be_disabled(tmp_path):
    core = build_core(settings_for(tmp_path, JARVIS_SECURITY_AUDIT_ENABLED="false", JARVIS_SECURITY_CONFIRMATION="deny"))
    core.tools.execute("permission_demo", target="a.txt")
    assert not (tmp_path / "logs" / "audit.jsonl").exists() and core.permissions.audit.sinks == []


def test_secrets_of_the_configuration_are_redacted_by_the_engine(tmp_path):
    s = settings_for(tmp_path, JARVIS_LLM_API_KEY="llm-plain-secret-value-1", JARVIS_VOICE_API_KEY="voice-plain-secret-2")
    e = build_permission_engine(s)
    out = e.redact("keys: llm-plain-secret-value-1 and voice-plain-secret-2")
    assert "plain-secret" not in out and out.count("[REDACTED]") == 2


# ---- bootstrap / core wiring ---------------------------------------------------------------------------------------------------
def test_build_core_wires_a_strict_engine_into_the_tool_registry(tmp_path):
    core = build_core(settings_for(tmp_path))
    assert core.permissions is core.tools.permissions and core.permissions.require_protected_tools
    assert core.tools.execute("echo", text="hi").output == "hi"
    assert "permission_demo" in core.tools  # development mode


def test_production_mode_has_no_demo_tool(tmp_path):
    core = build_core(settings_for(tmp_path, JARVIS_MODE="production"))
    assert "permission_demo" not in core.tools and core.tools.names() == ["current_time", "echo"]


def test_core_tools_reject_unprotected_non_green_tools(tmp_path):
    core = build_core(settings_for(tmp_path))

    class Sneaky(Tool):
        name, description, permission = "sneaky", "x", Y

        def run(self, **kw):
            return ToolResult.ok("x")

    with pytest.raises(ToolError):
        core.tools.register(Sneaky())


def test_headless_deny_mode_never_prompts(tmp_path):
    asked = []
    core = build_core(settings_for(tmp_path, JARVIS_SECURITY_CONFIRMATION="deny"))
    assert not core.tools.execute("permission_demo", target="a.txt").success and asked == []


def test_lockdown_blocks_everything_but_green(tmp_path):
    core = build_core(settings_for(tmp_path, JARVIS_SECURITY_MODE="lockdown"))
    assert core.tools.execute("echo", text="x").success
    r = core.tools.execute("permission_demo", target="a.txt")
    assert not r.success and r.permission.matched_rule == "invariant:lockdown"


# ---- CLI confirmation provider -------------------------------------------------------------------------------------------------------
def creq(session=True, **kw):
    return ConfirmationRequest(request_id="r1", tool="filesystem", action="write", level=Y,
                               resource="/ws/a.txt", reason="Notiz speichern", session_allowed=session, **kw)


def ask(answer, request=None):
    out, prompts = [], []

    def fake_input(prompt):
        prompts.append(prompt)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return CliConfirmation(fake_input, out.append).confirm(request or creq()), out, prompts


@pytest.mark.parametrize("answer,expected", [
    ("j", ConfirmationChoice.ALLOW_ONCE), ("ja", ConfirmationChoice.ALLOW_ONCE), ("J", ConfirmationChoice.ALLOW_ONCE),
    ("  Ja ", ConfirmationChoice.ALLOW_ONCE), ("y", ConfirmationChoice.ALLOW_ONCE), ("YES", ConfirmationChoice.ALLOW_ONCE),
    ("s", ConfirmationChoice.ALLOW_SESSION), ("Sitzung", ConfirmationChoice.ALLOW_SESSION),
    ("session", ConfirmationChoice.ALLOW_SESSION),
    ("", ConfirmationChoice.DENY), ("n", ConfirmationChoice.DENY), ("nein", ConfirmationChoice.DENY),
    ("no", ConfirmationChoice.DENY), ("vielleicht", ConfirmationChoice.DENY), ("yes please", ConfirmationChoice.DENY),
    ("jj", ConfirmationChoice.DENY), ("1", ConfirmationChoice.DENY), ("ok", ConfirmationChoice.DENY),
    (EOFError(), ConfirmationChoice.DENY), (KeyboardInterrupt(), ConfirmationChoice.DENY),
])
def test_cli_confirmation_only_explicit_yes_allows(answer, expected):
    choice, _, _ = ask(answer)
    assert choice is expected


def test_cli_confirmation_shows_the_decision_relevant_facts():
    _, out, prompts = ask("n")
    text = "\n".join(out)
    for expected in ("JARVIS möchte", "Aktion: write", "Werkzeug: filesystem", "Ziel: /ws/a.txt", "Risiko: YELLOW",
                     "Grund: Notiz speichern", "Erlauben?"):
        assert expected in text
    assert "[s]itzung" in prompts[0]


def test_cli_confirmation_hides_session_option_when_not_available():
    choice, out, prompts = ask("s", creq(session=False))
    assert choice is ConfirmationChoice.DENY and "[s]itzung" not in prompts[0]


def test_confirmation_request_summary_is_speakable():
    s = creq().summary
    assert s.startswith("JARVIS möchte") and "write" in s and "/ws/a.txt" in s and "\n" not in s


def test_scripted_and_deny_all_providers():
    sp = ScriptedConfirmation(["allow_once", ConfirmationChoice.DENY])
    assert sp.confirm(creq()) is ConfirmationChoice.ALLOW_ONCE and sp.confirm(creq()) is ConfirmationChoice.DENY
    assert sp.confirm(creq()) is ConfirmationChoice.DENY and len(sp.requests) == 3  # exhausted -> deny
    assert DenyAllConfirmation().confirm(creq()) is ConfirmationChoice.DENY
    with pytest.raises(ValueError):
        ScriptedConfirmation(["maybe"])


def test_cli_provider_can_be_rebound_to_other_io():
    p = CliConfirmation(lambda s: (_ for _ in ()).throw(AssertionError("old io used")), lambda t: None)
    got = []
    p.bind_io(lambda prompt: "j", got.append)
    assert p.confirm(creq()) is ConfirmationChoice.ALLOW_ONCE and got


# ---- CLI commands -----------------------------------------------------------------------------------------------------------------------
def run_repl(core, lines, settings=None):
    it = iter(lines)
    out = []

    def fake_input(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    repl(core, fake_input, out.append, settings=settings)
    return "\n".join(out)


def test_cli_run_asks_through_the_repl_terminal(tmp_path):
    core = build_core(settings_for(tmp_path))
    out = run_repl(core, ["/run permission_demo target=notes.txt", "j", "/run echo text=\"hallo welt\"", "/exit"])
    assert "Risiko: YELLOW" in out and "Erlauben?" in out
    assert "OK: demo: would modify notes.txt" in out and "OK: hallo welt" in out


def test_cli_run_decline_and_traversal(tmp_path):
    core = build_core(settings_for(tmp_path))
    out = run_repl(core, ["/run permission_demo target=a.txt", "n", "/run permission_demo target=../../etc/passwd", "/exit"])
    assert "Nicht ausgeführt: permission denied for tool 'permission_demo': the user declined" in out
    assert "outside the allowed directories" in out
    assert out.count("Erlauben?") == 1  # the traversal was refused without bothering the user


def test_cli_session_permission_and_revoke(tmp_path):
    core = build_core(settings_for(tmp_path))
    out = run_repl(core, ["/run permission_demo target=a.txt", "s", "/run permission_demo target=a.txt", "/permissions",
                          "/revoke", "/permissions", "/exit"])
    assert out.count("Erlauben?") == 1 and out.count("OK: demo") == 2
    assert "Sitzungsfreigaben: \n  permission_demo.write" in out and "1 Sitzungsfreigabe(n) widerrufen." in out
    assert out.rstrip().endswith("Bis bald.") and "Sitzungsfreigaben: keine" in out


def test_cli_permissions_and_audit_views(tmp_path):
    core = build_core(settings_for(tmp_path))
    first = run_command(core, "/audit")  # only the registration of the (YELLOW) demo tool so far
    assert "tool_registered" in first and "permission_requested" not in first and " ." not in first
    d = run_command(core, "/permissions")
    assert "Modus: standard" in d and str((tmp_path / "ws").resolve()) in d and "Regeln: keine" in d
    run_repl(core, ["/run permission_demo target=a.txt", "j", "/exit"])
    log = run_command(core, "/audit 50")
    for expected in ("tool_registered", "permission_requested", "confirmation_accepted", "permission_granted",
                     "execution_result"):
        assert expected in log


def test_cli_run_argument_errors(tmp_path):
    core = build_core(settings_for(tmp_path))
    assert "Verwendung" in run_command(core, "/run")
    assert "Ungültiges Argument" in run_command(core, "/run echo text")
    assert "Ungültige Eingabe" in run_command(core, "/run echo text='unterminated")
    assert "unknown tool" in run_command(core, "/run nope a=b")
    assert "missing parameters" in run_command(core, "/run echo")


# ---- architecture: the permission layer is independent -------------------------------------------------------------------------------------------
def imports(path):
    mods = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return {m for m in mods if m.startswith("jarvis")}


def test_permissions_package_depends_only_on_errors_and_redaction():
    allowed = ("jarvis.errors", "jarvis.redaction", "jarvis.permissions")
    for f in (SRC / "permissions").glob("*.py"):
        extra = {m for m in imports(f) if not m.startswith(allowed)}
        if f.name == "factory.py":
            extra -= {"jarvis.config"}  # the composition helper reads the settings
        assert not extra, f"{f.name} imports {extra}"


def test_voice_memory_llm_planning_tasks_and_core_do_not_know_the_permission_system():
    for pkg in ("voice", "memory", "llm", "planning", "tasks", "core"):
        for f in (SRC / pkg).glob("*.py"):
            assert not {m for m in imports(f) if m.startswith("jarvis.permissions")}, f"{pkg}/{f.name}"
    assert not {m for m in imports(SRC / "redaction.py") if not m.startswith("jarvis.errors")}


def test_only_tools_bootstrap_and_cli_use_the_permission_package():
    # `computer/` (Phase 4), `browser/` (Phase 5) and `coding/` (Phase 6) are the additional legitimate consumers; each is checked on its own
    # in test_computer_security.py / test_browser_security.py / test_coding_security.py
    users = sorted(f.relative_to(SRC).as_posix() for f in SRC.rglob("*.py")
                   if any(m.startswith("jarvis.permissions") for m in imports(f))
                   and f.parent.name not in ("permissions", "computer", "browser", "coding", "providers"))
    assert users == ["bootstrap.py", "interface/cli.py", "interface/gui.py", "tools/analysis.py", "tools/base.py", "tools/builtin/__init__.py", "tools/registry.py"]

def test_memory_and_permissions_share_only_the_neutral_redaction_module():
    assert "jarvis.redaction" in imports(SRC / "memory" / "guard.py")
    assert "jarvis.redaction" in imports(SRC / "permissions" / "engine.py")
    assert not any(m.startswith("jarvis.memory") for f in (SRC / "permissions").glob("*.py") for m in imports(f))


def test_secret_detector_is_shared_behaviour():
    from jarvis.memory import SecretGuard
    assert issubclass(SecretGuard, SecretDetector)
    det = SecretDetector(known_secrets=["known-secret-xyz-1"])
    assert det.redact("x known-secret-xyz-1 password=abcdefgh y") == "x [REDACTED] [REDACTED] y"
    assert det.redact_mapping({"api_key": "v", "n": "known-secret-xyz-1", 5: "ok"}) == \
           {"api_key": "[REDACTED]", "n": "[REDACTED]", "5": "ok"}
