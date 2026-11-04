"""Brave Search provider (step research-search-provider): the one chosen source behind SearchProvider. Fake transport only - no network, no real key."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import jarvis.research.providers.brave as B
from jarvis.research import ResearchUrlPolicy
from jarvis.research.providers.brave import BraveSearchProvider, SearchProviderError
from jarvis.research.search import SearchProviderUnavailable, SearchQuery, SearchRefused, SearchService, create_search_provider

KEY = "BSA-test-key-0123456789abcdef"
PAYLOAD = {"web": {"results": [
    {"title": "Eins", "url": "https://example.com/a", "description": "Auszug eins"},
    {"title": "Intern", "url": "http://127.0.0.1/admin", "description": "intern"},
    {"title": "Zwei", "url": "https://example.org/b", "description": "Auszug <b>zwei</b>"},
]}}


class FakeTransport:
    def __init__(self, status=200, body=None, exc=None):
        self.status, self.exc, self.calls = status, exc, []
        self.body = json.dumps(PAYLOAD).encode() if body is None else body

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        if self.exc:
            raise self.exc
        return self.status, self.body


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make(transport=None, **kw):
    kw.setdefault("clock", Clock())
    return BraveSearchProvider(KEY, transport=transport or FakeTransport(), **kw)


def test_search_returns_hits_and_sends_key_only_as_header():
    t = FakeTransport()
    hits = make(t).search(SearchQuery("python lernen", 5))
    assert [h.title for h in hits] == ["Eins", "Intern", "Zwei"]
    url, headers, timeout = t.calls[0]
    assert url.startswith("https://api.search.brave.com/res/v1/web/search?") and "q=python+lernen" in url and "count=5" in url
    assert headers["X-Subscription-Token"] == KEY and KEY not in url
    assert 0 < timeout <= 30
    assert hits[2].excerpt == "Auszug zwei"            # markup stripped


def test_missing_or_blank_key_is_a_clear_error():
    for k in (None, "", "   "):
        with pytest.raises(SearchProviderUnavailable, match="BRAVE_SEARCH_API_KEY"):
            BraveSearchProvider(k, transport=FakeTransport())


def test_rate_limit_refuses_too_fast_calls_without_sending():
    t, clock = FakeTransport(), Clock()
    p = BraveSearchProvider(KEY, transport=t, clock=clock, min_interval_seconds=1.0)
    p.search(SearchQuery("a"))
    with pytest.raises(SearchProviderError, match="rate limit"):
        p.search(SearchQuery("b"))
    assert len(t.calls) == 1
    clock.now += 1.01
    p.search(SearchQuery("c"))
    assert len(t.calls) == 2


def test_timeout_is_capped_and_validated():
    t = FakeTransport()
    make(t, timeout_seconds=7).search(SearchQuery("x"))
    assert t.calls[0][2] == 7
    for bad in (0, -1, 31, True):
        with pytest.raises(ValueError):
            make(timeout_seconds=bad)
    with pytest.raises(ValueError):
        make(min_interval_seconds=-1)


def test_transport_timeout_and_http_errors_never_leak_the_key():
    for t in (FakeTransport(exc=TimeoutError(f"timed out {KEY}")), FakeTransport(status=429, body=f"too many {KEY}".encode()),
              FakeTransport(status=500, body=b"x"), FakeTransport(body=b"not json"), FakeTransport(body=b'{"web": 5}')):
        with pytest.raises(SearchProviderError) as e:
            make(t).search(SearchQuery("x"))
        assert KEY not in str(e.value) and KEY not in repr(e.value)


def test_oversized_response_is_refused():
    with pytest.raises(SearchProviderError, match="too large"):
        make(FakeTransport(body=b"x" * (B.MAX_RESPONSE_BYTES + 1))).search(SearchQuery("x"))


def test_query_is_redacted_before_sending():
    t = FakeTransport()
    make(t).search(SearchQuery(f"wetter password: hunter2hunter2 {KEY} sk-abcdefghijklmnopqrstuvwx"))
    sent = t.calls[0][0]
    assert KEY not in sent and "hunter2" not in sent and "sk-abcdef" not in sent and "REDACTED" in sent


def test_hit_count_is_capped_by_query():
    many = {"web": {"results": [{"title": f"t{i}", "url": f"https://example.com/{i}", "description": ""} for i in range(30)]}}
    assert len(make(FakeTransport(body=json.dumps(many).encode())).search(SearchQuery("x", 3))) == 3


def test_service_guards_apply_to_the_brave_provider():
    t = FakeTransport()
    s = SearchService(make(t), ResearchUrlPolicy(), enabled=True)
    r = s.search("python")
    assert [h.title for h in r.hits] == ["Eins", "Zwei"] and r.refused and r.refused[0]["host"]     # private host dropped by the URL policy
    s.halt("test")
    with pytest.raises(SearchRefused):
        s.search("python")
    assert len(t.calls) == 1
    off = SearchService(make(t), ResearchUrlPolicy())
    with pytest.raises(SearchRefused, match="disabled"):
        off.search("python")


def test_service_reports_provider_failure_without_the_key():
    s = SearchService(make(FakeTransport(exc=OSError(KEY))), ResearchUrlPolicy(), enabled=True)
    r = s.search("python")
    assert r.error and KEY not in r.error


def test_factory_builds_brave_lazily_and_needs_the_key():
    p = create_search_provider("brave", api_key=KEY, transport=FakeTransport())
    assert isinstance(p, BraveSearchProvider)
    with pytest.raises(SearchProviderUnavailable, match="BRAVE_SEARCH_API_KEY"):
        create_search_provider("brave", transport=FakeTransport())


def test_default_transport_only_talks_https_to_the_brave_host():
    with pytest.raises(SearchProviderError):
        B.urllib_transport("http://api.search.brave.com/res/v1/web/search?q=x", {}, 5)
    with pytest.raises(SearchProviderError):
        B.urllib_transport("https://evil.example/res/v1/web/search?q=x", {}, 5)


def test_module_has_only_the_expected_imports_and_no_tool_bypass():
    tree = ast.parse(Path(B.__file__).read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module)
    bad = {m for m in mods if m.split(".")[0] in {"socket", "http", "requests", "httpx", "subprocess", "ssl", "playwright", "os", "threading"}
           or m.startswith(("jarvis.tools", "jarvis.permissions", "jarvis.browser", "jarvis.bootstrap", "jarvis.config"))}
    assert not bad, bad


def test_pyproject_keeps_empty_hard_dependencies():
    text = (Path(B.__file__).parents[4] / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in text
