"""Conversation context with a bounded history window."""
from __future__ import annotations

from typing import Sequence

from jarvis.llm.base import Message

SYSTEM_PROMPT = (
    "You are JARVIS, a personal AI assistant. Be concise, precise and helpful. "
    "Answer in the user's language. If a task is complex, break it down instead of refusing; "
    "if something is truly impossible, state the concrete reason and offer an alternative."
)


class Context:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT, max_messages: int = 20) -> None:
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self._history: list[Message] = []

    def add_user(self, text: str) -> None:
        self._add(Message.user(text))

    def add_assistant(self, text: str) -> None:
        self._add(Message.assistant(text))

    def _add(self, msg: Message) -> None:
        self._history.append(msg)
        if len(self._history) > self.max_messages:
            self._history = self._history[-self.max_messages:]

    def build(self, extra_system: Sequence[str] = ()) -> list[Message]:
        """System prompt, optional per-request system notes (e.g. relevant memories), then the history.
        Notes are temporary: they are not added to the history."""
        return [Message.system(self.system_prompt), *(Message.system(t) for t in extra_system), *self._history]

    def pop_last_user(self) -> None:
        if self._history and self._history[-1].role.value == "user":
            self._history.pop()

    def clear(self) -> None:
        self._history.clear()

    def __len__(self) -> int:
        return len(self._history)
