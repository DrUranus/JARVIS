"""Brave Search API behind `SearchProvider` (step research-search-provider; the one source chosen in docs/integrations/research.md).

WHAT LEAVES THE MACHINE (per search): the query text (after secret redaction, <= 300 chars), the result count, and the API key as the header
`X-Subscription-Token`, plus the usual connection data (your IP) - sent over HTTPS to api.search.brave.com ONLY. Nothing else: no page content, no
files, no memory, no screen data. Hits are returned as candidates and are not stored by this module (Brave terms: no permanent storage without a plan
with storage rights). The key comes from the environment only (BRAVE_SEARCH_API_KEY), is never logged and never appears in an error text.

The transport is a plain callable `(url, headers, timeout) -> (status, body)`; tests pass a fake, the default speaks HTTPS to the fixed host with
the standard library (no dependency, no redirects). The provider does not touch pages, tools or the permission engine; `SearchService` guards it
(off by default, emergency stop, budgets, URL policy for every hit)."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

from jarvis.redaction import SecretDetector
from jarvis.research.errors import ResearchError
from jarvis.research.search import SearchHit, SearchProviderUnavailable, SearchQuery

ENV_KEY = "BRAVE_SEARCH_API_KEY"
HOST = "api.search.brave.com"
ENDPOINT = f"https://{HOST}/res/v1/web/search"
MAX_RESPONSE_BYTES = 1_000_000
MAX_TIMEOUT_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MIN_INTERVAL_SECONDS = 1.0       # Brave's entry plan allows 1 request per second
MAX_MIN_INTERVAL_SECONDS = 60.0
_TAG = re.compile(r"<[^>]*>")

Transport = Callable[[str, Mapping[str, str], float], "tuple[int, bytes]"]


class SearchProviderError(ResearchError):
    """A search request failed. The text never contains the key, the query or the response body."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any):
        return None


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
    """Default transport: HTTPS GET to the fixed Brave host only, no redirects, response size capped."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HOST or parts.username or parts.password:
        raise SearchProviderError("the search transport only talks HTTPS to the Brave Search host")
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:      # noqa: S310 - scheme and host checked above
            return resp.status, resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SearchProviderError(f"the search request failed ({type(exc).__name__})") from None


def _plain(text: Any, limit: int) -> str:
    return html.unescape(_TAG.sub("", text if isinstance(text, str) else ""))[:limit]


class BraveSearchProvider:
    def __init__(self, api_key: str | None, transport: Transport | None = None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise SearchProviderUnavailable(f"the Brave search source needs its API key in the environment variable {ENV_KEY}")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout_seconds must be > 0 and <= {MAX_TIMEOUT_SECONDS}")
        if isinstance(min_interval_seconds, bool) or not isinstance(min_interval_seconds, (int, float)) \
                or not 0 <= min_interval_seconds <= MAX_MIN_INTERVAL_SECONDS:
            raise ValueError(f"min_interval_seconds must be 0..{MAX_MIN_INTERVAL_SECONDS}")
        self._key = api_key.strip()
        self._transport = transport or urllib_transport
        self._timeout = timeout_seconds
        self._interval = min_interval_seconds
        self._clock = clock
        self._last: float | None = None
        self._detector = SecretDetector([self._key])

    def __repr__(self) -> str:
        return "BraveSearchProvider()"

    def search(self, query: SearchQuery) -> list[SearchHit]:
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            raise SearchProviderError("search rate limit: too many requests, try again shortly")
        self._last = now
        params = urllib.parse.urlencode({"q": self._detector.redact(query.text)[:300], "count": query.max_hits, "text_decorations": "false"})
        try:
            status, body = self._transport(f"{ENDPOINT}?{params}", {"X-Subscription-Token": self._key, "Accept": "application/json"}, self._timeout)
        except SearchProviderError:
            raise
        except Exception as exc:
            raise SearchProviderError(f"the search request failed ({type(exc).__name__})") from None
        if status != 200:
            raise SearchProviderError(f"the search source answered HTTP {status}")
        if len(body) > MAX_RESPONSE_BYTES:
            raise SearchProviderError("the search response is too large")
        try:
            results = json.loads(body.decode("utf-8", "replace"))["web"]["results"]
            if not isinstance(results, list):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise SearchProviderError("the search response has an unexpected format") from None
        hits = []
        for r in results:
            if isinstance(r, dict) and isinstance(r.get("url"), str):
                hits.append(SearchHit(_plain(r.get("title"), 200), r["url"], _plain(r.get("description"), 500)))
            if len(hits) >= query.max_hits:
                break
        return hits
