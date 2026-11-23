"""V2 Vorbereitung (Bereich C): keine doppelte Ausfuehrung durch automatische Wiederholung. Ein Schritt mit Faehigkeiten, die ausserhalb von JARVIS etwas veraendern koennen
(files.write, office.create, computer.input, browser.interact, coding.write/test ...), wird nach einem voruebergehenden Fehler (timeout, agent_crashed, executor_failed ...) NICHT
automatisch wiederholt: der Agent kann seine Aktion schon ausgefuehrt haben. Lesende/rechnende Schritte werden wie bisher wiederholt. Keine Berechtigung aendert sich."""
from __future__ import annotations

import pytest

from goals_util import FakeAgent, chain, rig, step
from jarvis.goals import GoalStatus, StepStatus
from jarvis.goals import policy as P

WRITE = [frozenset({"files.write"}), frozenset({"office.create"}), frozenset({"computer.input"}), frozenset({"browser.interact"}), frozenset({"coding.write"}), frozenset({"coding.test"}),
         frozenset({"research.web", "files.write"}), frozenset({"files.read", "computer.input"})]
READ = [frozenset({"research.web"}), frozenset({"browser.read"}), frozenset({"files.read"}), frozenset({"office.read"}), frozenset({"computer.screen"}), frozenset({"coding.read"}),
        frozenset({"coding.plan"}), frozenset({"business.analyze"}), frozenset({"business.strategy"}), frozenset({"finance.analyze"}), frozenset({"research.web", "browser.read"})]


@pytest.mark.parametrize("caps", WRITE, ids=lambda c: "+".join(sorted(c)))
def test_a_step_that_may_change_something_outside_is_not_retried_automatically(caps):
    assert P.may_change_outside(caps, "fake") is True
    agent = FakeAgent("fake", capabilities=caps, script=["failure", "success"], failure_code="step_failed")

    def make(goal):
        return [step(goal, "s1", "fake", caps=caps, attempts=2), step(goal, "ev", None, deps=("s1",))]
    engine, *_ = rig([agent], make, max_attempts=2)
    res = engine.run(engine.create("x").goal_id)
    assert len(agent.tasks) == 1 and res.status is not GoalStatus.SUCCEEDED
    r = res.steps[0].result
    assert r.attempts == 1 and r.error_code == "step_failed" and r.status in (StepStatus.FAILED, StepStatus.TIMEOUT)
    assert any("not retried" in w and "s1" in w for w in res.warnings)            # sichtbar im Ergebnis, nicht nur im Log


@pytest.mark.parametrize("caps", READ, ids=lambda c: "+".join(sorted(c)))
def test_read_only_and_computing_steps_are_still_retried(caps):
    assert P.may_change_outside(caps, "fake") is False
    agent = FakeAgent("fake", capabilities=caps, script=["failure", "success"], failure_code="step_failed")

    def make(goal):
        return [step(goal, "s1", "fake", caps=caps, attempts=2), step(goal, "ev", None, deps=("s1",))]
    engine, *_ = rig([agent], make, max_attempts=2)
    res = engine.run(engine.create("x").goal_id)
    assert res.status is GoalStatus.SUCCEEDED and len(agent.tasks) == 2 and res.steps[0].result.attempts == 2


def test_an_unknown_or_empty_capability_set_with_an_agent_counts_as_possibly_changing_something():
    assert P.may_change_outside(frozenset(), "fake") is True            # konservativ, wie die Journal-Markierung
    assert P.may_change_outside(frozenset(), None) is False             # reiner Auswertungsschritt
    assert P.may_change_outside(frozenset({"something.new"}), "x") is True


def test_the_same_failure_on_a_write_step_without_retry_budget_is_unchanged():
    agent = FakeAgent("fake", capabilities=frozenset({"files.write"}), behavior="crash")

    def make(goal):
        return [step(goal, "s1", "fake", caps=frozenset({"files.write"}), attempts=1), step(goal, "ev", None, deps=("s1",))]
    engine, *_ = rig([agent], make, max_attempts=1)
    res = engine.run(engine.create("x").goal_id)
    assert len(agent.tasks) == 1 and res.status is GoalStatus.FAILED


def test_the_retryable_code_list_itself_is_unchanged():
    assert P.RETRYABLE_CODES == frozenset({"timeout", "agent_crashed", "executor_failed", "queue_full", "step_failed"})


# ---- Neuplanung (Plan-Ebene) und nie gestartete Aufgaben ----------------------------------------------------------------------------------------------------
from test_goals_replanning import Rig, split  # noqa: E402
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry  # noqa: E402
from jarvis.goals import GoalEngine  # noqa: E402
from jarvis.goals.planner import GoalPlanner  # noqa: E402
from jarvis.goals.replanner import LLMReplanner  # noqa: E402
from jarvis.llm.mock import MockProvider  # noqa: E402
from agents_util import FakeClock, InlineExecutor, ManualScheduler  # noqa: E402


class WritePlanner(GoalPlanner):
    """Erster Plan: ein schreibender Schritt (files.write) und die Auswertung; Neuplanung ist der ECHTE GoalPlanner.replan mit einem Modell, das einen Ersatzplan liefert."""

    def plan(self, goal, ctx, max_steps):
        return self._build(goal, [{"objective": "Lege den Ordner notizen an", "caps": {"files.write"}, "input": {"steps": [{"action": "mkdir", "path": "notizen"}]}}, {"evaluate": True}])


def write_rig(code, behavior="failure"):
    agent = FakeAgent("files", {"files.write"}, behavior=behavior, failure_code=code)
    reg = AgentRegistry()
    reg.register(agent)
    orch = AgentOrchestrator(reg, scheduler=ManualScheduler(), clock=FakeClock(), executor=InlineExecutor())
    provider = MockProvider(lambda request: __import__("json").dumps({"steps": [{"objective": "Lege den Ordner notizen erneut an", "capabilities": ["files.write"], "input": {"steps": [{"action": "mkdir", "path": "notizen"}]}, "depends_on": []},
                                                                             {"evaluate": True}], "rationale": "nochmal"}))
    planner = WritePlanner(AgentPlanner(reg), max_attempts=1, replanner=LLMReplanner(provider))
    engine = GoalEngine(orch, planner, max_attempts=1, cancel_wait=0.3)
    return engine, agent, provider


def test_replanning_never_routes_around_a_failed_step_that_may_already_have_written():
    engine, agent, provider = write_rig("step_failed")
    res = engine.run(engine.create("Schreibe etwas").goal_id)
    assert len(provider.calls) == 0 and res.replans == 0 and len(agent.tasks) == 1 and res.status is GoalStatus.FAILED     # kein Ersatzplan: die Schreibaktion koennte schon erfolgt sein
    assert any("not replanned" in w and "s1" in w for w in res.warnings)


def test_replanning_still_works_for_read_steps_as_before():
    r = Rig([split()])
    res = r.run()
    assert res.replans == 1 and r.calls == 1


@pytest.mark.parametrize("caps", [frozenset({"files.write"}), frozenset({"computer.input"})])
def test_a_task_that_never_started_is_safe_to_repeat_even_for_write_steps(caps):
    """`executor_failed`: der Orchestrator konnte die Arbeit nicht einmal starten - es gibt nichts, was doppelt ausgefuehrt werden koennte."""
    assert P.may_change_outside(caps, "fake") is True and "executor_failed" in P.NEVER_STARTED_CODES
    agent = FakeAgent("fake", capabilities=caps, script=["failure", "success"], failure_code="executor_failed")

    def make(goal):
        return [step(goal, "s1", "fake", caps=caps, attempts=2), step(goal, "ev", None, deps=("s1",))]
    engine, *_ = rig([agent], make, max_attempts=2)
    res = engine.run(engine.create("x").goal_id)
    assert res.status is GoalStatus.SUCCEEDED and len(agent.tasks) == 2


def test_the_never_started_codes_are_a_subset_of_the_retryable_codes_and_exclude_timeouts_and_crashes():
    assert P.NEVER_STARTED_CODES <= P.RETRYABLE_CODES and not {"timeout", "agent_crashed", "step_failed"} & P.NEVER_STARTED_CODES


# ---- sichere Wiederaufnahme nach einem fehlgeschlagenen oder abgebrochenen Schreibschritt ---------------------------------------------------------------
from test_journal_resume import Rig as ResumeRig, crash as journal_crash, jstep  # noqa: E402


@pytest.mark.parametrize("status", ["FAILED", "TIMEOUT", "RUNNING", "CANCELLED", "PENDING"])
def test_resume_asks_again_for_every_unfinished_write_step_whatever_its_last_status(tmp_path, status):
    r = ResumeRig(tmp_path, answer=False)
    journal_crash(r.store, steps=[jstep(1, "lese Datei"), jstep(2, "schreibe Datei", status, True)])
    res = r.manager().resume("g-old")
    assert res.status == "DECLINED" and len(r.asked) == 1 and "schreibe Datei" in r.asked[0]
    assert r.engine.list() == [] and r.agent.calls == 0                        # nichts gestartet, nichts doppelt ausgefuehrt


def test_a_failed_read_step_is_resumed_without_asking_and_a_denied_question_never_runs_the_write_step(tmp_path):
    r = ResumeRig(tmp_path, answer=True)
    journal_crash(r.store, steps=[jstep(1, "lese Datei", "FAILED", False)])
    res = r.manager().resume("g-old")
    assert r.asked == [] and res.status == "SUCCEEDED"                          # lesend: keine Rueckfrage noetig
