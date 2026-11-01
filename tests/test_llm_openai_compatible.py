"""Provider 'openai_compatible': only with an injected fake transport, never the network."""
import json
import logging

import pytest

from jarvis.config import ConfigError, LLMSettings, load_settings
from jarvis.errors import LLMError
from jarvis.llm import LLMRequest, Message, MockProvider, create_provider
from jarvis.llm.openai_compatible import OpenAICompatibleProvider

KEY = "sk-test-SECRET-1234567890"
LOCAL = "http://127.0.0.1:11434/v1"
REQ = LLMRequest([Message.system("s"), Message.user("u")])


def ok_body(content="hallo"):
    return json.dumps({"choices": [{"message": {"content": content}}], "model": "m1", "usage": {"total_tokens": 3}}).encode()


class Fake:
    def __init__(self, status=200, body=None, exc=None):
        self.status, self.body, self.exc, self.calls = status, ok_body() if body is None else body, exc, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, dict(headers), json.loads(body), timeout))
        if self.exc:
            raise self.exc
        return self.status, self.body


def make(fake, base_url=LOCAL, api_key=None, **kw):
    return OpenAICompatibleProvider("m1", base_url, api_key=api_key, transport=fake, **kw)


def test_default_stays_mock():
    assert LLMSettings().provider == "mock" and LLMSettings().allow_remote is False
    assert isinstance(create_provider(LLMSettings()), MockProvider)


def test_factory_creates_provider():
    p = create_provider(LLMSettings(provider="openai_compatible", model="m1", base_url=LOCAL))
    assert isinstance(p, OpenAICompatibleProvider) and p.name == "openai_compatible" and p.is_remote is False


def test_success_payload_and_parse():
    f = Fake()
    r = make(f, timeout=7.0).complete(REQ)
    assert r.content == "hallo" and r.model == "m1" and r.usage == {"total_tokens": 3}
    url, headers, payload, timeout = f.calls[0]
    assert url == LOCAL + "/chat/completions" and timeout == 7.0
    assert payload["model"] == "m1" and payload["messages"][0] == {"role": "system", "content": "s"}
    assert "Authorization" not in headers  # key is optional on loopback


def test_complete_text_interface():
    assert make(Fake()).complete_text("s", "u") == "hallo"


def test_key_sent_as_bearer_when_given():
    f = Fake()
    make(f, api_key=KEY).complete(REQ)
    assert f.calls[0][1]["Authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("url", ["http://localhost:1234/v1", "http://127.0.0.1:1/v1", "http://[::1]:8080/v1"])
def test_loopback_allowed_by_default(url):
    assert make(Fake(), base_url=url).is_remote is False


@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://192.168.1.5:11434/v1", "http://example.com/v1"])
def test_remote_refused_without_allow_remote(url):
    with pytest.raises(LLMError, match="allow_remote"):
        make(Fake(), base_url=url, api_key=KEY)


def test_remote_allowed_explicitly_needs_https_and_key():
    p = make(Fake(), base_url="https://api.example.com/v1", api_key=KEY, allow_remote=True)
    assert p.is_remote is True
    with pytest.raises(LLMError, match="https"):
        make(Fake(), base_url="http://192.168.1.5:11434/v1", api_key=KEY, allow_remote=True)
    with pytest.raises(LLMError, match="key"):
        make(Fake(), base_url="https://api.example.com/v1", allow_remote=True)


@pytest.mark.parametrize("url", ["", "ftp://127.0.0.1/v1", "http://user:pw@127.0.0.1/v1", "127.0.0.1:11434/v1", "http:///v1"])
def test_bad_urls_refused(url):
    with pytest.raises(LLMError):
        make(Fake(), base_url=url)


def test_missing_base_url_refused():
    with pytest.raises(LLMError, match="base_url"):
        OpenAICompatibleProvider("m1", None)


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500, 503])
def test_http_errors(status):
    body = json.dumps({"error": {"code": status, "message": "Loading model", "type": "unavailable_error"}}).encode()
    with pytest.raises(LLMError, match=f"HTTP {status}.*Loading model"):
        make(Fake(status=status, body=body)).complete(REQ)


def test_http_error_with_plain_text_body():
    with pytest.raises(LLMError, match="HTTP 502"):
        make(Fake(status=502, body=b"Bad gateway")).complete(REQ)


@pytest.mark.parametrize("exc", [TimeoutError("timed out"), OSError("refused")])
def test_timeout_and_connection_errors(exc):
    with pytest.raises(LLMError, match="failed"):
        make(Fake(exc=exc)).complete(REQ)


def test_timeout_message_is_distinct():
    with pytest.raises(LLMError, match="timed out"):
        make(Fake(exc=TimeoutError("x"))).complete(REQ)


@pytest.mark.parametrize("body", [b"not json", b"[]", b"{}", b'{"choices": []}', b'{"choices": [{"message": {}}]}',
                                  b'{"choices": [{"message": {"content": 5}}]}', b'{"choices": "x"}'])
def test_invalid_response(body):
    with pytest.raises(LLMError, match="unexpected|invalid"):
        make(Fake(body=body)).complete(REQ)


def test_null_content_becomes_empty():
    assert make(Fake(body=b'{"choices": [{"message": {"content": null}}]}')).complete(REQ).content == ""


def test_key_never_in_repr_logs_or_errors(caplog):
    caplog.set_level(logging.DEBUG)
    echo = json.dumps({"error": {"message": f"bad key {KEY}"}}).encode()
    p = make(Fake(), api_key=KEY)
    assert KEY not in repr(p) and KEY not in str(vars(p).get("__dict__", ""))
    p.complete(REQ)
    for fake in (Fake(status=401, body=echo), Fake(status=500, body=KEY.encode()), Fake(exc=OSError(f"x {KEY}")),
                 Fake(body=KEY.encode())):
        with pytest.raises(LLMError) as ei:
            make(fake, api_key=KEY).complete(REQ)
        assert KEY not in str(ei.value) and KEY not in repr(ei.value)
    assert KEY not in caplog.text


def test_settings_repr_hides_key():
    assert KEY not in repr(LLMSettings(provider="openai_compatible", api_key=KEY))


def test_key_only_from_environment(tmp_path):
    cfg = tmp_path / "j.toml"
    cfg.write_text(f'[llm]\nprovider = "openai_compatible"\nbase_url = "{LOCAL}"\napi_key = "{KEY}"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="environment"):
        load_settings(cfg, env={})
    cfg.write_text(f'[llm]\nprovider = "openai_compatible"\nbase_url = "{LOCAL}"\n', encoding="utf-8")
    s = load_settings(cfg, env={"JARVIS_LLM_API_KEY": KEY})
    assert s.llm.api_key == KEY
    s = load_settings(cfg, env={"OPENAI_COMPATIBLE_API_KEY": KEY})
    assert s.llm.api_key == KEY
    assert load_settings(cfg, env={}).llm.api_key is None


def test_allow_remote_via_env():
    s = load_settings(None, env={"JARVIS_LLM_PROVIDER": "openai_compatible", "JARVIS_LLM_ALLOW_REMOTE": "true"})
    assert s.llm.allow_remote is True


def test_no_redirects_or_new_dependency():
    import inspect
    import jarvis.llm.openai_compatible as mod
    src = inspect.getsource(mod)
    assert "requests" not in src and "httpx" not in src and "import openai" not in src
