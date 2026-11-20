"""Spracherkennungs-Strategie: eine Kette austauschbarer STT-Provider mit verstaendlichen Fehlern (Speech Recognition Upgrade V1).

`stt_provider = "local"`  -> lokales Hauptmodell, dann das lokale Rueckfallmodell (z. B. whisper-base). Audio verlaesst den PC nie.
`stt_provider = "auto"`   -> wie local; Cloud (OpenAI) steht NUR in der Kette, wenn `voice.stt_cloud_enabled = true` UND ein Schluessel gesetzt ist. Standard: aus.
`stt_provider = "openai"` -> ausdruecklich nur Cloud (die Person hat sie gewaehlt).
Die Kette fuehrt nichts aus und gewaehrt nichts; sie entscheidet nur, welcher Provider das Audio erkennt. Cloud-Provider sind als solche markiert (`cloud = True`),
damit die Anzeige ehrlich sagen kann, wo erkannt wurde. Audio wird nie gespeichert; fuer die Diagnose bleiben nur Text und Metadaten der letzten Erkennungen im Speicher."""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Sequence

from jarvis.errors import STTError, VoiceUnavailableError
from jarvis.voice.base import AudioClip, STTProvider

log = logging.getLogger("jarvis.voice")
HISTORY = 5


class STTHalted(STTError):
    """Not-Aus/Sitzungsbudget haben die Erkennung gestoppt: nie auf einen anderen Provider (erst recht nicht Cloud) ausweichen."""


@dataclass(frozen=True)
class Recognition:
    """Diagnose einer Erkennung (kein Audio)."""
    provider: str
    cloud: bool
    seconds: float
    text: str                                   # Originaltranskript (vor jeder Nachbearbeitung)
    skipped: tuple[str, ...] = ()               # Provider davor, die gescheitert sind (Kurzgrund)


class FallbackSTT(STTProvider):
    name = "chain"

    def __init__(self, providers: Sequence[STTProvider], *, labels: Sequence[str] | None = None, guard: Callable[[], str | None] | None = None) -> None:
        if not providers:
            raise STTError("Spracherkennung: kein Provider verfuegbar")
        self._providers = list(providers)
        self._labels = list(labels) if labels is not None else [getattr(p, "name", type(p).__name__) for p in providers]
        self.guard = guard                                    # von build_listener gesetzt (Not-Aus/Sitzungsbudget), vor jedem Provider geprueft
        self.history: deque[Recognition] = deque(maxlen=HISTORY)

    @property
    def last(self) -> Recognition | None:
        return self.history[-1] if self.history else None

    def transcribe(self, clip: AudioClip, language: str | None = None) -> str:
        failures: list[str] = []
        for label, provider in zip(self._labels, self._providers):
            if self.guard is not None:                           # Not-Aus/Budget vor JEDEM Provider, besonders vor der Cloud
                reason = self.guard()
                if reason:
                    raise STTHalted(f"Spracherkennung gestoppt: {reason}")
            t0 = time.perf_counter()
            try:
                text = provider.transcribe(clip, language)
            except STTHalted:
                raise
            except (STTError, VoiceUnavailableError) as exc:
                failures.append(f"{label}: {exc}")
                log.warning("STT provider %s failed (%s); trying the next one", label, type(exc).__name__)
                continue
            self.history.append(Recognition(label, bool(getattr(provider, "cloud", False)), time.perf_counter() - t0, text, tuple(f.split(":", 1)[0] for f in failures)))
            return text
        raise STTError("Spracherkennung fehlgeschlagen. " + " | ".join(failures))
