"""Mikrofon-Pegel fuer die Anzeige (NEXUS "voice_level"): ein winziger, thread-sicherer Zwischenspeicher.

Die Aufnahmeschleife (devices.SoundDeviceSource) meldet je Chunk den Pegel; der UI-Adapter liest ihn beim naechsten Pump und sendet daraus das Ereignis
`voice_level`. Reine Anzeige: das Modul entscheidet nichts, erkennt keine Sprache, speichert kein Audio (nur eine Zahl 0..1) und hat keine Abhaengigkeit.
Ein veralteter Wert (keine Aufnahme laeuft mehr) zaehlt als 0, damit die Anzeige nie "haengen bleibt"."""
from __future__ import annotations

import threading
import time
from typing import Callable

FULL_SCALE_RMS = 6000.0          # RMS (16-bit-PCM), ab dem die Anzeige voll ausschlaegt; normale Sprache liegt meist bei 500..4000
MAX_AGE_SECONDS = 0.6            # aelter als das = keine Aufnahme mehr -> 0


def level_from_rms(value: float) -> float:
    """RMS eines 16-bit-PCM-Chunks -> Anzeigepegel 0..1 (begrenzt, nie NaN)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not v > 0.0:
        return 0.0
    return min(1.0, v / FULL_SCALE_RMS)


class LevelMeter:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_age: float = MAX_AGE_SECONDS) -> None:
        self._clock, self._max_age = clock, max_age
        self._lock = threading.Lock()
        self._level, self._at = 0.0, 0.0

    def push(self, level: float) -> None:
        with self._lock:
            self._level, self._at = max(0.0, min(1.0, float(level))), self._clock()

    def clear(self) -> None:
        with self._lock:
            self._level, self._at = 0.0, 0.0

    def read(self) -> float:
        with self._lock:
            return self._level if self._clock() - self._at <= self._max_age else 0.0


METER = LevelMeter()
