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
