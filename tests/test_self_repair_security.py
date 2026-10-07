"""Source scans and boundary checks of the self-repair layer: it touches no file, runs no command, decides no permission and adds no capability."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from jarvis.self_repair import (InvalidRepairError, PlanBlocked, RepairContext, RepairEngine, RepairPlanner, check_context, policy)
from jarvis.self_repair.fake import test_run  # noqa: F401

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
PKG = SRC / "self_repair"
EDIT = {"path": "calc.py", "mode": "replace", "old_text": "a - b", "new_text": "a + b"}


def modules():
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


BANNED_MODULES = {"subprocess", "os", "shutil", "socket", "ssl", "http", "urllib", "requests", "httpx", "ftplib", "smtplib", "ctypes", "pty", "pyautogui",
                  "mss", "playwright", "selenium", "pickle", "marshal", "importlib", "multiprocessing", "webbrowser", "tempfile", "pathlib", "sqlite3",
                  "asyncio", "signal", "winreg", "keyring", "getpass", "openai", "anthropic", "sys", "builtins", "runpy", "code", "codeop", "git", "pip",
                  "setuptools", "site", "zipimport", "pkgutil", "inspect", "glob", "fnmatch", "paramiko", "telnetlib", "xmlrpc", "imp"}
FORBIDDEN_JARVIS = ("jarvis.browser", "jarvis.coding", "jarvis.computer", "jarvis.permissions", "jarvis.llm", "jarvis.voice", "jarvis.planning",
                    "jarvis.core", "jarvis.interface", "jarvis.bootstrap", "jarvis.tools", "jarvis.memory", "jarvis.tasks", "jarvis.goals",
                    "jarvis.agents.context", "jarvis.agents.adapters", "jarvis.agents.factory", "jarvis.agents.fake", "jarvis.agents.registry")
ALLOWED_JARVIS = ("jarvis.self_repair", "jarvis.errors", "jarvis.redaction", "jarvis.config", "jarvis.agents")
ALLOWED_AGENT_MODULES = {"jarvis.agents", "jarvis.agents.errors", "jarvis.agents.models", "jarvis.agents.result", "jarvis.agents.state",
                         "jarvis.agents.policy", "jarvis.agents.agent", "jarvis.agents.context"}


def test_no_dangerous_low_level_or_installer_module_is_imported():
    for f, tree in modules():
        for m in imports(tree):
            assert m.split(".")[0] not in BANNED_MODULES, f"{f.name} imports {m}"


def test_never_imports_subsystems_providers_tools_permissions_or_a_second_orchestrator():
    for f, tree in modules():
        for m in imports(tree):
            if f.name == "fake.py" and m.startswith(("jarvis.agents.agent", "jarvis.agents.context")):
                continue                   # the scripted test agent implements the Agent interface
            assert not m.startswith(FORBIDDEN_JARVIS), f"{f.name} imports {m}"
            if m.startswith("jarvis."):
                assert any(m == a or m.startswith(a + ".") for a in ALLOWED_JARVIS), f"{f.name} imports {m}"
            if m.startswith("jarvis.agents"):
                assert m in ALLOWED_AGENT_MODULES or m.rsplit(".", 1)[0] in ALLOWED_AGENT_MODULES, f"{f.name} imports {m}"
    for f, tree in modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                assert "Orchestrator" not in n.name and "Scheduler" not in n.name and "Executor" not in n.name, f"{f.name}: {n.name}"


def test_only_the_factory_touches_the_config():
    assert [f.name for f, t in modules() if any(m.startswith("jarvis.config") for m in imports(t))] == ["factory.py"]


def test_no_eval_exec_open_system_popen_shell_or_dynamic_tricks():
    banned_names = {"eval", "exec", "compile", "open", "__import__", "breakpoint", "input", "globals", "locals", "vars"}
    banned_attrs = {"system", "popen", "Popen", "check_output", "check_call", "spawn", "startfile", "kill", "killpg", "terminate", "write_text", "write_bytes",
                    "read_text", "read_bytes", "unlink", "rmtree", "remove", "mkdir", "makedirs", "chmod", "symlink", "environ", "getenv", "putenv", "execute",
                    "run_command", "run_test", "perform", "commit", "push", "install", "load_plugin", "import_module"}
    for f, tree in modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = n.func
                if isinstance(fn, ast.Name):
                    assert fn.id not in banned_names, f"{f.name}:{n.lineno} {fn.id}()"
                if isinstance(fn, ast.Attribute) and not (isinstance(fn.value, ast.Name) and fn.value.id == "atexit"):
                    assert fn.attr not in banned_attrs or f.name == "fake.py" and fn.attr == "perform", f"{f.name}:{n.lineno} .{fn.attr}()"
            if isinstance(n, ast.keyword):
                assert n.arg not in {"shell", "confirmed", "confirm", "force", "bypass", "skip_permissions", "unsafe", "grant", "approval"}, f"{f.name}: keyword {n.arg}"
            if isinstance(n, ast.Attribute):
                assert n.attr not in {"__dict__", "__globals__", "__subclasses__", "__builtins__", "__code__"}, f"{f.name}:{n.lineno} .{n.attr}"
            if isinstance(n, ast.FunctionDef) and f.name != "fake.py":
                assert n.name != "perform"          # the layer is no agent: it contains no tool-executing code


def test_code_never_names_providers_registries_gateways_or_permission_internals():
    banned = {"ToolRegistry", "ToolGateway", "PermissionEngine", "PermissionDecision", "ProtectedTool", "ExecutionGrant", "BrowserProvider", "ComputerProvider",
              "CodingProvider", "LocalProvider", "FakeCodingProvider", "BrowserController", "ComputerController", "CodingController", "tools", "provider"}
    for f, tree in modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                assert n.id not in banned, f"{f.name}:{n.lineno} {n.id}"
            if isinstance(n, ast.Attribute):
                assert n.attr not in banned, f"{f.name}:{n.lineno} .{n.attr}"
            if isinstance(n, ast.arg):
                assert n.arg not in banned, f"{f.name}:{n.lineno} arg {n.arg}"


def test_the_only_orchestrator_calls_are_the_public_task_interface():
    called = {n.func.attr for f, t in modules() for n in ast.walk(t) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "_orch"}
    assert called <= {"submit", "start", "wait", "wait_any", "cancel", "notify_waiters"}, called
    assert {"submit", "start", "wait_any", "cancel"} <= called


def test_text_scan_for_forbidden_calls_in_code():
    for f, tree in modules():
        docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr)}
        code = " ".join(ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Call, ast.Import, ast.ImportFrom)))
        for needle in ("shell=True", "os.system", "subprocess", "Popen(", "pyautogui", "playwright", "socket.", "requests.", "pip install", ".execute(",
                       "git commit", "git push", "powershell", "cmd.exe"):
            assert needle not in code, f"{f.name}: {needle}"


def test_no_persistence_and_no_memory():
    for f, tree in modules():
        assert "memory" not in " ".join(imports(tree)).lower(), f.name
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                assert n.id not in {"MemoryStore", "NullMemoryStore", "remember", "TaskManager"}, f"{f.name}:{n.lineno}"
    for name in ("remember", "memory.add", "memory.save", ".store(", "sqlite"):
        assert not any(name in f.read_text(encoding="utf-8") for f in PKG.glob("*.py")), name


def test_no_git_or_package_commands_are_ever_built():
    text = " ".join(f.read_text(encoding="utf-8") for f in PKG.glob("*.py") if f.name != "policy.py")
    for needle in ('"action": "git"', "'git'", "pip install", "npm install", "'commit'", '"commit"', '"push"'):
        assert needle not in text, needle
    steps = {a for f, t in modules() for n in ast.walk(t) if isinstance(n, ast.Dict) for k, v in zip(n.keys, n.values)
             if isinstance(k, ast.Constant) and k.value == "action" and isinstance(v, ast.Constant) for a in [v.value]}
    assert steps == {"start", "info", "test", "write", "changes", "stop"}, steps          # the complete vocabulary of coding actions this layer ever asks for


def test_core_agent_goal_and_tool_layers_do_not_import_the_repair_layer():
    for path in [*sorted((SRC / "core").glob("*.py")), *sorted((SRC / "agents").rglob("*.py")), *sorted((SRC / "tools").glob("*.py")),
                 *sorted((SRC / "permissions").glob("*.py")), *sorted((SRC / "goals").glob("*.py")), *sorted((SRC / "coding").rglob("*.py"))]:
        assert "jarvis.self_repair" not in path.read_text(encoding="utf-8"), path.name


def test_public_api_has_no_permission_parameters():
    for cls in (RepairEngine, RepairPlanner):
        for name, fn in inspect.getmembers(cls, inspect.isfunction):
            for p in inspect.signature(fn).parameters:
                assert p.lower() not in policy.RESERVED_KEYS, f"{cls.__name__}.{name}({p})"
    for attr in ("execute", "grant", "confirm", "write", "commit", "push", "install"):
        assert not hasattr(RepairEngine, attr)


def test_the_engine_holds_no_handle_on_tools_or_permissions_at_runtime():
    from repair_util import rig
    engine, *_ = rig()
    assert not {k for k in vars(engine) if any(w in k.lower() for w in ("tool", "permission", "registry", "provider", "gateway", "file", "path"))}


def test_hard_limits_exist():
    assert policy.MAX_ATTEMPTS_HARD == 5 and policy.MAX_ATTEMPTS_DEFAULT == 3 and policy.MAX_TIMEOUT <= 3600


# ---- behavioural invariants ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(policy.RESERVED_KEYS))
def test_bypass_keys_are_refused_in_contexts_and_proposals(key):
    with pytest.raises(InvalidRepairError):
        check_context("/w", "x", {key: True})
    with pytest.raises(InvalidRepairError):
        check_context("/w", "x", {"candidates": [{"edits": [{**EDIT, key: True}]}]})
    from jarvis.self_repair import Diagnosis, ErrorCategory, TestResult
    ctx = RepairContext("/w", (), None, ({"edits": [EDIT], key: True},), True)
    with pytest.raises(PlanBlocked):
        RepairPlanner().plan(TestResult(False), Diagnosis(ErrorCategory.ASSERTION_FAILURE, "", (), (), True), ctx, 1)


@pytest.mark.parametrize("path", [".env", "a/.env", "x.pem", "x.key", "credentials.json", "secrets.py", "id_rsa", "../x.py", "/etc/passwd", "C:\\x.py",
                                  "tests/test_a.py", ".git/hooks/pre-commit", "pyproject.toml", "setup.py", "src/jarvis/permissions/engine.py"])
def test_planner_never_accepts_secret_traversal_test_manifest_or_security_targets(path):
    from jarvis.self_repair import Diagnosis, ErrorCategory, TestResult
    ctx = RepairContext("/w", (), None, ({"edits": [{**EDIT, "path": path}]},), True)
    with pytest.raises(PlanBlocked):
        RepairPlanner().plan(TestResult(False), Diagnosis(ErrorCategory.ASSERTION_FAILURE, "", (), (), True), ctx, 1)


def test_the_engine_only_ever_sends_the_coding_vocabulary_to_the_agent():
    from repair_util import EDIT as E, FakeCodingAgent, candidates, failing, rig
    agent = FakeCodingAgent([failing(), test_run(True), test_run(True)])
    engine, *_ = rig(agent)
    engine.run(engine.create("Behebe", workspace="/w", context={"candidates": candidates(E)}).run_id)
    for t in agent.tasks:
        assert t.required_capabilities <= {"coding.read", "coding.write", "coding.test"} and t.agent_id == "coding"
        assert set(t.input) == {"steps"} and policy.find_reserved(t.input) is None
        for s in t.input["steps"]:
            assert s["action"] in {"start", "info", "test", "write", "changes", "stop"} and "confirmed" not in s
