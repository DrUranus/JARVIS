"""Datei-/Office-E2E (Aufgabe 4): echter Control-Center-Server (HTTP, Loopback, Token) -> Befehl -> Assistent -> Router -> FilesAgent -> ToolRegistry -> PermissionEngine ->
Tool -> Ergebnis im Ereignisstrom und in den lesenden Ansichten (Journal/Audit). Es gibt keine zweite Agentenimplementierung: der Test faehrt dieselbe Kette wie NEXUS."""
from __future__ import annotations

import http.client
import json
import time

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.control_center.launcher import build_server
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.confirmation import ScriptedConfirmation
from test_computer_integration import env_for
from test_control_center_binding import cmd, post

ONCE, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.DENY
ENV = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_CONTROL_CENTER_ENABLED="true",
           JARVIS_FILES_ENABLED="true", JARVIS_OFFICE_ENABLED="true", JARVIS_JOURNAL_ENABLED="true", JARVIS_ASSISTANT_CONFIRMATION_TIMEOUT_SECONDS="1")


def start(tmp_path, answers):
    env = env_for(tmp_path, **ENV, JARVIS_JOURNAL_PATH=str(tmp_path / "j.db"))
    settings = load_settings(env=env)
    core = build_core(settings)
    core.permissions.set_confirmation_provider(ScriptedConfirmation(answers), source="test")
    srv = build_server(settings, core)
    srv.start()
    return core, srv, tmp_path / "ws"


def get(srv, path):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", f"{path}{'&' if '?' in path else '?'}t={srv.token}", headers={"Host": f"127.0.0.1:{srv.port}"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, json.loads(body or b"{}")


def say(srv, text, cid, wait=20.0):
    status, ack = post(srv, cmd("submit_text", {"text": text}, cid=cid))
    assert status == 200 and ack["data"]["ok"], ack
    end = time.monotonic() + wait
    seen = 0
    while time.monotonic() < end:
        evs = srv.backend.events_since(0, 1000)
        replies = [e for e in evs if e["type"] == "chat" and e["data"]["sender"] == "jarvis"]
        if len(replies) > seen and evs[-1]["type"] != "activity":
            time.sleep(0.3)
            return [e["data"]["text"] for e in srv.backend.events_since(0, 1000) if e["type"] == "chat" and e["data"]["sender"] == "jarvis"]
        time.sleep(0.1)
    return []


def test_read_and_create_through_the_server_show_up_as_chat_results_and_in_the_audit(tmp_path):
    core, srv, ws = start(tmp_path, (ONCE,) * 20)
    try:
        (ws / "notiz.txt").write_text("Hallo aus der Datei", encoding="utf-8")
        replies = say(srv, "Lies die Datei notiz.txt", "e1")
        assert replies and "Hallo aus der Datei" in replies[-1]
        replies = say(srv, "Erstelle den Ordner Archiv", "e2")
        assert (ws / "Archiv").is_dir() and replies
        status, audit = get(srv, "/view/audit")
        assert status == 200
        text = json.dumps(audit)
        assert "files" in text                                                         # beide Aktionen stehen im Audit der echten Engine
        status, hist = get(srv, "/view/history")
        assert status == 200 and "notiz" in json.dumps(hist)                         # Verlauf zeigt die Anfrage
    finally:
        srv.stop()


def test_a_declined_write_through_the_server_changes_nothing_and_is_explained(tmp_path):
    core, srv, ws = start(tmp_path, (NO,) * 20)
    try:
        replies = say(srv, "Erstelle den Ordner Verboten", "e3")
        assert not (ws / "Verboten").exists() and replies                             # abgelehnt: nichts passiert, der Chat sagt es
    finally:
        srv.stop()


def test_emergency_stop_blocks_file_requests_through_the_server(tmp_path):
    core, srv, ws = start(tmp_path, (ONCE,) * 20)
    try:
        status, ack = post(srv, cmd("emergency_stop", cid="n1"))
        assert ack["data"]["ok"] and core.permissions.emergency.engaged
        status, ack = post(srv, cmd("submit_text", {"text": "Erstelle den Ordner Nein"}, cid="n2"))
        assert ack["data"]["ok"] is False and ack["data"]["code"] == "emergency"
        assert not (ws / "Nein").exists()
    finally:
        srv.stop()


# ---- Fehlerweitergabe und Statusabgleich (Aufgabe 8) -------------------------------------------------------------------------------------------
def test_a_failing_file_step_is_propagated_to_nexus_with_a_reason_and_is_not_retried_without_limit(tmp_path):
    core, srv, ws = start(tmp_path, (ONCE,) * 40)
    try:
        replies = say(srv, "Lies die Datei gibtsnicht.txt", "r1")
        assert replies and replies[-1].strip()                                                     # der Chat erklaert den Fehlschlag, kein Schweigen
        evs = srv.backend.events_since(0, 2000)
        updates = [e["data"] for e in evs if e["type"] == "task_update"]
        final = [u for u in updates if str(u["status"]).upper() in {"FAILED", "BLOCKED", "SUCCEEDED", "CANCELLED"}]
        assert final and str(final[-1]["status"]).upper() in {"FAILED", "BLOCKED"}               # Status in NEXUS stimmt mit dem Ergebnis ueberein
        per_task: dict[str, int] = {}
        for u in updates:
            if str(u["status"]).upper() == "RUNNING":
                per_task[u["id"]] = per_task.get(u["id"], 0) + 1
        assert all(n <= 5 for n in per_task.values())                                              # harte Obergrenze der Versuche (max_attempts_per_step <= 5)
        assert not any(p.is_file() for p in ws.glob("**/*"))                                       # ein fehlgeschlagener Lesezugriff schreibt nichts
    finally:
        srv.stop()


def test_a_cancel_command_for_an_unknown_task_is_answered_not_ignored_and_changes_nothing(tmp_path):
    core, srv, ws = start(tmp_path, (ONCE,) * 5)
    try:
        status, ack = post(srv, cmd("cancel", {"kind": "agent_task", "id": "gibt-es-nicht"}, cid="c9"))
        assert status == 200 and ack["data"]["ok"] is False and ack["data"].get("code")      # echte Antwort des Backends statt stillem Erfolg
        assert core.permissions.emergency.engaged is False
    finally:
        srv.stop()


def test_a_missing_file_is_not_retried_and_is_explained_in_plain_words(tmp_path):
    core, srv, ws = start(tmp_path, (ONCE,) * 20)
    try:
        replies = say(srv, "Lies die Datei gibt-es-nicht.txt", "e4")
        assert replies
        assert "Versuche" not in replies[-1]                                          # ein Eingabefehler wird nicht wiederholt (kein "(2 Versuche)")
        assert "existieren nicht" in replies[-1] and "file_not_found" not in replies[-1]
    finally:
        srv.stop()


def test_a_folder_request_without_a_name_explains_what_is_missing_and_creates_nothing(tmp_path):
    core, srv, ws = start(tmp_path, (ONCE,) * 20)
    try:
        replies = say(srv, "Erstelle einen Ordner auf dem Desktop", "e5")
        assert replies and "Ordnername" in replies[-1]
        assert not (ws / "auf").exists()
        replies = say(srv, "Erstelle einen Ordner namens Projekte", "e6")
        assert (ws / "Projekte").is_dir() and replies
    finally:
        srv.stop()
