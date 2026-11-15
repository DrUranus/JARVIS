"""V2.1 M1 als Vorabpruefung des Plans im Zielmotor (goals.plan_analysis, Standard AUS): vor dem ersten Schritt prueft `plan_graph.analyse`, ob der Plan ueberhaupt ausfuehrbar ist
(gueltiger Graph, jede verlangte Faehigkeit wird von einem Agenten angeboten). Ein unloesbarer Plan fuehrt KEINEN Schritt aus (kein halb ausgefuehrtes Ziel). Der Zielmotor bleibt
der einzige Ausfuehrer; Neuplanung und Wiederaufnahme sind unveraendert (hier nur auf Widerspruchsfreiheit geprueft)."""
from __future__ import annotations

import pytest

from goals_util import FakeAgent, chain, rig, step
from jarvis.agents import TaskStatus
from jarvis.config import GoalsSettings, Settings, load_settings
from jarvis.goals import GoalStatus
from jarvis.goals import policy as GP
from jarvis.goals.plan_check import make_plan_check
from jarvis.goals.plan_graph import NEVER_REPLAN

from pathlib import Path


def plan_needing_business(goal):
    return [step(goal, "s1", "fake"), step(goal, "s2", "fake", deps=("s1",), caps=frozenset({"business.analyze"})), step(goal, "ev", None, deps=("s2",))]


def run_goal(make, agent, check):
    engine, orch, reg, *_ = rig([agent], make, plan_check=check)
    g = engine.create("Ziel")
    return engine.run(g.goal_id), agent


def test_off_by_default_in_code_and_in_the_shipped_toml():
    assert GoalsSettings().plan_analysis is False and Settings().goals.plan_analysis is False
    assert load_settings(Path(__file__).resolve().parents[1] / "config" / "jarvis.toml", env={}).goals.plan_analysis is False


def test_without_the_check_nothing_changes_the_first_step_runs_before_the_second_is_refused():
    res, agent = run_goal(plan_needing_business, FakeAgent("fake"), None)
    assert len(agent.tasks) == 1 and res.status is not GoalStatus.SUCCEEDED                      # Schritt 1 lief schon, bevor Schritt 2 scheiterte


def test_an_unsolvable_plan_is_blocked_before_any_step_runs():
    engine, orch, reg, *_ = rig([FakeAgent("fake")], plan_needing_business, plan_check=None)
    check = make_plan_check(reg)
    res, agent = run_goal(plan_needing_business, FakeAgent("fake"), make_plan_check(reg))
    assert res.status is GoalStatus.BLOCKED and res.reason_code == "plan_unsolvable" and agent.tasks == []
    assert "business.analyze" in res.summary and "s2" in res.summary                              # Schritt-ID und fehlende Faehigkeit, keine Inhalte
    assert check is not None


def test_a_solvable_plan_runs_exactly_as_without_the_check():
    engine, orch, reg, *_ = rig([FakeAgent("fake")], chain("s1", "s2"), plan_check=None)
    check = make_plan_check(reg)
    res, agent = run_goal(chain("s1", "s2"), FakeAgent("fake"), make_plan_check(reg))
    base, base_agent = run_goal(chain("s1", "s2"), FakeAgent("fake"), None)
    assert res.status is base.status is GoalStatus.SUCCEEDED and len(agent.tasks) == len(base_agent.tasks) == 2 and check is not None


def test_a_failing_check_is_a_closed_check():
    def boom(steps):
        raise RuntimeError("kaputt sk-" + "a1" * 12)
    res, agent = run_goal(chain("s1"), FakeAgent("fake"), boom)
    assert res.status is GoalStatus.BLOCKED and res.reason_code == "plan_analysis_failed" and agent.tasks == [] and "sk-" not in res.summary


def test_disabled_or_failed_agents_do_not_count_as_offering_a_capability():
    from jarvis.agents.state import AgentStatus
    biz = FakeAgent("biz", {"business.analyze"})
    engine, orch, reg, *_ = rig([FakeAgent("fake"), biz], plan_needing_business)
    check = make_plan_check(reg)
    assert check([step("g", "s1", "fake"), step("g", "s2", "biz", caps=frozenset({"business.analyze"}))]) is None
    biz.state.transition(AgentStatus.DISABLED, "off")
    assert "business.analyze" in check([step("g", "s2", "biz", caps=frozenset({"business.analyze"}))])


# ---- Widerspruchsfreiheit mit der bestehenden Neuplanung ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("code", sorted(NEVER_REPLAN))
def test_no_code_the_plan_graph_never_replans_is_retryable_in_the_goal_engine(code):
    assert not GP.is_retryable(TaskStatus.FAILED, code)
    assert not GP.is_retryable(TaskStatus.BLOCKED, code)


def test_the_new_goal_codes_are_never_replanned_either():
    assert {"plan_unsolvable", "plan_analysis_failed"} <= set(NEVER_REPLAN)


def test_the_switch_wires_the_check_only_when_on(tmp_path):
    from jarvis.bootstrap import build_core
    from test_computer_integration import env_for
    base = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", JARVIS_SECURITY_CONFIRMATION="deny",
                JARVIS_CODING_ENABLED="false", JARVIS_COMPUTER_ENABLED="false")
    off = build_core(load_settings(env=env_for(tmp_path, **base)))
    on = build_core(load_settings(env=env_for(tmp_path, JARVIS_GOALS_PLAN_ANALYSIS="true", **base)))
    assert off.subsystems["goals"].engine._plan_check is None and callable(on.subsystems["goals"].engine._plan_check)
