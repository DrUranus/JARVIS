"""Configuration, bootstrap, Core, goals, /run tools and CLI of research / business / finance."""
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.agents import AgentStatus
from jarvis.bootstrap import build_core
from jarvis.config import BusinessSettings, ConfigError, FinanceSettings, ResearchSettings, load_settings
from jarvis.goals import GoalStatus
from jarvis.interface.cli import run_command
from test_computer_integration import env_for, run_repl

REPO = Path(__file__).resolve().parent.parent
ON = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_RESEARCH_ENABLED="true", JARVIS_BUSINESS_ENABLED="true",
          JARVIS_FINANCE_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_SECURITY_CONFIRMATION="deny", JARVIS_CODING_ENABLED="false", JARVIS_COMPUTER_ENABLED="false")


def core_for(tmp_path, **extra):
    env = dict(ON)
    env.update(extra)
    return build_core(load_settings(env=env_for(tmp_path, **env)))


# ---- configuration -----------------------------------------------------------------------------------------------------------------------------------
def test_defaults_are_safe_and_off_and_repo_config_matches():
    s = load_settings(env={})
    assert s.research == ResearchSettings() and s.business == BusinessSettings() and s.finance == FinanceSettings()
    assert not (s.research.enabled or s.business.enabled or s.finance.enabled) and s.finance.paper_trading_only is True and s.finance.max_leverage == 1.0
    r = load_settings(REPO / "config" / "jarvis.toml", env={})
    assert r.research == ResearchSettings() and r.business == BusinessSettings() and r.finance == FinanceSettings()


def test_env_overrides_and_validation():
    s = load_settings(env={"JARVIS_RESEARCH_ENABLED": "true", "JARVIS_RESEARCH_MAX_SOURCES": "5", "JARVIS_FINANCE_MAX_STEPS": "100"})
    assert s.research.enabled and s.research.max_sources == 5 and s.finance.max_steps == 100
    for env in ({"JARVIS_BUSINESS_MAX_RESULT_CHARS": "10"}, {"JARVIS_RESEARCH_MAX_RESULT_CHARS": "1000000"}, {"JARVIS_FINANCE_DAILY_LOSS_LIMIT_PCT": "0"},
                {"JARVIS_FINANCE_MAX_TOTAL_EXPOSURE_PCT": "150"}):
        with pytest.raises(ConfigError):
            load_settings(env=env)


# ---- composition ------------------------------------------------------------------------------------------------------------------------------------------
def test_disabled_by_default_jarvis_starts_and_the_old_research_placeholder_stays(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake")))
    for name in ("research", "business", "finance"):
        assert core.subsystems[name].status == "disabled" and name not in core.tools
        assert "deaktiviert" in run_command(core, f"/{name}") and f"JARVIS_{name.upper()}_ENABLED" in run_command(core, f"/{name}")
    reg = core.subsystems["agents"].registry
    assert [a.id for a in reg.list()] == ["browser", "coding", "computer", "research"] and type(reg.get("research")).__module__ == "jarvis.agents.adapters.research"
    assert core.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit."


def test_enabled_registers_the_agents_tools_and_status(tmp_path):
    core = core_for(tmp_path)
    reg = core.subsystems["agents"].registry
    assert {a.id for a in reg.list()} == {"browser", "coding", "computer", "research", "business", "finance"}
    assert type(reg.get("research")).__module__ == "jarvis.research.agent" and reg.get("business").status is AgentStatus.AVAILABLE and reg.get("finance").status is AgentStatus.AVAILABLE
    assert reg.get("research").status is AgentStatus.AVAILABLE and {"research", "business", "finance"} <= set(core.tools.names())
    r = run_command(core, "/research")
    assert "Research-Agent: aktiv" in r and "research.web" in r and "max_sources=8" in r and "Aktive/wartende Tasks: 0" in r and "browser (permission-checked)" in r
    b = run_command(core, "/business status")
    assert "Business-Agent: aktiv" in b and "business.analyze" in b and "sendet nichts" in b
    f = run_command(core, "/finance")
    assert "Finance-Agent: aktiv" in f and "paper_trading_only=True" in f and "max_leverage=1.0" in f and "no broker, no orders, no transfers" in f
    assert "Verwendung" in run_command(core, "/finance foo")


def test_research_needs_the_browser_and_everything_needs_the_agent_layer(tmp_path):
    no_browser = core_for(tmp_path, JARVIS_BROWSER_ENABLED="false")
    assert no_browser.subsystems["agents"].registry.get("research").status is AgentStatus.DISABLED
    assert no_browser.subsystems["business"].status == "enabled"
    (tmp_path / "off").mkdir()
    off = core_for(tmp_path / "off", JARVIS_AGENTS_ENABLED="false")
    for name in ("research", "business", "finance"):
        assert off.subsystems[name].status == "disabled" and "agents.enabled" in off.subsystems[name].reason and name not in off.tools.names()


def test_active_tasks_are_counted(tmp_path):
    core = core_for(tmp_path)
    from jarvis.agents import AgentTask
    sub = core.subsystems["agents"]
    sub.orchestrator.submit(AgentTask("Analyse", agent_id="finance", input={"kind": "risk_analysis", "prices": [1, 2, 3]}, required_capabilities=frozenset({"finance.analyze"})))
    assert core.subsystems["finance"].describe()["active_tasks"] == 1 and "Aktive/wartende Tasks: 1" in run_command(core, "/finance")


# ---- /run tools --------------------------------------------------------------------------------------------------------------------------------------------
def test_run_tools_compute_through_the_registry(tmp_path):
    core = core_for(tmp_path)
    rr = run_command(core, "/run finance action=risk_reward direction=long entry=100 stop=95 target=115")
    assert "COMPUTED" in rr and "'value': 3.0" in rr
    assert "'value': 20.0" in run_command(core, "/run finance action=position_size account=10000 risk_pct=1 entry=100 stop=95")
    assert "UNKNOWN" in run_command(core, "/run finance action=pe price=100 eps=0")
    assert "-0.25" in run_command(core, "/run finance action=drawdown prices=100,120,90,130")
    assert "'units': 34.28" in run_command(core, "/run business action=break_even fixed_costs=1200 price=50 variable_cost=15")
    assert "'median': 52.5" in run_command(core, "/run business action=price_stats values=50,80,52.5")
    assert "'allowed': False" in run_command(core, "/run research action=check_url url=http://10.0.0.5/")
    assert "'allowed': True" in run_command(core, "/run research action=check_url url=https://example.com/a?utm_source=x")
    assert "aktiv" not in run_command(core, "/run finance action=status") and "enabled" in run_command(core, "/run finance action=status")


@pytest.mark.parametrize("cmd", ["/run finance action=place_order symbol=AAPL qty=10", "/run finance action=withdraw amount=100", "/run finance action=transfer to=DE00 amount=5",
                                 "/run finance action=buy symbol=AAPL", "/run business action=send_email to=a@b.de text=hi", "/run business action=send_message to=x text=y",
                                 "/run research action=login user=a password=b", "/run finance action=risk_reward direction=long entry=x stop=1 target=2",
                                 "/run finance action=drawdown prices=1,abc", "/run business action=break_even fixed_costs=-5 price=1 variable_cost=0"])
def test_run_tools_have_no_live_actions_and_reject_bad_input(tmp_path, cmd):
    out = run_command(core_for(tmp_path), cmd)
    assert out.startswith("Nicht ausgeführt"), out


def test_run_tools_are_green_and_side_effect_free(tmp_path):
    core = core_for(tmp_path)
    for name in ("research", "business", "finance"):
        assert core.tools.get(name).permission.value == "green"
    before = list(core.permissions.describe()["session_grants"])
    run_command(core, "/run finance action=pe price=100 eps=5")
    assert list(core.permissions.describe()["session_grants"]) == before


# ---- goals through the Core --------------------------------------------------------------------------------------------------------------------------------
def test_a_finance_goal_through_the_core_and_nothing_is_stored_in_memory(tmp_path):
    core = core_for(tmp_path, JARVIS_MEMORY_ENABLED="true")
    before = list(core.recall("", limit=50))
    g = core.create_goal("Analysiere ACME GEHEIM-ZIEL-QQQ", context={"template": "financial_analysis", "finance": {"company": {"name": "ACME", "price": 100, "eps": 5}}})
    res = core.run_goal(g.goal_id)
    assert res.status is GoalStatus.SUCCEEDED and res.steps[0].result.output["metrics"][0]["value"] == 20
    after = list(core.recall("", limit=50))
    assert before == after and not any("GEHEIM-ZIEL-QQQ" in str(e) for e in after)


def test_a_research_goal_without_confirmation_is_blocked_not_bypassed(tmp_path):
    core = core_for(tmp_path)
    g = core.create_goal("Recherchiere", context={"template": "research_web", "research": {"urls": ["https://example.com/"]}})
    res = core.run_goal(g.goal_id)
    assert res.status is GoalStatus.BLOCKED and res.steps[0].result.error_code == "permission_denied"


def test_chat_never_starts_analysis(tmp_path):
    core = core_for(tmp_path)
    for text in ("Analysiere diese Aktie AAPL", "Recherchiere den Markt für Fahrzeugaufbereitung", "Erstelle mir einen Businessplan", "Kaufe 10 Aktien von Tesla"):
        core.handle(text)
    assert core.list_goals() == [] and core.subsystems["agents"].orchestrator.list() == []


def test_cli_help_and_repl(tmp_path):
    core = core_for(tmp_path)
    h = run_command(core, "/help")
    assert "/research" in h and "/business" in h and "/finance" in h
    out = run_repl(core, ["/finance", "/research status", "/exit"])
    assert "Finance-Agent: aktiv" in out and "Research-Agent: aktiv" in out
