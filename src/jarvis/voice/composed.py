"""Compose low-level parts into Listener / Speaker."""
from __future__ import annotations

import logging

from jarvis.voice.base import AudioSource, Listener, Speaker, STTProvider, TTSProvider

log = logging.getLogger("jarvis.voice")


class SpeechListener(Listener):
    """AudioSource (microphone) + STTProvider -> text."""

    def __init__(self, source: AudioSource, stt: STTProvider, language: str | None = None) -> None:
        self._source, self._stt, self._language = source, stt, language

    def listen(self) -> str | None:
        clip = self._source.record()
        if clip is None or clip.is_empty:
            return None
        text = self._stt.transcribe(clip, self._language).strip()
        log.debug("transcribed: %r", text)
        return text or None


class TTSSpeaker(Speaker):
    def __init__(self, tts: TTSProvider) -> None:
        self._tts = tts

    def say(self, text: str) -> None:
        self._tts.speak(text)
