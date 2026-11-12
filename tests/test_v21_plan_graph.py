"""V2.1 Mission 1: Plananalyse (Abhaengigkeitsgraph, Wellen, Priorisierung, fehlende Voraussetzungen, Neuplanung, Wiederaufnahme) und Vorgehensvergleich.
Reine Logik: kein Netzwerk, keine Agenten, keine Wahrscheinlichkeiten."""
from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest

from jarvis.goals import policy as GP
from jarvis.goals.decision import Approach, compare
from jarvis.goals.plan_graph import Node, analyse, from_steps, replan, resume

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
CAPS = {"research.web", "business.analyze", "finance.analyze", "files.write"}
TOOLS = {"browser", "files"}


def n(i, deps=(), cap="research.web", tool=None, **kw):
    return Node(i, tuple(deps), capability=cap, tool=tool, **kw)


def business_plan(extra=0):
    """Marktanalyse -> Geschaeftsmodelle -> Kosten -> Wettbewerb -> Businessplan (14 Knoten + extra unabhaengige Recherchen)."""
    nodes = [n("markt", needs=("region",), provides=("marktdaten",), value=5, est_seconds=60),
             n("zielgruppe", ["markt"], provides=("zielgruppe",), value=4, est_seconds=30),
             n("wettbewerb-a", ["markt"], tool="browser", provides=("preise-a",), est_seconds=40),
             n("wettbewerb-b", ["markt"], tool="browser", provides=("preise-b",), est_seconds=45),
             n("wettbewerb-c", ["markt"], tool="browser", provides=("preise-c",), est_seconds=50),
             n("preisvergleich", ["wettbewerb-a", "wettbewerb-b", "wettbewerb-c"], cap="business.analyze", needs=("preise-a", "preise-b", "preise-c"), provides=("marktpreis",), est_seconds=10),
             n("modelle", ["zielgruppe", "preisvergleich"], cap="business.analyze", provides=("modelle",), value=5, est_seconds=20),
             n("startkosten", ["modelle"], cap="finance.analyze", needs=("budget",), provides=("startkosten",), est_seconds=15),
             n("laufende-kosten", ["modelle"], cap="finance.analyze", provides=("fixkosten",), est_seconds=15),
             n("break-even", ["startkosten", "laufende-kosten", "preisvergleich"], cap="finance.analyze", needs=("marktpreis", "fixkosten"), provides=("break-even",), est_seconds=5),
             n("risiken", ["modelle"], cap="business.analyze", risk=2, est_seconds=20),
             n("rangfolge", ["break-even", "risiken"], cap="business.analyze", provides=("rangfolge",), value=5, est_seconds=10),
             n("plan-30-90", ["rangfolge"], cap="business.analyze", provides=("plan",), est_seconds=30),
             n("pruefung", ["plan-30-90"], cap="business.analyze", verify=True, est_seconds=10)]
    nodes += [n(f"zusatz-{i}", ["markt"], est_seconds=5) for i in range(extra)]
    return nodes


KNOWN = {"region", "budget"}


def run(nodes, **kw):
    kw.setdefault("capabilities", CAPS)
    kw.setdefault("available_tools", TOOLS)
    kw.setdefault("known_info", KNOWN)
    return analyse(nodes, **kw)


# ---- Zerlegung, Wellen, Parallelitaet -------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("extra", [0, 6, 16])                       # 14, 20 und 30 Teilaufgaben
def test_a_complex_plan_is_valid_layered_and_every_dependency_runs_earlier(extra):
    nodes = business_plan(extra)
    a = run(nodes, max_parallel=4)
    assert a.ok and not a.blocked and len(a.runnable) == len(nodes) == 14 + extra
    pos = {nid: i for i, wave in enumerate(a.waves) for nid in wave}
    for node in nodes:
        assert all(pos[d] < pos[node.id] for d in node.deps), node.id
    assert all(len(w) <= 4 for w in a.waves) and a.waves[0] == ("markt",)
    assert max(len(w) for w in a.waves) >= 2                         # unabhaengige Teilaufgaben laufen parallel


def test_parallel_limit_one_gives_a_strictly_serial_order():
    a = run(business_plan(), max_parallel=1)
    assert all(len(w) == 1 for w in a.waves) and len(a.waves) == 14


def test_priority_inside_a_wave_is_value_then_low_risk_then_low_cost_then_id():
    nodes = [n("start"), n("b", ["start"], value=3, risk=1), n("a", ["start"], value=5, risk=4), n("c", ["start"], value=5, risk=2, cost=3), n("d", ["start"], value=5, risk=2, cost=1)]
    a = run(nodes, max_parallel=10)
    assert a.waves[1] == ("d", "c", "a", "b")
    limited = run(nodes, max_parallel=2)
    assert limited.waves[1] == ("d", "c") and limited.waves[2] == ("a", "b")   # das Wichtigste zuerst


def test_the_order_is_deterministic_whatever_the_input_order():
    nodes = business_plan(6)
    base = run(nodes).waves
    rng = random.Random(21)
    for _ in range(5):
        shuffled = nodes[:]
        rng.shuffle(shuffled)
        assert run(shuffled).waves == base


def test_critical_path_is_the_longest_chain_and_unknown_durations_stay_unknown():
    a = run(business_plan())
    assert a.critical_path[0] == "markt" and a.critical_path[-1] == "pruefung" and "wettbewerb-c" in a.critical_path
    assert a.critical_seconds == 60 + 50 + 10 + 20 + 15 + 5 + 10 + 30 + 10
    nodes = business_plan()
    nodes[3] = n("wettbewerb-b", ["markt"], tool="browser", provides=("preise-b",))          # keine Schaetzung
    b = run(nodes)
    assert b.critical_seconds is None and "wettbewerb-b" in b.unknown_durations             # nichts wird geraten


# ---- unloesbare Voraussetzungen -------------------------------------------------------------------------------------------------------------------------
def test_missing_information_blocks_the_node_and_everything_behind_it_but_not_the_rest():
    a = run(business_plan(), known_info={"region"})                  # "budget" fehlt
    assert not a.ok and a.missing_info == {"startkosten": ("budget",)}
    assert set(a.blocked) == {"startkosten", "break-even", "rangfolge", "plan-30-90", "pruefung"}
    assert "laufende-kosten" in a.runnable and "risiken" in a.runnable
    assert a.questions == ("budget",)                                # das ist die Rueckfrage an den Nutzer


def test_information_must_come_from_an_ancestor_not_from_a_sibling():
    nodes = [n("a", provides=("x",)), n("b", needs=("x",))]           # b haengt nicht von a ab
    a = run(nodes)
    assert a.missing_info == {"b": ("x",)} and "b" in a.blocked


def test_missing_tool_and_missing_capability_abort_with_the_reason():
    a = run(business_plan(), available_tools={"files"})
    assert not a.ok and {"wettbewerb-a", "wettbewerb-b", "wettbewerb-c"} <= set(a.missing_tools)
    assert "preisvergleich" in a.blocked and a.unsolvable                # das Ziel selbst (pruefung) ist nicht erreichbar
    b = run(business_plan(), capabilities={"research.web"})
    assert not b.ok and "modelle" in b.missing_capabilities and b.unsolvable


def test_a_plan_whose_goal_stays_reachable_is_not_unsolvable():
    nodes = [n("a"), n("b", ["a"]), n("neben", ["a"], tool="mikroskop")]
    a = run(nodes, goals=("b",))
    assert not a.ok and not a.unsolvable and a.blocked == ("neben",)


@pytest.mark.parametrize("nodes,code", [
    ([n("a", ["b"]), n("b", ["a"])], "cycle"),
    ([n("a", ["a"])], "cycle"),
    ([n("a"), n("b", ["c"])], "unknown_dependency"),
    ([n("a"), n("a")], "duplicate_id"),
    ([], "empty"),
    ([n(f"s{i}", [f"s{i - 1}"] if i else []) for i in range(GP.MAX_DEPTH_HARD + 2)], "too_deep"),
    ([n(f"s{i}") for i in range(GP.MAX_STEPS_HARD + 1)], "too_many_steps"),
    ([n("Bad Id")], "invalid_id"),
])
def test_invalid_plans_are_refused_with_a_stable_code(nodes, code):
    a = run(nodes)
    assert not a.ok and a.error == code and a.waves == () and a.runnable == ()


def test_a_cycle_report_names_the_nodes():
    a = run([n("a", ["c"]), n("b", ["a"]), n("c", ["b"]), n("frei")])
    assert a.error == "cycle" and set(a.cycle) == {"a", "b", "c"}


def test_reserved_bypass_words_cannot_enter_a_plan():
    for bad in ("confirmed", "force", "bypass", "skip_permissions"):
        a = run([n("a", needs=(bad,))])
        assert a.error == "reserved_key", bad


# ---- Neuplanung ---------------------------------------------------------------------------------------------------------------------------------------
def test_replanning_replaces_a_failed_node_by_its_next_alternative_and_keeps_finished_work():
    nodes = business_plan()
    alt = {"wettbewerb-b": [n("wettbewerb-b2", ["markt"], tool="browser", provides=("preise-b",), est_seconds=45)]}
    r = replan(nodes, failed="wettbewerb-b", code="timeout", done={"markt", "zielgruppe", "wettbewerb-a"}, alternatives=alt, capabilities=CAPS, available_tools=TOOLS, known_info=KNOWN)
    assert r.action == "replaced" and r.replacement == "wettbewerb-b2" and r.analysis.ok
    ids = [x for w in r.analysis.waves for x in w]
    assert "wettbewerb-b" not in ids and "markt" not in ids and "wettbewerb-b2" in ids and ids.index("wettbewerb-b2") < ids.index("preisvergleich")


def test_replanning_never_retries_a_fatal_code_and_never_exceeds_the_attempt_limit():
    nodes = business_plan()
    alt = {"wettbewerb-b": [n("wettbewerb-b2", ["markt"], tool="browser", provides=("preise-b",))]}
    for code in ("permission_denied", "halted", "agent_budget_exceeded", "budget_exhausted", "cancelled"):
        r = replan(nodes, failed="wettbewerb-b", code=code, done={"markt"}, alternatives=alt, capabilities=CAPS, available_tools=TOOLS, known_info=KNOWN)
        assert r.action == "abort" and r.replacement is None, code
    r = replan(nodes, failed="wettbewerb-b", code="timeout", done={"markt"}, alternatives=alt, attempts_used=2, capabilities=CAPS, available_tools=TOOLS, known_info=KNOWN)
    assert r.action == "abort" and "attempt" in r.reason


def test_without_an_alternative_the_dependents_are_blocked_and_the_rest_continues():
    r = replan(business_plan(), failed="risiken", code="invalid_result", done={"markt"}, alternatives={}, capabilities=CAPS, available_tools=TOOLS, known_info=KNOWN)
    assert r.action == "degraded" and set(r.analysis.blocked) == {"risiken", "rangfolge", "plan-30-90", "pruefung"} and "break-even" in r.analysis.runnable
    assert r.analysis.unsolvable                                       # das Ziel ist ohne den Knoten nicht erreichbar: ehrlich gemeldet


def test_an_alternative_cannot_smuggle_in_a_capability_the_plan_did_not_have():
    alt = {"risiken": [n("risiken2", ["modelle"], cap="files.write")]}
    r = replan(business_plan(), failed="risiken", code="timeout", done=set(), alternatives=alt, capabilities=CAPS, available_tools=TOOLS, known_info=KNOWN)
    assert r.action != "replaced" and "capability" in r.reason


# ---- Wiederaufnahme --------------------------------------------------------------------------------------------------------------------------------------
def test_resume_runs_only_what_is_not_done_and_never_repeats_a_side_effect_step_silently():
    nodes = business_plan() + [n("speichern", ["plan-30-90"], cap="files.write", tool="files", side_effect=True)]
    r = resume(nodes, done={"markt", "zielgruppe", "wettbewerb-a", "wettbewerb-b"}, interrupted={"wettbewerb-c"}, capabilities=CAPS, available_tools=TOOLS, known_info=KNOWN)
    ids = [x for w in r.analysis.waves for x in w]
    assert "markt" not in ids and "wettbewerb-c" in ids and r.needs_confirmation == ()
    r2 = resume(nodes, done={x.id for x in business_plan()}, interrupted={"speichern"}, capabilities=CAPS, available_tools=TOOLS, known_info=KNOWN)
    assert r2.needs_confirmation == ("speichern",)                     # unterbrochener Schritt mit Wirkung: erst nach neuer Freigabe


def test_quality_gate_nodes_are_reported_and_a_plan_without_one_is_flagged():
    assert run(business_plan()).verify_nodes == ("pruefung",)
    a = run([n("a"), n("b", ["a"])])
    assert a.ok and a.verify_nodes == () and "no_quality_gate" in a.warnings


def test_from_steps_adapts_real_goal_steps():
    from jarvis.goals.fake import step
    from jarvis.goals.models import Goal
    g = Goal("Testziel")
    steps = [step(g, "s1", "fake"), step(g, "s2", "fake", deps=("s1",)), step(g, "ev", None, deps=("s2",))]
    nodes = from_steps(steps)
    a = analyse(nodes, capabilities={c for s in steps for c in s.required_capabilities}, available_tools=set(), known_info=set())
    assert a.ok and [w for w in a.waves] == [("s1",), ("s2",), ("ev",)] and a.verify_nodes == ("ev",)


# ---- Vorgehensvergleich ------------------------------------------------------------------------------------------------------------------------------
def approaches():
    return [Approach("gruendlich", quality=5, compute=2, time=1, risk=4, permissions=("browser.read",), note="alle Quellen lesen"),
            Approach("schnell", quality=3, compute=5, time=5, risk=3, permissions=()),
            Approach("ausgewogen", quality=4, compute=4, time=3, risk=4, permissions=("browser.read",)),
            Approach("riskant", quality=5, compute=3, time=4, risk=1, permissions=("browser.read", "files.write"))]


def test_at_least_three_approaches_are_compared_with_an_explained_ranking():
    c = compare(approaches(), granted={"browser.read"})
    assert [r.name for r in c.ranking][0] == "ausgewogen" and len(c.ranking) == 4
    top = c.ranking[0]
    assert set(top.contributions) == {"quality", "compute", "time", "risk", "permissions"} and abs(sum(top.contributions.values()) - top.score) < 1e-9
    why = c.explain("ausgewogen", "schnell")
    assert "quality" in why and "ausgewogen" in why and "schnell" in why
    assert "%" not in c.disclaimer and "keine Wahrscheinlichkeit" in c.disclaimer


def test_fewer_than_three_approaches_or_bad_ratings_are_refused():
    with pytest.raises(ValueError):
        compare(approaches()[:2], granted=set())
    for bad in (0, 6, 2.5, True, "4"):
        with pytest.raises(ValueError):
            Approach("x", quality=bad, compute=3, time=3, risk=3)
    with pytest.raises(ValueError):
        compare([Approach("a", 3, 3, 3, 3), Approach("a", 3, 3, 3, 3), Approach("b", 3, 3, 3, 3)], granted=set())


def test_missing_permissions_are_shown_as_needed_approvals_never_assumed():
    c = compare(approaches(), granted={"browser.read"})
    r = {x.name: x for x in c.ranking}
    assert r["riskant"].needs_approval == ("files.write",) and r["ausgewogen"].needs_approval == ()
    strict = compare(approaches(), granted=set(), approvals_possible=False)
    assert [x.name for x in strict.ranking if x.feasible] == ["schnell"] and strict.ranking[0].name == "schnell"
    assert all(not x.feasible for x in strict.ranking[1:])


def test_unknown_ratings_give_a_range_not_a_guess_and_can_change_the_verdict():
    opts = [Approach("a", quality=None, compute=3, time=3, risk=3), Approach("b", quality=3, compute=3, time=3, risk=3), Approach("c", quality=2, compute=3, time=3, risk=3)]
    c = compare(opts, granted=set())
    a = next(x for x in c.ranking if x.name == "a")
    assert a.score is None and a.low < a.high and a.unknown == ("quality",)
    assert c.decided is False and "a" in c.open_questions[0]             # die Rangfolge haengt an einer unbekannten Bewertung
    d = compare([Approach("a", quality=None, compute=5, time=5, risk=5), Approach("b", 1, 1, 1, 1), Approach("c", 1, 1, 1, 2)], granted=set())
    assert d.decided is True and d.ranking[0].name == "a"               # auch im schlechtesten Fall vorn


def test_weights_change_the_ranking_and_are_validated():
    fast = compare(approaches(), granted={"browser.read"}, weights={"time": 5, "quality": 1})
    assert fast.ranking[0].name == "schnell"
    for bad in ({"quality": -1}, {"nonsense": 1}, {"quality": 0, "compute": 0, "time": 0, "risk": 0, "permissions": 0}):
        with pytest.raises(ValueError):
            compare(approaches(), granted=set(), weights=bad)


def test_ties_are_broken_deterministically_and_reported():
    opts = [Approach("b", 3, 3, 3, 3), Approach("a", 3, 3, 3, 3), Approach("c", 3, 3, 3, 3)]
    c = compare(opts, granted=set())
    assert [x.name for x in c.ranking] == ["a", "b", "c"] and c.tie is True


def test_both_modules_are_pure():
    for name in ("plan_graph.py", "decision.py"):
        tree = ast.parse((SRC / "goals" / name).read_text(encoding="utf-8"))
        mods = {a.name for x in ast.walk(tree) if isinstance(x, ast.Import) for a in x.names} | {x.module for x in ast.walk(tree) if isinstance(x, ast.ImportFrom)}
        assert mods <= {"__future__", "dataclasses", "typing", "jarvis.goals", "jarvis.goals.policy"}, mods
