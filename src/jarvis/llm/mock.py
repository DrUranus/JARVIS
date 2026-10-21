"""Offline provider for development and tests. Deterministic, no network."""
from __future__ import annotations

from typing import Callable

from jarvis.llm.base import LLMProvider, LLMRequest, LLMResponse, Role

Responder = Callable[[LLMRequest], str]


def _default_responder(request: LLMRequest) -> str:
    last = next((m.content for m in reversed(request.messages) if m.role is Role.USER), "")
    low = last.lower()
    if any(g in low for g in ("hallo", "hello", "hi jarvis", "hey")):
        return "Hallo. Ich bin bereit."
    return f"[mock] Ich habe verstanden: {last}"


class MockProvider(LLMProvider):
    """Records every request in `calls`; reply logic is injectable."""

    name = "mock"

    def __init__(self, responder: Responder | None = None, model: str = "mock-1") -> None:
        self._responder = responder or _default_responder
        self._model = model
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(content=self._responder(request), model=request.model or self._model)
