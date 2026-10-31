"""Voice interfaces. Every concrete engine/device sits behind one of these."""
from __future__ import annotations

import io
import struct
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioClip:
    """Mono 16-bit little-endian PCM."""
    pcm: bytes
    sample_rate: int = 16000

    @property
    def duration(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate

    @property
    def is_empty(self) -> bool:
        return not self.pcm

    def to_wav(self) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(self.pcm)
        return buf.getvalue()

    @classmethod
    def from_wav(cls, data: bytes) -> "AudioClip":
        with wave.open(io.BytesIO(data), "rb") as w:
            return cls(w.readframes(w.getnframes()), w.getframerate())


def rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return (sum(x * x for x in samples) / n) ** 0.5


class AudioSource(ABC):
    """Microphone (or any audio producer)."""

    @abstractmethod
    def record(self) -> AudioClip | None:
        """Block until one utterance is captured. None = nothing heard (silence/timeout).
        Raise VoiceUnavailableError if the device cannot be used, EndOfInput when exhausted."""


class AudioPlayer(ABC):
    @abstractmethod
    def play(self, clip: AudioClip) -> None:
        """Play audio. Raise VoiceUnavailableError if no output is possible."""

    def stop(self) -> None:
        """Barge-in: cut off a running playback. Default: nothing to stop (never raises)."""


class HotwordDetector(ABC):
    """Local wake-word spotting on raw audio. Must not use the network; it only says yes/no, it never triggers an action."""

    @abstractmethod
    def detect(self, clip: AudioClip) -> bool:
        """True if the hotword is in the clip."""


class STTProvider(ABC):
    name: str = "base"

    @abstractmethod
    def transcribe(self, clip: AudioClip, language: str | None = None) -> str:
        """Return the recognised text ('' if nothing recognised). Raise STTError on failure."""


class TTSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def speak(self, text: str) -> None:
        """Speak the text aloud (blocking). Raise TTSError / VoiceUnavailableError on failure."""

    def stop(self) -> None:
        """Barge-in: cut off speech in progress. Default: nothing to stop."""


class Listener(ABC):
    """Anything that yields user utterances as text: microphone+STT, or the console."""

    @abstractmethod
    def listen(self) -> str | None:
        """Next utterance as text; None when nothing was heard. Raise EndOfInput when finished."""


class Speaker(ABC):
    @abstractmethod
    def say(self, text: str) -> None: ...

    def stop(self) -> None:
        """Barge-in: cut off speech in progress. Default: nothing to stop."""
