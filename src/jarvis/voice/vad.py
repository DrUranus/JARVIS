"""Sprachaktivitaetserkennung (VAD) fuer das Aufnahme-Ende: Eine Aufnahme endet nach einer Sprechpause, nie spaeter als `max_seconds`.

Regeln (docs/integrations/stt-local.md, Schritt `stt-vad-endpointing`):
- Reine Logik ohne Hardware: `record_utterance` bekommt eine Lesefunktion, so laeuft es mit synthetischem Audio.
- Optionale Bibliotheken (faster-whisper mit mitgeliefertem Silero-Modell, numpy) werden erst in `load_silero_detector` importiert (lazy).
  Fehlen sie, kommt eine klare VoiceUnavailableError-Meldung statt eines Absturzes.
- Kein Netzwerk. Dieses Modul entscheidet nur, wann eine Aufnahme endet; es erkennt kein Schluesselwort und gibt nichts aus.
- `guard` ist die Naht fuer Notaus und Sitzungsbudget: liefert er einen Grund, bricht die Aufnahme ab (kein Audio wird weitergegeben).
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable, Protocol

from jarvis.errors import VoiceError, VoiceUnavailableError
from jarvis.voice.base import AudioClip, rms

SILERO_RATE = 16000
EPS = 1e-9                                    # Gleitkomma-Summen von Chunk-Dauern (10 x 0,1 s < 1,0 s)


class SpeechDetector(Protocol):
    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        """True, wenn dieser Ausschnitt (16-bit-PCM, mono) Sprache enthaelt."""


class EnergyDetector:
    """Pegelbasiert (RMS ueber der Schwelle), wie der bisherige Endpointer; bruchsicher und ohne Zusatzpaket."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        return rms(pcm) >= self.threshold


class _SileroDetector:
    def __init__(self, get_speech_timestamps: Callable[..., Any], options: Any, np: Any) -> None:
        self._timestamps, self._options, self._np = get_speech_timestamps, options, np

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        if sample_rate != SILERO_RATE:
            raise VoiceError(f"Silero-VAD braucht {SILERO_RATE} Hz, bekam {sample_rate} Hz (voice.sample_rate = 16000 setzen).")
        audio = self._np.frombuffer(pcm, dtype="<i2").astype(self._np.float32) / 32768.0
        return bool(self._timestamps(audio, vad_options=self._options, sampling_rate=sample_rate))


def load_silero_detector(numpy_module: Any = None) -> SpeechDetector:
    """Silero-VAD aus dem Paket faster-whisper (Extra 'stt-local'); das Modell liegt im Paket, es gibt keinen Download."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps  # type: ignore[import-not-found]
        np = numpy_module if numpy_module is not None else __import__("numpy")
    except ImportError as exc:
        raise VoiceUnavailableError(
            "Silero-VAD braucht das Extra 'stt-local': pip install -e \".[stt-local]\" "
            f"(faster-whisper/numpy nicht importierbar: {exc})") from exc
    # Das Fenster ist ein einzelner Aufnahme-Chunk: kurze Mindestdauer, die Mindestsprechzeit prueft record_utterance
    return _SileroDetector(get_speech_timestamps, VadOptions(min_speech_duration_ms=30, min_silence_duration_ms=30), np)


def record_utterance(read_chunk: Callable[[], bytes], detector: SpeechDetector, *, sample_rate: int, chunk_seconds: float,
                     silence_seconds: float, max_seconds: float, initial_wait_seconds: float = 5.0,
                     min_speech_seconds: float = 0.2, preroll_seconds: float = 0.3,
                     guard: Callable[[], str | None] | None = None) -> AudioClip | None:
    """Liest Chunks, bis nach Sprache `silence_seconds` Stille kamen oder `max_seconds` erreicht sind. None = nichts gesprochen.

    Sprache zaehlt erst nach `min_speech_seconds` am Stueck (Klicks sind keine Sprache); `preroll_seconds` vor dem Sprechbeginn bleiben erhalten.
    Die Aufnahme ist hoechstens `max_seconds` lang (auch ohne Sprache wird nie laenger gewartet)."""
    wait_limit = min(initial_wait_seconds, max_seconds)
    keep = max(0, round(preroll_seconds / chunk_seconds))
    pre: deque[bytes] = deque(maxlen=keep) if keep else deque(maxlen=0)
    pending: list[bytes] = []                      # Sprachchunks, die noch die Mindestdauer erreichen muessen
    clip: list[bytes] = []
    elapsed = quiet = pending_seconds = 0.0
    speaking = False
    while True:
        if guard is not None:
            reason = guard()
            if reason:
                raise VoiceUnavailableError(f"Aufnahme gestoppt: {reason}")
        chunk = read_chunk()
        elapsed += chunk_seconds
        voiced = detector.is_speech(chunk, sample_rate)
        if speaking:
            clip.append(chunk)
            quiet = 0.0 if voiced else quiet + chunk_seconds
            if quiet + EPS >= silence_seconds or elapsed + EPS >= max_seconds:
                break
            continue
        if voiced:
            pending.append(chunk)
            pending_seconds += chunk_seconds
            if pending_seconds + EPS >= min_speech_seconds:
                speaking, quiet = True, 0.0
                clip = [*pre, *pending]
                pending = []
                if elapsed + EPS >= max_seconds:
                    break
                continue
        else:
            if pending:                            # zu kurz: war ein Klick
                pre.extend(pending)
                pending, pending_seconds = [], 0.0
            pre.append(chunk)
        if elapsed + EPS >= wait_limit:
            return None
    pcm = b"".join(clip)
    limit = int(max_seconds * sample_rate) * 2     # harte Grenze, auch mit vorgelagertem Puffer
    return AudioClip(pcm[:limit], sample_rate)
