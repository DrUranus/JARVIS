"""Diktierte Dateinamen (F-V-2, Windows-Livetest 2026-11-20): die deutsche Spracherkennung liefert „Dashboard, Strich, Test, Punkt, TXT“ statt `dashboard-test.txt`.
Nur eindeutig erkennbare Namen werden zusammengesetzt; bei Mehrdeutigkeit wird nachgefragt. Weiter derselbe Weg wie der Textchat (Goal Engine, Freigabedialog).
Echter Kern (Mock-LLM), echte Dateien in tmp_path, keine Netz- oder Mikrofonzugriffe."""
from __future__ import annotations

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.interface.cli import research_route, run_command
from jarvis.interface.gui_model import VoiceTextHandler
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.confirmation import ScriptedConfirmation
from jarvis.voice.postprocess import normalize_dictated_filename
from test_computer_integration import env_for

SPOKEN = "erstelle die Datei, Dashboard, Strich, Test, Punkt, TXT, mit dem Inhalt, JARVIS, Test, erfolgreich."
ONCE, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.DENY
ENV = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_FILES_ENABLED="true", JARVIS_JOURNAL_ENABLED="true")


# ---- Normalisierung -------------------------------------------------------------------------------------------------------------------------
def test_the_exact_owner_sentence_becomes_one_clear_file_name():
    text, ambiguous = normalize_dictated_filename(SPOKEN)
    assert not ambiguous
    assert "dashboard-test.txt" in text and "Strich" not in text and "Punkt" not in text
    assert "mit dem Inhalt:" in text                       # Diktier-Komma nach „Inhalt“ ist nur ein Trenner


@pytest.mark.parametrize("spoken,name", [
    ("Erstelle die Datei notizen Punkt txt mit dem Inhalt: x", "notizen.txt"),
    ("erstelle die Datei Mein Unterstrich Plan Punkt MD mit dem Inhalt x", "mein_plan.md"),
    ("lege die Datei Bericht Bindestrich Eins Punkt csv an mit dem Inhalt a", "bericht-eins.csv"),
    ("erstelle die Datei dashboard-test.txt mit dem Inhalt: x", "dashboard-test.txt"),        # schon sauber: unveraendert
])
def test_clear_names_are_assembled_and_lowercased(spoken, name):
    text, ambiguous = normalize_dictated_filename(spoken)
    assert not ambiguous and name in text


@pytest.mark.parametrize("spoken", [
    "erstelle die Datei Dashboard Test Punkt TXT mit dem Inhalt x",           # zwei Woerter ohne Verbinder: Leerzeichen, Strich oder zusammen?
    "erstelle die Datei Strich Test Punkt TXT mit dem Inhalt x",              # Verbinder am Anfang
    "erstelle die Datei Dashboard Strich Strich Test Punkt TXT mit dem Inhalt x",
])
def test_ambiguous_names_are_flagged_not_guessed(spoken):
    assert normalize_dictated_filename(spoken)[1] is True


def test_sentences_without_a_dictated_name_are_unchanged():
    t = "Wie spaet ist es, Punkt. Danke"
    assert normalize_dictated_filename(t) == (t, False)


# ---- Laufzeit: gleicher Weg wie der Textchat, Freigabe vor der Ausfuehrung ---------------------------------------------------------------------
def make(tmp_path, answers):
    settings = load_settings(env=env_for(tmp_path, **ENV, JARVIS_JOURNAL_PATH=str(tmp_path / "j.db")))
    core = build_core(settings)
    prompts = ScriptedConfirmation(answers)
    core.permissions.set_confirmation_provider(prompts, source="test")
    handler = VoiceTextHandler(core, lambda t: research_route(core, t), lambda line: run_command(core, line, settings, lambda _t: None, lambda _p: ""))
    return core, handler, prompts, tmp_path / "ws"


def test_the_spoken_sentence_asks_first_and_creates_the_file_only_after_allow_once(tmp_path):
    core, handler, prompts, ws = make(tmp_path, [ONCE])
    reply = handler.handle(SPOKEN)
    assert len(prompts.requests) == 1 and "dashboard-test.txt" in str(prompts.requests[0].resource)      # die Engine hat gefragt, mit dem normalisierten Namen
    assert (ws / "dashboard-test.txt").exists() and "Plan" not in reply.text.split(":")[0]


def test_declining_the_spoken_request_creates_nothing(tmp_path):
    core, handler, prompts, ws = make(tmp_path, [NO])
    handler.handle(SPOKEN)
    assert len(prompts.requests) == 1 and not (ws / "dashboard-test.txt").exists()
    assert not list(ws.glob("*"))


def test_an_ambiguous_spoken_name_asks_back_and_runs_nothing(tmp_path):
    core, handler, prompts, ws = make(tmp_path, [ONCE])
    reply = handler.handle("erstelle die Datei Dashboard Test Punkt TXT mit dem Inhalt x")
    assert prompts.requests == [] and not list(ws.glob("*")) and "Dateiname" in reply.text
