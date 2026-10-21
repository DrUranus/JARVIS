"""Composition: bootstrap, Core task manager, CLI commands and the delegate() entry point."""
import pytest

from jarvis.agents import AgentStatus, TaskStatus
from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.interface.cli import run_command
from jarvis.tasks import TaskStatus as CoreStatus
from test_computer_integration import env_for, run_repl

S = TaskStatus


def core_for(tmp_path, **extra):
    env = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_CODING_ENABLED="true",
               JARVIS_CODING_PROVIDER="fake", JARVIS_COMPUTER_ENABLED="true", JARVIS_COMPUTER_BACKEND="fake", JARVIS_COMPUTER_USE_DEFAULT_APPS="false")
    env.update(extra)
    return build_core(load_settings(env=env_for(tmp_path, **env)))


def test_disabled_by_default_and_jarvis_starts_normally(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    sub = core.subsystems["agents"]
    assert sub.status == "disabled" and sub.orchestrator is None and not sub.available
    assert "deaktiviert" in run_command(core, "/agents") and "JARVIS_AGENTS_ENABLED" in run_command(core, "/agents")
    assert run_command(core, "/agenttasks").startswith("Multi-Agent: deaktiviert") and "deaktiviert" in run_command(core, "/agent browser")
    assert core.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit." and core.tools.execute("echo", text="ok").success
    with pytest.raises(Exception):
        sub.delegate("x")


def test_enabled_registers_the_four_agents_and_ties_their_status_to_their_tools(tmp_path):
    core = core_for(tmp_path)
    sub = core.subsystems["agents"]
    assert sub.status == "enabled" and sub.available
    assert [a.id for a in sub.registry.list()] == ["browser", "coding", "computer", "research"]
    assert all(a.status is AgentStatus.AVAILABLE for a in sub.registry.list())
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    off = core_for(tmp_path / "x", JARVIS_BROWSER_ENABLED="false", JARVIS_CODING_ENABLED="false")
    reg = off.subsystems["agents"].registry
    assert reg.get("browser").status is AgentStatus.DISABLED and reg.get("research").status is AgentStatus.DISABLED
    assert reg.get("coding").status is AgentStatus.DISABLED and "not available" in reg.get("coding").state.reason
    assert reg.get("computer").status is AgentStatus.AVAILABLE
    only = build_core(load_settings(env=env_for(tmp_path / "y", JARVIS_AGENTS_ENABLED="true")))
    assert all(a.status is AgentStatus.DISABLED for a in only.subsystems["agents"].registry.list())  # no tool, no agent: nothing to coordinate


def test_cli_commands(tmp_path):
    core = core_for(tmp_path)
    out = run_command(core, "/agents")
    for line in ("browser", "coding", "computer", "research", "AVAILABLE"):
        assert line in out
    assert "aktiv 0/3" in out
    detail = run_command(core, "/agent browser")
    assert "Browser Agent" in detail and "browser.read" in detail and "browser.interact" in detail and "Werkzeuge: browser" in detail
    assert "Nicht möglich" in run_command(core, "/agent nobody") and run_command(core, "/agent").startswith("Verwendung")
    assert run_command(core, "/agenttasks") == "Keine Agent-Tasks."
    assert "Geeignet: browser" in run_command(core, "/agent plan Öffne die Webseite https://example.com")
    assert "Kein Agent gewählt" in run_command(core, "/agent plan wie spät ist es")
    assert "browser: DISABLED" in run_command(core, "/agent disable browser") and "DISABLED" in run_command(core, "/agents")
    assert "browser: AVAILABLE" in run_command(core, "/agent enable browser")
    assert "Nicht möglich" in run_command(core, "/agent enable ghost") and "Nicht möglich" in run_command(core, "/agent halt at-unknown")
    assert "/agents" in run_command(core, "/help") and "/agenttasks" in run_command(core, "/help")


def test_delegate_goes_through_the_permission_engine_and_the_core_task_list(tmp_path):
    core = core_for(tmp_path, JARVIS_SECURITY_CONFIRMATION="deny")             # headless: nothing YELLOW can be confirmed
    sub = core.subsystems["agents"]
    r = sub.delegate("Öffne die Webseite https://example.com", {"steps": [{"action": "start"}, {"action": "goto", "url": "https://example.com/"}]})
    assert r.status is S.BLOCKED and r.agent_id == "browser" and r.error_code == "permission_denied"
    assert core.subsystems["browser"].controller.overview()["session"] is None       # the engine said no, so no browser started
    mirrored = [t for t in core.tasks.list() if t.required_agents == ["browser"]]
    assert len(mirrored) == 1 and mirrored[0].status is CoreStatus.FAILED
    read = sub.delegate("Lies den Status des Browsers", {"steps": [{"action": "status"}]}, agent_id="browser")   # GREEN: needs no confirmation
    assert read.status is S.SUCCEEDED and read.output["steps"][0]["output"]["running"] is False


def test_delegate_without_a_suitable_agent_is_a_blocked_result_not_an_exception(tmp_path):
    sub = core_for(tmp_path).subsystems["agents"]
    r = sub.delegate("Erzähl mir einen Witz")
    assert r.status is S.BLOCKED and r.error_code == "no_suitable_agent" and r.error
    explicit = sub.delegate("x", {}, agent_id="ghost")
    assert explicit.status is S.BLOCKED and explicit.error_code == "unknown_agent"


def test_the_planner_chooses_and_the_agent_acts_with_the_chosen_capabilities_only(tmp_path):
    core = core_for(tmp_path, JARVIS_SECURITY_CONFIRMATION="deny")
    sub = core.subsystems["agents"]
    sel = sub.select("Führe die Tests dieses Projekts aus")
    assert sel.agent_id == "coding" and "coding.test" in sel.capabilities and "coding.write" not in sel.capabilities
    r = sub.delegate("Führe die Tests dieses Projekts aus", {"steps": [{"action": "write", "path": "x.py", "mode": "create", "content": "x"}]})
    assert r.status is S.BLOCKED and r.error_code == "capability_not_allowed"       # the planner only granted read+test: a write step is refused


def test_cli_cancel_of_a_waiting_task_and_the_task_list(tmp_path):
    core = core_for(tmp_path)
    orch = core.subsystems["agents"].orchestrator
    from jarvis.agents import AgentTask
    t = AgentTask("Öffne die Webseite später", agent_id="browser", input={"steps": [{"action": "status"}]}, task_id="later-1")
    orch.submit(t)
    assert "PENDING" in run_command(core, "/agenttasks") and "later-1" in run_command(core, "/agenttasks")
    assert "CANCELLED" in run_command(core, "/agent halt later-1")
    out = run_command(core, "/agenttasks")
    assert "CANCELLED" in out and "Öffne die Webseite" in out
    assert "bereits" in run_command(core, "/agent halt later-1") or "already" in run_command(core, "/agent halt later-1")
    orch.run(AgentTask("status", agent_id="browser", input={"steps": [{"action": "status"}]}, task_id="done-1"))
    assert "SUCCEEDED" in run_command(core, "/agenttasks")


def test_repl_shows_agent_commands(tmp_path):
    core = core_for(tmp_path)
    out = run_repl(core, ["/agents", "/agent plan Mach einen Screenshot vom Bildschirm", "/exit"])
    assert "browser" in out and "Geeignet: computer" in out
