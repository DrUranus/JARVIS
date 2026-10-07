"""Source scans and boundary checks of the goal layer: it adds no capability, no permission and no way around the agent layer."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from jarvis.goals import GoalEngine, GoalPlanner, check_user_context, policy
from jarvis.goals.errors import InvalidGoalError

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
GOALS = SRC / "goals"


def modules():
    for f in sorted(GOALS.glob("*.py")):
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
                  "asyncio", "signal", "winreg", "keyring", "getpass", "openai", "anthropic", "sys", "builtins", "runpy", "code", "codeop", "git",
                  "pip", "setuptools", "site", "zipimport", "pkgutil", "inspect"}
FORBIDDEN_JARVIS = ("jarvis.browser", "jarvis.coding", "jarvis.computer", "jarvis.permissions", "jarvis.llm", "jarvis.voice", "jarvis.planning",
                    "jarvis.core", "jarvis.interface", "jarvis.bootstrap", "jarvis.tools", "jarvis.memory", "jarvis.tasks",
                    "jarvis.agents.context", "jarvis.agents.adapters", "jarvis.agents.factory", "jarvis.agents.fake")
ALLOWED_JARVIS = ("jarvis.goals", "jarvis.errors", "jarvis.redaction", "jarvis.config", "jarvis.agents")


def test_no_dangerous_low_level_or_installer_module_is_imported():
    for f, tree in modules():
        for m in imports(tree):
            assert m.split(".")[0] not in BANNED_MODULES, f"{f.name} imports {m}"


def test_goal_layer_never_imports_subsystems_providers_tools_or_permissions():
    for f, tree in modules():
        for m in imports(tree):
            assert not m.startswith(FORBIDDEN_JARVIS), f"{f.name} imports {m}"
            if m.startswith("jarvis."):
                assert any(m == a or m.startswith(a + ".") for a in ALLOWED_JARVIS), f"{f.name} imports {m}"


def test_only_the_factory_touches_the_config_and_only_the_agent_layers_data_types_are_used():
    cfg = [f.name for f, t in modules() if any(m.startswith("jarvis.config") for m in imports(t))]
    assert cfg == ["factory.py"]
    allowed_agents = {"jarvis.agents", "jarvis.agents.errors", "jarvis.agents.models", "jarvis.agents.result", "jarvis.agents.state",
                      "jarvis.agents.planner", "jarvis.agents.policy"}
    for f, tree in modules():
        for m in imports(tree):
            if m.startswith("jarvis.agents"):
                assert any(m == a or m.startswith(a + ".") for a in allowed_agents), f"{f.name} imports {m}"


def test_no_eval_exec_open_system_popen_shell_or_dynamic_attribute_tricks():
    banned_names = {"eval", "exec", "compile", "open", "__import__", "breakpoint", "input", "globals", "locals", "vars", "getattr_static"}
    banned_attrs = {"system", "popen", "Popen", "check_output", "check_call", "spawn", "startfile", "kill", "killpg", "terminate", "write_text",
                    "write_bytes", "unlink", "rmtree", "remove", "mkdir", "makedirs", "chmod", "symlink", "environ", "getenv", "putenv", "execute",
                    "run_command", "run_test", "perform", "call", "commit", "push", "install", "load_plugin", "register"}
    for f, tree in modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = n.func
                if isinstance(fn, ast.Name):
                    assert fn.id not in banned_names, f"{f.name}:{n.lineno} {fn.id}()"
                if isinstance(fn, ast.Attribute) and not (isinstance(fn.value, ast.Name) and fn.value.id == "atexit"):   # atexit.register(shutdown) only
                    assert fn.attr not in banned_attrs, f"{f.name}:{n.lineno} .{fn.attr}()"
            if isinstance(n, ast.keyword):
                assert n.arg not in {"shell", "confirmed", "confirm", "force", "bypass", "skip_permissions", "unsafe", "grant", "approval"}, \
                    f"{f.name}: keyword {n.arg}"
            if isinstance(n, ast.Attribute):
                assert n.attr not in {"__dict__", "__globals__", "__subclasses__", "__builtins__", "__code__"}, f"{f.name}:{n.lineno} .{n.attr}"


def test_code_never_names_providers_registries_or_permission_internals():
    """Identifiers (not docstrings/strings): the goal layer has no handle on anything below the orchestrator."""
    banned = {"ToolRegistry", "ToolGateway", "PermissionEngine", "PermissionDecision", "ProtectedTool", "ExecutionGrant", "BrowserProvider",
              "ComputerProvider", "CodingProvider", "BrowserController", "ComputerController", "CodingController", "AgentContext", "tools"}
    for f, tree in modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                assert n.id not in banned, f"{f.name}:{n.lineno} {n.id}"
            if isinstance(n, ast.Attribute):
                assert n.attr not in banned, f"{f.name}:{n.lineno} .{n.attr}"
            if isinstance(n, (ast.arg,)):
                assert n.arg not in banned, f"{f.name}:{n.lineno} arg {n.arg}"


def test_the_only_orchestrator_calls_are_the_public_task_interface():
    used: set[str] = set()
    for f, tree in modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr in ("_orch",):
                used.add(n.attr)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" and n.attr == "_orch":
                pass
    called = {n.func.attr for f, t in modules() for n in ast.walk(t) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "_orch"}
    assert called <= {"submit", "start", "wait", "wait_any", "cancel", "notify_waiters"}, called
    assert {"submit", "start", "wait_any", "cancel"} <= called


def test_text_scan_for_forbidden_calls_in_code_lines():
    """Docstrings may SAY what is not done; no code line may do it."""
    for f, tree in modules():
        strings = {id(c) for n in ast.walk(tree) for c in ast.walk(n) if isinstance(n, ast.Expr) and isinstance(c, ast.Constant)}   # docstring nodes
        code = ast.unparse(ast.parse("\n".join(ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Call, ast.Import, ast.ImportFrom)) and id(n) not in strings)))
        for needle in ("shell=True", "os.system", "subprocess", "Popen(", "pyautogui", "playwright", "socket.", "requests.", "pip install", ".execute("):
            assert needle not in code, f"{f.name}: {needle}"


def test_the_goal_layer_writes_nothing_and_has_no_persistence():
    for f, tree in modules():
        text = f.read_text(encoding="utf-8")
        assert "memory" not in " ".join(imports(tree)).lower(), f.name
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                assert n.id not in {"MemoryStore", "NullMemoryStore", "remember", "TaskManager"}, f"{f.name}:{n.lineno}"
    for name in ("remember", "memory.add", "memory.save", ".add_entry(", ".store("):
        assert not any(name in f.read_text(encoding="utf-8") for f in GOALS.glob("*.py")), name


def test_core_and_agent_layer_do_not_import_the_goal_layer():
    for path in [*sorted((SRC / "core").glob("*.py")), *sorted((SRC / "agents").rglob("*.py")), *sorted((SRC / "tools").glob("*.py")),
                 *sorted((SRC / "permissions").glob("*.py"))]:
        assert "jarvis.goals" not in path.read_text(encoding="utf-8"), path.name


def test_public_api_has_no_permission_parameters():
    reserved = policy.RESERVED_KEYS
    for cls in (GoalEngine, GoalPlanner):
        for name, fn in inspect.getmembers(cls, inspect.isfunction):
            for p in inspect.signature(fn).parameters:
                assert p.lower() not in reserved, f"{cls.__name__}.{name}({p})"
    assert not hasattr(GoalEngine, "execute") and not hasattr(GoalEngine, "grant") and not hasattr(GoalEngine, "confirm")


def test_the_engine_has_no_handle_on_tools_or_permissions_at_runtime():
    from goals_util import rig
    engine, *_ = rig()
    held = {k for k, v in vars(engine).items()}
    assert not {k for k in held if any(w in k.lower() for w in ("tool", "permission", "registry", "provider", "gateway"))}


# ---- behavioural invariants ------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(policy.RESERVED_KEYS))
def test_reserved_bypass_keys_are_refused_everywhere(key):
    with pytest.raises(InvalidGoalError):
        check_user_context({"edits": [{"path": "a", key: True}]})
    with pytest.raises(InvalidGoalError):
        check_user_context({key: True})
    from goals_util import FakeAgent, rig, step
    agent = FakeAgent("fake")
    engine, *_ = rig([agent], lambda goal: [step(goal, "s1", input={"steps": [{"action": "click", "x": {"y": {key: True}}}]})])
    res = engine.run(engine.create("x").goal_id)
    assert res.status.value == "BLOCKED" and not agent.tasks


def test_unknown_capability_or_agent_cannot_be_smuggled_in_by_a_planner():
    from goals_util import FakeAgent, rig, step
    agent = FakeAgent("fake")
    for make in (lambda g: [step(g, "s1", caps=frozenset({"admin.root"}))], lambda g: [step(g, "s1", "ghost")]):
        engine, *_ = rig([agent], make)
        res = engine.run(engine.create("x").goal_id)
        assert res.status.value == "BLOCKED" and not agent.tasks


def test_a_goal_gets_exactly_the_capabilities_its_step_names():
    """The task handed to the orchestrator carries ONLY the step's capabilities (least privilege) and no bypass-style input."""
    from goals_util import FakeAgent, chain, rig
    agent = FakeAgent("fake")
    engine, *_ = rig([agent], chain("s1"))
    engine.run(engine.create("x", context={"url": "https://a.test/"}).goal_id)
    t = agent.tasks[0]
    assert t.required_capabilities == {"research.web"} and policy.find_reserved(t.input) is None and t.agent_id == "fake"
    assert set(t.metadata) == {"goal_id", "step_id"}


def test_the_user_context_cannot_reach_agents_except_through_the_planner(tmp_path):
    from goals_util import FakeAgent, chain, rig
    agent = FakeAgent("fake")
    engine, _, _, _, planner = rig([agent], chain("s1"))
    engine.run(engine.create("x", context={"url": "https://a.test/"}).goal_id)
    assert planner.calls[0].explicit_user_context == {"url": "https://a.test/"}
    assert "a.test" not in str(agent.tasks[0].input)          # the engine passed the plan's input, not the context
