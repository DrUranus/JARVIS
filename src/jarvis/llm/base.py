"""Provider-agnostic LLM interface. The Core only ever sees these types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    role: Role
    content: str

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(Role.SYSTEM, content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(Role.USER, content)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        return cls(Role.ASSISTANT, content)


@dataclass(frozen=True)
class LLMRequest:
    messages: list[Message]
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None


class LLMProvider(ABC):
    """Implement `complete` to add a new backend (OpenAI, Anthropic, local...)."""

    name: str = "base"

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return the model's reply. Must raise LLMError on any failure."""

    def complete_text(self, system: str, user: str, *, max_tokens: int | None = None, temperature: float | None = 0.0) -> str:
        """One system + one user message in, the reply text out (for callers that must not depend on the request types, e.g. the goal replanner)."""
        return self.complete(LLMRequest([Message.system(system), Message.user(user)], temperature=temperature, max_tokens=max_tokens)).content
