"""Wiring of the Brave search source (step research-search-provider): config defaults, builder, emergency stop. Fake transport only."""
from __future__ import annotations

import json

import pytest

from jarvis.agents.factory import build_research_search
from jarvis.config import ConfigError, ResearchSettings, Settings

KEY = "BSA-test-key-0123456789abcdef"
BODY = json.dumps({"web": {"results": [{"title": "Eins", "url": "https://example.com/a", "description": "x"}]}}).encode()


def cfg(**kw) -> Settings:
    return Settings(research=ResearchSettings(**kw))


def tr(calls):
    def t(url, headers, timeout):
        calls.append(url)
        return 200, BODY
    return t


def test_defaults_are_off_and_safe():
    r = Settings().research
    assert r.search_enabled is False and r.search_provider == "brave"
    assert r.search_max_searches <= 100 and r.search_timeout_seconds <= 30
    sub = build_research_search(Settings(), env={"BRAVE_SEARCH_API_KEY": KEY})
    assert not sub.available and "off" in sub.reason and sub.service is None


@pytest.mark.parametrize("kw", [{"search_provider": "google"}, {"search_max_searches": 101}, {"search_max_searches": 0}, {"search_timeout_seconds": 31},
                                {"search_timeout_seconds": 0}, {"search_min_interval_seconds": -1}])
def test_invalid_limits_are_rejected(kw):
    with pytest.raises(ConfigError):
        cfg(**kw).validate()


def test_enabled_without_key_stays_unavailable_with_a_clear_reason():
    sub = build_research_search(cfg(search_enabled=True), env={})
    assert not sub.available and "BRAVE_SEARCH_API_KEY" in sub.reason and KEY not in sub.reason


def test_enabled_with_key_works_and_obeys_budget_halt_and_session_budget():
    calls = []
    refusal = {"v": None}
    sub = build_research_search(cfg(search_enabled=True, search_max_searches=2, search_min_interval_seconds=0), env={"BRAVE_SEARCH_API_KEY": KEY},
                                budget_check=lambda: refusal["v"], transport=tr(calls))
    assert sub.available
    assert sub.service.search("python").hits[0].title == "Eins"
    refusal["v"] = "session budget used up"
    from jarvis.research.search import SearchRefused
    with pytest.raises(SearchRefused, match="session budget"):
        sub.service.search("python")
    refusal["v"] = None
    assert sub.halt("Notaus: test") is True
    with pytest.raises(SearchRefused, match="halted"):
        sub.service.search("python")
    sub.resume()
    sub.service.search("python")
    with pytest.raises(SearchRefused, match="budget"):
        sub.service.search("python")
    assert len(calls) == 2
    assert KEY not in json.dumps(sub.describe())


def test_halt_when_off_is_a_noop():
    sub = build_research_search(Settings(), env={})
    assert not sub.available
    sub.resume()


def test_bootstrap_registers_the_search_source_with_the_emergency_stop(monkeypatch, tmp_path):
    from jarvis.bootstrap import build_core
    from jarvis.research.search import SearchRefused
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", KEY)
    s = cfg(search_enabled=True)
    assert not build_core(Settings()).subsystems["research_search"].available            # default: off, nothing built
    core = build_core(s)
    sub = core.subsystems["research_search"]
    assert sub.available
    assert "research_search" in core.permissions.emergency.names()
    core.permissions.emergency.trigger("test", "t")
    with pytest.raises(SearchRefused, match="Notaus"):
        sub.service.search("python")
    assert sub.service.status()["halted"] is not None            # the registered stopper also halted the service itself
