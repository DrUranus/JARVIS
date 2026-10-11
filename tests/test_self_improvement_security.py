"""Boundaries of the self-improvement layer: source scans, defaults, configuration, and that a model can neither approve nor reach the approval path."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import ConfigError, SelfImprovementSettings, load_settings
from jarvis.interface.cli import run_command
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.audit import AuditEventType
from jarvis.permissions.confirmation import ScriptedConfirmation
from jarvis.self_improvement import ImprovementError, LLMImprovementWriter, ProposalStatus as S, policy
from si_util import GOOD, ONCE, TESTS, git, make_repo, rig
from test_computer_integration import env_for

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
PKG = SRC / "self_improvement"


def trees():
    for f in sorted(PKG.glob("*.py")):
        yield f, ast.parse(f.read_text(encoding="utf-8"))


def imports(tree) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


# ---- source scans -------------------------------------------------------------------------------------------------------------------------
def test_only_the_workspace_module_runs_processes_or_touches_the_filesystem():
    for f, tree in trees():
        mods = imports(tree)
        if f.name == "workspace.py":
            continue
        assert not mods & {"subprocess", "shutil", "socket", "ctypes", "pickle", "marshal", "importlib", "multiprocessing", "http", "urllib"}, f.name
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {"eval", "exec", "compile", "__import__", "open"} for n in ast.walk(tree)), f.name


def test_no_shell_and_no_string_commands_anywhere():
    text = "\n".join(f.read_text(encoding="utf-8") for f in PKG.glob("*.py"))
    assert "shell=True" not in text and "os.system" not in text and "os.popen" not in text
    tree = ast.parse((PKG / "workspace.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("Popen", "run") and getattr(n.func.value, "id", "") == "subprocess":
            kws = {k.arg: k.value for k in n.keywords}
            assert "shell" not in kws or (isinstance(kws["shell"], ast.Constant) and kws["shell"].value is False)


def test_model_facing_modules_cannot_reach_the_approval_path():
    for name in ("analysis.py", "llm.py", "pipeline.py", "models.py", "policy.py", "store.py"):
        tree = ast.parse((PKG / name).read_text(encoding="utf-8"))
        mods = imports(tree)
        assert not any(m.endswith((".approval", ".manager")) for m in mods), name
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not used & {"ApprovalGate", "ImprovementManager", "APPROVED", "ACTIVATED"}, name
    assert not hasattr(LLMImprovementWriter, "approve") and not hasattr(LLMImprovementWriter, "activate")


def test_approved_and_activated_are_set_in_exactly_one_place_each_and_after_the_gate():
    tree = ast.parse((PKG / "manager.py").read_text(encoding="utf-8"))
    moves = {}
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("_move", "moved") and len(n.args) >= 2:
                tgt = n.args[1] if n.func.attr == "_move" else n.args[0]
                if isinstance(tgt, ast.Attribute) and tgt.attr in ("APPROVED", "ACTIVATED"):
                    moves.setdefault(tgt.attr, []).append(fn.name)
    assert moves == {"APPROVED": ["approve"], "ACTIVATED": ["activate"]}
    src = (PKG / "manager.py").read_text(encoding="utf-8")
    approve = src[src.index("def approve"):src.index("def _verify_unchanged")]
    assert approve.index("self._gate.ask") < approve.index("S.APPROVED")
    activate = src[src.index("def activate"):src.index("def rollback")]
    assert activate.index("p.approval is None") < activate.index("fast_forward") < activate.index("S.ACTIVATED")


def test_core_and_the_agent_layers_do_not_import_the_improvement_layer():
    for rel in ("core", "agents", "goals", "self_repair", "permissions", "tools", "coding", "browser", "computer", "llm", "memory"):
        for f in (SRC / rel).rglob("*.py"):
            assert not any("self_improvement" in m for m in imports(ast.parse(f.read_text(encoding="utf-8")))), f
    assert "self_improvement" in (SRC / "bootstrap.py").read_text(encoding="utf-8")


def test_the_improvement_layer_registers_no_tool_the_model_could_call(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_SELF_IMPROVEMENT_ENABLED="true")))
    assert not [t for t in core.tools.describe_all() if "improve" in t["name"].lower()]


def test_policy_rules():
    for ok in ("src/jarvis/goals/engine.py", "src/jarvis/tools/analysis.py"):
        assert policy.refuse_target(ok) is None, ok
    for sec in ("src/jarvis/permissions/engine.py", "src/jarvis/permissions/audit.py", "src/jarvis/self_improvement/manager.py", "src/jarvis/config.py", "src/jarvis/bootstrap.py",
                "src/jarvis/redaction.py", "src/jarvis/goals/policy.py", "src/jarvis/agents/policy.py", "src/jarvis/computer/safety.py", "src/jarvis/memory/guard.py",
                "src/jarvis/tools/registry.py", "src/jarvis/self_repair/policy.py", "SRC/JARVIS/PERMISSIONS/x.py"):
        assert policy.is_security_refusal(policy.refuse_target(sec)), sec
    for bad in ("tests/test_x.py", "README.md", "config/jarvis.toml", "../x.py", "src/jarvis/x.txt", "src/jarvis/__pycache__/x.py", "src/x.py", "src/jarvis/goals/.env", "src/jarvis"):
        assert policy.refuse_target(bad), bad
    assert policy.scan_added("x = 1\n# subprocess mentioned in a comment\n") is None
    for line in ("import subprocess", "os.system('x')", "eval(s)", "__import__('os')", "from jarvis.permissions import PermissionEngine", "audit_strict = False", "import socket", "shutil.rmtree(p)"):
        assert policy.scan_added(line), line


# ---- configuration: conservative by default -------------------------------------------------------------------------------------------------
def test_defaults_are_off_and_conservative():
    s = load_settings(env={}).self_improvement
    assert s == SelfImprovementSettings() and not (s.enabled or s.use_llm or s.allow_prepare or s.allow_activation) and s.repo_path == ""


@pytest.mark.parametrize("env", [
    {"JARVIS_SELF_IMPROVEMENT_ALLOW_PREPARE": "true"}, {"JARVIS_SELF_IMPROVEMENT_ALLOW_ACTIVATION": "true", "JARVIS_SELF_IMPROVEMENT_REPO_PATH": "/x"},
    {"JARVIS_SELF_IMPROVEMENT_MAX_EDITS": "99"}, {"JARVIS_SELF_IMPROVEMENT_MIN_OCCURRENCES": "0"}, {"JARVIS_SELF_IMPROVEMENT_TEST_TIMEOUT_SECONDS": "0"},
    {"JARVIS_SELF_IMPROVEMENT_MAX_DIFF_BYTES": "5"}, {"JARVIS_SELF_IMPROVEMENT_DATA_DIR": " "}])
def test_invalid_configuration_is_rejected(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


def test_disabled_subsystem_builds_nothing(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    sub = core.subsystems["self_improvement"]
    assert not sub.available and sub.status == "disabled" and not (tmp_path / "data").exists()
    assert "deaktiviert" in run_command(core, "/improve list")


def test_audit_type_exists_and_the_security_machinery_is_unchanged():
    assert AuditEventType.IMPROVEMENT.value == "improvement"
    assert {t.value for t in AuditEventType} >= {"permission_denied", "confirmation_accepted", "security_error"}


# ---- end to end through bootstrap + CLI -------------------------------------------------------------------------------------------------------
def cli_core(tmp_path, repo, **extra):
    env = env_for(tmp_path, JARVIS_SELF_IMPROVEMENT_ENABLED="true", JARVIS_SELF_IMPROVEMENT_REPO_PATH=repo, JARVIS_SELF_IMPROVEMENT_DATA_DIR=tmp_path / "imp",
                  JARVIS_SELF_IMPROVEMENT_ALLOW_PREPARE="true", JARVIS_SELF_IMPROVEMENT_ALLOW_ACTIVATION="true", JARVIS_SECURITY_CONFIRMATION="deny", **extra)
    return build_core(load_settings(env=env))


def test_cli_flow_needs_the_users_confirmation(tmp_path):
    repo = make_repo(tmp_path)
    core = cli_core(tmp_path, repo)
    assert core.subsystems["self_improvement"].available
    out = run_command(core, '/improve propose "Fix add" "add subtracts"')
    pid = out.split()[0]
    edits = tmp_path / "edits.json"
    edits.write_text(json.dumps([GOOD]), encoding="utf-8")
    assert "PREPARED" in run_command(core, f"/improve prepare {pid} edits={edits}")
    mgr = core.subsystems["self_improvement"].manager
    p = mgr._store.get(pid).evolve(suggested_tests=TESTS)
    mgr._store.save(p)
    assert "TESTED" in run_command(core, f"/improve test {pid}")
    assert "READY_FOR_APPROVAL" in run_command(core, f"/improve submit {pid}")
    # headless (confirmation = deny): the user cannot be asked, so nothing is approved
    assert "Nicht möglich" in run_command(core, f"/improve approve {pid}")
    assert mgr.get(pid).status is S.READY_FOR_APPROVAL
    # the CURRENT provider of the permission engine is used, so a GUI/terminal swap is respected
    core.permissions.set_confirmation_provider(ScriptedConfirmation([ONCE]))
    assert "APPROVED" in run_command(core, f"/improve approve {pid}")
    assert "ACTIVATED" in run_command(core, f"/improve activate {pid}")
    assert "a + b" in (repo / "src/jarvis/goals/engine.py").read_text(encoding="utf-8")
    show = run_command(core, f"/improve show {pid}")
    assert "Freigabe" in show and "bestanden" in show
    audit = (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert '"tool": "self_improvement"' in audit and "approved" in audit and "activated" in audit
    assert "Nicht möglich" in run_command(core, "/improve approve imp-000000000000") and "Verwendung" in run_command(core, "/improve nope")


def test_cli_analyze_reports_missing_data_honestly(tmp_path):
    core = cli_core(tmp_path, make_repo(tmp_path))
    out = run_command(core, "/improve analyze")
    assert "0 neue" in out and "Keine Datengrundlage" in out and "goal engine" in out


def test_only_approval_and_manager_import_the_permission_package():
    users = sorted(f.name for f, tree in trees() if any(m.startswith("jarvis.permissions") for m in imports(tree)))
    assert users == ["approval.py", "manager.py"]
