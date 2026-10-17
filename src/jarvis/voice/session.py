"""VoiceSession: Listener -> JarvisCore.handle(text) -> Speaker.

The session depends only on a `TextHandler` (anything with handle(text) -> Response), so it
never touches core internals and works unchanged with future Memory/Agent-backed cores.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Callable, Protocol

from jarvis.core.core import Response, ResponseKind
from jarvis.errors import EndOfInput, STTError, TTSError, VoiceError, VoiceUnavailableError
from jarvis.voice.base import Listener, Speaker

log = logging.getLogger("jarvis.voice")

EXIT_PHRASES = frozenset({"exit", "quit", "stop", "stopp", "beenden", "beende", "tschüss", "tschuess", "goodbye"})
MAX_CONSECUTIVE_FAILURES = 3

# State names reported through `on_state(state, detail)`. They are reported only when the session really is in that state (an interface such as the GUI shows them).
VOICE_STATES = ("listening", "processing", "speaking", "idle", "error")


class TextHandler(Protocol):
    def handle(self, user_input: str) -> Response: ...


def speech_text(response: Response) -> str:
    """What to say aloud. Long structured output (plans) is summarised, the full text stays on screen."""
    if response.kind is ResponseKind.PLAN and response.task is not None:
        n = len(response.task.subtasks)
        return f"Ich habe einen Plan mit {n} Schritten erstellt. Er steht auf dem Bildschirm."
    return response.text


def _norm(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


class VoiceSession:
    def __init__(self, handler: TextHandler, listener: Listener, speaker: Speaker, *,
                 wake_word: str = "jarvis", require_wake_word: bool = False, speak_responses: bool = True,
                 display: Callable[[str], None] = print, on_state: Callable[[str, str], None] | None = None) -> None:
        self._handler, self._listener, self._speaker = handler, listener, speaker
        self._on_state = on_state
        self._wake = wake_word.strip().lower()
        self._require_wake = require_wake_word
        self._speak_responses = speak_responses
        self._display = display
        self._awake = False  # True after a bare wake word: the next utterance needs no wake word
        self._speaker_ok = True
        self._wake_re = re.compile(rf"^\W*{re.escape(self._wake)}\b[\s,.:;!?\-]*", re.IGNORECASE)

    def _state(self, state: str, detail: str = "") -> None:
        if self._on_state is None:
            return
        try:
            self._on_state(state, detail)
        except Exception:                                   # a faulty observer must never break the conversation
            log.exception("voice state observer failed")

    # -- output -----------------------------------------------------------------------------
    def _say(self, text: str) -> None:
        if not (self._speak_responses and self._speaker_ok and text):
            return
        self._state("speaking")
        try:
            self._speaker.say(text)
        except VoiceUnavailableError as exc:
            self._speaker_ok = False  # stop retrying a dead device; text output continues
            self._display(f"(Sprachausgabe nicht verfügbar: {exc} – nur Text)")
        except TTSError as exc:
            log.warning("TTS failed: %s", exc)
            self._display(f"(Sprachausgabe fehlgeschlagen: {exc})")
            self._state("error", f"Sprachausgabe fehlgeschlagen: {exc}")
        finally:
            self._state("idle")

    def _reply(self, text: str, spoken: str | None = None) -> None:
        self._display(f"JARVIS: {text}")
        self._say(spoken if spoken is not None else text)

    # -- one utterance ------------------------------------------------------------------------
    def process(self, utterance: str) -> bool:
        """Handle one transcript. Returns False if the session should end."""
        text = utterance.strip()
        if not text:
            return True
        m = self._wake_re.match(text)
        if m:
            text = text[m.end():].strip()
            if not text:  # bare wake word: "JARVIS." -> "Ja?"
                self._awake = True
                self._reply("Ja?")
                return True
        elif self._require_wake and not self._awake:
            log.debug("ignored (no wake word): %r", text)
            return True
        self._awake = False
        self._display(f"Du: {text}")
        if _norm(text) in EXIT_PHRASES:
            self._reply("Sprachmodus beendet.")
            return False
        self._state("processing")
        try:
            response = self._handler.handle(text)
        finally:
            self._state("idle")
        self._reply(response.text, speech_text(response))
        return True

    # -- main loop ------------------------------------------------------------------------------
    def run(self, max_turns: int | None = None, stop: threading.Event | None = None) -> int:
        """Run until an exit phrase, end of input, repeated device failures or `stop` is set. Returns utterances processed.
        `stop` is checked between utterances: a recording that is already running is finished first (at most voice.max_record_seconds)."""
        turns = failures = 0
        try:
            while max_turns is None or turns < max_turns:
                if stop is not None and stop.is_set():
                    break
                self._state("listening")
                try:
                    utterance = self._listener.listen()
                except EndOfInput:
                    break
                except STTError as exc:
                    failures += 1
                    log.warning("STT failed: %s", exc)
                    self._display(f"(Spracherkennung fehlgeschlagen: {exc})")
                    self._state("error", f"Spracherkennung fehlgeschlagen: {exc}")
                    if failures >= MAX_CONSECUTIVE_FAILURES:
                        self._display("Zu viele Fehler in Folge – Sprachmodus wird beendet.")
                        break
                    continue
                except VoiceUnavailableError as exc:
                    self._display(f"Audio nicht verfügbar: {exc}")
                    self._state("error", f"Audio nicht verfügbar: {exc}")
                    break
                except VoiceError as exc:
                    self._display(f"Sprachfehler: {exc}")
                    self._state("error", f"Sprachfehler: {exc}")
                    break
                failures = 0
                if stop is not None and stop.is_set():
                    break                                       # the user ended the voice mode while recording: do not act on this utterance
                if utterance is None or not utterance.strip():
                    continue
                turns += 1
                if not self.process(utterance):
                    break
        finally:
            self._state("idle")
        return turns
