"""OpenAI speech endpoints (Whisper STT, TTS) over plain HTTPS. Compatible servers work via base_url."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid

from jarvis.errors import STTError, TTSError
from jarvis.voice.base import AudioClip, AudioPlayer, STTProvider, TTSProvider


def _request(req: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https endpoint from config
        return resp.read()


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_LANG_CODE = re.compile(r"^[a-z]{2,3}(-[a-z]{2})?$")


def http_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    """Seam for tests: monkeypatch this to avoid network access."""
    try:
        return _request(urllib.request.Request(url, data=body, headers=headers), timeout)
    except urllib.error.HTTPError as exc:
        raise OSError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OSError(str(exc)) from exc


def multipart(fields: "dict[str, str] | list[tuple[str, str]]", file_field: str, filename: str, content: bytes,
              content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for k, v in (fields.items() if isinstance(fields, dict) else fields):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                  f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n').encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class OpenAISTT(STTProvider):
    """OpenAI-Transkription. CLOUD: das Audio verlaesst den PC (kostet Geld). Wird nur gebaut, wenn die Person `openai` waehlt oder bei `auto` die Cloud ausdruecklich
    aktiviert hat (`voice.stt_cloud_enabled`). Modell `gpt-transcribe`: `languages[]` ersetzt `language`, `keywords[]` und `prompt` sind Hinweise (offizielle Doku);
    aeltere Modelle (whisper-1, gpt-4o-*) bekommen `language` und `prompt`."""
    name = "openai"
    cloud = True

    def __init__(self, api_key: str | None, model: str = "gpt-transcribe", base_url: str | None = None,
                 timeout: float = 30.0, *, keywords: tuple[str, ...] = (), prompt: str | None = None) -> None:
        if not api_key:
            raise STTError("OpenAI STT needs OPENAI_API_KEY (or JARVIS_VOICE_API_KEY)")
        self._key, self._model, self._timeout = api_key, model, timeout
        self._keywords = tuple(k.strip() for k in keywords if k and k.strip() and not any(c in k for c in "<>\r\n"))[:30]   # Zeilenumbrueche/<> lehnt die API komplett ab
        self._prompt = (prompt or "").strip()[:500] or None
        self._url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/audio/transcriptions"

    def _fields(self, language: str | None) -> list[tuple[str, str]]:
        fields: list[tuple[str, str]] = [("model", self._model)]
        lang = None if language is None or language.strip().lower() in ("", "auto") else language.strip().lower()
        if lang and not _LANG_CODE.match(lang):                            # die API lehnt ungueltige Codes ab: vorher klar melden statt Kosten/Fehlversuch
            raise STTError(f"voice.language {language!r} ist kein Sprachcode (ISO 639-1, z. B. 'de', 'en'; 'auto' = Modell erkennt selbst)")
        if not self._model.startswith("gpt-transcribe"):
            fields.append(("response_format", "json"))                    # gpt-transcribe: Standard ist json; fuer aeltere Modelle ausdruecklich
        if self._model.startswith("gpt-transcribe"):
            if lang:
                fields.append(("languages[]", lang))                      # gpt-transcribe: languages[] ersetzt language (nie beide senden)
            fields += [("keywords[]", k) for k in self._keywords]
        elif lang:
            fields.append(("language", lang))
        if self._prompt:
            fields.append(("prompt", self._prompt))
        return fields

    def transcribe(self, clip: AudioClip, language: str | None = None) -> str:
        wav = clip.to_wav()
        if len(wav) > MAX_UPLOAD_BYTES:                                    # laut API-Doku hoechstens 25 MB je Datei
            raise STTError("Aufnahme ist groesser als das Limit von 25 MB der OpenAI-Spracherkennung (voice.max_record_seconds verkleinern)")
        body, ctype = multipart(self._fields(language), "file", "speech.wav", wav, "audio/wav")
        try:
            raw = http_post(self._url, {"Authorization": f"Bearer {self._key}", "Content-Type": ctype}, body, self._timeout)
            return str(json.loads(raw.decode())["text"]).strip()
        except OSError as exc:
            raise STTError(f"OpenAI-Spracherkennung fehlgeschlagen: {_explain(str(exc))}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise STTError(f"OpenAI-Spracherkennung: unerwartete Antwort ({type(exc).__name__})") from exc


def _explain(message: str) -> str:
    """Verstaendliche Ursache statt roher HTTP-Texte (der Schluessel steht nie in einer Meldung)."""
    m = message.lower()
    if "http 401" in m or "http 403" in m:
        return "Schluessel ungueltig oder ohne Berechtigung (OPENAI_API_KEY pruefen)"
    if "http 404" in m:
        return "Modell oder Adresse nicht gefunden (voice.stt_model / voice.base_url pruefen)"
    if "http 429" in m:
        return "Limit oder Guthaben erreicht (spaeter erneut versuchen)"
    if "http 400" in m or "http 422" in m:
        return "Anfrage abgelehnt (Modell/Sprache/Hinweise pruefen): " + message[:160]
    if "http 5" in m:
        return "Dienst derzeit gestoert (spaeter erneut versuchen)"
    if "timed out" in m or "timeout" in m:
        return "Zeitlimit ueberschritten (voice.timeout erhoehen oder lokal erkennen)"
    return "Verbindung nicht moeglich (Netzwerk pruefen): " + message[:160]


class OpenAITTS(TTSProvider):
    name = "openai"

    def __init__(self, api_key: str | None, player: AudioPlayer, model: str = "tts-1", voice: str = "alloy",
                 base_url: str | None = None, timeout: float = 30.0) -> None:
        if not api_key:
            raise TTSError("OpenAI TTS needs OPENAI_API_KEY (or JARVIS_VOICE_API_KEY)")
        self._key, self._player, self._model, self._voice, self._timeout = api_key, player, model, voice, timeout
        self._url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/audio/speech"

    def speak(self, text: str) -> None:
        payload = json.dumps({"model": self._model, "voice": self._voice, "input": text,
                              "response_format": "wav"}).encode()
        try:
            audio = http_post(self._url, {"Authorization": f"Bearer {self._key}",
                                          "Content-Type": "application/json"}, payload, self._timeout)
            clip = AudioClip.from_wav(audio)
        except (OSError, EOFError, ValueError) as exc:
            raise TTSError(f"OpenAI speech synthesis failed: {exc}") from exc
        self._player.play(clip)  # VoiceUnavailableError propagates to the session

    def stop(self) -> None:
        self._player.stop()
