"""WP03b: mehrere URLs vollstaendig planen (M1) und Speicherwuensche fuer noch nicht vorliegende Ergebnisse als `incomplete` ablehnen (M2a).

Reine Planung: kein Netzwerk, keine Dateien, keine neue Berechtigung. Ein Speicherwunsch ohne sicheren Datenfluss Ergebnis -> Dateiinhalt wird nie still verworfen."""
from __future__ import annotations

import pytest

from jarvis.agents import AgentPlanner
from jarvis.goals import Goal, GoalContext, GoalPlanner, PlanningError, validate_plan
from jarvis.journal.resume import ResumeAwarePlanner
from tests.test_goals_mixed import caps, plan, registry, work

A, B, C = "https://example.org", "https://example.net", "https://example.com/x"


def urls(steps):
    return [s.input["url"] for s in work(steps) if "url" in s.input]


# ---- M1: mehrere URLs ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("objective", [f"Fasse {A} und {B} zusammen", f"Vergleiche {A} mit {B}", f"Fasse {A} und example.net zusammen"])
def test_every_named_url_gets_its_own_independent_research_step(objective):
    g, steps = plan(objective)
    assert len(urls(steps)) == 2 and len(set(urls(steps))) == 2
    assert all(s.dependencies == () for s in work(steps))
    ev = steps[-1]
    assert ev.is_evaluation and sum(s.is_evaluation for s in steps) == 1 and set(ev.dependencies) == {s.step_id for s in work(steps)}
    validate_plan(g, steps, max_steps=20)


def test_order_is_kept_and_duplicates_are_removed():
    _, steps = plan(f"Vergleiche {A} mit {B} und noch einmal {A} sowie {C}")
    assert [u.rstrip("/") for u in urls(steps)] == [A, B, C]


def test_a_bare_domain_and_the_same_url_count_once():
    _, steps = plan(f"Fasse {A} zusammen, also example.org")
    assert len(urls(steps)) == 1


def test_five_distinct_urls_are_planned_six_are_refused_with_a_reason():
    five = [f"https://example.org/p{i}" for i in range(5)]
    _, steps = plan("Vergleiche " + " ".join(five))
    assert [u for u in urls(steps)] == five
    with pytest.raises(PlanningError, match=r"incomplete.*(5|fünf|five)"):
        plan("Vergleiche " + " ".join(five + ["https://example.org/p5"]))


def test_six_urls_that_contain_only_five_distinct_ones_are_fine():
    five = [f"https://example.org/p{i}" for i in range(5)]
    _, steps = plan("Vergleiche " + " ".join(five + [five[0]]))
    assert len(urls(steps)) == 5


def test_two_urls_plus_a_file_give_three_branches_and_one_evaluation():
    g, steps = plan(f"Lies a.txt, {A} und {B}")
    assert caps(work(steps)) == {"files.read", "research.web"} and len(work(steps)) == 3 and sum(s.is_evaluation for s in steps) == 1
    validate_plan(g, steps, max_steps=20)


def test_the_step_limit_applies_to_the_whole_multi_url_plan():
    with pytest.raises(PlanningError, match="limit"):
        plan(f"Vergleiche {A} mit {B} und {C}", max_steps=3)


def test_single_url_plans_are_unchanged():
    _, steps = plan(f"Fasse {A} zusammen")
    assert [s.assigned_agent for s in steps] == ["research", None] and steps[1].dependencies == (steps[0].step_id,)


def test_a_url_in_the_context_and_a_different_one_in_the_text_are_both_planned():
    _, steps = plan(f"Fasse {B} zusammen", {"url": A})
    assert [u.rstrip("/") for u in urls(steps)] == [A, B]           # Kontext-URL zuerst


def test_a_decomposer_cannot_smuggle_in_an_additional_url():
    def sneaky(goal, ctx, max_steps, baseline, allowed):
        return [{"objective": "Seiten lesen und zusammenfassen", "capabilities": ["research.web"],
                 "input": {"kind": "research_web", "urls": [A, B, "https://evil.example/steal"]}}, {"evaluate": True}]
    g = Goal(f"Vergleiche {A} mit {B}")
    ctx = GoalContext(g.goal_id, g.objective, None, (), {})
    base = GoalPlanner(AgentPlanner(registry())).plan(g, ctx, 20)
    got = GoalPlanner(AgentPlanner(registry()), decomposer=sneaky).plan(g, ctx, 20)
    assert [dict(s.input) for s in got] == [dict(s.input) for s in base]
    assert "evil" not in repr([dict(s.input) for s in got])


def test_resume_skips_a_finished_url_branch_but_keeps_the_evaluation():
    g = Goal(f"Vergleiche {A} mit {B}")
    ctx = GoalContext(g.goal_id, g.objective, None, (), {})
    planner = ResumeAwarePlanner(GoalPlanner(AgentPlanner(registry())))
    full = planner.plan(g, ctx, 20)
    planner.skip(g.goal_id, [full[0].objective])
    left = planner.plan(g, ctx, 20)
    assert len(left) == 2 and left[-1].is_evaluation and set(left[-1].dependencies) == {left[0].step_id}


# ---- M2a: Speicherwunsch ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("objective", [
    f"Fasse {A} zusammen und speichere das Ergebnis in ergebnis.txt",
    f"Recherchiere {A} und schreibe die Ergebnisse in notiz.md",
    f"Speichere die Zusammenfassung von {A} in zusammenfassung.txt",
    f"Lies {A} und speichere es in einer Datei",
    f"Vergleiche {A} mit {B} und exportiere das Ergebnis nach vergleich.csv",
    f"Summarize {A} and save the result to a file",
    f"Lies a.txt und {A} und speichere die Auswertung unter report.md",
])
def test_a_save_wish_for_a_result_that_does_not_exist_yet_refuses_the_whole_goal(objective):
    with pytest.raises(PlanningError, match="incomplete"):
        plan(objective)


@pytest.mark.parametrize("objective", [
    f"Speichere die Seite {A} als Lesezeichen",
    f"Lege ein Lesezeichen für {A} an",
    f"Speichere {A} in meinen Favoriten",
    f"Schreibe mir eine Zusammenfassung von {A}",
    f"Fasse {A} zusammen und merke dir das Ergebnis",
    f"Lies {A} und speichere es im Gedächtnis",
    f"Zeige mir {A} und erkläre die Datei-Struktur",
    f"Fasse {A} zusammen und sende mir das Ergebnis",
    f"Speichere die Seite {A} in der Leseliste",
])
def test_bookmarks_and_similar_wishes_are_not_mistaken_for_save_to_file(objective):
    _, steps = plan(objective)
    assert "research.web" in caps(work(steps))


def test_no_file_intent_is_invented_without_a_save_wish():
    _, steps = plan(f"Fasse {A} zusammen")
    assert caps(work(steps)) == {"research.web"}


def test_explicit_literal_content_still_plans_the_file_write():
    _, steps = plan(f"Lies {A} und erstelle x.txt mit dem Inhalt: fertig")
    assert caps(work(steps)) == {"research.web", "files.write"}
    _, steps = plan(f"Lies {A} und speichere in x.txt den Inhalt: fertig")
    assert "research.web" in caps(work(steps))


def test_save_wishes_without_a_web_or_screen_part_keep_their_old_behaviour():
    with pytest.raises(PlanningError, match="no plan"):
        plan("Speichere die Ergebnisse in x.txt")
    _, steps = plan("Behebe den Fehler und speichere die Änderung in utils.py", {"workspace": "/w", "edits": [{"path": "utils.py", "content": "x"}]})
    assert "coding.write" in caps(work(steps))


def test_a_refused_save_goal_creates_no_steps_and_no_write_capability():
    with pytest.raises(PlanningError) as e:
        plan(f"Fasse {A} und {B} zusammen und speichere das Ergebnis in x.txt")
    assert "incomplete" in str(e.value)
