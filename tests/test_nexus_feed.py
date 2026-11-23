"""V2 Vorbereitung (Bereich B): `control_center.nexus_feed` - ein reiner, nur lesender Adapter von ECHTEN Backend-Daten (validierte UI-Vertragsereignisse und die lesenden
Ansichten agents/trace/mission/doctor) auf die Seitenstruktur von NEXUS Ultimate. Er erfindet nichts: ohne Daten ist jede Flaeche "nicht verfuegbar" mit Grund, nie ein
Standardwert wie "bereit"; Freigaben werden nur angezeigt (beantwortet wird im vorhandenen V1-Dialog); er hat keinen Schreibweg."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from jarvis.control_center.nexus_feed import PAGES, build_feed
from jarvis.ui_contract import FakeUiBackend
from jarvis.ui_contract.schema import validate_event

KEY = "sk-" + "a1" * 12
SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "control_center" / "nexus_feed.py"


def ev(seq, type_, data):
    return validate_event({"v": "1.0", "seq": seq, "ts": "2026-11-23T10:00:00Z", "type": type_, "data": data})


def hello(emergency=False):
    return ev(1, "hello", {"contract": "1.0", "backend": "jarvis", "capabilities": ["voice"], "emergency": emergency})


def confirmation(seq, rid="r1"):
    return ev(seq, "confirmation_request", {"request_id": rid, "tool": "files", "action": "write", "resource": "a.txt", "level": "yellow", "reason": "Datei anlegen",
                                           "context": [{"key": "pfad", "value": "a.txt"}], "choices": ["allow_once", "deny"], "timeout_s": 30})


# ---- nichts erfunden --------------------------------------------------------------------------------------------------------------------------------
def test_without_any_data_nothing_is_available_and_no_default_state_is_shown():
    f = build_feed([])
    assert f["v"] == 1 and f["connection"]["attached"] is False and f["core"] is None and f["emergency"] is None and f["voice"] is None
    assert f["tasks"]["items"] == [] and f["approvals"]["pending"] == [] and f["events"] == []
    assert set(f["pages"]) == set(PAGES) and not any(p["available"] for p in f["pages"].values()) and all(p["reason"] for p in f["pages"].values())


def test_pages_are_exactly_the_ten_pages_of_the_ultimate_frontend_model():
    model = (Path(__file__).resolve().parents[1] / "src/jarvis/control_center/nexus_ultimate/model.js").read_text(encoding="utf-8")
    assert list(PAGES) == re.findall(r'\["([a-z\-]+)", "[^"]+", "[a-z]+"\]', model.split("export { STATES")[0])


def test_core_voice_emergency_and_connection_come_only_from_events():
    f = build_feed([hello(), ev(2, "state", {"state": "processing", "detail": "plant"}), ev(3, "voice_level", {"level": 0.4, "active": True}),
                    ev(4, "emergency", {"engaged": True, "reason": "test", "report": ["agents: stopped"]})])
    assert f["connection"] == {"attached": True, "backend": "jarvis", "contract": "1.0", "last_seq": 4, "seq_gap": False, "rejected_events": 0}
    assert f["core"] == {"state": "processing", "detail": "plant"} and f["voice"] == {"level": 0.4, "active": True}
    assert f["emergency"] == {"engaged": True, "reason": "test", "report": ["agents: stopped"]}
    assert f["pages"]["ai-core"]["available"] is True and f["pages"]["overview"]["available"] is True


def test_the_latest_event_wins_and_a_sequence_gap_is_reported_not_hidden():
    f = build_feed([hello(), ev(2, "state", {"state": "ready"}), ev(5, "state", {"state": "error", "detail": "x"})])
    assert f["core"]["state"] == "error" and f["connection"]["seq_gap"] is True


def test_invalid_or_foreign_events_are_counted_and_never_change_the_state():
    f = build_feed([hello(), {"v": "1.0", "seq": 2, "ts": "x", "type": "state", "data": {"state": "ready-ish"}}, "kaputt", None, {"type": "state"}])
    assert f["core"] is None and f["connection"]["rejected_events"] == 4


# ---- Freigaben: nur Anzeige --------------------------------------------------------------------------------------------------------------------------------
def test_approvals_are_listed_while_open_and_disappear_when_closed_and_are_display_only():
    open_ = build_feed([hello(), confirmation(2)])
    assert [a["request_id"] for a in open_["approvals"]["pending"]] == ["r1"] and open_["approvals"]["display_only"] is True and open_["approvals"]["answer_via"] == "v1_dialog"
    closed = build_feed([hello(), confirmation(2), ev(3, "confirmation_closed", {"request_id": "r1", "outcome": "denied"})])
    assert closed["approvals"]["pending"] == [] and closed["approvals"]["recent"][0]["outcome"] == "denied"


def test_the_feed_never_offers_or_makes_an_answer():
    f = build_feed([hello(), confirmation(2)])
    blob = json.dumps(f)
    for forbidden in ("allow_once", "allow_session", "confirm_url", "auto_approved", "granted"):
        assert forbidden not in blob
    assert "choices" not in f["approvals"]["pending"][0]                    # keine Antwortmoeglichkeiten im Feed: die Antwort geschieht nur im V1-Dialog


# ---- Aufgaben, Routing, Ergebnisse ---------------------------------------------------------------------------------------------------------------------
def test_tasks_merge_activity_updates_routing_and_results():
    f = build_feed([hello(), ev(2, "activity", {"items": [{"kind": "agent_task", "id": "at-1", "title": "Preise", "status": "RUNNING", "note": "", "cancellable": True}], "problems": [], "inactive": []}),
                    ev(3, "routing", {"task_id": "at-1", "agent": "research", "source": "rules", "reason": "Recherche"}),
                    ev(4, "task_update", {"kind": "agent_task", "id": "at-1", "status": "SUCCEEDED", "detail": "fertig"}),
                    ev(5, "result", {"task_id": "at-1", "summary": "3 Quellen", "artifacts": []})])
    t = f["tasks"]["items"][0]
    assert (t["id"], t["status"], t["agent"], t["routing_reason"], t["summary"]) == ("at-1", "SUCCEEDED", "research", "Recherche", "3 Quellen")
    assert f["pages"]["agent-center"]["available"] is True


def test_secrets_in_texts_are_redacted_and_lists_are_bounded():
    f = build_feed([hello(), ev(2, "chat", {"sender": "jarvis", "text": "Schluessel " + KEY}), ev(3, "error", {"code": "x", "message": "boese " + KEY})] +
                   [ev(10 + i, "task_update", {"kind": "agent_task", "id": f"at-{i}", "status": "RUNNING"}) for i in range(300)], max_items=20)
    assert KEY not in json.dumps(f) and len(f["tasks"]["items"]) <= 20 and len(f["events"]) <= 20 and f["tasks"]["truncated"] is True


# ---- die lesenden V2-Ansichten ----------------------------------------------------------------------------------------------------------------------------
AGENTS_VIEW = {"available": True, "agents": [{"id": "research", "status": "AVAILABLE", "capabilities": ["research.web"], "reason": ""}, {"id": "business", "status": "DISABLED", "capabilities": [], "reason": "aus"}],
               "items": [], "reason": ""}
MISSION = {"available": True, "business": {"available": True, "items": [{"task_id": "t1", "agent_id": "strategist", "kind": "rank", "summary": "x", "confidence": "low", "unknowns": 1, "sources": 0}]},
           "memory": {"available": False, "reason": "M3 nicht angebunden"}, "budget": {"available": True, "session": {"calls": 2, "max_calls": 10, "exhausted": None}}, "graph": {"available": True, "nodes": []}}


def test_agent_status_comes_from_the_real_agents_view_and_unavailable_views_say_why():
    f = build_feed([hello()], agents_view=AGENTS_VIEW, mission=MISSION)
    assert [(a["id"], a["status"]) for a in f["agents"]["items"]] == [("business", "DISABLED"), ("research", "AVAILABLE")]
    assert f["pages"]["business-center"]["available"] is True and f["pages"]["memory-settings"]["available"] is False and "M3" in f["pages"]["memory-settings"]["reason"]
    off = build_feed([hello()], agents_view={"available": False, "reason": "Die Agentenschicht ist nicht aktiv", "agents": [], "items": []})
    assert off["agents"]["available"] is False and "nicht aktiv" in off["agents"]["reason"]


def test_pages_without_a_backend_endpoint_stay_honestly_unavailable_even_with_full_data():
    f = build_feed([hello(), ev(2, "state", {"state": "ready"})], agents_view=AGENTS_VIEW, mission=MISSION)
    for page in ("live-workspace", "creative-studio", "coding-studio", "trading-center", "automations"):
        assert f["pages"][page]["available"] is False and "endpunkt" in f["pages"][page]["reason"].lower(), page


def test_malformed_views_do_not_crash_and_are_reported_unavailable():
    f = build_feed([hello()], agents_view="kaputt", mission=[1], trace=5, doctor=None)
    assert f["agents"]["available"] is False and f["pages"]["business-center"]["available"] is False


# ---- echtes Backend (FakeUiBackend des Vertrags) -------------------------------------------------------------------------------------------------------
def test_events_of_the_real_contract_backend_fold_into_a_consistent_feed():
    b = FakeUiBackend()
    ack = b.send({"v": "1.0", "id": "c1", "type": "emergency_stop", "data": {}})
    assert ack["data"]["ok"] is True
    f = build_feed(b.snapshot() + b.events_since(0))
    assert f["connection"]["attached"] is True and f["emergency"]["engaged"] is True and f["connection"]["rejected_events"] == 0


# ---- Struktur: rein lesend ----------------------------------------------------------------------------------------------------------------------------
def test_the_module_is_pure_and_has_no_write_path():
    t = ast.parse(SRC.read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(t) if isinstance(n, ast.Import) for a in n.names} | {n.module or "" for n in ast.walk(t) if isinstance(n, ast.ImportFrom)}
    assert not [m for m in mods if m.startswith(("jarvis.permissions", "jarvis.tools", "jarvis.agents", "jarvis.bootstrap", "jarvis.goals", "os", "subprocess", "socket", "http", "urllib", "threading"))], mods
    names = [n.name for n in ast.walk(t) if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    assert not [n for n in names if re.search(r"write|delete|confirm|submit|start|run|approve|grant|reset|engage|send|cancel", n, re.I)], names


def test_it_is_wired_nowhere_yet():
    root = Path(__file__).resolve().parents[1] / "src" / "jarvis"
    assert not [p for p in root.rglob("*.py") if p.name != "nexus_feed.py" and "nexus_feed" in p.read_text(encoding="utf-8")]
