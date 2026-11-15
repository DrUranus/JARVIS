"""Compose low-level parts into Listener / Speaker."""
from __future__ import annotations

import logging

from jarvis.voice.base import AudioSource, Listener, Speaker, STTProvider, TTSProvider
from jarvis.voice.postprocess import normalize_transcript

log = logging.getLogger("jarvis.voice")


class SpeechListener(Listener):
    """AudioSource (microphone) + STTProvider -> text."""

    def __init__(self, source: AudioSource, stt: STTProvider, language: str | None = None) -> None:
        self._source, self._stt, self._language = source, stt, language
        self.last_original: str | None = None            # Originaltranskript der letzten Erkennung (Diagnose; kein Audio)

    def listen(self) -> str | None:
        clip = self._source.record()
        if clip is None or clip.is_empty:
            return None
        original = self._stt.transcribe(clip, self._language).strip()
        self.last_original = original
        text = normalize_transcript(original)             # nur bekannte Fehlhoerungen der Eigennamen (JARVIS/NEXUS); sonst unveraendert
        log.debug("transcribed: %r (original %r)", text, original)
        return text or None


class TTSSpeaker(Speaker):
    def __init__(self, tts: TTSProvider) -> None:
        self._tts = tts

    def say(self, text: str) -> None:
        self._tts.speak(text)

    def stop(self) -> None:
        self._tts.stop()

    @property
    def speaking(self) -> bool:
        return bool(getattr(self._tts, "speaking", False))
