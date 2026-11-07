"""Besitzer-Zurueckstellung (deferred): ein Schritt wird bewusst aus der automatischen Auswahl und Wiederholung genommen, ohne done/approved zu veraendern, ohne Versuche
zu zaehlen und ohne Ablaufschutz zu umgehen. Sie steht in backlog.json (Freigabe-Instanz, nur der Besitzer), gilt nur zwischen since und until (hoechstens 60 Tage) und endet danach
von selbst. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_jarvis_automation import NOW, ROOT, FakeApi, cfg, state_of  # noqa: E402
from test_plan import ACC, begin  # noqa: E402

import jarvis_automation as ja  # noqa: E402

TODAY = dt.datetime.now(dt.timezone.utc).date()
HOLD = {"reason": "B9: echte Desktop-Abnahme (Issue #186) steht aus", "since": (TODAY - dt.timedelta(days=1)).isoformat(), "until": (TODAY + dt.timedelta(days=20)).isoformat()}


def backlog(hold=None, **over):
    items = [{"id": "a", "task": "Aufgabe A", "approved": False, "depends_on": [], "acceptance": ACC},
             {"id": "b", "task": "Aufgabe B", "approved": False, "depends_on": [], "acceptance": ACC},
             {"id": "c", "task": "Aufgabe C", "approved": False, "depends_on": ["a"], "acceptance": ACC}]
    if hold is not None:
        items[0]["deferred"] = hold
    items[0].update(over)
    p = Path(tempfile.mkdtemp()) / "backlog.json"
    p.write_text(json.dumps({"plan": {"id": "pc", "approved": True, "approved_items": ["a", "b", "c"]}, "items": items}))
    return p


# ---- Pruefung der Eintraege -------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "text", [], {}, {"reason": "x"}, {**HOLD, "extra": 1}, {**HOLD, "reason": ""}, {**HOLD, "reason": "x" * 301}, {**HOLD, "since": "gestern"}, {**HOLD, "until": None},
    {**HOLD, "since": "2026-11-10", "until": "2026-11-01"}, {**HOLD, "since": "2026-11-01", "until": "2027-03-01"}])
def test_malformed_or_unbounded_deferrals_are_rejected_at_load(bad):
    with pytest.raises(ja.AutomationError):
        ja.load_backlog(backlog(bad))


def test_a_done_step_needs_no_deferral_and_a_valid_one_loads_unchanged():
    with pytest.raises(ja.AutomationError):
        ja.load_backlog(backlog(HOLD, done=True))
    items = ja.load_backlog(backlog(HOLD))
    a = items[0]
    assert a["deferred"] == HOLD and a["approved"] is True and not a.get("done")                    # weder done noch approved veraendert


# ---- Auswahl: 'next' ueberspringt, Abhaengige bleiben gesperrt, Ablauf hebt auf --------------------------------------------------------------
def test_next_skips_the_deferred_step_and_its_dependents_but_not_the_rest():
    items = ja.load_backlog(backlog(HOLD))
    assert ja.select_next_item(items, set(), set())["id"] == "b"                                    # a ist zurueckgestellt, c haengt an a
    assert ja.select_next_item(items, {"b"}, set()) is None                                         # nichts ausser den gesperrten Schritten uebrig: die Kette endet, startet aber nichts
    items_free = ja.load_backlog(backlog())
    assert ja.select_next_item(items_free, set(), set())["id"] == "a"


def test_the_deferral_ends_by_itself_after_until_and_before_since():
    items = ja.load_backlog(backlog(HOLD))
    after = TODAY + dt.timedelta(days=21)
    before = TODAY - dt.timedelta(days=5)
    assert ja.select_next_item(items, set(), set(), today=after)["id"] == "a"
    assert ja.select_next_item(items, set(), set(), today=before)["id"] == "a"
    assert ja.deferral_of(items[0], TODAY) == HOLD and ja.deferral_of(items[0], after) is None
    assert ja.deferral_of(items[1], TODAY) is None


def test_an_unapproved_or_done_step_is_never_selected_just_because_a_deferral_expired():
    items = ja.load_backlog(backlog(HOLD))
    items[0]["approved"] = False
    assert ja.select_next_item(items, set(), set(), today=TODAY + dt.timedelta(days=99))["id"] == "b"
    assert ja.select_next_item(items, {"a", "b"}, set(), today=TODAY + dt.timedelta(days=99))["id"] == "c"


# ---- Start per ID und Wiederholung -----------------------------------------------------------------------------------------------------------
def test_an_explicit_start_of_a_deferred_step_is_refused_with_the_reason_and_creates_nothing():
    api = FakeApi()
    with pytest.raises(ja.AutomationError, match="zurueckgestellt.*Desktop-Abnahme"):
        begin(api, "a", path=backlog(HOLD))
    assert not api.issues
    r = begin(api, "next", path=backlog(HOLD))                                                       # 'next' nimmt stattdessen den naechsten zulaessigen Schritt
    assert state_of(api, r["issue"])["chain"]["item_id"] == "b"


def test_no_retry_for_a_deferred_step_and_attempt_limits_stay_untouched(monkeypatch):
    items = ja.load_backlog(backlog(HOLD))
    issue = {"labels": [], "number": 5}
    base = {"chain": {"auto_continue": True, "index": 1, "budget": 5, "item_id": "a", "attempt": 1, "id": "c1"}, "report": {"status": "failed"}, "status": "failed"}
    plan, why = ja.decide_followup(base, cfg(JARVIS_AUTO_CONTINUE_ENABLED="true"), issue, items=items, done=set(), day_count=0, branch_exists=True)
    assert plan is None and "zurueckgestellt" in why
    # ohne Zurueckstellung greift weiter die bestehende Versuchsgrenze (Versuch 1 von 2: Wiederholung erlaubt; Versuch 2 von 2: nicht)
    free = ja.load_backlog(backlog())
    ok, _ = ja.decide_followup(base, cfg(JARVIS_AUTO_CONTINUE_ENABLED="true"), issue, items=free, done=set(), day_count=0, branch_exists=True)
    assert ok and ok["attempt"] == 2
    last = {**base, "chain": {**base["chain"], "attempt": 2}}
    none, why2 = ja.decide_followup(last, cfg(JARVIS_AUTO_CONTINUE_ENABLED="true"), issue, items=items, done=set(), day_count=0, branch_exists=True)
    assert none is None
    expired = {**HOLD, "since": "2026-01-01", "until": "2026-02-01"}
    items_exp = ja.load_backlog(backlog(expired))
    none2, _ = ja.decide_followup(last, cfg(JARVIS_AUTO_CONTINUE_ENABLED="true"), issue, items=items_exp, done=set(), day_count=0, branch_exists=True)
    assert none2 is None                                                                              # ein abgelaufener Hold gibt KEINEN zusaetzlichen Versuch frei


# ---- die ausgelieferte Datei ----------------------------------------------------------------------------------------------------------------
def test_the_shipped_backlog_defers_only_b9_without_changing_approval_data():
    raw = json.loads((ROOT / ".github/automation/backlog.json").read_text(encoding="utf-8"))
    assert [i["id"] for i in raw["items"] if "deferred" in i] == ["cc-windows-smoke"]                                    # den Eintrag setzt allein der Besitzer (siehe .github/automation/README.md)


def test_the_backlog_file_is_not_declarable_by_a_job_so_only_the_owner_can_defer():
    assert ".github/automation/backlog.json" in ja.NEVER_DECLARABLE
