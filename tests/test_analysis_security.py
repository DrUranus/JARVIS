"""Source scans and boundary proofs for research / business / finance (+ their /run tools): no new capability, no direct access to anything, no live money."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from analysis_util import SHOP_A, make_rig, plain_orch
from browser_util import NO, ONCE
from jarvis.agents import AgentTask, TaskStatus
from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext, ToolGateway
from jarvis.agents.errors import ToolAccessError
from jarvis.business.agent import BusinessAgent
from jarvis.finance import RiskLimits
from jarvis.finance.agent import FinanceAgent, LIVE_KINDS
from jarvis.permissions import PermissionLevel, ActionSpec, ResourceType
from jarvis.research.agent import ResearchAgent
from jarvis.tools.base import ProtectedTool, ToolParameter, ToolResult

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
PKGS = {name: SRC / name for name in ("research", "business", "finance")}
S = TaskStatus


def modules(root: Path):
    for f in sorted(root.glob("*.py")):
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


BANNED = {"subprocess", "os", "shutil", "socket", "ssl", "http", "requests", "httpx", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "ctypes", "pty", "pyautogui", "mss",
          "playwright", "selenium", "pickle", "marshal", "importlib", "multiprocessing", "threading", "concurrent", "asyncio", "sched", "webbrowser", "tempfile", "pathlib", "sqlite3",
          "signal", "winreg", "keyring", "getpass", "openai", "anthropic", "sys", "builtins", "runpy", "code", "codeop", "git", "pip", "glob", "fnmatch", "paramiko", "xmlrpc", "imp",
          "inspect", "shelve", "dbm", "csv", "json5", "yaml", "toml", "tomllib", "logging", "atexit", "smtp", "email", "urllib3"}
ALLOWED_URLLIB = {"urllib.parse"}
FORBIDDEN_JARVIS = ("jarvis.browser", "jarvis.coding", "jarvis.computer", "jarvis.permissions", "jarvis.llm", "jarvis.voice", "jarvis.planning", "jarvis.core", "jarvis.interface",
                    "jarvis.bootstrap", "jarvis.tools", "jarvis.memory", "jarvis.tasks", "jarvis.goals", "jarvis.self_repair", "jarvis.config", "jarvis.agents.factory",
                    "jarvis.agents.adapters", "jarvis.agents.fake", "jarvis.agents.orchestrator", "jarvis.agents.registry", "jarvis.agents.groups")
ALLOWED_AGENT_MODULES = {"jarvis.agents", "jarvis.agents.agent", "jarvis.agents.context", "jarvis.agents.errors", "jarvis.agents.models", "jarvis.agents.policy",
                         "jarvis.agents.result", "jarvis.agents.state"}


def all_modules():
    for pkg, root in PKGS.items():
        for f, tree in modules(root):
            yield pkg, f, tree


def test_no_dangerous_network_file_process_or_scheduling_module_is_imported():
    for pkg, f, tree in all_modules():
        for m in imports(tree):
            top = m.split(".")[0]
            assert top not in BANNED, f"{pkg}/{f.name} imports {m}"
            if top == "urllib":
                assert any(m == a or m.startswith(a + ".") for a in ALLOWED_URLLIB), f"{pkg}/{f.name} imports {m}"       # only URL PARSING


def test_only_agent_interfaces_and_neighbouring_pure_modules_are_imported():
    allowed_siblings = {"research": {"research"}, "business": {"business", "research"}, "finance": {"finance", "research"}}
    for pkg, f, tree in all_modules():
        for m in imports(tree):
            assert not m.startswith(FORBIDDEN_JARVIS), f"{pkg}/{f.name} imports {m}"
            if m.startswith("jarvis.agents"):
                assert m in ALLOWED_AGENT_MODULES or m.rsplit(".", 1)[0] in ALLOWED_AGENT_MODULES, f"{pkg}/{f.name} imports {m}"
            elif m.startswith("jarvis."):
                assert m.split(".")[1] in allowed_siblings[pkg] | {"errors", "redaction"}, f"{pkg}/{f.name} imports {m}"
    for pkg in ("research",):
        for f, tree in modules(PKGS[pkg]):
            assert not any(m.startswith(("jarvis.business", "jarvis.finance")) for m in imports(tree))
    # business and finance do not know each other
    for f, tree in modules(PKGS["finance"]):
        assert not any(m.startswith("jarvis.business") for m in imports(tree))
    for f, tree in modules(PKGS["business"]):
        assert not any(m.startswith("jarvis.finance") for m in imports(tree))


def test_no_eval_exec_open_system_popen_shell_network_or_dynamic_tricks():
    names = {"eval", "exec", "compile", "open", "__import__", "breakpoint", "input", "globals", "locals", "vars", "setattr", "delattr"}
    attrs = {"system", "popen", "Popen", "check_output", "check_call", "spawn", "startfile", "kill", "terminate", "write_text", "write_bytes", "read_text", "read_bytes", "unlink",
             "rmtree", "remove", "mkdir", "makedirs", "chmod", "symlink", "environ", "getenv", "putenv", "urlopen", "urlretrieve", "connect", "sendall", "send", "sendmail",
             "import_module", "execute", "run_command", "run_test", "commit", "push", "install"}
    for pkg, f, tree in all_modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name):
                    assert n.func.id not in names, f"{pkg}/{f.name}:{n.lineno} {n.func.id}()"
                if isinstance(n.func, ast.Attribute):
                    assert n.func.attr not in attrs, f"{pkg}/{f.name}:{n.lineno} .{n.func.attr}()"
            if isinstance(n, ast.keyword):
                assert n.arg not in {"shell", "confirmed", "confirm", "force", "bypass", "skip_permissions", "unsafe", "grant", "approval"}, f"{pkg}/{f.name}: keyword {n.arg}"
            if isinstance(n, ast.Attribute):
                assert n.attr not in {"__dict__", "__globals__", "__subclasses__", "__builtins__", "__code__"}, f"{pkg}/{f.name}:{n.lineno} .{n.attr}"


def test_nothing_names_providers_registries_permission_internals_or_a_second_orchestrator():
    banned = {"ToolRegistry", "ToolGateway", "PermissionEngine", "PermissionDecision", "ProtectedTool", "ExecutionGrant", "BrowserProvider", "ComputerProvider", "CodingProvider",
              "BrowserController", "ComputerController", "CodingController", "AgentOrchestrator", "MemoryStore", "TaskManager"}
    for pkg, f, tree in all_modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                assert n.id not in banned, f"{pkg}/{f.name}:{n.lineno} {n.id}"
            if isinstance(n, ast.ClassDef):
                assert not any(w in n.name for w in ("Orchestrator", "Scheduler", "Executor", "Permission", "Registry", "Gateway", "Broker", "Order")), f"{pkg}/{f.name}: class {n.name}"
            if isinstance(n, ast.FunctionDef):
                assert not any(w in n.name.lower() for w in ("place_order", "execute_order", "withdraw", "transfer", "send_email", "send_message", "login", "credential")), \
                    f"{pkg}/{f.name}: def {n.name}"


def test_text_scan_of_code_for_forbidden_calls():
    for pkg, f, tree in all_modules():
        code = " ".join(ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Call, ast.Import, ast.ImportFrom)))
        for needle in ("shell=True", "os.system", "subprocess", "Popen(", "pyautogui", "playwright", "socket.", "requests.", "pip install", "git commit", "git push", "powershell", "cmd.exe",
                       "smtplib", "sendmail"):
            assert needle not in code, f"{pkg}/{f.name}: {needle}"


def test_no_persistence_no_memory_no_global_state():
    for pkg, f, tree in all_modules():
        assert "memory" not in " ".join(imports(tree)).lower(), f"{pkg}/{f.name}"
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                assert n.id not in {"remember", "NullMemoryStore"}, f"{pkg}/{f.name}:{n.lineno}"
            if isinstance(n, ast.Global):
                raise AssertionError(f"{pkg}/{f.name}:{n.lineno} uses a global statement")
    for name in ("memory.add", "memory.save", ".remember(", "sqlite", "shelve", "pickle"):
        assert not any(name in f.read_text(encoding="utf-8") for root in PKGS.values() for f in root.glob("*.py")), name


def test_the_browser_actions_the_research_agent_can_issue_are_read_only():
    tree = ast.parse((PKGS["research"] / "agent.py").read_text(encoding="utf-8"))
    actions = {kw.value.value for n in ast.walk(tree) if isinstance(n, ast.Call) for kw in n.keywords if kw.arg == "action" and isinstance(kw.value, ast.Constant)}
    assert actions == {"status", "start", "goto", "text", "links", "stop"}, actions                  # no click, fill, submit, upload, download, select, check ...


def test_nothing_else_imports_the_analysis_layers_except_the_composition_code():
    allowed = {"agents/factory.py", "agents/groups.py", "tools/analysis.py", "goals/planner.py"}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.split("/")[0] in ("research", "business", "finance") or rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        assert not any(f"jarvis.{p}" in text for p in ("research", "business", "finance")), rel
    for rel in ("core", "permissions", "browser", "coding", "computer", "memory", "llm"):
        for path in (SRC / rel).rglob("*.py"):
            assert "jarvis.finance" not in path.read_text(encoding="utf-8") and "jarvis.business" not in path.read_text(encoding="utf-8"), path.name


def test_goals_planner_only_uses_plain_data_not_the_analysis_packages():
    text = (SRC / "goals" / "planner.py").read_text(encoding="utf-8")
    assert "jarvis.research" not in text and "jarvis.business" not in text and "jarvis.finance" not in text


# ---- finance: no live money -----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", sorted(LIVE_KINDS) + ["place_live_order", "wire_transfer", "withdraw_funds", "broker_connect", "order_buy"])
def test_finance_agent_refuses_every_live_action(kind):
    o, _ = plain_orch([FinanceAgent()])
    res = o.run(AgentTask("Kaufe 10 Aktien", agent_id="finance", input={"kind": kind, "symbol": "AAPL", "quantity": 10, "amount": 1000, "iban": "DE00"},
                          required_capabilities=frozenset({"finance.analyze"})))
    assert res.status is S.BLOCKED and res.error_code == "live_trading_not_supported"


def test_there_is_no_way_to_enable_live_trading_by_configuration_or_limits():
    from jarvis.config import ConfigError, FinanceSettings, load_settings
    assert FinanceSettings().paper_trading_only is True
    for env in ({"JARVIS_FINANCE_PAPER_TRADING_ONLY": "false"}, {"JARVIS_FINANCE_MAX_LEVERAGE": "2"}, {"JARVIS_FINANCE_MAX_LEVERAGE": "0.5"}):
        with pytest.raises(ConfigError):
            load_settings(env=env)
    with pytest.raises(Exception):
        RiskLimits(max_leverage=3.0)
    with pytest.raises(Exception):
        RiskLimits(allow_withdrawals=True)


def test_finance_and_business_have_no_tool_access_at_all_and_research_has_exactly_the_browser():
    assert FinanceAgent.tool_names == frozenset() and BusinessAgent.tool_names == frozenset() and ResearchAgent.tool_names == frozenset({"browser"})
    for cls in (FinanceAgent, BusinessAgent, ResearchAgent):
        assert issubclass(cls, Agent) and "tools" not in cls.__init__.__code__.co_varnames


def test_finance_output_always_says_paper_and_analysis_only():
    o, _ = plain_orch([FinanceAgent()])
    res = o.run(AgentTask("Risiko", agent_id="finance", input={"kind": "risk_analysis", "prices": [100, 101, 99]}, required_capabilities=frozenset({"finance.analyze"})))
    assert res.output["paper"] is True and "nothing was ordered, transferred or withdrawn" in res.output["disclaimer"]


# ---- business: no messages without permission --------------------------------------------------------------------------------------------------------
class Outbox(ProtectedTool):
    """A stand-in for any future 'send a message' tool: YELLOW, so the permission engine decides every call."""
    name = "outbox"
    description = "send a message (test double)"
    parameters = (ToolParameter("to", "recipient"), ToolParameter("text", "text"))
    permission = PermissionLevel.YELLOW
    sent: list = []

    def describe_action(self, **kw):
        return ActionSpec(action="send", resource=str(kw.get("to")), resource_type=ResourceType.OTHER, reason="send a message")

    def _perform(self, **kw):
        Outbox.sent.append(kw)
        return ToolResult.ok("sent")


class Chatty(BusinessAgent):
    """A business agent that (against its design) tries to use a messaging tool: it needs the tool declared AND the permission engine's yes."""
    tool_names = frozenset({"outbox"})

    def perform(self, task, ctx):
        res = ctx.tools.call("outbox", to="lead@example.com", text="Hallo, unser Angebot ...")
        return super().perform(task, ctx) if res.success else __import__("jarvis.agents", fromlist=["AgentOutcome"]).AgentOutcome.blocked(str(res.error), code="permission_denied")


def chatty_rig(tmp_path, answers):
    r = make_rig(tmp_path, answers, agents=[Chatty()])
    Outbox.sent = []
    r.registry.register(Outbox())
    return r


def test_a_message_tool_is_only_reachable_through_the_permission_engine(tmp_path):
    r = chatty_rig(tmp_path, [NO])
    res = r.run("business", {"kind": "lead_list"}, caps={"business.analyze"})
    assert res.status is S.BLOCKED and res.error_code == "permission_denied" and Outbox.sent == [] and [q.tool for q in r.prompts.requests] == ["outbox"]
    r2 = chatty_rig(tmp_path / "none", [])
    assert r2.run("business", {"kind": "lead_list"}, caps={"business.analyze"}).status is S.BLOCKED and Outbox.sent == []        # no answer = no message


def test_the_real_business_agent_cannot_reach_a_message_tool_at_all(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, agents=[BusinessAgent()])
    Outbox.sent = []
    r.registry.register(Outbox())
    res = r.run("business", {"kind": "lead_list"}, caps={"business.analyze"})
    assert res.status is S.SUCCEEDED and Outbox.sent == [] and not r.prompts.requests
    gw = ToolGateway(r.registry, BusinessAgent.tool_names, __import__("threading").Event())
    with pytest.raises(ToolAccessError):
        gw.call("outbox", to="x", text="y")
    assert Outbox.sent == []


# ---- research: the browser's own security stays in charge ---------------------------------------------------------------------------------------------
def test_a_more_permissive_research_filter_cannot_get_past_the_browser_rules(tmp_path):
    r = make_rig(tmp_path, private_ok=("10.0.0.5",))                       # the research layer would let it through; the browser controller + engine are RED
    res = r.run("research", {"urls": ["http://10.0.0.5/secret"], "questions": ["x"]})
    assert not [c for c in r.provider.calls_named("page.goto") if "10.0.0.5" in str(c[1])] and res.status in (S.FAILED, S.BLOCKED)


def test_the_gateway_refuses_bypass_arguments_and_foreign_tools_for_every_new_agent(tmp_path):
    r = make_rig(tmp_path)
    gw = ToolGateway(r.registry, ResearchAgent.tool_names, __import__("threading").Event())
    for kw in ({"confirmed": True}, {"force": True}, {"bypass": True}, {"skip_permissions": True}, {"approval": "x"}, {"grant": 1}, {"unsafe": 1}):
        with pytest.raises(ToolAccessError):
            gw.call("browser", action="goto", url=SHOP_A, **kw)
    for tool in ("computer", "coding", "mouse", "keyboard", "outbox", "echo"):
        with pytest.raises(ToolAccessError):
            gw.call(tool)
    assert not r.provider.calls_named("page.goto")


def test_task_input_cannot_smuggle_confirmations_into_any_agent(tmp_path):
    r = make_rig(tmp_path, agents=[ResearchAgent(), BusinessAgent(), FinanceAgent()])
    for agent, cap, base in (("research", "research.web", {"urls": [SHOP_A]}), ("business", "business.analyze", {"kind": "lead_list"}),
                             ("finance", "finance.analyze", {"kind": "risk_analysis", "prices": [1, 2, 3]})):
        res = r.run(agent, {**base, "confirmed": True}, caps={cap})
        assert res.status is S.FAILED or res.status is S.SUCCEEDED
        assert not [q for q in r.prompts.requests if getattr(q, "confirmed", False)]
    assert r.run("research", {"urls": [SHOP_A], "confirmed": True}, caps={"research.web"}).error_code == "invalid_input"


def test_limits_have_hard_maxima():
    from jarvis.config import ConfigError, load_settings
    for env in ({"JARVIS_RESEARCH_MAX_SOURCES": "21"}, {"JARVIS_RESEARCH_MAX_ACTIONS": "201"}, {"JARVIS_RESEARCH_TIMEOUT_SECONDS": "1801"}, {"JARVIS_BUSINESS_MAX_STEPS": "101"},
                {"JARVIS_BUSINESS_TIMEOUT_SECONDS": "601"}, {"JARVIS_FINANCE_MAX_STEPS": "1001"}, {"JARVIS_FINANCE_TIMEOUT_SECONDS": "601"}, {"JARVIS_RESEARCH_MAX_SOURCES": "0"},
                {"JARVIS_FINANCE_MAX_POSITION_PCT": "101"}, {"JARVIS_FINANCE_MAX_RISK_PER_TRADE_PCT": "6"}):
        with pytest.raises(ConfigError):
            load_settings(env=env)
