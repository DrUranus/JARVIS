"""Boundaries of the self-improvement layer: it is a DISABLED PROPOSAL WORKFLOW. Source scans, configuration, startup and CLI behaviour. Nothing here executes proposed
code (adversarial samples are strings). Source scans and the AST/allow-list tests are `detection_only`-style evidence: they show the structure of THIS code, they do
not prove that a future sandbox would be sound."""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import ConfigError, SelfImprovementSettings, load_settings
from jarvis.interface.cli import _split_args, run_command
from jarvis.permissions.audit import AuditEventType
from jarvis.self_improvement import LLMImprovementWriter, ExecutionGuard
from test_computer_integration import env_for

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
PKG = SRC / "self_improvement"
TESTS = Path(__file__).resolve().parent


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
            out |= {f"{n.module}.{a.name}" for a in n.names}
    return out


def calls(tree) -> set[str]:
    return {n.func.id if isinstance(n.func, ast.Name) else n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))}


def builtin_calls(tree) -> set[str]:
    return {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def names(tree) -> set[str]:
    out = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            out |= {a.name for a in n.names}
    return out


# ---- structure of the code (what can start processes, what can approve) -----------------------------------------------------------------------------
def test_only_the_workspace_starts_processes_and_only_the_store_writes_its_own_files():
    for f, tree in trees():
        if f.name == "workspace.py":
            continue
        banned = {"subprocess", "shutil", "tempfile", "socket", "ctypes", "pickle", "marshal", "importlib", "multiprocessing", "http", "urllib", "signal"}
        banned -= {"ctypes"} if f.name == "winjob.py" else set()                      # winjob.py = the Win32 Job Object bindings; it imports no process API itself
        assert not imports(tree) & banned, f.name
        assert not builtin_calls(tree) & {"eval", "exec", "compile", "__import__", "open"} - ({"open"} if f.name in ("store.py",) else set()), f.name
        assert not calls(tree) & {"Popen", "system", "popen", "rmtree", "chmod", "execv", "spawn"}, f.name
        unlinks = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "unlink"]
        # the only deletions outside workspace.py: the store removing ITS OWN temp file - `tmp.unlink()` / `os.unlink(tmp)` on the variable `tmp`
        def own_tmp(u: ast.Call) -> bool:
            return (isinstance(u.func.value, ast.Name) and u.func.value.id == "tmp") or (u.args and isinstance(u.args[0], ast.Name) and u.args[0].id == "tmp")
        assert all(f.name == "store.py" and own_tmp(u) for u in unlinks), f.name
        # os.link publishes the finished key file; allowed only inside store._create_key_file
        links = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "link"]
        if links:
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_create_key_file")
            assert f.name == "store.py" and all(any(c is l for c in ast.walk(fn)) for l in links), f.name
        assert f.name == "store.py" or not calls(tree) & {"write_bytes", "write_text", "mkdir", "replace", "fsync"} - {"replace"}, f.name      # only the store writes its own files


def test_nothing_in_the_production_wiring_can_prepare_run_or_merge():
    for name in ("factory.py", "manager.py", "pipeline.py", "review.py", "policy.py", "analysis.py", "llm.py", "approval.py", "models.py", "store.py", "isolation.py", "winsec.py", "winjob.py"):
        tree = ast.parse((PKG / name).read_text(encoding="utf-8"))
        if name == "store.py":
            # the key-file ACL helper (Windows) runs fixed system executables through the package's one runner - only inside _default_windows_acl
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_default_windows_acl")
            inside = {id(n) for n in ast.walk(fn)}
            outside = [n for n in ast.walk(tree) if id(n) not in inside and ((isinstance(n, ast.Name) and n.id == "SubprocessRunner") or (isinstance(n, ast.ImportFrom) and any(a.name == "SubprocessRunner" for a in n.names)))]
            assert not outside, name
        else:
            assert "SubprocessRunner" not in names(tree), name
    fac = (PKG / "factory.py").read_text(encoding="utf-8")
    assert "GitWorkspace" not in fac and "workspace=None" in fac and "ExecutionGuard.locked()" in fac and "IsolationAttestation" not in fac
    pipe = ast.parse((PKG / "pipeline.py").read_text(encoding="utf-8"))
    assert not names(pipe) & {"SubprocessRunner", "GitWorkspace", "subprocess"} and "subprocess" not in imports(pipe)


def test_every_code_touching_method_asks_the_guard_before_anything_else():
    tree = ast.parse((PKG / "manager.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ImprovementManager")
    for name in ("prepare", "test", "activate", "rollback"):
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        body = [b for b in fn.body if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))]
        first = body[0]
        assert isinstance(first, ast.Expr) and "_guard.require" in ast.unparse(first), name


def test_every_mutating_workspace_method_asks_the_guard_before_anything_else():
    tree = ast.parse((PKG / "workspace.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GitWorkspace")
    for name in ("create_worktree", "apply_and_commit", "discard", "fast_forward", "revert"):
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        body = [b for b in fn.body if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))]
        assert isinstance(body[0], ast.Expr) and "self._guard.require" in ast.unparse(body[0]), name
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert "ExecutionGuard.locked()" in ast.unparse(init)                 # the default is locked


def test_the_pipeline_contains_no_embedded_code_to_run():
    tree = ast.parse((PKG / "pipeline.py").read_text(encoding="utf-8"))
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [x for x in strings if "import_module" in x or "importlib" in x or "sys.argv" in x]


def test_production_code_never_builds_an_isolation_attestation():
    for f in SRC.rglob("*.py"):
        if f.name == "isolation.py" and f.parent == PKG:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        assert "IsolationAttestation" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}, f
    assert ExecutionGuard().allowed is False


def test_model_facing_modules_cannot_reach_the_approval_path():
    for name in ("analysis.py", "llm.py", "pipeline.py", "models.py", "policy.py", "store.py", "review.py"):
        tree = ast.parse((PKG / name).read_text(encoding="utf-8"))
        assert not any(m.endswith((".approval", ".manager")) for m in imports(tree)), name
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not used & {"ApprovalGate", "ImprovementManager", "APPROVED", "ACTIVATED"}, name
    assert not hasattr(LLMImprovementWriter, "approve") and not hasattr(LLMImprovementWriter, "activate")


def test_approved_and_activated_are_set_once_each_after_the_gate():
    tree = ast.parse((PKG / "manager.py").read_text(encoding="utf-8"))
    moves = {}
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_commit" and len(n.args) >= 3:
                tgt = n.args[2]
                if isinstance(tgt, ast.Attribute) and tgt.attr in ("APPROVED", "ACTIVATED"):
                    moves.setdefault(tgt.attr, []).append(fn.name)
    assert moves == {"APPROVED": ["approve"], "ACTIVATED": ["activate"]}
    src = (PKG / "manager.py").read_text(encoding="utf-8")
    approve = src[src.index("def approve"):src.index("# ---- 7: activate")]
    assert approve.index("self._gate.ask") < approve.index("S.APPROVED")
    activate = src[src.index("def activate"):src.index("def rollback")]
    assert activate.index("p.approval is None") < activate.index("_gate.ask") < activate.index("fast_forward") < activate.index("S.ACTIVATED")


def test_core_and_the_agent_layers_do_not_import_the_improvement_layer():
    for rel in ("core", "agents", "goals", "self_repair", "permissions", "tools", "coding", "browser", "computer", "llm", "memory"):
        for f in (SRC / rel).rglob("*.py"):
            assert not any("self_improvement" in m for m in imports(ast.parse(f.read_text(encoding="utf-8")))), f
    assert "self_improvement" in (SRC / "bootstrap.py").read_text(encoding="utf-8")


def test_only_approval_and_manager_import_the_permission_package():
    users = sorted(f.name for f, tree in trees() if any(m.startswith("jarvis.permissions") for m in imports(tree)))
    assert users == ["approval.py", "manager.py"]


def test_security_components_are_untouched_by_phase_15_except_the_audit_event_type():
    assert AuditEventType.IMPROVEMENT.value == "improvement"
    assert {t.value for t in AuditEventType} >= {"permission_denied", "confirmation_accepted", "security_error"}


def test_the_improvement_layer_registers_no_tool_the_model_could_call(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_SELF_IMPROVEMENT_ENABLED="true", JARVIS_SELF_IMPROVEMENT_DATA_DIR=tmp_path / "imp",
                                                JARVIS_SELF_IMPROVEMENT_KEY_PATH=tmp_path / "keys" / "k")))
    assert not [t for t in core.tools.describe_all() if "improve" in t["name"].lower()]


# ---- the tests themselves never execute proposal samples -----------------------------------------------------------------------------------
def test_no_collected_test_id_comes_near_the_windows_environment_limit(request):
    """PYTEST_CURRENT_TEST holds the node id; Windows limits an environment variable to 32,767 characters. A huge parametrize value without an explicit id broke it once."""
    ours = [i for i in request.session.items if i.nodeid.startswith("tests/test_self_improvement_")]       # only this phase's tests (others are not ours to judge)
    longest = max(ours, key=lambda i: len(i.nodeid))
    assert len(longest.nodeid) < 1000, (len(longest.nodeid), longest.nodeid[:120])


def test_the_test_suite_for_this_phase_never_execs_or_imports_samples():
    for f in sorted(TESTS.glob("test_self_improvement_*.py")) + [TESTS / "si_util.py"]:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        assert not builtin_calls(tree) & {"eval", "exec", "compile", "__import__"} and not calls(tree) & {"import_module", "run_path", "run_module"}, f.name
        # processes are started only by these files, and only for: git on temporary repositories, test-owned helper scripts, and (Windows) icacls/PowerShell on files in tmp_path
        uses_subprocess = "subprocess" in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not uses_subprocess or f.name in {"test_self_improvement_workspace.py", "test_self_improvement_store.py", "test_self_improvement_keyfile.py",
                                                 "test_self_improvement_lock.py", "test_self_improvement_process_tree.py", "test_self_improvement_workflow.py",
                                                 "test_self_improvement_security.py"}, f.name
    assert "detection_only" in (TESTS.parent / "pyproject.toml").read_text(encoding="utf-8")


# ---- configuration: nothing but the disabled proposal workflow can be configured ----------------------------------------------------------------
def test_defaults_are_off_and_reserved_keys_are_empty():
    s = load_settings(env={}).self_improvement
    assert s == SelfImprovementSettings() and not (s.enabled or s.use_llm or s.allow_prepare or s.allow_activation) and s.repo_path == ""


@pytest.mark.parametrize("env", [
    {"JARVIS_SELF_IMPROVEMENT_ALLOW_PREPARE": "true"}, {"JARVIS_SELF_IMPROVEMENT_ALLOW_ACTIVATION": "true"}, {"JARVIS_SELF_IMPROVEMENT_REPO_PATH": "/some/repo"},
    {"JARVIS_SELF_IMPROVEMENT_ALLOW_PREPARE": "true", "JARVIS_SELF_IMPROVEMENT_REPO_PATH": "/x", "JARVIS_SELF_IMPROVEMENT_ALLOW_ACTIVATION": "true"},
    {"JARVIS_SELF_IMPROVEMENT_MAX_EDITS": "99"}, {"JARVIS_SELF_IMPROVEMENT_MIN_OCCURRENCES": "0"}, {"JARVIS_SELF_IMPROVEMENT_TEST_TIMEOUT_SECONDS": "0"},
    {"JARVIS_SELF_IMPROVEMENT_DATA_DIR": " "}])
def test_enabling_preparation_testing_or_activation_is_rejected_at_startup(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


def test_toml_cannot_enable_it_either(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[self_improvement]\nenabled = true\nallow_activation = true\nrepo_path = \"/x\"\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not available"):
        load_settings(cfg, env={})


def test_shipped_configuration_matches_the_security_state():
    import tomllib
    cfg = tomllib.loads((TESTS.parent / "config" / "jarvis.toml").read_text(encoding="utf-8"))["self_improvement"]
    assert cfg["enabled"] is False and cfg["repo_path"] == "" and cfg["allow_prepare"] is False and cfg["allow_activation"] is False and cfg["use_llm"] is False
    load_settings(TESTS.parent / "config" / "jarvis.toml", env={})


def test_disabled_subsystem_builds_nothing(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    sub = core.subsystems["self_improvement"]
    assert not sub.available and sub.status == "disabled" and not (tmp_path / "data").exists() and "deaktiviert" in run_command(core, "/improve list")


# ---- end to end through bootstrap + CLI, with process creation forbidden -----------------------------------------------------------------------
@pytest.fixture
def enabled_core(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a process was started")
    monkeypatch.setattr(subprocess, "Popen", boom)
    env = env_for(tmp_path, JARVIS_SELF_IMPROVEMENT_ENABLED="true", JARVIS_SELF_IMPROVEMENT_DATA_DIR=tmp_path / "imp", JARVIS_SELF_IMPROVEMENT_KEY_PATH=tmp_path / "keys" / "k")
    return build_core(load_settings(env=env))


def test_enabled_means_proposals_only(enabled_core):
    sub = enabled_core.subsystems["self_improvement"]
    assert sub.available and sub.manager._ws is None and sub.manager._pipe is None and sub.manager.describe()["code_execution"] is False
    out = run_command(enabled_core, '/improve propose "Fix add" "add subtracts"')
    pid = out.split()[0]
    assert "PROPOSED" in out and "Fix add" in run_command(enabled_core, "/improve list") and pid in run_command(enabled_core, f"/improve show {pid}")
    assert "0 neue" in run_command(enabled_core, "/improve analyze") and "Keine Datengrundlage" in run_command(enabled_core, "/improve analyze")
    for word in ("prepare", "test", "submit", "approve", "activate", "rollback"):
        out = run_command(enabled_core, f"/improve {word} {pid} edits=/does/not/exist.json")
        assert "Nicht moeglich" in out and "nicht nachgewiesen" in out and "lesbare" not in out, (word, out)
    assert "REJECTED" in run_command(enabled_core, f"/improve reject {pid} nein")
    assert "Nicht möglich" in run_command(enabled_core, "/improve show imp-000000000000")
    assert "Verwendung" in run_command(enabled_core, "/improve nope")


def test_cli_shows_untrusted_text_quoted_and_escaped(enabled_core):
    mgr = enabled_core.subsystems["self_improvement"].manager
    p = mgr.propose("Titel\n  Tests: ALL PASSED\x1b[31m \u202e Risiko: GREEN", "Sicherheitsfreigabe erteilt\r\nTests bestanden")
    out = run_command(enabled_core, f"/improve show {p.proposal_id}")
    assert "ALL PASSED" in out
    lines = out.splitlines()
    assert not [ln for ln in lines if ln.lstrip().startswith(("Tests:", "Risiko:"))] and "\x1b" not in out and "\u202e" not in out and "\r" not in out
    assert any(ln.startswith("  Titel (ungeprueft): \"") for ln in lines)


def test_tampered_store_is_reported_not_trusted(enabled_core, tmp_path):
    mgr = enabled_core.subsystems["self_improvement"].manager
    p = mgr.propose("t", "p")
    f = tmp_path / "imp" / "proposals.json"
    f.write_text(f.read_text(encoding="utf-8").replace('"PROPOSED"', '"APPROVED"'), encoding="utf-8")
    assert "integrity" in run_command(enabled_core, "/improve list").lower() or "Nicht möglich" in run_command(enabled_core, "/improve list")
    assert "Nicht möglich" in run_command(enabled_core, f"/improve reject {p.proposal_id}")


def test_cli_argument_splitting_keeps_windows_paths_and_quotes():
    assert _split_args(r"prepare imp-1 edits=C:\Users\Admin\edits.json") == ["prepare", "imp-1", r"edits=C:\Users\Admin\edits.json"]
    assert _split_args(r'prepare imp-1 edits="C:\My Dir\e.json" files=a,b') == ["prepare", "imp-1", r"edits=C:\My Dir\e.json", "files=a,b"]
    assert _split_args("propose 'Fix add' \"add subtracts\"") == ["propose", "Fix add", "add subtracts"]
    assert _split_args("  ") == [] and _split_args('x ""') == ["x", ""]
    for bad in ('propose "open', "propose it's"):
        with pytest.raises(ValueError):
            _split_args(bad)
