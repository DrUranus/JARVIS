"""Windows-Sprachausgabe mit Windows-Bordmitteln: Windows PowerShell 5.1 (`powershell.exe`) und `System.Speech.Synthesis` (lokal, ohne Zusatzsoftware, ohne Netz).

Sicherheitsregeln (siehe docs/integrations/windows-tts.md):
- Der Befehl ist FEST: `powershell.exe -NoProfile -NonInteractive -Command <fester Skripttext>`; nie ueber eine Shell und nie mit dem Schalter, der die Standardeingabe als BEFEHLE ausfuehren wuerde.
- Der zu sprechende Text geht AUSSCHLIESSLICH als UTF-8-Bytes ueber die Standardeingabe und wird im Skript als Daten gelesen (`OpenStandardInput`), nie als Argument, nie im
  Skripttext, nie in der Umgebung. Der Argumentaufbau (`_argv`) bekommt den Text deshalb gar nicht.
- Steuerzeichen werden entfernt, die Laenge ist begrenzt (`max_chars`), lange Texte werden in begrenzte Abschnitte geteilt (`chunk_chars`); es gibt genau EINEN Prozess je Aufruf
  und keine Warteschlange: nichts, was abgebrochen wurde, wird spaeter wieder abgespielt.
- Zeitlimit, `stop()` beendet den Prozess (unter Windows samt Prozessbaum ueber ein Job-Object, falls verfuegbar). Fehlermeldungen enthalten nie den Text und nie die Fehlerausgabe.
- Not-Aus: mit gesetztem `guard` (liefert einen Grund, solange der Not-Aus aktiv ist) startet keine neue Sprachausgabe; ein fehlschlagender Guard sperrt ebenfalls (fail-closed).
Nichts wird installiert; ohne installierte Windows-Stimme meldet der Provider `VoiceUnavailableError`."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
import unicodedata
from typing import Any, Callable

from jarvis.errors import TTSError, VoiceUnavailableError
from jarvis.voice.base import TTSProvider

log = logging.getLogger("jarvis.voice")

EXE = "powershell.exe"
NO_VOICE_EXIT = 3
# Fester Skripttext (ohne Anfuehrungszeichen): Bytes der Standardeingabe als UTF-8 lesen, abschnittsweise sprechen. Die Umgebungsvariable JARVIS_TTS_WAV (nur ein Dateipfad, nie
# Text) lenkt die Ausgabe in eine WAV-Datei um - fuer den Windows-Runner-Test ohne Audiogeraet.
SCRIPT = ("$ErrorActionPreference='Stop';"
          "$ms=New-Object System.IO.MemoryStream;[Console]::OpenStandardInput().CopyTo($ms);"
          "$t=[System.Text.Encoding]::UTF8.GetString($ms.ToArray());"
          "Add-Type -AssemblyName System.Speech;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          f"if($s.GetInstalledVoices().Count -eq 0){{exit {NO_VOICE_EXIT}}};"
          "if($env:JARVIS_TTS_WAV){$s.SetOutputToWaveFile($env:JARVIS_TTS_WAV)};"
          "foreach($l in $t.Split([char]10)){if($l.Trim().Length -gt 0){$s.Speak($l)}};"
          "$s.Dispose()")
_SENTENCE_END = re.compile(r"(?<=[.!?…:;])\s+")


def _clean(text: str) -> str:
    """Remove control and format characters (bidi overrides included), collapse every kind of whitespace to a single space."""
    kept = "".join(ch for ch in str(text) if ch.isspace() or unicodedata.category(ch) not in ("Cc", "Cf"))
    return " ".join(kept.split())


def _pieces(sentence: str, limit: int) -> list[str]:
    """A sentence longer than `limit`: split at word boundaries; a single word longer than `limit` is cut."""
    out: list[str] = []
    cur = ""
    for word in sentence.split(" "):
        while len(word) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(word[:limit])
            word = word[limit:]
        if cur and len(cur) + 1 + len(word) > limit:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        out.append(cur)
    return out


def sections(text: str, max_chars: int, chunk_chars: int) -> list[str]:
    """The text as bounded sections (at most `chunk_chars` each, at sentence boundaries where possible); the total is cut at `max_chars`."""
    clean = _clean(text)[:max_chars].strip()
    if not clean:
        return []
    out: list[str] = []
    cur = ""
    for sentence in _SENTENCE_END.split(clean):
        if len(sentence) > chunk_chars:
            if cur:
                out.append(cur)
                cur = ""
            out.extend(_pieces(sentence, chunk_chars))
        elif cur and len(cur) + 1 + len(sentence) > chunk_chars:
            out.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}" if cur else sentence
    if cur:
        out.append(cur)
    return out


def _default_contain(pid: int) -> Any:
    """Put the started process into a kill-on-close job (Windows only); None when that is not possible (the caller then ends the single process directly)."""
    if sys.platform != "win32":
        return None
    try:
        from jarvis.self_improvement import winjob
        return winjob.attach(pid)
    except Exception:                                                              # noqa: BLE001 - containment is a bonus, never a reason to fail
        return None


class WindowsTTS(TTSProvider):
    name = "windows"

    def __init__(self, *, timeout: float | None = None, max_chars: int = 4000, chunk_chars: int = 500, wave_file: str | None = None,
                 popen: Callable[..., Any] = subprocess.Popen, contain: Callable[[int], Any] | None = _default_contain,
                 guard: Callable[[], str | None] | None = None) -> None:
        if timeout is not None and not 0 < timeout <= 300:
            raise TTSError("tts timeout must be within 0..300 seconds")
        if not 0 < chunk_chars <= 1000 or not chunk_chars <= max_chars <= 20_000:
            raise TTSError("tts limits: 0 < chunk_chars <= 1000 and chunk_chars <= max_chars <= 20000")
        self._timeout, self._max, self._chunk, self._wave = timeout, max_chars, chunk_chars, wave_file
        self._popen, self._contain = popen, contain
        self.guard = guard                                  # set by the composition root: a reason while the emergency stop is active (else None)
        self._lock = threading.Lock()
        self._gen = 0                                       # raised by stop(): a speech that was cut off is never continued or replayed
        self._proc: Any = None
        self._job: Any = None

    # -- state ------------------------------------------------------------------------------------------------------------------------------
    @property
    def speaking(self) -> bool:
        return self._proc is not None

    # -- command (never receives the text) -----------------------------------------------------------------------------------------------------
    @staticmethod
    def _argv() -> list[str]:
        return [EXE, "-NoProfile", "-NonInteractive", "-Command", SCRIPT]

    @staticmethod
    def _flags() -> dict[str, Any]:
        return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

    def _timeout_for(self, size: int) -> float:
        return self._timeout if self._timeout is not None else min(300.0, 15.0 + size / 8)

    def _blocked(self) -> bool:
        if self.guard is None:
            return False
        try:
            reason = self.guard()
        except Exception:                                   # noqa: BLE001 - fail closed
            log.warning("speech guard failed: no speech is started")
            return True
        if reason:
            log.info("speech not started: %s", reason)
            return True
        return False

    # -- speak / stop ---------------------------------------------------------------------------------------------------------------------------
    def speak(self, text: str) -> None:
        if self._blocked():
            return
        parts = sections(text, self._max, self._chunk)
        if not parts:
            return
        payload = "\n".join(parts).encode("utf-8")
        with self._lock:
            gen = self._gen
        extra: dict[str, Any] = self._flags()
        if self._wave:
            extra["env"] = {**os.environ, "JARVIS_TTS_WAV": str(self._wave)}
        try:
            proc = self._popen(self._argv(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, shell=False, **extra)
        except FileNotFoundError:
            raise VoiceUnavailableError("Windows PowerShell (powershell.exe) wurde nicht gefunden: die Windows-Sprachausgabe gibt es nur unter Windows") from None
        except OSError as exc:
            raise TTSError(f"Windows-Sprachausgabe konnte nicht gestartet werden ({type(exc).__name__})") from None
        job = self._contain(proc.pid) if self._contain is not None else None
        with self._lock:
            cut_off = self._gen != gen                      # stop() came in while the process was being started
            if not cut_off:
                self._proc, self._job = proc, job
        if cut_off:
            self._kill(proc, job)
            return
        try:
            proc.communicate(payload, timeout=self._timeout_for(len(payload)))
        except subprocess.TimeoutExpired:
            self._kill(proc, job)
            raise TTSError("Windows-Sprachausgabe: Zeitlimit überschritten, der Vorgang wurde beendet") from None
        except OSError:
            self._kill(proc, job)
            if self._gen != gen:
                return
            raise TTSError("Windows-Sprachausgabe: Verbindung zum Sprachprozess verloren") from None
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = self._job = None
            self._release(job)
        if self._gen != gen:
            return                                          # cut off by stop(): not an error, and nothing is replayed
        rc = proc.returncode
        if rc == NO_VOICE_EXIT:
            raise VoiceUnavailableError("Keine Windows-Stimme installiert (Windows-Einstellungen: Zeit und Sprache > Sprache > Sprachausgabe)")
        if rc != 0:
            raise TTSError(f"Windows-Sprachausgabe fehlgeschlagen (Exit-Code {rc})")

    def stop(self) -> None:
        """Barge-in / emergency stop: end the running speech. Idempotent, never raises, queues nothing."""
        with self._lock:
            self._gen += 1
            proc, job = self._proc, self._job
        if proc is not None:
            self._kill(proc, job)

    @staticmethod
    def _kill(proc: Any, job: Any) -> None:
        if job is not None:
            try:
                job.terminate()
            except Exception:                               # noqa: BLE001
                pass
        try:
            proc.kill()
        except Exception:                                   # noqa: BLE001
            pass

    @staticmethod
    def _release(job: Any) -> None:
        if job is not None:
            try:
                job.close()
            except Exception:                               # noqa: BLE001
                pass
