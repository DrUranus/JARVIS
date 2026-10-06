"""OpenAI speech endpoints (Whisper STT, TTS) over plain HTTPS. Compatible servers work via base_url."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from jarvis.errors import STTError, TTSError
from jarvis.voice.base import AudioClip, AudioPlayer, STTProvider, TTSProvider


def _request(req: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https endpoint from config
        return resp.read()


def http_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    """Seam for tests: monkeypatch this to avoid network access."""
    try:
        return _request(urllib.request.Request(url, data=body, headers=headers), timeout)
    except urllib.error.HTTPError as exc:
        raise OSError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OSError(str(exc)) from exc


def multipart(fields: dict[str, str], file_field: str, filename: str, content: bytes,
              content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                  f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n').encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class OpenAISTT(STTProvider):
    name = "openai"

    def __init__(self, api_key: str | None, model: str = "whisper-1", base_url: str | None = None,
                 timeout: float = 30.0) -> None:
        if not api_key:
            raise STTError("OpenAI STT needs OPENAI_API_KEY (or JARVIS_VOICE_API_KEY)")
        self._key, self._model, self._timeout = api_key, model, timeout
        self._url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/audio/transcriptions"

    def transcribe(self, clip: AudioClip, language: str | None = None) -> str:
        fields = {"model": self._model, "response_format": "json"}
        if language:
            fields["language"] = language
        body, ctype = multipart(fields, "file", "speech.wav", clip.to_wav(), "audio/wav")
        try:
            raw = http_post(self._url, {"Authorization": f"Bearer {self._key}", "Content-Type": ctype},
                            body, self._timeout)
            return str(json.loads(raw.decode())["text"]).strip()
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise STTError(f"OpenAI transcription failed: {exc}") from exc


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
