"""Folgeregressionen zu den Datei-Intents (Produktivstart): Namensformeln, fehlende Namen, nicht geratene Orte, Fragen starten kein Ziel.
Alles ohne Dateisystemzugriff (reine Textanalyse) - ausser den E2E-Tests in test_agents_files_e2e.py (nur pytest-tmp_path)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.goals.files_intent import FileIntentError, parse_file_goal
from jarvis.interface.cli import research_route

CORE = SimpleNamespace(subsystems={"goals": SimpleNamespace(engine=object())})
FULL = r"C:\Users\Test\Desktop\Projekte"


@pytest.mark.parametrize("text,path", [("Erstelle einen Ordner namens Projekte", "Projekte"), ("Erstelle einen Ordner mit dem Namen Projekte", "Projekte"),
                                       ("Create a folder called Reports", "Reports"), ("Make a folder named Reports", "Reports")])
def test_folder_with_a_naming_phrase_uses_the_name(text, path):
    assert parse_file_goal(text) == {"tool": "files", "action": "mkdir", "path": path}


@pytest.mark.parametrize("text", ["Erstelle einen Ordner", "Erstelle einen neuen Ordner.", "Create a folder", "Lege einen Ordner an", "Erstelle einen Ordner in C:\\Temp",
                                  "Erstelle einen Ordner auf dem Desktop"])
def test_folder_request_without_any_name_asks_for_one(text):
    with pytest.raises(FileIntentError, match="Ordnername"):
        parse_file_goal(text)


@pytest.mark.parametrize("text", ["Erstelle einen Ordner Projekte auf dem Desktop", "Create a folder Reports on the desktop"])
def test_a_named_place_instead_of_a_path_is_never_guessed(text):
    with pytest.raises(FileIntentError, match="vollständigen Pfad"):
        parse_file_goal(text)


def test_a_create_request_with_a_place_between_name_and_content_is_never_an_action():
    assert parse_file_goal("Erstelle die Datei a.txt auf dem Desktop mit dem Inhalt: x") is None


def test_a_full_path_in_quotes_is_accepted_even_with_a_place_word():
    assert parse_file_goal(f'Erstelle den Ordner "{FULL}" auf dem Desktop') == {"tool": "files", "action": "mkdir", "path": FULL}


@pytest.mark.parametrize("text", ["Wie öffne ich notizen.txt?", "Wie kann ich a.txt nach b.txt kopieren?", "How do I read notes.txt?"])
def test_more_how_to_questions_are_no_file_requests(text):
    assert parse_file_goal(text) is None


@pytest.mark.parametrize("text", ["Recherchierst du für mich?", "Recherche-Methoden erklärt", "Wie erstelle ich einen Ordner?", "Hallo JARVIS", "Was ist ein Ordner?"])
def test_questions_and_chat_do_not_start_a_goal(text):
    assert research_route(CORE, text) is None


def test_imperative_research_and_clear_file_requests_still_start_a_goal():
    assert research_route(CORE, "Recherchiere die Preise für Laptops") == "/goal Recherchiere die Preise für Laptops"
    assert research_route(CORE, "Lies die Datei notizen.txt").startswith("/goal ")


@pytest.mark.parametrize("text", ["Erstelle ein Word-Dokument namens bericht.docx", "Erstelle eine Datei notizen.txt", "Create the sheet preise.xlsx"])
def test_creating_a_named_document_without_content_asks_for_the_content(text):
    with pytest.raises(FileIntentError, match="Inhalt"):
        parse_file_goal(text)


def test_a_folder_and_a_file_in_one_request_are_refused_not_half_done():
    with pytest.raises(FileIntentError, match="mehrere Dateiaktionen"):
        parse_file_goal("Erstelle einen Ordner Projekte und lege darin die Datei a.txt mit dem Inhalt: x an")


def test_a_word_document_with_explicit_content_is_still_one_office_step():
    assert parse_file_goal("Erstelle ein Word-Dokument bericht.docx mit dem Inhalt: Hallo Welt") == \
        {"tool": "office", "action": "create", "path": "bericht.docx", "content": "Hallo Welt"}


# ---- S7-Abnahmefehler: fehlender Arbeitsordner und verlorener Zielordner ("unter C:\...") ------------------------------------------------
@pytest.mark.parametrize("text", ["Erstelle den Ordner TestAbnahme", r"Erstelle einen neuen Ordner namens TestAbnahme unter C:\JARVIS-Test\V2"])
def test_s7_folder_requests_are_recognised_as_creating_a_new_folder(text):
    step = parse_file_goal(text)
    assert step["action"] == "mkdir" and step["path"].endswith("TestAbnahme")


def test_a_named_parent_folder_is_part_of_the_path_never_silently_dropped():
    assert parse_file_goal(r"Erstelle einen neuen Ordner namens TestAbnahme unter C:\JARVIS-Test\V2") == \
        {"tool": "files", "action": "mkdir", "path": r"C:\JARVIS-Test\V2\TestAbnahme"}
    assert parse_file_goal(r'Create a folder Reports in "C:\Users\Test\Work"') == {"tool": "files", "action": "mkdir", "path": r"C:\Users\Test\Work\Reports"}


def test_a_missing_working_directory_is_named_instead_of_a_misleading_missing_parent(tmp_path):
    import os
    from jarvis.config import FilesSettings
    from jarvis.files import FilesController, FilesError
    from jarvis.files.factory import baseline_rules
    from jarvis.permissions import Policy
    from secutil import make_engine
    engine, _sink, ws = make_engine(tmp_path)
    root = os.path.join(os.path.realpath(ws), "arbeitsordner-fehlt")                      # liegt im erlaubten Bereich, existiert aber nicht
    controller = FilesController(engine.guard, FilesSettings(enabled=True), roots=(root,))
    with pytest.raises(FilesError) as exc:
        controller.plan("mkdir", path="TestAbnahme")
    assert exc.value.code == "root_missing" and "Arbeitsordner" in str(exc.value)
