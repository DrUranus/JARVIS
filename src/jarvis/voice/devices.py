"""Real audio devices. Optional dependencies are imported lazily so that a missing
library or microphone raises VoiceUnavailableError instead of breaking JARVIS."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time

from jarvis.errors import VoiceUnavailableError
from jarvis.voice.base import AudioClip, AudioPlayer, AudioSource, rms

log = logging.getLogger("jarvis.voice")


class Endpointer:
    """Decides when an utterance is over: speech seen, then `silence_seconds` of quiet,
    or `max_seconds` reached. Pure logic, so it is testable without a microphone."""

    def __init__(self, threshold: float, silence_seconds: float, max_seconds: float,
                 initial_wait_seconds: float = 5.0) -> None:
        self.threshold, self.silence_seconds = threshold, silence_seconds
        self.max_seconds, self.initial_wait = max_seconds, initial_wait_seconds
        self.elapsed = self.quiet = 0.0
        self.heard_speech = False

    def feed(self, chunk_rms: float, chunk_seconds: float) -> bool:
        """Return True when recording should stop."""
        self.elapsed += chunk_seconds
        if chunk_rms >= self.threshold:
            self.heard_speech, self.quiet = True, 0.0
        else:
            self.quiet += chunk_seconds
        if self.heard_speech:
            return self.quiet >= self.silence_seconds or self.elapsed >= self.max_seconds
        return self.elapsed >= self.initial_wait  # nobody spoke: give up (-> None)


class SoundDeviceSource(AudioSource):
    """Microphone via the optional `sounddevice` package (pip install 'jarvis-ai[voice]')."""

    def __init__(self, sample_rate: int = 16000, threshold: float = 500, silence_seconds: float = 1.0,
                 max_seconds: float = 15.0, chunk_seconds: float = 0.1) -> None:
        self._rate, self._threshold = sample_rate, threshold
        self._silence, self._max, self._chunk = silence_seconds, max_seconds, chunk_seconds
        self._sd = self._import()

    @staticmethod
    def _import():
        try:
            import sounddevice  # type: ignore[import-not-found]
        except ImportError as exc:
            raise VoiceUnavailableError(
                "microphone backend missing: pip install 'jarvis-ai[voice]' (needs PortAudio)") from exc
        except OSError as exc:  # PortAudio shared library not found
            raise VoiceUnavailableError(f"PortAudio library unavailable: {exc}") from exc
        return sounddevice

    def record(self) -> AudioClip | None:
        frames = int(self._rate * self._chunk)
        ep = Endpointer(self._threshold, self._silence, self._max)
        chunks: list[bytes] = []
        try:
            with self._sd.RawInputStream(samplerate=self._rate, channels=1, dtype="int16") as stream:
                while True:
                    data, _overflow = stream.read(frames)
                    raw = bytes(data)
                    stop = ep.feed(rms(raw), self._chunk)
                    if ep.heard_speech:
                        chunks.append(raw)
                    if stop:
                        break
        except Exception as exc:  # PortAudioError etc.: no device, busy, permission denied
            raise VoiceUnavailableError(f"cannot record from microphone: {exc}") from exc
        return AudioClip(b"".join(chunks), self._rate) if ep.heard_speech else None


_PLAYERS = (("afplay", []), ("paplay", []), ("aplay", ["-q"]), ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]))


class SystemPlayer(AudioPlayer):
    """Plays WAV through whichever common system player exists (afplay, paplay, aplay, ffplay)."""

    def __init__(self) -> None:
        self._cmd = next(([path, *args] for name, args in _PLAYERS if (path := shutil.which(name))), None)

    def play(self, clip: AudioClip) -> None:
        if self._cmd is None:
            raise VoiceUnavailableError("no audio player found (afplay/paplay/aplay/ffplay)")
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(clip.to_wav())
            subprocess.run([*self._cmd, path], check=True, capture_output=True, timeout=120)
        except (subprocess.SubprocessError, OSError) as exc:
            raise VoiceUnavailableError(f"audio playback failed: {exc}") from exc
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class NullPlayer(AudioPlayer):
    def play(self, clip: AudioClip) -> None:
        log.debug("NullPlayer dropped %.2fs of audio", clip.duration)
