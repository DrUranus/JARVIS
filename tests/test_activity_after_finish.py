"""Statusprojektion nach Abschluss (Windows-Livebefund 2026-11-20, Ziele g-29eb9410ff52 / g-93eee4617dbc): Backend und Journal sagen SUCCEEDED, das Dashboard zeigte
weiter RUNNING + „Abbrechen“, auch nach F5. Ursache: der zuletzt veroeffentlichte `activity`-Schnappschuss (er wird beim Neuladen wieder ausgeliefert) stammte aus der
Bearbeitung; nach dem Ende wurde kein neuer angefordert. Echter Kern, geskriptete Freigabe, kein Netz."""
import threading
import time

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.confirmation import ConfirmationProvider
from test_computer_integration import env_for

ENV = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_FILES_ENABLED="true", JARVIS_JOURNAL_ENABLED="true")


class Gated(ConfirmationProvider):
    def __init__(self, choice):
        self.gate, self.choice = threading.Event(), choice

    def confirm(self, request):
        self.gate.wait(15)
        return self.choice


def cmd(t, cid):
    return {"v": "1.0", "id": cid, "type": t, "data": {}}


def run_goal(tmp_path, choice):
    core = build_core(load_settings(env=env_for(tmp_path, **ENV, JARVIS_JOURNAL_PATH=str(tmp_path / "j.db"))))
    gate = Gated(choice)
    core.permissions.set_confirmation_provider(gate, source="test")
    ui = core.subsystems["assistant"].ui
    assert ui.send({"v": "1.0", "id": "g1", "type": "submit_text", "data": {"text": "Erstelle die Datei a.txt mit dem Inhalt: x"}})["data"]["ok"]
    time.sleep(0.8)
    ui.send(cmd("request_snapshot", "p1"))                                  # die Seite fragt waehrend der Bearbeitung
    time.sleep(0.6)
    assert any(i["status"] in ("WAITING", "RUNNING") for e in ui.snapshot() if e["type"] == "activity" for i in e["data"]["items"])   # waehrend der Bearbeitung offen
    gate.gate.set()
    end = time.monotonic() + 15
    while time.monotonic() < end:
        time.sleep(0.2)
        if any(e["type"] == "task_update" for e in ui.events_since(0, 500)):
            time.sleep(0.8)
            break
    return core, ui


def latest_items(ui):
    acts = [e for e in ui.snapshot() if e["type"] == "activity"]
    return acts[-1]["data"]["items"] if acts else []


def test_after_a_goal_succeeds_the_replayed_snapshot_lists_nothing_as_running(tmp_path):
    core, ui = run_goal(tmp_path, ConfirmationChoice.ALLOW_ONCE)
    assert [(i["kind"], i["status"]) for i in latest_items(ui) if i["status"] in ("RUNNING", "WAITING", "PENDING")] == []
    assert core.subsystems["goals"].engine.list()[0].status.value == "SUCCEEDED"       # das Backend war immer richtig


def test_after_a_declined_goal_nothing_stays_open_in_the_snapshot_either(tmp_path):
    core, ui = run_goal(tmp_path, ConfirmationChoice.DENY)
    assert [(i["kind"], i["status"]) for i in latest_items(ui) if i["status"] in ("RUNNING", "WAITING", "PENDING")] == []


# ---- Abbrechen mit offener Freigabefrage (Test 11.3): nichts darf nach dem Abbruch noch ausgefuehrt werden --------------------------------------------
def test_cancel_with_an_open_question_closes_it_as_denied_and_a_late_allow_creates_nothing(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, **ENV, JARVIS_JOURNAL_PATH=str(tmp_path / "j.db"))))
    ui = core.subsystems["assistant"].ui                                # echter UI-Bestaetigungsweg (Frage als Ereignis)
    assert ui.send({"v": "1.0", "id": "g1", "type": "submit_text", "data": {"text": "Erstelle die Datei a.txt mit dem Inhalt: x"}})["data"]["ok"]
    end = time.monotonic() + 10
    while time.monotonic() < end and not [e for e in ui.snapshot() if e["type"] == "confirmation_request"]:
        time.sleep(0.1)
    ui.send(cmd("request_snapshot", "p1"))
    time.sleep(0.6)
    goal = next(i for e in ui.snapshot() if e["type"] == "activity" for i in e["data"]["items"] if i["kind"] == "goal")
    ask = [e for e in ui.snapshot() if e["type"] == "confirmation_request"][0]["data"]
    assert ui.send({"v": "1.0", "id": "c1", "type": "cancel", "data": {"kind": "goal", "id": goal["id"]}})["data"]["ok"]
    time.sleep(1.0)
    assert [e for e in ui.snapshot() if e["type"] == "confirmation_request"] == []                              # die Frage ist weg (abgelehnt), nicht mehr beantwortbar
    late = ui.send({"v": "1.0", "id": "k1", "type": "confirm", "data": {"request_id": ask["request_id"], "choice": "allow_once"}})["data"]
    assert late["ok"] is False and late["code"] == "unknown_request"                                           # ein spaetes „Erlauben“ geht ins Leere
    time.sleep(1.5)
    assert not (tmp_path / "ws" / "a.txt").exists()                                                            # nichts wurde ausgefuehrt
    assert core.subsystems["goals"].engine.list()[0].status.value == "CANCELLED"
