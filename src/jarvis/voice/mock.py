"""Deterministic fakes for tests and hardware-free development."""
from __future__ import annotations

from typing import Callable, Iterable

from jarvis.errors import EndOfInput
from jarvis.voice.base import AudioClip, AudioPlayer, AudioSource, HotwordDetector, STTProvider, TTSProvider


class MockSTT(STTProvider):
    """Returns scripted transcripts in order; records the clips it received."""
    name = "mock"

    def __init__(self, transcripts: Iterable[str] = (), result: str | Callable[[AudioClip], str] | None = None) -> None:
        self._queue = list(transcripts)
        self._result = result
        self.clips: list[AudioClip] = []
        self.languages: list[str | None] = []

    def transcribe(self, clip: AudioClip, language: str | None = None) -> str:
        self.clips.append(clip)
        self.languages.append(language)
        if self._queue:
            return self._queue.pop(0)
        if callable(self._result):
            return self._result(clip)
        return self._result or ""


class MockTTS(TTSProvider):
    name = "mock"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)


class MockAudioSource(AudioSource):
    """Yields `count` dummy clips, then raises EndOfInput."""

    def __init__(self, count: int = 1, clip: AudioClip | None = None) -> None:
        self._left = count
        self._clip = clip or AudioClip(b"\x01\x00" * 160)

    def record(self) -> AudioClip | None:
        if self._left <= 0:
            raise EndOfInput("mock audio exhausted")
        self._left -= 1
        return self._clip


class MockAudioPlayer(AudioPlayer):
    def __init__(self) -> None:
        self.played: list[AudioClip] = []
        self.stops = 0

    def play(self, clip: AudioClip) -> None:
        self.played.append(clip)

    def stop(self) -> None:
        self.stops += 1


class MockHotwordDetector(HotwordDetector):
    """Scripted answers per clip (False once the script is exhausted)."""

    def __init__(self, answers: Iterable[bool] = ()) -> None:
        self._answers = list(answers)
        self.seen = 0

    def detect(self, clip: AudioClip) -> bool:
        self.seen += 1
        return self._answers.pop(0) if self._answers else False
