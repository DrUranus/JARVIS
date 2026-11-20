"""Der API-Schluessel darf nie in einer Fehlermeldung landen, auch wenn der Anbieter ihn in der Antwort wiederholt. Kein Netz (urlopen ersetzt)."""
import io
import urllib.error
import urllib.request

import pytest

from jarvis.errors import LLMError
from jarvis.llm.base import LLMRequest, Message, Role
from jarvis.llm.http_providers import AnthropicProvider, OpenAIProvider

KEY = "sk-TESTFAKE1234567890abcdef"


def req():
    return LLMRequest(messages=[Message(Role.USER, "hallo")])


@pytest.mark.parametrize("cls", [OpenAIProvider, AnthropicProvider])
def test_http_error_body_that_echoes_the_key_is_scrubbed(monkeypatch, cls):
    def fake(r, timeout=None):
        raise urllib.error.HTTPError(r.full_url, 401, "x", {}, io.BytesIO(f'{{"error":"Incorrect API key provided: {KEY}."}}'.encode()))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(LLMError) as e:
        cls(KEY, "m").complete(req())
    assert KEY not in str(e.value) and "401" in str(e.value) and "***" in str(e.value)


@pytest.mark.parametrize("cls", [OpenAIProvider, AnthropicProvider])
def test_network_error_that_echoes_the_key_is_scrubbed(monkeypatch, cls):
    def fake(r, timeout=None):
        raise urllib.error.URLError(f"failed for {KEY}")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(LLMError) as e:
        cls(KEY, "m").complete(req())
    assert KEY not in str(e.value) and KEY not in repr(e.value.__cause__ or "")
