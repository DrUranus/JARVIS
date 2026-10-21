import pytest

from jarvis.config import LLMSettings
from jarvis.errors import LLMError, ProviderNotFoundError
from jarvis.llm import LLMRequest, Message, MockProvider, available_providers, create_provider, register_provider
from jarvis.llm.http_providers import AnthropicProvider, OpenAIProvider


def test_mock_greeting_and_recording():
    p = MockProvider()
    r = p.complete(LLMRequest([Message.user("Hallo JARVIS")]))
    assert r.content == "Hallo. Ich bin bereit."
    assert len(p.calls) == 1


def test_factory_default_and_unknown():
    assert isinstance(create_provider(LLMSettings()), MockProvider)
    with pytest.raises(ProviderNotFoundError):
        create_provider(LLMSettings(provider="nope"))


def test_custom_provider_registration():
    register_provider("custom", lambda s: MockProvider(responder=lambda r: "custom!"))
    assert "custom" in available_providers()
    assert create_provider(LLMSettings(provider="custom")).complete(LLMRequest([Message.user("x")])).content == "custom!"


@pytest.mark.parametrize("cls", [OpenAIProvider, AnthropicProvider])
def test_http_providers_require_key(cls):
    with pytest.raises(LLMError):
        cls(None, "m")


def test_openai_payload_and_parse(monkeypatch):
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=payload)
        return {"choices": [{"message": {"content": "hi"}}], "model": "gpt-x"}

    monkeypatch.setattr("jarvis.llm.http_providers._post", fake_post)
    r = OpenAIProvider("k", "gpt-x").complete(LLMRequest([Message.system("s"), Message.user("u")]))
    assert r.content == "hi" and seen["payload"]["messages"][0]["role"] == "system"
    assert seen["headers"]["Authorization"] == "Bearer k"


def test_anthropic_splits_system(monkeypatch):
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(payload=payload)
        return {"content": [{"type": "text", "text": "yo"}]}

    monkeypatch.setattr("jarvis.llm.http_providers._post", fake_post)
    r = AnthropicProvider("k", "m").complete(LLMRequest([Message.system("sys"), Message.user("u")]))
    assert r.content == "yo" and seen["payload"]["system"] == "sys"
    assert all(m["role"] != "system" for m in seen["payload"]["messages"])


def test_bad_response_shape(monkeypatch):
    monkeypatch.setattr("jarvis.llm.http_providers._post", lambda *a, **k: {"oops": 1})
    with pytest.raises(LLMError):
        OpenAIProvider("k", "m").complete(LLMRequest([Message.user("u")]))
