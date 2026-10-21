"""Self-repair end to end: RepairEngine -> AgentPlanner/Orchestrator -> CodingAgent -> ToolGateway -> ToolRegistry -> the REAL PermissionEngine (scripted
answers) -> CodingController on the fake provider; plus configuration, bootstrap, Core and CLI."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents_util import tool_rig
from jarvis.agents import AgentPlanner
from jarvis.bootstrap import build_core
from jarvis.coding.models import CommandResult
from jarvis.config import ConfigError, SelfRepairSettings, load_settings
from jarvis.errors import JarvisError
from jarvis.interface.cli import run_command
from jarvis.permissions import ConfirmationChoice
from jarvis.self_repair import AttemptStatus, RepairEngine, RepairStatus
from repair_util import EDIT, candidates
from test_computer_integration import env_for, run_repl

ONCE, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.DENY
S = RepairStatus
REPO = Path(__file__).resolve().parent.parent
FAILED_RUN = CommandResult(1, "FAILED tests/test_calc.py::test_add - AssertionError\nE   AssertionError: assert -1 == 5\n1 failed, 1 passed in 0.02s\n", "", False, False, 0.02)
PASSED_RUN = CommandResult(0, "2 passed in 0.02s\n", "", False, False, 0.02)


def repair_rig(tmp_path, answers, runs, **kw):
    tr = tool_rig(tmp_path, answers)
    it = iter(runs)
    tr.coding_provider.command_handler = lambda spec: next(it)
    orch, reg = tr.agents()
    engine = RepairEngine(orch, AgentPlanner(reg), repair_timeout=60, step_timeout=30, **kw)
    return tr, engine, orch


def run(engine, tr, objective="Behebe den Fehler in calc.py", cands=None, **ctx):
    context = dict(ctx)
    if cands is not None:
        context["candidates"] = cands
    return engine.run(engine.create(objective, workspace=str(tr.project), context=context).run_id)


def test_repair_through_the_real_permission_engine(tmp_path):
    tr, engine, orch = repair_rig(tmp_path, [ONCE] * 8, [FAILED_RUN, PASSED_RUN, PASSED_RUN])
    res = run(engine, tr, cands=candidates(EDIT))
    assert res.status is S.SUCCEEDED, (res.run.final_summary, res.warnings)
    assert "return a + b" in tr.coding_provider.text(str(tr.project / "calc.py"))
    actions = [q.action for q in tr.prompts.requests]
    assert actions[:2] == ["start", "test"] and actions.count("write") == 1 and actions.count("test") == 3          # the engine asked; nobody answered for it
    assert tr.coding.overview()["session"]["status"] == "completed" and not res.warnings
    assert [a.status for a in res.attempts] == [AttemptStatus.SUCCEEDED]


def test_declined_write_blocks_and_changes_nothing(tmp_path):
    tr, engine, orch = repair_rig(tmp_path, [ONCE, ONCE, NO, ONCE], [FAILED_RUN, PASSED_RUN])
    res = run(engine, tr, cands=candidates(EDIT, EDIT))
    assert res.status is S.BLOCKED and res.reason_code == "permission_denied" and res.run.attempt_count == 1
    assert "return a - b" in tr.coding_provider.text(str(tr.project / "calc.py"))
    assert [q.action for q in tr.prompts.requests].count("write") == 1                                              # asked once, never again


def test_unanswered_confirmation_means_no_repair(tmp_path):
    tr, engine, orch = repair_rig(tmp_path, [ONCE, ONCE], [FAILED_RUN, PASSED_RUN])
    res = run(engine, tr, cands=candidates(EDIT))
    assert res.status is S.BLOCKED and "return a - b" in tr.coding_provider.text(str(tr.project / "calc.py"))


def test_a_symlink_to_a_secret_cannot_be_used_as_a_target(tmp_path):
    tr, engine, orch = repair_rig(tmp_path, [ONCE] * 8, [FAILED_RUN, PASSED_RUN])
    tr.coding_provider.put(str(tr.project / ".env"), "API_KEY=abcdefghijklmnop\n")
    tr.coding_provider.symlinks[str(tr.project / "link.py")] = str(tr.project / ".env")
    res = run(engine, tr, cands=candidates({"path": "link.py", "mode": "overwrite", "content": "x = 1\n"}))
    assert res.status in (S.BLOCKED, S.FAILED) and tr.coding_provider.text(str(tr.project / ".env")) == "API_KEY=abcdefghijklmnop\n"
    assert "abcdefghijklmnop" not in repr(res.to_dict())


def test_failed_targeted_test_runs_no_regression(tmp_path):
    tr, engine, orch = repair_rig(tmp_path, [ONCE] * 12, [FAILED_RUN, FAILED_RUN, FAILED_RUN, FAILED_RUN],)
    res = run(engine, tr, cands=candidates(EDIT, {**EDIT, "old_text": "a + b", "new_text": "a * b"}, {**EDIT, "old_text": "a * b", "new_text": "b - a"}))
    assert res.status is S.FAILED and res.run.attempt_count == 3 and all(a.regression_result is None for a in res.attempts)


def test_unrepairable_environment_error_is_blocked(tmp_path):
    bad = CommandResult(1, "", "/usr/bin/python: No module named pytest\n", False, False, 0.01)
    tr, engine, orch = repair_rig(tmp_path, [ONCE] * 4, [bad])
    res = run(engine, tr, cands=candidates(EDIT))
    assert res.status is S.BLOCKED and "return a - b" in tr.coding_provider.text(str(tr.project / "calc.py"))


def test_self_test_without_repair(tmp_path):
    tr, engine, orch = repair_rig(tmp_path, [ONCE] * 4, [PASSED_RUN])
    res = run(engine, tr, "Teste das aktuelle Projekt")
    assert res.status is S.SUCCEEDED and res.reason_code == "tests_pass" and not [q for q in tr.prompts.requests if q.action == "write"]


def test_a_running_user_session_is_not_taken_over(tmp_path):
    tr, engine, orch = repair_rig(tmp_path, [ONCE] * 6, [FAILED_RUN, PASSED_RUN])
    tr.registry.execute("coding", action="start", workspace=str(tr.project))
    res = run(engine, tr, cands=candidates(EDIT))
    assert res.status in (S.FAILED, S.BLOCKED) and tr.coding.overview()["session"]["status"] != "completed"        # the user's session was not stopped by the run


# ---- configuration ---------------------------------------------------------------------------------------------------------------------------------
def test_defaults_are_safe_and_off_and_repo_config_matches():
    s = load_settings(env={}).self_repair
    assert s == SelfRepairSettings() and s.enabled is False and (s.max_attempts, s.repair_timeout_seconds) == (3, 900.0)
    assert load_settings(REPO / "config" / "jarvis.toml", env={}).self_repair == SelfRepairSettings()


@pytest.mark.parametrize("env", [{"JARVIS_SELF_REPAIR_MAX_ATTEMPTS": "0"}, {"JARVIS_SELF_REPAIR_MAX_ATTEMPTS": "6"}, {"JARVIS_SELF_REPAIR_REPAIR_TIMEOUT_SECONDS": "0"},
                                 {"JARVIS_SELF_REPAIR_REPAIR_TIMEOUT_SECONDS": "99999"}, {"JARVIS_SELF_REPAIR_STEP_TIMEOUT_SECONDS": "-1"},
                                 {"JARVIS_SELF_REPAIR_STEP_TIMEOUT_SECONDS": "99999"}, {"JARVIS_SELF_REPAIR_MAX_ACTIVE_REPAIRS": "0"},
                                 {"JARVIS_SELF_REPAIR_MAX_HISTORY": "0"}])
def test_unlimited_or_nonsensical_values_are_rejected(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


# ---- composition -----------------------------------------------------------------------------------------------------------------------------------
def core_for(tmp_path, **extra):
    env = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_SELF_REPAIR_ENABLED="true", JARVIS_CODING_ENABLED="true", JARVIS_CODING_PROVIDER="fake",
               JARVIS_BROWSER_ENABLED="false", JARVIS_COMPUTER_ENABLED="false", JARVIS_SECURITY_CONFIRMATION="deny")
    env.update(extra)
    return build_core(load_settings(env=env_for(tmp_path, **env)))


def test_disabled_by_default_and_jarvis_starts(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    sub = core.subsystems["self_repair"]
    assert sub.status == "disabled" and sub.engine is None and not sub.available
    assert run_command(core, "/repair").startswith("Self-Repair: deaktiviert") and "JARVIS_SELF_REPAIR_ENABLED" in run_command(core, "/repair")
    assert "deaktiviert" in run_command(core, "/repair Teste workspace=x")
    for call in (lambda: core.create_repair("x", workspace="/w"), lambda: core.list_repairs(), lambda: core.get_repair("r-1"), lambda: core.run_repair("r-1"),
                 lambda: core.cancel_repair("r-1")):
        with pytest.raises(JarvisError):
            call()
    assert core.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit."


@pytest.mark.parametrize("extra,word", [({"JARVIS_AGENTS_ENABLED": "false"}, "agents.enabled"), ({"JARVIS_CODING_ENABLED": "false"}, "coding.enabled")])
def test_needs_agents_and_coding(tmp_path, extra, word):
    sub = core_for(tmp_path, **extra).subsystems["self_repair"]
    assert sub.status == "disabled" and word in sub.reason and sub.engine is None


def test_enabled_builds_the_engine_with_configured_limits(tmp_path):
    sub = core_for(tmp_path, JARVIS_SELF_REPAIR_MAX_ATTEMPTS="4", JARVIS_SELF_REPAIR_REPAIR_TIMEOUT_SECONDS="120").subsystems["self_repair"]
    assert sub.status == "enabled" and sub.engine.max_attempts == 4 and sub.engine.repair_timeout == 120.0 and sub.describe()["status"] == "enabled"


def test_ordinary_chat_never_starts_a_repair(tmp_path):
    core = core_for(tmp_path)
    for text in ("Behebe den Fehler in calc.py", "repariere meinen Code", "Teste das Projekt"):
        core.handle(text)
    assert core.list_repairs() == []


def test_core_interface_and_cli(tmp_path):
    core = core_for(tmp_path)
    ws = tmp_path / "ws"
    assert run_command(core, "/repair") .startswith("Keine Reparaturläufe") and run_command(core, "/repair status").startswith("Keine Reparaturläufe")
    assert "Workspace ist erforderlich" in run_command(core, "/repair Teste das Projekt")
    out = run_command(core, f'/repair Teste das aktuelle Projekt workspace="{ws}"')
    run_id = core.list_repairs()[0].run_id
    first = out.splitlines()[0]
    assert first.startswith(f"Lauf {run_id}: ") and any(f": {st}" in first for st in ("FAILED", "BLOCKED")) and "SUCCEEDED" not in first   # nothing can be approved
    assert run_id in run_command(core, "/repair status") and "Versuche 0/3" in run_command(core, "/repair status")
    assert run_id in run_command(core, f"/repair status {run_id}")
    assert "Noch keine Reparaturversuche" in run_command(core, f"/repair attempts {run_id}")
    assert "already" in run_command(core, f"/repair cancel {run_id}")
    assert "Nicht möglich" in run_command(core, "/repair status r-nope") and "Nicht möglich" in run_command(core, "/repair cancel r-nope")
    assert "Nicht möglich" in run_command(core, f'/repair x workspace="{ws}" runner=rm') and "JSON" in run_command(core, f'/repair x workspace="{ws}" candidates=\'[oops\'')
    assert "/repair <Ziel>" in run_command(core, "/help")
    g = core.create_repair("Behebe", workspace=str(ws))
    assert core.get_repair(g.run_id).status is S.PENDING and core.cancel_repair(g.run_id).accepted and core.get_repair(g.run_id).status is S.CANCELLED


def test_cli_cannot_approve_anything(tmp_path):
    core = core_for(tmp_path)
    cands = '[{"edits":[{"path":"calc.py","mode":"overwrite","content":"x=1"}]}]'
    out = run_command(core, f"/repair Behebe den Fehler workspace=\"{tmp_path / 'ws'}\" candidates='{cands}'")
    assert "SUCCEEDED" not in out


def test_repl_runs_repair_command(tmp_path):
    core = core_for(tmp_path)
    out = run_repl(core, [f'/repair Teste das Projekt workspace="{tmp_path / "ws"}"', "/repair status", "/exit"])
    assert "Lauf r-" in out and "Reparaturläufe" in out


def test_repairs_are_not_written_to_memory(tmp_path):
    core = core_for(tmp_path, JARVIS_MEMORY_ENABLED="true")
    before = list(core.recall("", limit=50))
    r = core.create_repair("Teste GEHEIMNIS-ZIEL-XYZ", workspace=str(tmp_path / "ws"))
    core.run_repair(r.run_id)
    after = list(core.recall("", limit=50))
    assert before == after and not any("GEHEIMNIS-ZIEL-XYZ" in str(e) for e in after)
