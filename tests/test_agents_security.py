"""Source scans and boundary checks of the orchestration layer: it must add no capability and offer no way around ToolRegistry/PermissionEngine."""
import ast
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
AGENTS = SRC / "agents"
ADAPTERS = AGENTS / "adapters"


def modules(root: Path, recursive: bool = True):
    for f in sorted(root.rglob("*.py") if recursive else root.glob("*.py")):
        yield f, ast.parse(f.read_text(encoding="utf-8"))


def imports(tree) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


BANNED_MODULES = {"subprocess", "os", "shutil", "socket", "ssl", "http", "urllib", "requests", "httpx", "ftplib", "smtplib", "ctypes", "pty", "pyautogui",
                  "mss", "playwright", "selenium", "pickle", "marshal", "importlib", "multiprocessing", "webbrowser", "tempfile", "pathlib", "sqlite3",
                  "asyncio", "signal", "winreg", "keyring", "getpass", "openai", "anthropic", "sys", "builtins", "runpy", "code", "codeop"}
FORBIDDEN_JARVIS = ("jarvis.browser", "jarvis.coding", "jarvis.computer", "jarvis.permissions", "jarvis.llm", "jarvis.voice", "jarvis.planning",
                    "jarvis.core", "jarvis.interface", "jarvis.bootstrap")


def test_the_layer_imports_no_dangerous_or_low_level_module():
    for f, tree in modules(AGENTS):
        for m in imports(tree):
            assert m.split(".")[0] not in BANNED_MODULES, f"{f.relative_to(AGENTS)} imports {m}"


def test_the_layer_never_imports_the_subsystems_it_coordinates_nor_the_permission_internals():
    for f, tree in modules(AGENTS):
        for m in imports(tree):
            assert not m.startswith(FORBIDDEN_JARVIS), f"{f.relative_to(AGENTS)} imports {m}"
    allowed_jarvis = {"jarvis.errors", "jarvis.redaction", "jarvis.tasks", "jarvis.tools", "jarvis.config", "jarvis.memory"}
    for f, tree in modules(AGENTS):
        for m in imports(tree):
            if m.startswith("jarvis.") and not m.startswith("jarvis.agents"):
                # only the composition code (factory.py) builds the Phase-10 agents; nothing else in the layer knows research/business/finance
                extra = {"jarvis.research", "jarvis.business", "jarvis.finance"} if f.name == "factory.py" else set()
                assert any(m == a or m.startswith(a + ".") for a in allowed_jarvis | extra), f"{f.relative_to(AGENTS)} imports {m}"
    mem_users = [f.name for f, t in modules(AGENTS) if any(m.startswith("jarvis.memory") for m in imports(t))]
    assert mem_users == ["factory.py"]      # only the composition code touches the memory TYPE; the orchestrator gets a read-only callable


def test_no_eval_exec_open_system_popen_shell_or_dynamic_attribute_tricks():
    banned_names = {"eval", "exec", "compile", "open", "__import__", "breakpoint", "input", "globals", "locals", "vars"}
    banned_attrs = {"system", "popen", "Popen", "check_output", "check_call", "spawn", "startfile", "kill", "killpg", "terminate",
                    "write_text", "write_bytes", "unlink", "rmtree", "remove", "mkdir", "makedirs", "chmod", "symlink", "environ", "getenv", "putenv"}
    for f, tree in modules(AGENTS):
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = n.func
                if isinstance(fn, ast.Name):
                    assert fn.id not in banned_names, f"{f.name}:{n.lineno} {fn.id}()"
                if isinstance(fn, ast.Attribute):
                    assert fn.attr not in banned_attrs, f"{f.name}:{n.lineno} .{fn.attr}()"
            if isinstance(n, ast.keyword):
                assert n.arg != "shell", f"{f.name}: shell="
            if isinstance(n, ast.Attribute):
                assert n.attr not in {"__dict__", "__globals__", "__subclasses__", "__builtins__", "__code__"}, f"{f.name}:{n.lineno} .{n.attr}"
        text = f.read_text(encoding="utf-8")
        for needle in ("shell=True", "os.system", "subprocess", "Popen", "pyautogui", "playwright", "socket.", "requests."):
            code_lines = [ln for ln in text.splitlines() if needle in ln and not ln.lstrip().startswith(("#", '"""', "*"))]
            for ln in code_lines:  # a mention is allowed only inside prose (docstrings/comments describing what is NOT done)
                assert ln.lstrip().startswith(("The ", "It ", "`", "-", "(", "Nothing", "no ", "No ")) or '"' in ln or "'" in ln or needle in "".join(
                    l for l in ln.split("#")[1:]), f"{f.name}: {ln.strip()[:80]}"


def test_agents_reach_tools_only_through_the_gateway():
    """`.execute(` on a ToolRegistry exists in exactly one place (the gateway); adapters and agents never see a registry, an engine or a controller."""
    execs = [(f.name, n.lineno) for f, t in modules(AGENTS) for n in ast.walk(t)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"]
    assert execs == [("context.py", execs[0][1])]
    for f, tree in modules(ADAPTERS):
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id in {"ToolRegistry", "PermissionEngine", "Controller", "Provider"}:
                pytest.fail(f"adapters/{f.name}:{n.lineno} names {n.id}")
            if isinstance(n, ast.Attribute) and n.attr in {"_registry", "registry", "engine", "permissions", "controller", "_controller", "provider", "_provider",
                                                           "execute", "authorize", "execution_scope", "_cancel"}:
                pytest.fail(f"adapters/{f.name}:{n.lineno} touches .{n.attr}")
    for f, tree in modules(AGENTS):
        if f.name in ("orchestrator.py", "factory.py"):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in {"controller", "_controller", "authorize", "execution_scope", "update_policy", "revoke_session_grants"}:
                pytest.fail(f"{f.name}:{n.lineno} touches .{n.attr}")


def test_nothing_in_the_layer_creates_or_alters_permissions():
    for f, tree in modules(AGENTS):
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id in {"PermissionLevel", "PermissionRequest", "PermissionDecision", "ExecutionGrant", "Policy", "Rule", "PathGuard",
                                                    "ConfirmationProvider", "ScriptedConfirmation", "DenyAllConfirmation", "current_grant"}:
                pytest.fail(f"{f.name}:{n.lineno} uses {n.id}")
    text = "\n".join(f.read_text(encoding="utf-8") for f in AGENTS.rglob("*.py"))
    for needle in ("confirmed=True", "force=True", "bypass=True", "caller_confirmed", "trust_caller_confirmation", "require_protected_tools=False"):
        assert needle not in text


def test_no_module_level_state_no_singletons():
    classes = {n.name for _, t in modules(AGENTS) for n in ast.walk(t) if isinstance(n, ast.ClassDef)}
    for f, tree in modules(AGENTS):
        for n in tree.body:
            assert not isinstance(n, ast.Global)
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id in classes:
                pytest.fail(f"{f.name}:{n.lineno} module-level instance {n.value.func.id}()")
        for n in ast.walk(tree):
            assert not isinstance(n, ast.Global), f"{f.name}:{n.lineno} global statement"


def test_logging_never_carries_objectives_inputs_summaries_or_outputs():
    forbidden = {"objective", "input", "summary", "output", "error", "text", "args", "kwargs", "ctx", "context", "memory", "task", "result", "res", "outcome"}
    for f, tree in modules(AGENTS):
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"debug", "info", "warning", "error", "exception", "critical"}
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "log"):
                for arg in n.args[1:]:
                    if isinstance(arg, ast.Attribute) and arg.attr in {"task_id", "id", "value"}:  # identifiers and enum values only
                        continue
                    for sub in ast.walk(arg):
                        if isinstance(sub, ast.Name):
                            assert sub.id not in forbidden, f"{f.name}:{n.lineno} logs {sub.id!r}"
                        if isinstance(sub, ast.Attribute):
                            assert sub.attr not in {"objective", "input", "summary", "output", "error"}, f"{f.name}:{n.lineno} logs .{sub.attr}"


def test_the_rest_of_jarvis_does_not_depend_on_the_agent_layer():
    for f, tree in modules(SRC):
        rel = f.relative_to(SRC)
        if rel.parts[0] in ("agents", "goals", "self_repair", "research", "business", "finance") or f.name == "bootstrap.py" or rel.as_posix() == "interface/cli.py":
            continue
        assert not any(m == "jarvis.agents" or m.startswith("jarvis.agents.") for m in imports(tree)), rel
    cli = (SRC / "interface" / "cli.py").read_text(encoding="utf-8")
    assert "jarvis.agents.errors" in cli and "import jarvis.agents" not in cli.replace("from jarvis.agents.errors import AgentError", "")


def test_the_existing_subsystems_are_untouched_by_this_layer():
    for pkg in ("browser", "coding", "computer", "permissions", "memory"):
        for f, tree in modules(SRC / pkg):
            assert "jarvis.agents" not in "".join(imports(tree)), f"{pkg}/{f.name}"


def test_the_layer_has_no_agent_that_can_change_the_system_itself():
    caps = (AGENTS / "policy.py").read_text(encoding="utf-8")
    assert "self" not in caps.lower().replace("itself", "").split("known_capabilities")[1].split(")")[0]
    from jarvis.agents import policy
    assert policy.KNOWN_CAPABILITIES == {"browser.read", "browser.interact", "coding.read", "coding.write", "coding.test", "coding.plan", "computer.screen",
                                         "computer.input", "research.web", "business.analyze", "finance.analyze"}      # no shell/install/commit/push/network capability exists
    assert not any(w in c for c in policy.KNOWN_CAPABILITIES for w in ("shell", "git", "install", "ssh", "network", "credential", "admin", "self"))


def test_importing_and_building_the_layer_starts_no_thread_and_needs_no_extra_library():
    code = ("import sys, threading; before = threading.active_count(); import jarvis.agents, jarvis.agents.adapters, jarvis.agents.factory; "
            "from jarvis.agents import AgentOrchestrator, AgentRegistry; AgentOrchestrator(AgentRegistry()); "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('playwright','selenium','pyautogui','mss','requests','httpx','openai','anthropic','subprocess_run')]; "
            "print('CLEAN' if not bad and threading.active_count() == before else ('BAD', bad, threading.active_count(), before))")
    with tempfile.TemporaryDirectory():
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    assert "CLEAN" in out.stdout, out.stdout + out.stderr


def test_the_orchestrator_does_not_start_more_threads_than_its_limit(tmp_path):
    import threading
    from agents_util import FakeAgent, make, task, wait_event
    agents = [FakeAgent(f"t{i}", behavior="wait") for i in range(6)]
    orch, _, _ = make(agents, inline=False, max_concurrent=2)
    base = threading.active_count()
    ids = []
    for i in range(6):
        t = task(f"x{i}", agent_id=f"t{i}")
        ids.append(t.task_id)
        orch.submit(t), orch.start(t.task_id)
    wait_event(agents[0].started), wait_event(agents[1].started)
    assert threading.active_count() - base <= 2          # six tasks, two workers: no thread per queued task
    orch.shutdown(wait=10)
