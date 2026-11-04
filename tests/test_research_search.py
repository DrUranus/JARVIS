"""Research search interface (step research-search-interface): SearchProvider, FakeSearchProvider, SearchService. No network, no real search source."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import jarvis.research.search as S
from jarvis.research import (InvalidResearchRequest, ResearchUrlPolicy)
from jarvis.research.search import (FakeSearchProvider, MAX_HITS_CAP, MAX_QUERY_CHARS, SearchHit, SearchProvider, SearchProviderUnavailable, SearchQuery,
                                    SearchRefused, SearchService, create_search_provider)

HITS = [SearchHit("Eins", "https://example.com/a?utm_source=x", "Auszug eins"),
        SearchHit("Intern", "http://127.0.0.1/admin", "intern"),
        SearchHit("Meta", "http://169.254.169.254/latest", "meta"),
        SearchHit("Datei", "file:///etc/passwd", "datei"),
        SearchHit("Zwei", "https://example.org/b", "Auszug zwei"),
        SearchHit("Doppelt", "https://www.example.com/a", "dup")]


def svc(**kw):
    kw.setdefault("enabled", True)
    kw.setdefault("provider", FakeSearchProvider(HITS))
    kw.setdefault("policy", ResearchUrlPolicy())
    return SearchService(**kw)


# ---- query and hit limits --------------------------------------------------------------------------------------------------------------------
def test_query_has_hard_caps():
    q = SearchQuery("  hallo  ", max_hits=3)
    assert q.text == "hallo" and q.max_hits == 3
    assert SearchQuery("x").max_hits <= MAX_HITS_CAP
    for bad in ("", "   ", "a" * (MAX_QUERY_CHARS + 1), 5, None, "a\x00b"):
        with pytest.raises(InvalidResearchRequest):
            SearchQuery(bad)
    for bad in (0, -1, MAX_HITS_CAP + 1, True, "3"):
        with pytest.raises(InvalidResearchRequest):
            SearchQuery("x", max_hits=bad)


def test_hit_fields_are_clipped_and_json_compatible():
    h = SearchHit("t" * 1000, "https://example.com/" + "p" * 3000, "e" * 5000)
    assert len(h.title) <= 200 and len(h.url) <= 500 and len(h.excerpt) <= 500
    json.dumps(h.to_dict())
    assert "Auszug" not in repr(SearchHit("t", "https://example.com/", "Auszug geheim"))


def test_fake_provider_is_a_search_provider_and_respects_max_hits():
    p = FakeSearchProvider(HITS)
    assert isinstance(p, SearchProvider)
    assert len(p.search(SearchQuery("x", max_hits=2))) == 2
    assert p.calls == 1


def test_fake_provider_cannot_exceed_the_cap_even_with_many_hits():
    many = [SearchHit(f"t{i}", f"https://example.com/{i}", "") for i in range(500)]
    assert len(FakeSearchProvider(many).search(SearchQuery("x", max_hits=MAX_HITS_CAP))) <= MAX_HITS_CAP


# ---- every hit URL goes through the existing URL policy ----------------------------------------------------------------------------------------
def test_hit_urls_pass_the_existing_url_policy():
    r = svc().search("python", max_hits=10)
    urls = [h.url for h in r.hits]
    assert urls == ["https://example.com/a", "https://example.org/b"]          # canonicalised (tracking removed), duplicate merged
    assert len(r.refused) == 3 and all(x["reason"] for x in r.refused)
    assert {x["host"] for x in r.refused} >= {"127.0.0.1", "169.254.169.254"}


def test_service_uses_the_given_policy_allow_and_exclusion_lists():
    r = svc(policy=ResearchUrlPolicy(allowed_domains=("example.org",))).search("x")
    assert [h.url for h in r.hits] == ["https://example.org/b"]
    r = svc(policy=ResearchUrlPolicy(excluded_domains=("example.org",))).search("x")
    assert "https://example.org/b" not in [h.url for h in r.hits]


def test_service_calls_the_policy_for_every_hit():
    seen = []

    class Spy(ResearchUrlPolicy):
        def check(self, raw):
            seen.append(raw)
            return super().check(raw)
    svc(policy=Spy()).search("x", max_hits=10)
    assert len(seen) == len(HITS)


def test_provider_returning_more_than_max_hits_is_cut():
    class Greedy:
        def search(self, query):
            return [SearchHit(f"t{i}", f"https://example.com/{i}", "") for i in range(100)]
    r = svc(provider=Greedy()).search("x", max_hits=4)
    assert len(r.hits) == 4


def test_provider_returning_garbage_is_handled():
    class Bad:
        def search(self, query):
            return [None, "https://example.com", {"url": 1}]
    r = svc(provider=Bad()).search("x")
    assert r.hits == () and r.error == ""


# ---- off by default, emergency stop, session budget ---------------------------------------------------------------------------------------------
def test_disabled_by_default_and_never_calls_provider():
    p = FakeSearchProvider(HITS)
    s = SearchService(provider=p, policy=ResearchUrlPolicy())
    assert s.status()["enabled"] is False
    with pytest.raises(SearchRefused, match="disabled"):
        s.search("x")
    assert p.calls == 0


def test_halt_blocks_until_resume():
    p = FakeSearchProvider(HITS)
    s = svc(provider=p)
    s.halt("emergency")
    assert s.status()["halted"] == "emergency"
    with pytest.raises(SearchRefused, match="halted"):
        s.search("x")
    assert p.calls == 0
    s.resume()
    assert s.search("x").hits and p.calls == 1


def test_search_budget_is_enforced_and_capped():
    p = FakeSearchProvider(HITS)
    s = svc(provider=p, max_searches=2)
    s.search("a"); s.search("b")
    with pytest.raises(SearchRefused, match="budget"):
        s.search("c")
    assert p.calls == 2
    assert svc(max_searches=10_000).status()["max_searches"] <= S.MAX_SEARCHES_CAP
    with pytest.raises(ValueError):
        svc(max_searches=0)


def test_session_budget_refusal_blocks_the_search():
    p = FakeSearchProvider(HITS)
    booked = []
    s = svc(provider=p, budget_check=lambda: "Sitzungsbudget erschöpft")
    with pytest.raises(SearchRefused, match="Sitzungsbudget"):
        s.search("x")
    assert p.calls == 0 and not booked


def test_provider_errors_become_a_result_not_a_crash():
    class Boom:
        def search(self, query):
            raise RuntimeError("secret-token-123 leaked")
    r = svc(provider=Boom()).search("x")
    assert r.hits == () and r.error and "secret-token-123" not in r.error


def test_invalid_query_does_not_use_budget_or_provider():
    p = FakeSearchProvider(HITS)
    s = svc(provider=p, max_searches=1)
    with pytest.raises(InvalidResearchRequest):
        s.search("")
    assert p.calls == 0 and s.search("ok").hits


# ---- optional library: lazy factory, clear message -----------------------------------------------------------------------------------------------
def test_factory_builds_the_fake_without_any_library():
    assert isinstance(create_search_provider("fake", hits=HITS), FakeSearchProvider)


def test_factory_unknown_or_missing_library_is_a_clear_error(monkeypatch):
    with pytest.raises(SearchProviderUnavailable, match="unknown"):
        create_search_provider("gibtsnicht")
    with pytest.raises(SearchProviderUnavailable):
        create_search_provider("")


# ---- structure: no fetch path, no network, no tool bypass --------------------------------------------------------------------------------------
SRC = Path(S.__file__)
FORBIDDEN = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "playwright", "subprocess", "ssl", "ftplib", "smtplib", "webbrowser", "trafilatura",
             "jarvis.browser", "jarvis.tools", "jarvis.permissions", "jarvis.bootstrap"}


def test_search_module_has_no_network_or_fetch_imports():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module)
    bad = {m for m in mods if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)}
    assert not bad, bad


def test_pages_are_fetched_only_via_existing_controlled_paths():
    """Only research/agent.py reaches pages (through the agent gateway -> browser tool -> PermissionEngine). The search module has no fetch path at all
    and no other research module (and nothing in the agent) imports it."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    names = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"execute", "toolregistry", "toolgateway", "gateway", "goto", "open", "browser", "popen", "urlopen", "fetch"}, names
    for f in SRC.parent.glob("*.py"):
        if f.name != "search.py":
            assert f.name == "__init__.py" or "research.search" not in f.read_text(encoding="utf-8"), f.name


def test_pyproject_keeps_empty_hard_dependencies():
    text = (SRC.parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in text
