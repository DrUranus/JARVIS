"""Search interface of the research layer (step research-search-interface): a `SearchProvider` turns a bounded query into hits (title, URL, excerpt).

This module only DEFINES the interface, a fake provider and a guarding `SearchService`. It has no network access, no real search source and no way to
read a page: a hit is only a candidate. Every hit URL is run through the existing `ResearchUrlPolicy` (urls.py) and only the canonical, accepted
URLs are returned. The pages themselves are read - as before - by the research agent through the permission-checked `browser` tool.

The service is off by default (`enabled=False`), refuses while halted (emergency stop, same halt/resume pattern as the other controllers) and has a
search budget plus an optional session-budget hook. A real provider library may only be an optional extra, imported lazily in `create_search_provider`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from jarvis.research.errors import InvalidResearchRequest, ResearchError
from jarvis.research.models import clip
from jarvis.research.urls import ResearchUrlPolicy

MAX_QUERY_CHARS = 300
MAX_HITS_CAP = 20            # hard upper limit of hits per query, whatever the caller asks for
DEFAULT_HITS = 8
MAX_SEARCHES_CAP = 100       # hard upper limit of searches per session
DEFAULT_MAX_SEARCHES = 20


class SearchRefused(ResearchError):
    """The search was not run: disabled, halted or out of budget."""


class SearchProviderUnavailable(ResearchError):
    """The requested provider is unknown or its optional library is not installed."""


@dataclass(frozen=True)
class SearchQuery:
    text: str
    max_hits: int = DEFAULT_HITS

    def __post_init__(self) -> None:
        t = self.text
        if not isinstance(t, str) or not t.strip():
            raise InvalidResearchRequest("the search query must be non-empty text")
        t = t.strip()
        if len(t) > MAX_QUERY_CHARS or any(ord(c) < 32 or ord(c) == 127 for c in t):
            raise InvalidResearchRequest(f"the search query is too long (max {MAX_QUERY_CHARS}) or contains control characters")
        n = self.max_hits
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_HITS_CAP:
            raise InvalidResearchRequest(f"max_hits must be an integer from 1 to {MAX_HITS_CAP}")
        object.__setattr__(self, "text", t)


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    excerpt: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", clip(self.title, 200))
        object.__setattr__(self, "url", clip(self.url, 500))
        object.__setattr__(self, "excerpt", clip(self.excerpt, 500))

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "excerpt": self.excerpt}


@runtime_checkable
class SearchProvider(Protocol):
    def search(self, query: SearchQuery) -> Sequence[SearchHit]: ...


class FakeSearchProvider:
    """Deterministic provider for tests and offline use: returns its fixed hits (at most `query.max_hits`). Never touches the network."""

    def __init__(self, hits: Sequence[SearchHit] = ()) -> None:
        self._hits = tuple(hits)
        self.calls = 0

    def search(self, query: SearchQuery) -> list[SearchHit]:
        self.calls += 1
        return list(self._hits[: query.max_hits])


@dataclass(frozen=True)
class SearchResult:
    query: str
    hits: tuple[SearchHit, ...] = ()
    refused: tuple[dict[str, str], ...] = ()      # hits dropped by the URL policy: {"host", "reason"} (the URL itself is not repeated)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"query": self.query, "hits": [h.to_dict() for h in self.hits], "refused": list(self.refused), "error": self.error}


class SearchService:
    """Guards a provider: enabled flag, emergency stop, budgets, query/hit caps and the URL policy for every hit."""

    def __init__(self, provider: SearchProvider | None = None, policy: ResearchUrlPolicy | None = None, enabled: bool = False,
                 max_searches: int = DEFAULT_MAX_SEARCHES, budget_check: Callable[[], str | None] | None = None) -> None:
        if not isinstance(max_searches, int) or isinstance(max_searches, bool) or max_searches < 1:
            raise ValueError("max_searches must be a positive integer")
        self._provider = provider
        self._policy = policy or ResearchUrlPolicy()
        self._enabled = bool(enabled)
        self._max = min(max_searches, MAX_SEARCHES_CAP)
        self._budget_check = budget_check          # returns a refusal text when the session budget is used up, else None
        self._halted: str | None = None
        self._used = 0

    def halt(self, reason: str = "stopped by user") -> None:
        self._halted = reason or "stopped by user"

    def resume(self) -> None:
        self._halted = None

    def status(self) -> dict[str, Any]:
        return {"enabled": self._enabled, "halted": self._halted, "searches": self._used, "max_searches": self._max}

    def search(self, text: str, max_hits: int = DEFAULT_HITS) -> SearchResult:
        query = SearchQuery(text, max_hits)           # validates before anything is booked
        if not self._enabled or self._provider is None:
            raise SearchRefused("search is disabled")
        if self._halted is not None:
            raise SearchRefused(f"search is halted ({self._halted}); resume it explicitly")
        if self._budget_check is not None:
            reason = self._budget_check()
            if reason:
                raise SearchRefused(reason)
        if self._used >= self._max:                   # no lock: research modules may not import threading (test_analysis_security); the agent calls this serially
            raise SearchRefused(f"search budget used up ({self._used}/{self._max}); restart JARVIS to continue")
        self._used += 1
        try:
            raw = list(self._provider.search(query))
        except Exception as e:                        # provider text may hold anything (keys, URLs): only the type is reported
            return SearchResult(query.text, error=f"the search provider failed ({type(e).__name__})")
        hits: list[SearchHit] = []
        refused: list[dict[str, str]] = []
        seen: set[str] = set()
        for h in raw:
            if not isinstance(h, SearchHit):
                continue
            d = self._policy.check(h.url)
            if not d.ok:
                refused.append({"host": d.host, "reason": d.reason})
                continue
            if d.key in seen:
                continue
            seen.add(d.key)
            hits.append(SearchHit(h.title, d.url, h.excerpt))
            if len(hits) >= query.max_hits:
                break
        return SearchResult(query.text, tuple(hits), tuple(refused))


def create_search_provider(name: str, **options: Any) -> SearchProvider:
    """Factory. Only 'fake' exists; a real source would be an optional extra imported HERE (lazily) with a clear message when it is missing."""
    if name == "fake":
        return FakeSearchProvider(options.get("hits", ()))
    raise SearchProviderUnavailable(f"unknown search provider {name!r}; available: fake")
