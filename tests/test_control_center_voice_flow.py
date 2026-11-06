"""Sprachmodus im Control Center Ende-zu-Ende (echtes Chromium, echte Engine, kontrollierte Testdaten statt Hardware).

STT/TTS: ein geskripteter Listener (ersetzt Mikrofon + Spracherkennung) und ein aufzeichnender Speaker (ersetzt Lautsprecher + TTS) laufen in der ECHTEN `VoiceSession`
mit dem echten Kern (Mock-LLM); der Pfad Knopf -> Vertragsbefehl -> Adapter -> GuiController -> VoiceSession -> Ereignisse -> Anzeige ist der produktive. Fehlendes Mikrofon:
die echte Fabrik `build_voice_session` ohne Audio-Backend. NICHT getestet (Hardware): echte Mikrofon-/Lautsprecherausgabe. Ohne Playwright/Chromium uebersprungen = nicht bestanden."""
from __future__ import annotations

import time

import pytest

from test_control_center_e2e_browser import Gui, browser, until  # noqa: F401  (browser: Fixture)
from test_control_center_binding import real_env

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.interface.gui_model import GuiController
from jarvis.interface.ui_events import ControllerUiBackend
from jarvis.permissions import ConfirmationChoice
from jarvis.voice.base import Listener, Speaker
from jarvis.voice.session import VoiceSession


class ScriptedListener(Listener):
    """Liefert die Testsaetze nacheinander, danach 'nichts gehoert' (die Sitzung laeuft weiter, bis der Mensch beendet)."""

    def __init__(self, lines):
        self.lines = list(lines)

    def listen(self):
        if self.lines:
            time.sleep(0.4)
            return self.lines.pop(0)
        time.sleep(0.05)
        return None


class RecordingSpeaker(Speaker):
    def __init__(self):
        self.said: list[str] = []

    def say(self, text: str) -> None:
        time.sleep(0.5)                                        # ein Sprechen dauert: der Zustand "spricht" ist sichtbar
        self.said.append(text)


class Rig:
    def __init__(self, browser, tmp_path, lines=("Hallo JARVIS",), real_factory=False, settings_env=None):
        env = {"JARVIS_VOICE_STT_PROVIDER": "mock", "JARVIS_VOICE_TTS_PROVIDER": "mock"}      # "console" waere fuer die GUI abgelehnt; die Engines selbst ersetzt die Fabrik
        env.update(settings_env or {})
        self.settings = load_settings(env=real_env(tmp_path, **env))
        self.core = build_core(self.settings)
        self.listener, self.speaker = ScriptedListener(lines), RecordingSpeaker()
        factory = None if real_factory else (lambda st, co, display, input_fn, on_state: VoiceSession(
            co, self.listener, self.speaker, display=display, on_state=on_state, wake_word="jarvis", require_wake_word=False))
        self.ctl = GuiController(self.core, self.settings, voice_factory=factory)
        self.gui = Gui(browser, ControllerUiBackend(self.ctl, choice_enum=ConfirmationChoice))

    def close(self):
        self.ctl.stop_voice()
        self.gui.close()


def chat(gui):
    return gui.page.locator("#chat").inner_text()


def test_voice_mode_start_utterance_spoken_answer_and_stop(browser, tmp_path):
    r = Rig(browser, tmp_path)
    p = r.gui.page
    try:
        until(p, "document.getElementById('voice-start').disabled === false")
        p.click("#voice-start")
        until(p, "document.getElementById('voice-mic').textContent === 'Mikrofon: an'")          # Live-Mikrofonstatus
        assert p.locator("#voice-start").is_disabled() and p.locator("#voice-stop").is_enabled()
        seen = set()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not {"listening", "speaking"} <= seen:             # Zustandswechsel kommen vom Backend, nicht von der Seite
            seen.add(p.evaluate("document.body.dataset.state"))
            time.sleep(0.05)
        assert {"listening", "speaking"} <= seen, seen
        until(p, "document.getElementById('chat').textContent.includes('Hallo JARVIS')", 20.0)    # erkannter Satz erscheint im Chat
        end = time.monotonic() + 15
        while not r.speaker.said and time.monotonic() < end:
            time.sleep(0.05)
        assert r.speaker.said                                                                     # TTS-Pfad: die Antwort wurde gesprochen
        r.gui.shot("voice_running")
        p.click("#voice-stop")
        until(p, "document.getElementById('voice-mic').textContent === 'Mikrofon: aus'", 20.0)
        assert p.locator("#voice-start").is_enabled() and p.locator("#voice-stop").is_disabled()
        assert "Mikrofon ist aus" in chat(r.gui)
    finally:
        r.close()


def test_missing_microphone_is_reported_and_text_stays_usable(browser, tmp_path):
    try:
        import sounddevice  # noqa: F401
        pytest.skip("sounddevice ist installiert: 'kein Mikrofon' ist hier nicht herstellbar (uebersprungen, nicht bestanden)")
    except ImportError:
        pass
    r = Rig(browser, tmp_path, real_factory=True, settings_env={"JARVIS_VOICE_STT_PROVIDER": "mock", "JARVIS_VOICE_TTS_PROVIDER": "mock", "JARVIS_VOICE_AUDIO_INPUT": "sounddevice"})
    p = r.gui.page
    try:
        p.click("#voice-start")
        until(p, "document.getElementById('chat').textContent.includes('voice_unavailable')", 15.0)
        assert p.locator("#voice-mic").inner_text() != "Mikrofon: an" and p.locator("#voice-start").is_enabled()
        p.fill("#input", "Text geht weiter")
        p.press("#input", "Enter")
        until(p, "document.getElementById('chat').textContent.includes('Text geht weiter')")
        r.gui.shot("voice_unavailable")
    finally:
        r.close()


def test_console_stt_provider_is_refused_for_the_gui(browser, tmp_path):
    r = Rig(browser, tmp_path, real_factory=True, settings_env={"JARVIS_VOICE_STT_PROVIDER": "console"})
    try:
        r.gui.page.click("#voice-start")
        until(r.gui.page, "document.getElementById('chat').textContent.includes('voice_unavailable')", 15.0)
        assert "console" in chat(r.gui).lower() and r.gui.page.locator("#voice-start").is_enabled()
    finally:
        r.close()


def test_emergency_stop_ends_the_voice_mode_and_blocks_a_restart(browser, tmp_path):
    r = Rig(browser, tmp_path, lines=())
    p = r.gui.page
    try:
        p.click("#voice-start")
        until(p, "document.getElementById('voice-mic').textContent === 'Mikrofon: an'", 15.0)
        p.click("#emergency")
        r.gui.state("emergency")
        until(p, "document.getElementById('voice-mic').textContent !== 'Mikrofon: an'", 15.0)       # der Notaus beendet den Sprachmodus
        assert r.core.permissions.emergency.engaged is True and p.locator("#voice-start").is_disabled()
        r.gui.shot("voice_emergency")
    finally:
        r.close()
