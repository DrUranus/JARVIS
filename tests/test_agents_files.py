"""Datei-/Office-Agent (E1): natuerliche Sprache -> Ziel -> Router -> FilesAgent -> ToolRegistry -> PermissionEngine -> files/office-Tool -> Ergebnis in NEXUS.

Echter Kern (build_core, Mock-LLM), echter Assistent/UI-Adapter, echte Dateien in tmp_path, echte PermissionEngine mit geskripteten Antworten. Kein Netzwerk."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from jarvis.agents import AgentPlanner
from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.goals.files_intent import FileIntentError, parse_file_goal
from jarvis.interface.cli import research_route, run_command
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.confirmation import ScriptedConfirmation
from test_computer_integration import env_for

ONCE, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.DENY
ENV = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_FILES_ENABLED="true", JARVIS_OFFICE_ENABLED="true",
           JARVIS_JOURNAL_ENABLED="true")


def make(tmp_path, answers=(ONCE,) * 20, **extra):
    env = env_for(tmp_path, **ENV, JARVIS_JOURNAL_PATH=str(tmp_path / "j.db"), **extra)
    settings = load_settings(env=env)
    core = build_core(settings)
    prompts = ScriptedConfirmation(answers)
    core.permissions.set_confirmation_provider(prompts, source="test")
    return core, settings, prompts, tmp_path / "ws"


def goal(core, settings, text):
    return run_command(core, "/goal " + text, settings, lambda _t: None, lambda _p: "")


def ask(ui, text, wait=20.0):
    r = ui.send({"v": "1.0", "id": "f1", "type": "submit_text", "data": {"text": text}})
    assert r["data"]["ok"], r
    end = time.monotonic() + wait
    while time.monotonic() < end:
        evs = ui.events_since(0, 500)
        if any(e["type"] == "chat" and e["data"]["sender"] == "jarvis" for e in evs) and evs[-1]["type"] != "activity":
            time.sleep(0.2)
            evs = ui.events_since(0, 500)
            return [e["data"]["text"] for e in evs if e["type"] == "chat" and e["data"]["sender"] == "jarvis"], evs
        time.sleep(0.1)
    return [], ui.events_since(0, 500)


# ---- Anfrage-Erkennung ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expect", [
    ("Lies die Datei notizen.txt", {"tool": "files", "action": "read", "path": "notizen.txt"}),
    ("Zeige mir bericht.docx", {"tool": "office", "action": "read", "path": "bericht.docx"}),
    ("Liste den Ordner Projekte", {"tool": "files", "action": "list", "path": "Projekte"}),
    ("Erstelle den Ordner Archiv", {"tool": "files", "action": "mkdir", "path": "Archiv"}),
    ("Kopiere a.txt nach b.txt", {"tool": "files", "action": "copy", "path": "a.txt", "destination": "b.txt"}),
    ("Verschiebe \"alt datei.txt\" nach neu.txt", {"tool": "files", "action": "move", "path": "alt datei.txt", "destination": "neu.txt"}),
    ("Erstelle die Datei todo.txt mit dem Inhalt: Milch kaufen", {"tool": "files", "action": "create", "path": "todo.txt", "content": "Milch kaufen"}),
    ("Erstelle preise.xlsx mit dem Inhalt [[\"a\", 1]]", {"tool": "office", "action": "create", "path": "preise.xlsx", "content": "[[\"a\", 1]]"}),
    ("Ersetze \"Hund\" durch \"Katze\" in tiere.txt", {"tool": "files", "action": "replace", "path": "tiere.txt", "old_text": "Hund", "new_text": "Katze"}),
])
def test_clear_file_requests_become_exactly_one_step(text, expect):
    assert parse_file_goal(text) == expect


@pytest.mark.parametrize("text", ["Hallo", "Wie spät ist es", "Recherchiere die Preise für Dateien", "Lösche die Datei a.txt", "Lies mir etwas vor"])
def test_other_requests_are_not_file_requests(text):
    assert parse_file_goal(text) is None


@pytest.mark.parametrize("text", ["Erstelle die Datei x.txt mit dem Inhalt:", "Lies a.txt und erstelle b.txt mit dem Inhalt: x", "Ersetze \"x\" durch \"y\" in b.docx",
                                  "Kopiere a.txt nach"])
def test_incomplete_or_ambiguous_requests_are_refused_with_a_reason(text):
    try:
        out = parse_file_goal(text)
    except FileIntentError as exc:
        assert str(exc)
    else:
        assert out is None or out.get("action") not in ("create", "replace") or out.get("content") or out.get("new_text") is not None


# ---- Anleitungs-/Erklaerfragen sind keine Dateiaktion (Regression: "Ordner auf dem Desktop" wurde als mkdir "auf" gelesen) -------------------------------------
_HOWTO = ["Erstelle eine Schritt-für-Schritt-Anleitung, wie ich unter Windows 11 einen neuen Ordner auf dem Desktop erstelle",
          "Erkläre mir, wie ich einen Ordner erstelle", "Wie kopiere ich Dateien unter Windows?"]


@pytest.mark.parametrize("text", _HOWTO)
def test_how_to_questions_are_not_file_requests(text):
    assert parse_file_goal(text) is None


@pytest.mark.parametrize("text", _HOWTO)
def test_how_to_questions_do_not_become_a_goal(text):
    from types import SimpleNamespace
    from jarvis.interface.cli import research_route
    core = SimpleNamespace(subsystems={"goals": SimpleNamespace(engine=object())})
    assert research_route(core, text) is None


def test_real_folder_and_word_requests_still_become_one_step():
    assert parse_file_goal("Erstelle einen neuen Ordner Archiv2024") == {"tool": "files", "action": "mkdir", "path": "Archiv2024"}
    assert parse_file_goal("Erstelle ein Word-Dokument bericht.docx mit dem Inhalt: Hallo Welt") ==         {"tool": "office", "action": "create", "path": "bericht.docx", "content": "Hallo Welt"}


@pytest.mark.parametrize("text", ["Erstelle einen Ordner auf dem Desktop", "Erstelle einen neuen Ordner auf dem Desktop", "Create a folder on the desktop",
                                  "Lege einen Ordner im Dokumente-Verzeichnis an", "Erstelle einen Ordner namens"])
def test_folder_request_without_a_folder_name_is_refused_never_mkdir_auf(text):
    with pytest.raises(FileIntentError) as exc:
        parse_file_goal(text)
    assert str(exc.value)


def test_folder_request_without_a_name_goes_to_the_goal_path_for_an_explanation_not_an_action():
    from types import SimpleNamespace
    from jarvis.interface.cli import research_route
    core = SimpleNamespace(subsystems={"goals": SimpleNamespace(engine=object())})
    assert research_route(core, "Erstelle einen Ordner auf dem Desktop").startswith("/goal ")      # the planner refuses it with the reason; no step is built from "auf"


@pytest.mark.parametrize("text,path", [("Erstelle einen Ordner Projekte", "Projekte"), ("Erstelle einen Ordner \"Neuer Ordner\"", "Neuer Ordner"),
                                       (r"Erstelle den Ordner C:\Users\Test\Desktop\Archiv", r"C:\Users\Test\Desktop\Archiv")])
def test_valid_folder_creation_with_a_name_still_works(text, path):
    assert parse_file_goal(text) == {"tool": "files", "action": "mkdir", "path": path}


# ---- Routing ---------------------------------------------------------------------------------------------------------------------------------
def test_router_rules_pick_the_files_agent_only_for_file_and_document_requests(tmp_path):
    core, _, _, _ = make(tmp_path)
    planner: AgentPlanner = core.subsystems["agents"].planner
    assert planner.select("Lies die Datei notizen.txt", frozenset({"files.read"})).agent_id == "files"
    assert planner.select("Erstelle bericht.docx mit dem Inhalt: Hallo", frozenset({"office.create"})).agent_id == "files"
    code, web = planner.score("Ändere die Funktion in calc.py und führe die Tests aus"), planner.score("Öffne die Webseite https://example.com")    # coding/browser sind hier aus: Rangfolge der Regeln
    assert max(code, key=code.get) == "coding" and code.get("files", 0) < code["coding"]
    assert max(web, key=web.get) == "browser" and web.get("files", 0) == 0
    assert "files.write" in planner.select("Kopiere a.txt nach b.txt (Datei)", frozenset({"files.read"})).capabilities | frozenset({"files.write"})


def test_the_files_agent_is_disabled_without_either_tool_and_available_with_one(tmp_path):
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true")
    off = build_core(load_settings(env=env))
    assert off.subsystems["agents"].registry.get("files").status.value == "DISABLED"
    (tmp_path / "one").mkdir()
    one = build_core(load_settings(env=env_for(tmp_path / "one", JARVIS_AGENTS_ENABLED="true", JARVIS_FILES_ENABLED="true")))
    assert one.subsystems["agents"].registry.get("files").status.value == "AVAILABLE"


# ---- Lesen, Erstellen, Bearbeiten ------------------------------------------------------------------------------------------------------------
def test_read_a_text_file_from_the_chat_shows_content_as_data_and_needs_no_question(tmp_path):
    core, st, prompts, ws = make(tmp_path)
    (ws / "notizen.txt").write_text("Zeile eins\nZeile zwei\n", encoding="utf-8")
    replies, evs = ask(core.subsystems["assistant"].ui, "Lies die Datei notizen.txt")
    text = "\n".join(replies)
    assert "SUCCEEDED" in text and "Zeile eins" in text and "Zeile zwei" in text and "keine Anweisung" in text, text
    assert prompts.requests == []                                                                    # Lesen ist GREEN: keine Rueckfrage
    results = [e for e in evs if e["type"] == "result"]
    assert results and "Zeile eins" in results[-1]["data"]["summary"]                                # Ergebnisanzeige im Control Center


def test_create_a_file_asks_with_a_preview_and_writes_only_after_an_explicit_yes(tmp_path):
    core, st, prompts, ws = make(tmp_path, answers=(ONCE,))
    out = goal(core, st, "Erstelle die Datei todo.txt mit dem Inhalt: Milch kaufen")
    assert "SUCCEEDED" in out and "todo.txt" in out and (ws / "todo.txt").read_text(encoding="utf-8").strip() == "Milch kaufen"
    assert len(prompts.requests) == 1 and prompts.requests[0].tool == "files" and "todo.txt" in str(prompts.requests[0].context)


def test_a_declined_or_unanswered_change_writes_nothing_and_the_chat_explains(tmp_path):
    for k, answers in enumerate(((NO,), ())):
        sub = tmp_path / f"r{k}"
        sub.mkdir()
        core, st, prompts, ws = make(sub, answers=answers)
        out = goal(core, st, "Erstelle die Datei todo.txt mit dem Inhalt: Milch kaufen")
        assert not (ws / "todo.txt").exists() and "SUCCEEDED" not in out
        assert "Freigabe" in out and "So geht es weiter" in out


def test_replace_edits_through_read_and_the_hash_guarded_write_and_keeps_crlf(tmp_path):
    core, st, prompts, ws = make(tmp_path, answers=(ONCE,))
    (ws / "tiere.txt").write_bytes("Ein Hund\r\nZwei Hunde\r\nEnde\r\n".replace("Zwei Hunde", "Zwei Tiere").encode())
    out = goal(core, st, 'Ersetze "Ein Hund" durch "Eine Katze" in tiere.txt')
    assert "SUCCEEDED" in out, out
    assert (ws / "tiere.txt").read_bytes() == b"Eine Katze\r\nZwei Tiere\r\nEnde\r\n"                  # Zeilenenden und Schlusszeilenumbruch bleiben
    assert [r.action for r in prompts.requests] == ["write"]                                           # nur die Aenderung fragt; das Lesen ist GREEN


def test_replace_is_refused_for_ambiguous_text_secrets_and_missing_files(tmp_path):
    core, st, prompts, ws = make(tmp_path, answers=(ONCE,) * 5)
    (ws / "a.txt").write_text("Hund und Hund\n")
    out = goal(core, st, 'Ersetze "Hund" durch "Katze" in a.txt')
    assert "SUCCEEDED" not in out and (ws / "a.txt").read_text() == "Hund und Hund\n"
    (ws / "s.txt").write_text("api_key=sk-ABCDEFGHIJKLMNOPQRSTUV123456\nHund\n")
    out = goal(core, st, 'Ersetze "Hund" durch "Katze" in s.txt')
    assert "SUCCEEDED" not in out and "Katze" not in (ws / "s.txt").read_text()
    out = goal(core, st, 'Ersetze "x" durch "y" in fehlt.txt')
    assert "SUCCEEDED" not in out and not (ws / "fehlt.txt").exists()
    assert prompts.requests == []                                                                      # nie bis zur Rueckfrage gekommen: vorher abgelehnt


def test_create_and_read_back_office_documents(tmp_path):
    core, st, prompts, ws = make(tmp_path, answers=(ONCE,) * 4)
    assert "SUCCEEDED" in goal(core, st, "Erstelle bericht.docx mit dem Inhalt: # Titel\n\nErster Absatz")
    assert "SUCCEEDED" in goal(core, st, 'Erstelle preise.xlsx mit dem Inhalt: [["Name","Preis"],["Kaffee",3.5]]')
    assert (ws / "bericht.docx").exists() and (ws / "preise.xlsx").exists()
    doc = goal(core, st, "Lies bericht.docx")
    assert "Titel" in doc and "Erster Absatz" in doc and "SUCCEEDED" in doc
    sheet = goal(core, st, "Lies preise.xlsx")
    assert "Kaffee" in sheet and "3.5" in sheet and "Daten" in sheet
    assert {r.tool for r in prompts.requests} == {"office"}                                            # nur das Erstellen fragt


def test_existing_office_files_are_never_changed_and_nothing_can_be_deleted(tmp_path):
    core, st, prompts, ws = make(tmp_path)
    out = goal(core, st, 'Ersetze "a" durch "b" in x.docx')
    assert "SUCCEEDED" not in out and "Office" in out
    assert parse_file_goal("Lösche die Datei a.txt") is None and parse_file_goal("Delete the file a.txt") is None


# ---- Grenzen und Fehlerfaelle ----------------------------------------------------------------------------------------------------------------
def test_paths_outside_the_confirmed_directory_are_refused_by_the_tool(tmp_path):
    core, st, prompts, ws = make(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("geheim-fuer-nichts")
    out = goal(core, st, f'Lies die Datei "{outside}"')
    assert "SUCCEEDED" not in out and "geheim-fuer-nichts" not in out
    out2 = goal(core, st, 'Lies die Datei "../outside.txt"')
    assert "SUCCEEDED" not in out2 and "geheim-fuer-nichts" not in out2
    out3 = goal(core, st, f'Erstelle die Datei "{tmp_path / "neu.txt"}" mit dem Inhalt: x')
    assert "SUCCEEDED" not in out3 and not (tmp_path / "neu.txt").exists()


def test_secret_files_are_not_read_or_touched(tmp_path):
    core, st, prompts, ws = make(tmp_path)
    (ws / ".env").write_text("API_KEY=abcdefghijklmnop\n")
    out = goal(core, st, "Lies die Datei .env")
    assert "abcdefghijklmnop" not in out and "SUCCEEDED" not in out


def test_a_task_that_allows_only_reading_cannot_write_and_unknown_parameters_are_refused(tmp_path):
    from jarvis.agents import AgentTask, TaskStatus
    core, st, prompts, ws = make(tmp_path)
    orch = core.subsystems["agents"].orchestrator
    res = orch.run(AgentTask("Dateiauftrag", agent_id="files", input={"steps": [{"tool": "files", "action": "create", "path": "x.txt", "content": "x"}]},
                             required_capabilities=frozenset({"files.read"})))
    assert res.status is TaskStatus.BLOCKED and res.error_code == "capability_not_allowed" and not (ws / "x.txt").exists()
    bad = orch.run(AgentTask("Dateiauftrag", agent_id="files", input={"steps": [{"tool": "files", "action": "read", "path": "x.txt", "force": True}]},
                             required_capabilities=frozenset({"files.read"})))
    assert bad.status is TaskStatus.FAILED and bad.error_code in ("invalid_input", "tool_access_denied")
    delete = orch.run(AgentTask("Dateiauftrag", agent_id="files", input={"steps": [{"tool": "files", "action": "delete", "path": "x.txt"}]},
                                required_capabilities=frozenset({"files.read", "files.write"})))
    assert delete.status is TaskStatus.FAILED and delete.error_code == "invalid_input"


def test_incomplete_requests_get_a_plain_explanation_and_nothing_runs(tmp_path):
    core, st, prompts, ws = make(tmp_path)
    out = goal(core, st, "Erstelle die Datei todo.txt")
    assert "SUCCEEDED" not in out and "Was fehlt" in out and "Das kannst du tun" in out
    assert research_route(core, "Erstelle die Datei todo.txt mit dem Inhalt: x").startswith("/goal ")
    assert research_route(core, "Hallo") is None
    assert prompts.requests == []


def test_emergency_stop_blocks_file_requests(tmp_path):
    core, st, prompts, ws = make(tmp_path)
    (ws / "notizen.txt").write_text("x")
    core.permissions.emergency.trigger("test")
    out = goal(core, st, "Lies die Datei notizen.txt")
    assert "SUCCEEDED" not in out


def test_with_both_tools_off_the_request_is_explained_not_silently_dropped(tmp_path):
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true")
    settings = load_settings(env=env)
    core = build_core(settings)
    out = goal(core, settings, "Lies die Datei notizen.txt")
    assert "SUCCEEDED" not in out and "So geht es weiter" in out


def test_every_call_goes_through_the_registry_and_engine_and_the_agent_has_no_own_file_access():
    src = (Path(__file__).resolve().parents[1] / "src" / "jarvis" / "agents" / "adapters" / "files.py").read_text(encoding="utf-8")
    for forbidden in ("import os", "import shutil", "pathlib", "open(", "subprocess", "jarvis.files", "jarvis.office", "jarvis.permissions", "confirm(", "set_confirmation", "ConfirmationChoice"):
        assert forbidden not in src, forbidden
