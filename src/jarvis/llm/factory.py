"""Provider registry: new backends register a factory; config picks one by name."""
from __future__ import annotations

from typing import Callable

from jarvis.config import LLMSettings
from jarvis.errors import ProviderNotFoundError
from jarvis.llm.base import LLMProvider
from jarvis.llm.http_providers import AnthropicProvider, OpenAIProvider
from jarvis.llm.mock import MockProvider

ProviderFactory = Callable[[LLMSettings], LLMProvider]

_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    _REGISTRY[name.lower()] = factory


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def create_provider(settings: LLMSettings) -> LLMProvider:
    try:
        factory = _REGISTRY[settings.provider.lower()]
    except KeyError:
        raise ProviderNotFoundError(
            f"unknown LLM provider {settings.provider!r}; available: {available_providers()}"
        ) from None
    return factory(settings)


def _http(cls):
    return lambda s: cls(s.api_key, s.model, s.base_url, s.temperature, s.max_tokens, s.timeout)


register_provider("mock", lambda s: MockProvider(model=s.model))
register_provider("openai", _http(OpenAIProvider))
register_provider("anthropic", _http(AnthropicProvider))
