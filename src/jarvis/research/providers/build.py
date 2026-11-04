"""Composition of the opt-in search source from plain settings values and the environment (called only from the composition code, see agents/factory.py)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from jarvis.research.providers.brave import ENV_KEY
from jarvis.research.search import SearchProviderUnavailable, SearchService, create_search_provider

SENDS = ("query text (secrets redacted, max 300 chars), hit count, API key (header) and your IP address, over HTTPS to api.search.brave.com only; "
         "no page content, files, memory or screen data")


@dataclass
class ResearchSearchSubsystem:
    """The opt-in web search (Brave Search API). Wraps `SearchService`: off by default, refuses while the emergency stop is engaged (`halt`) and when the
    session budget is used up. It starts nothing by itself."""
    status: str                            # enabled | disabled
    reason: str = ""
    service: Any = None
    sends: str = SENDS

    @property
    def available(self) -> bool:
        return self.status == "enabled" and self.service is not None

    def halt(self, reason: str = "stopped by user") -> bool:
        if self.service is None:
            return False
        self.service.halt(reason)
        return True

    def resume(self) -> None:
        if self.service is not None:
            self.service.resume()

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"name": "research_search", "status": self.status, "reason": self.reason, "provider": "brave", "sends": self.sends}
        if self.service is not None:
            info.update(self.service.status())
        return info


def build_research_search(r: Any, env: Mapping[str, str] | None = None, budget_check: Callable[[], str | None] | None = None,
                          transport: Any = None) -> ResearchSearchSubsystem:
    """`r` is the research settings. `env` and `transport` are injectable for tests (default: os.environ and the HTTPS transport)."""
    if not r.search_enabled:
        return ResearchSearchSubsystem("disabled", "web search is off (research.search_enabled = false)")
    env = os.environ if env is None else env
    try:
        provider = create_search_provider(r.search_provider, api_key=env.get(ENV_KEY), transport=transport,
                                          timeout_seconds=r.search_timeout_seconds, min_interval_seconds=r.search_min_interval_seconds)
    except SearchProviderUnavailable as exc:
        return ResearchSearchSubsystem("disabled", str(exc))
    return ResearchSearchSubsystem("enabled", "", SearchService(provider, enabled=True, max_searches=r.search_max_searches, budget_check=budget_check))
