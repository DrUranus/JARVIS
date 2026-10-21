"""Hardware-free 'voice': typed lines act as transcripts, speech is printed.

Lets the whole voice loop (wake word, speech summaries, exit phrases) run anywhere.
"""
from __future__ import annotations

from typing import Callable

from jarvis.errors import EndOfInput
from jarvis.voice.base import Listener, Speaker


class ConsoleListener(Listener):
    def __init__(self, input_fn: Callable[[str], str] = input, prompt: str = "voice> ") -> None:
        self._input, self._prompt = input_fn, prompt

    def listen(self) -> str | None:
        try:
            line = self._input(self._prompt).strip()
        except (EOFError, KeyboardInterrupt):
            raise EndOfInput("console closed") from None
        return line or None


class ConsoleSpeaker(Speaker):
    def __init__(self, output_fn: Callable[[str], None] = print) -> None:
        self._out = output_fn

    def say(self, text: str) -> None:
        self._out(f"🔊 {text}")
