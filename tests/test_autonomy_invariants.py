"""Phase 14, Teilziel 3: Autonomie-Invarianten als Tests.

Nagelt die Voreinstellungen (alles Autonome aus), die harten Obergrenzen und die einzige Kontrollstelle (ToolRegistry.execute -> PermissionEngine) fest.
Schlaegt an, sobald jemand ein Limit lockert, einen Default einschaltet oder goals/ bzw. agents/ an der Kontrollstelle vorbei Aktionen ausfuehren laesst.
Reine Textpruefung/AST: kein Netzwerk, keine Plattformabhaengigkeit.
"""
import ast
import tomllib
from pathlib import Path

import pytest

from jarvis.config import Settings, load_settings
from jarvis.errors import ConfigError
from jarvis.goals import policy as goal_policy

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "jarvis"
TOML = ROOT / "config" / "jarvis.toml"

DEFAULT_OFF = ["agents", "goals", "computer", "browser", "coding", "self_repair", "self_improvement", "research", "business", "finance"]


def _toml() -> dict:
    return tomllib.loads(TOML.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Voreinstellungen

@pytest.mark.parametrize("section", DEFAULT_OFF)
def test_shipped_toml_keeps_autonomous_subsystems_disabled(section):
    assert _toml()[section]["enabled"] is False


@pytest.mark.parametrize("section", DEFAULT_OFF)
def test_code_defaults_keep_autonomous_subsystems_disabled(section):
    assert getattr(Settings(), section).enabled is False


def test_replanning_default_off_in_toml_and_code():
    assert _toml()["goals"]["replanning"] is False
    assert Settings().goals.replanning is False


def test_shipped_toml_loads_with_everything_autonomous_off():
    s = load_settings(TOML, env={})
    for section in DEFAULT_OFF:
        assert getattr(s, section).enabled is False
    assert s.goals.replanning is False


def test_security_defaults_stay_strict():
    assert _toml()["security"]["audit_strict"] is True
    assert Settings().security.audit_strict is True
    assert _toml()["finance"]["paper_trading_only"] is True
    assert Settings().finance.paper_trading_only is True


def test_paper_trading_cannot_be_disabled():
    with pytest.raises(ConfigError):
        load_settings(env={"JARVIS_FINANCE_PAPER_TRADING_ONLY": "false"})


# ---------------------------------------------------------------- harte Obergrenzen

def _goals_file(tmp_path, **kv):
    f = tmp_path / "c.toml"
    f.write_text("[goals]\n" + "".join(f"{k} = {v}\n" for k, v in kv.items()), encoding="utf-8")
    return f


def test_goal_limits_in_shipped_config_are_within_hard_limits():
    g = _toml()["goals"]
    assert 1 <= g["max_steps"] <= 50
    assert 1 <= g["max_attempts_per_step"] <= 5


def test_goal_hard_limits_are_accepted_at_the_boundary(tmp_path):
    s = load_settings(_goals_file(tmp_path, max_steps=50, max_attempts_per_step=5), env={})
    assert (s.goals.max_steps, s.goals.max_attempts_per_step) == (50, 5)


@pytest.mark.parametrize("kv", [{"max_steps": 51}, {"max_steps": 0}, {"max_steps": 1000},
                                {"max_attempts_per_step": 6}, {"max_attempts_per_step": 0}, {"max_attempts_per_step": 100}])
def test_goal_limits_above_hard_limit_are_rejected(tmp_path, kv):
    with pytest.raises(ConfigError):
        load_settings(_goals_file(tmp_path, **kv), env={})


def test_agent_and_goal_resource_ceilings_are_rejected_when_loosened(tmp_path):
    for body in ("[agents]\nmax_concurrent = 17\n", "[agents]\ntool_call_limit = 5001\n", "[goals]\nmax_active_goals = 9\n",
                 "[goals]\ngoal_timeout_seconds = 86401\n"):
        f = tmp_path / "c.toml"
        f.write_text(body, encoding="utf-8")
        with pytest.raises(ConfigError):
            load_settings(f, env={})


def test_replanning_is_limited_to_two_attempts_and_pure_computation():
    assert goal_policy.MAX_REPLANS == 2
    assert goal_policy.REPLAN_AUTHORABLE == frozenset({"business.analyze", "finance.analyze"})
    # ein Replan darf weder Agenten, Tools noch Rechte waehlen
    for forbidden in ("agent", "tool", "tools", "permission", "permissions", "confirmed"):
        assert forbidden not in goal_policy.REPLAN_KEYS


# ---------------------------------------------------------------- AST: Kontrollstelle

def _py(sub: str):
    return sorted((SRC / sub).rglob("*.py"))


def _tree(p: Path) -> ast.AST:
    return ast.parse(p.read_text(encoding="utf-8"), filename=str(p))


def _imports(tree: ast.AST):
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name, n.lineno
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            yield n.module, n.lineno
            for a in n.names:
                yield f"{n.module}.{a.name}", n.lineno


FORBIDDEN_EVERYWHERE = ("subprocess", "ctypes", "socket", "urllib", "http", "requests", "httpx", "shutil", "pty", "multiprocessing")
# Direkter Zugriff auf Subsysteme/Kontrollstelle-Innereien: nur ueber ToolRegistry
FORBIDDEN_INTERNALS = ("jarvis.permissions", "jarvis.computer", "jarvis.browser", "jarvis.coding")


def _hits(mod: str, prefixes) -> bool:
    return any(mod == p or mod.startswith(p + ".") for p in prefixes)


def test_package_dirs_exist():
    assert _py("goals") and _py("agents")


@pytest.mark.parametrize("path", _py("goals") + _py("agents"), ids=lambda p: str(p.relative_to(SRC)))
def test_goals_and_agents_have_no_os_or_network_primitives(path):
    bad = [(m, ln) for m, ln in _imports(_tree(path)) if _hits(m, FORBIDDEN_EVERYWHERE)]
    assert not bad, f"{path.name}: direkter OS-/Netzwerkzugriff statt ToolRegistry: {bad}"


@pytest.mark.parametrize("path", _py("goals") + _py("agents"), ids=lambda p: str(p.relative_to(SRC)))
def test_goals_and_agents_do_not_import_subsystem_internals(path):
    bad = [(m, ln) for m, ln in _imports(_tree(path)) if _hits(m, FORBIDDEN_INTERNALS)]
    assert not bad, f"{path.name}: umgeht ToolRegistry/PermissionEngine: {bad}"


@pytest.mark.parametrize("path", _py("goals") + _py("agents"), ids=lambda p: str(p.relative_to(SRC)))
def test_goals_and_agents_do_not_call_dangerous_builtins(path):
    bad = []
    for n in ast.walk(_tree(path)):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in {"eval", "exec", "compile", "__import__", "open"}:
                bad.append((f.id, n.lineno))
            elif isinstance(f, ast.Attribute) and f.attr in {"system", "popen", "Popen", "startfile", "spawn", "fork", "kill", "unlink", "rmtree"}:
                bad.append((f.attr, n.lineno))
    assert not bad, f"{path.name}: {bad}"


def test_goals_never_import_tools_directly():
    """goals/ plant nur; Aktionen laufen ueber AgentOrchestrator -> ToolGateway -> ToolRegistry."""
    for path in _py("goals"):
        bad = [(m, ln) for m, ln in _imports(_tree(path)) if _hits(m, ("jarvis.tools", "jarvis.tasks", "jarvis.memory"))]
        assert not bad, f"{path.name}: {bad}"


def test_goals_never_call_execute():
    for path in _py("goals"):
        for n in ast.walk(_tree(path)):
            if isinstance(n, ast.Attribute) and n.attr in {"execute", "_execute"}:
                pytest.fail(f"{path.name}:{n.lineno} ruft .{n.attr} - goals/ darf keine Tools ausfuehren")


def test_agents_execute_tools_only_via_gateway_on_the_registry():
    """In agents/ ruft genau ToolGateway (context.py) `<registry>.execute` auf; sonst nirgends ein .execute."""
    calls = []
    for path in _py("agents"):
        for n in ast.walk(_tree(path)):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"execute", "_execute"}:
                calls.append((path.relative_to(SRC).as_posix(), ast.unparse(n.func)))
    assert calls == [("agents/context.py", "self._registry.execute")], calls


def test_toolgateway_executes_via_registry_with_arguments_screened():
    src = (SRC / "agents" / "context.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    gw = next(c for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "ToolGateway")
    call = next(f for f in gw.body if isinstance(f, ast.FunctionDef) and f.name == "call")
    text = ast.unparse(call)
    # vor dem execute: Kontrollen fuer Abbruch, Tool-Liste, reservierte Argumente (confirmed & Co.) und Aufruflimit
    assert text.index("RESERVED_TOOL_ARGS") < text.index("self._registry.execute")
    assert "ToolAccessError" in text


def test_reserved_tool_args_keep_confirmation_and_bypass_flags_blocked():
    from jarvis.agents.policy import RESERVED_TOOL_ARGS
    assert {"confirmed", "bypass", "force", "skip_permissions", "unsafe", "grant", "approval"} <= RESERVED_TOOL_ARGS


def test_only_bootstrap_wires_subsystems_into_the_core():
    """Verdrahtung nur in bootstrap.py: der Core importiert weder goals noch agents."""
    for path in SRC.glob("core*.py"):
        bad = [(m, ln) for m, ln in _imports(_tree(path)) if _hits(m, ("jarvis.goals", "jarvis.agents"))]
        assert not bad, f"{path.name}: {bad}"
    assert (SRC / "bootstrap.py").exists()
