"""Lokaler STT-Provider (optionales Extra 'stt-local', faster-whisper). Audio verlaesst den PC nie.

Regeln (docs/integrations/stt-local.md):
- Das Modell kommt nur aus dem konfigurierten lokalen Verzeichnis (`voice.stt_model_dir`); es gibt keinen Download.
- Die Bibliothek wird erst beim ersten Erkennen importiert (lazy). Fehlt sie, kommt eine klare Meldung.
- Dieses Modul importiert keine Netzwerkbibliothek (Strukturtest in tests/test_voice_local_stt.py).
- `guard` ist die Naht fuer Notaus und Sitzungsbudget: liefert er einen Grund, wird nichts geladen und nichts erkannt.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Iterable, Protocol

from jarvis.errors import STTError, VoiceUnavailableError
from jarvis.voice.base import AudioClip, STTProvider

REQUIRED_RATE = 16000


class Engine(Protocol):
    def transcribe(self, clip: AudioClip, language: str | None) -> tuple[Iterable[str], str | None]:
        """Segmenttexte (lazy erlaubt) und die erkannte/angegebene Sprache."""


def load_faster_whisper(model_dir: str, device: str = "cpu", compute_type: str = "int8") -> Engine:
    """Standard-Lader. Importiert faster-whisper erst hier und laedt nur aus `model_dir` (local_files_only)."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # vor dem Import: kein Hub-Zugriff
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError as exc:
        raise VoiceUnavailableError(
            "Lokale Spracherkennung braucht das Extra 'stt-local': pip install -e \".[stt-local]\" "
            f"(faster-whisper nicht importierbar: {exc})") from exc
    try:
        model = WhisperModel(model_dir, device=device, compute_type=compute_type, local_files_only=True)
    except Exception as exc:  # noqa: BLE001 - Bibliotheksfehler in klare Meldung wandeln
        raise STTError(f"Lokales Sprachmodell in {model_dir!r} konnte nicht geladen werden: {exc}") from exc
    return _FasterWhisperEngine(model)


class _FasterWhisperEngine:
    def __init__(self, model: object) -> None:
        self._model = model

    def transcribe(self, clip: AudioClip, language: str | None) -> tuple[Iterable[str], str | None]:
        try:
            import numpy as np
        except ImportError as exc:
            raise VoiceUnavailableError('Lokale Spracherkennung braucht numpy: pip install -e ".[stt-local]"') from exc
        audio = np.frombuffer(clip.pcm, dtype="<i2").astype(np.float32) / 32768.0
        segments, info = self._model.transcribe(audio, language=language, vad_filter=True)  # type: ignore[attr-defined]
        return (s.text for s in segments), getattr(info, "language", language)


class LocalWhisperSTT(STTProvider):
    name = "local"

    def __init__(self, model_dir: str | None, *, device: str = "cpu", compute_type: str = "int8",
                 timeout: float = 30.0, engine_loader: Callable[[str], Engine] | None = None,
                 guard: Callable[[], str | None] | None = None) -> None:
        if not model_dir:
            raise STTError("Lokale Spracherkennung: voice.stt_model_dir ist nicht gesetzt "
                           "(Verzeichnis eines lokal abgelegten Modells; kein automatischer Download).")
        path = Path(model_dir)
        if not path.exists():
            raise STTError(f"Lokale Spracherkennung: Modellverzeichnis voice.stt_model_dir={model_dir!r} fehlt "
                           "(Modell von Hand ablegen; kein automatischer Download).")
        if not path.is_dir():
            raise STTError(f"Lokale Spracherkennung: voice.stt_model_dir={model_dir!r} ist kein Verzeichnis.")
        self._dir, self._timeout, self._guard = str(path), timeout, guard
        self._loader = engine_loader or (lambda p: load_faster_whisper(p, device, compute_type))
        self._engine: Engine | None = None
        self.last_language: str | None = None

    def transcribe(self, clip: AudioClip, language: str | None = None) -> str:
        if self._guard is not None:
            reason = self._guard()
            if reason:
                raise STTError(f"Lokale Spracherkennung gestoppt: {reason}")
        if clip.is_empty:
            return ""
        if clip.sample_rate != REQUIRED_RATE:
            raise STTError(f"Lokale Spracherkennung braucht {REQUIRED_RATE} Hz, bekam {clip.sample_rate} Hz "
                           "(voice.sample_rate = 16000 setzen).")
        result: dict[str, object] = {}

        def work() -> None:
            try:
                if self._engine is None:
                    self._engine = self._loader(self._dir)
                segments, lang = self._engine.transcribe(clip, language)
                result["text"] = " ".join(t.strip() for t in segments if t and t.strip())
                result["lang"] = lang
            except BaseException as exc:  # noqa: BLE001 - in den aufrufenden Thread weiterreichen
                result["error"] = exc

        t = threading.Thread(target=work, name="local-stt", daemon=True)
        t.start()
        t.join(self._timeout)
        if t.is_alive():
            raise STTError(f"Lokale Spracherkennung: Zeitlimit von {self._timeout:g} s ueberschritten.")
        err = result.get("error")
        if isinstance(err, (STTError, VoiceUnavailableError)):
            raise err
        if err is not None:
            raise STTError(f"Lokale Spracherkennung fehlgeschlagen: {err}") from err  # type: ignore[arg-type]
        self.last_language = result.get("lang")  # type: ignore[assignment]
        return str(result.get("text", ""))
