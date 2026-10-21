"""Goal engine end to end: Goal -> GoalPlanner/AgentPlanner -> Orchestrator -> agents -> ToolGateway -> ToolRegistry -> the REAL PermissionEngine
(scripted answers) -> controllers on fake providers; plus configuration, bootstrap, Core and CLI."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents_util import tool_rig
from goals_util import FakeAgent, chain, rig
from jarvis.agents import AgentPlanner
from jarvis.bootstrap import build_core
from jarvis.coding.models import CommandResult
from jarvis.config import ConfigError, GoalsSettings, load_settings
from jarvis.errors import JarvisError
from jarvis.goals import GoalEngine, GoalPlanner, GoalStatus, StepStatus
from jarvis.interface.cli import run_command
from jarvis.permissions import ConfirmationChoice
from test_computer_integration import env_for, run_repl

ONCE, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.DENY
REPO = Path(__file__).resolve().parent.parent


def goal_rig(tmp_path, answers, **kw):
    tr = tool_rig(tmp_path, answers, **kw)
    orch, reg = tr.agents()
    engine = GoalEngine(orch, GoalPlanner(AgentPlanner(reg), max_attempts=2), max_steps=20, max_attempts=2, goal_timeout=60, step_timeout=30)
    return tr, engine, orch


# ---- the whole chain -------------------------------------------------------------------------------------------------------------------
def test_web_goal_reads_a_page_and_every_confirmation_was_asked_by_the_engine(tmp_path):
    tr, engine, orch = goal_rig(tmp_path, [ONCE] * 4)
    g = engine.create("Analysiere example.com und finde die Öffnungszeiten")
    res = engine.run(g.goal_id)
    assert res.status is GoalStatus.SUCCEEDED, res.summary
    assert [s.status for s in res.steps] == [StepStatus.SUCCEEDED] * 2
    read = res.steps[0].result
    assert read.agent_id == "research" and "Opening hours" in read.output["text"]
    assert {q.action for q in tr.prompts.requests} >= {"start", "goto"}                 # the PermissionEngine asked; nobody answered for it
    assert tr.browser_provider.calls_named("page.goto")
    assert orch.list() and all(t.task_id.startswith(g.goal_id) for t in orch.list())      # executed through the orchestrator


def test_declined_confirmation_blocks_the_goal_and_is_not_retried(tmp_path):
    tr, engine, orch = goal_rig(tmp_path, [NO])
    res = engine.run(engine.create("Lies https://example.com/").goal_id)
    assert res.status is GoalStatus.BLOCKED
    assert res.steps[0].status is StepStatus.BLOCKED and res.steps[0].result.attempts == 1 and res.steps[0].result.error_code == "permission_denied"
    assert res.steps[1].status is StepStatus.BLOCKED
    assert len(tr.prompts.requests) == 1 and not tr.browser_provider.calls_named("page.goto")


def test_no_answer_means_no_permission(tmp_path):
    tr, engine, orch = goal_rig(tmp_path, [])
    res = engine.run(engine.create("Lies https://example.com/").goal_id)
    assert res.status in (GoalStatus.BLOCKED, GoalStatus.FAILED) and not tr.browser_provider.calls_named("page.goto")


def test_coding_goal_writes_tests_and_closes_the_session(tmp_path):
    tr, engine, orch = goal_rig(tmp_path, [ONCE] * 8)
    outputs = iter([CommandResult(0, "2 passed in 0.02s\n", "", False, False, 0.02)])
    tr.coding_provider.command_handler = lambda spec: next(outputs)
    edits = [{"path": "calc.py", "mode": "replace", "old_text": "a - b", "new_text": "a + b"}]
    g = engine.create("Ändere calc.py und prüfe mit den Tests", context={"workspace": str(tr.project), "edits": edits, "runner": "pytest"})
    res = engine.run(g.goal_id)
    assert res.status is GoalStatus.SUCCEEDED, (res.summary, [(s.step_id, s.status.value, s.result and s.result.summary) for s in res.steps])
    assert [s.step_id for s in res.steps] == ["s1", "s2", "s3", "s4", "s5"] and all(s.status is StepStatus.SUCCEEDED for s in res.steps)
    assert "return a + b" in tr.coding_provider.text(str(tr.project / "calc.py"))
    actions = [q.action for q in tr.prompts.requests]
    assert actions.count("write") == 1 and actions.count("test") == 1 and "start" in actions
    assert tr.coding.overview()["session"]["status"] == "completed"       # the cleanup step closed what the goal opened
    assert not res.warnings


def test_failing_tests_fail_the_goal_honestly(tmp_path):
    tr, engine, orch = goal_rig(tmp_path, [ONCE] * 8)
    tr.coding_provider.command_handler = lambda spec: CommandResult(1, "FAILED tests/test_calc.py::test_add - assert -1 == 5\n1 failed in 0.02s\n", "", False, False, 0.02)
    res = engine.run(engine.create("Führe die Tests aus", context={"workspace": str(tr.project), "runner": "pytest"}).goal_id)
    test_step = next(s for s in res.steps if s.step_id == "s2")
    # the coding tool reports a failing run as a successful CALL with passed=False; the goal layer must not turn that into "goal reached"
    assert test_step.result.output["steps"][0]["output"]["passed"] is False
    assert res.status is GoalStatus.FAILED, res.summary


def test_red_secret_write_stays_refused_for_a_goal(tmp_path):
    tr, engine, orch = goal_rig(tmp_path, [ONCE] * 8)
    edits = [{"path": ".env", "content": "API_KEY=abcdefghijklmnop\n", "mode": "create"}]
    res = engine.run(engine.create("Schreibe die Datei .env", context={"workspace": str(tr.project), "edits": edits}).goal_id)
    assert res.status in (GoalStatus.BLOCKED, GoalStatus.FAILED)
    assert str(tr.project / ".env") not in tr.coding_provider.files and not tr.coding_provider.calls_named("write")
    assert "abcdefghijklmnop" not in repr(res.to_dict())


def test_screen_goal_through_the_computer_agent(tmp_path):
    tr, engine, orch = goal_rig(tmp_path, [ONCE] * 3)
    res = engine.run(engine.create("Zeige mir die offenen Fenster").goal_id)
    assert res.status is GoalStatus.SUCCEEDED and res.steps[0].result.agent_id == "computer"
    assert "Notepad" in str(res.steps[0].result.output)


def test_unplannable_goal_makes_no_agent_call(tmp_path):
    tr, engine, orch = goal_rig(tmp_path, [ONCE] * 3)
    res = engine.run(engine.create("Wie wird das Wetter morgen?").goal_id)
    assert res.status is GoalStatus.BLOCKED and orch.list() == [] and not tr.prompts.requests


def test_goals_are_not_written_to_memory(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_BROWSER_ENABLED="true",
                                                JARVIS_BROWSER_PROVIDER="fake", JARVIS_MEMORY_ENABLED="true", JARVIS_SECURITY_CONFIRMATION="deny")))
    before = list(core.recall("", limit=50))
    g = core.create_goal("Lies https://example.com/ Geheimnis-Ziel-XYZ")
    core.run_goal(g.goal_id)
    after = list(core.recall("", limit=50))
    assert before == after and not any("Geheimnis-Ziel-XYZ" in str(e) for e in after)


# ---- configuration ---------------------------------------------------------------------------------------------------------------------
def test_defaults_are_safe_and_off_and_repo_config_matches():
    s = load_settings(env={}).goals
    assert s == GoalsSettings() and s.enabled is False
    assert (s.max_steps, s.max_attempts_per_step, s.goal_timeout_seconds, s.step_timeout_seconds) == (20, 2, 1800.0, 300.0)
    assert load_settings(REPO / "config" / "jarvis.toml", env={}).goals == GoalsSettings()


@pytest.mark.parametrize("env", [{"JARVIS_GOALS_MAX_STEPS": "0"}, {"JARVIS_GOALS_MAX_STEPS": "51"}, {"JARVIS_GOALS_MAX_ATTEMPTS_PER_STEP": "0"},
                                 {"JARVIS_GOALS_MAX_ATTEMPTS_PER_STEP": "6"}, {"JARVIS_GOALS_GOAL_TIMEOUT_SECONDS": "0"},
                                 {"JARVIS_GOALS_GOAL_TIMEOUT_SECONDS": "999999"}, {"JARVIS_GOALS_STEP_TIMEOUT_SECONDS": "-1"},
                                 {"JARVIS_GOALS_STEP_TIMEOUT_SECONDS": "100000"}, {"JARVIS_GOALS_MAX_ACTIVE_GOALS": "0"}, {"JARVIS_GOALS_MAX_HISTORY": "0"}])
def test_unlimited_or_nonsensical_values_are_rejected(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


def test_env_overrides_apply():
    s = load_settings(env={"JARVIS_GOALS_ENABLED": "true", "JARVIS_GOALS_MAX_STEPS": "7"}).goals
    assert s.enabled and s.max_steps == 7


# ---- composition ---------------------------------------------------------------------------------------------------------------------------
def core_for(tmp_path, **extra):
    env = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake",
               JARVIS_CODING_ENABLED="true", JARVIS_CODING_PROVIDER="fake", JARVIS_COMPUTER_ENABLED="true", JARVIS_COMPUTER_BACKEND="fake",
               JARVIS_COMPUTER_USE_DEFAULT_APPS="false", JARVIS_SECURITY_CONFIRMATION="deny")
    env.update(extra)
    return build_core(load_settings(env=env_for(tmp_path, **env)))


def test_disabled_by_default_and_jarvis_starts(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    sub = core.subsystems["goals"]
    assert sub.status == "disabled" and sub.engine is None and not sub.available
    assert run_command(core, "/goals").startswith("Goal Engine: deaktiviert") and "JARVIS_GOALS_ENABLED" in run_command(core, "/goals")
    assert "deaktiviert" in run_command(core, "/goal Lies example.com")
    for call in (lambda: core.create_goal("x"), lambda: core.list_goals(), lambda: core.get_goal("g-1"), lambda: core.run_goal("g-1"),
                 lambda: core.cancel_goal("g-1")):
        with pytest.raises(JarvisError):
            call()
    assert core.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit."


def test_goals_need_the_agent_layer(tmp_path):
    core = core_for(tmp_path, JARVIS_AGENTS_ENABLED="false")
    sub = core.subsystems["goals"]
    assert sub.status == "disabled" and "agents.enabled" in sub.reason and sub.engine is None


def test_enabled_builds_engine_with_configured_limits(tmp_path):
    core = core_for(tmp_path, JARVIS_GOALS_MAX_STEPS="7", JARVIS_GOALS_MAX_ATTEMPTS_PER_STEP="3")
    sub = core.subsystems["goals"]
    assert sub.status == "enabled" and sub.engine.max_steps == 7 and sub.engine.max_attempts == 3 and sub.describe()["status"] == "enabled"


def test_ordinary_chat_never_creates_a_goal(tmp_path):
    core = core_for(tmp_path)
    for text in ("Analysiere example.com und finde die Öffnungszeiten", "erstelle eine Webseite", "Recherchiere Katzen"):
        core.handle(text)
    assert core.list_goals() == []


def test_core_goal_interface(tmp_path):
    core = core_for(tmp_path)
    g = core.create_goal("Wie wird das Wetter?")
    assert core.get_goal(g.goal_id).status is GoalStatus.PENDING and [x.goal_id for x in core.list_goals()] == [g.goal_id]
    res = core.run_goal(g.goal_id)
    assert res.status is GoalStatus.BLOCKED and core.get_goal(g.goal_id).status is GoalStatus.BLOCKED
    g2 = core.create_goal("x y z")
    rep = core.cancel_goal(g2.goal_id)
    assert rep.accepted and core.get_goal(g2.goal_id).status is GoalStatus.CANCELLED
    assert not core.cancel_goal(g2.goal_id).accepted


def test_cli_goal_commands_and_no_permission_bypass(tmp_path):
    core = core_for(tmp_path)
    assert run_command(core, "/goals") == "Keine Ziele."
    assert run_command(core, "/goal").startswith("Verwendung")
    out = run_command(core, "/goal Lies https://example.com/")
    assert "BLOCKED" in out and "s1" in out and "BLOCKED" in out.splitlines()[1]     # confirmation=deny: the CLI cannot say yes for the user
    gid = core.list_goals()[0].goal_id
    assert gid in run_command(core, "/goals") and "BLOCKED" in run_command(core, f"/goal status {gid}")
    steps = run_command(core, f"/goal steps {gid}")
    assert "s1" in steps and "research" in steps
    assert "already BLOCKED" in run_command(core, f"/goal cancel {gid}")
    assert "Nicht möglich" in run_command(core, "/goal status g-nope") and "Nicht möglich" in run_command(core, "/goal cancel g-nope")
    assert "/goal <Ziel>" in run_command(core, "/help")
    assert core.subsystems["browser"].describe()["actions_used"] == 0           # nothing was done behind the permission engine's back


def test_cli_goal_with_context_options(tmp_path):
    core = core_for(tmp_path)
    out = run_command(core, f'/goal Prüfe das Projekt mit den Tests workspace="{tmp_path}" runner=pytest')
    gid = core.list_goals()[0].goal_id
    assert gid in out and core.get_goal(gid).status in (GoalStatus.BLOCKED, GoalStatus.FAILED, GoalStatus.SUCCEEDED)
    assert core.get_goal(gid).objective == "Prüfe das Projekt mit den Tests"           # the options were taken out of the objective


def test_repl_runs_goal_command(tmp_path):
    core = core_for(tmp_path)
    out = run_repl(core, ["/goal Wie wird das Wetter?", "/goals", "/exit"])
    assert "BLOCKED" in out and "Ziele" in out
