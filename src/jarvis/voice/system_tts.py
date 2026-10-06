"""Offline TTS through a system command (espeak-ng, espeak, spd-say, say)."""
from __future__ import annotations

import shlex
import shutil
import subprocess

from jarvis.errors import TTSError, VoiceUnavailableError
from jarvis.voice.base import TTSProvider

_CANDIDATES = ("espeak-ng", "espeak", "spd-say", "say")


class SystemTTS(TTSProvider):
    name = "system"

    def __init__(self, command: str | None = None, timeout: float = 60.0) -> None:
        if command:
            self._cmd = shlex.split(command)
        else:
            found = next((c for c in _CANDIDATES if shutil.which(c)), None)
            self._cmd = [found] if found else None
        if not self._cmd:
            raise VoiceUnavailableError(f"no system TTS found (tried {', '.join(_CANDIDATES)}); "
                                        "install espeak-ng or set voice.tts_command")
        self._timeout = timeout

    def speak(self, text: str) -> None:
        try:
            subprocess.run([*self._cmd, text], check=True, capture_output=True, timeout=self._timeout)
        except FileNotFoundError as exc:
            raise VoiceUnavailableError(f"TTS command not found: {self._cmd[0]}") from exc
        except (subprocess.SubprocessError, OSError) as exc:
            raise TTSError(f"system TTS failed: {exc}") from exc
