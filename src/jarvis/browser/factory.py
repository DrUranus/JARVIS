"""Builds the browser subsystem. Never raises for an unusable provider: JARVIS must start without it.

    settings.browser -> provider (lazy import) -> BrowserController -> tool in the ToolRegistry
                     -> baseline policy rules in the PermissionEngine

Status: disabled (config) | unavailable (library missing, with the reason) | enabled | halted (emergency stop).
The browser itself is only launched by an approved `browser action=start`.
"""
from __future__ import annotations

import atexit
import importlib.util
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis.browser.backend import BrowserProvider
from jarvis.browser.controller import BrowserController
from jarvis.browser.errors import BrowserError, BrowserUnavailableError
from jarvis.browser.policy import baseline_rules
from jarvis.browser.tools import register_browser_tools
from jarvis.config import BrowserSettings, Settings
from jarvis.errors import JarvisError
from jarvis.permissions import PermissionEngine, Policy
from jarvis.tools import ToolRegistry

log = logging.getLogger("jarvis.browser")

INSTALL_HINT = "pip install -e \".[browser]\"  und danach  python -m playwright install chromium"
ProviderBuilder = Callable[[BrowserSettings], BrowserProvider]
_BUILDERS: dict[str, ProviderBuilder] = {}


def register_provider(name: str, builder: ProviderBuilder) -> None:
    """Add a provider (e.g. another automation library). Selected via browser.provider."""
    _BUILDERS[name.lower()] = builder


def _build_fake(settings: BrowserSettings) -> BrowserProvider:
    from jarvis.browser.providers.fake import FakeBrowserProvider
    return FakeBrowserProvider()


def _build_playwright(settings: BrowserSettings) -> BrowserProvider:
    if importlib.util.find_spec("playwright") is None:
        raise BrowserUnavailableError(f"the 'playwright' package is not installed ({INSTALL_HINT})")
    from jarvis.browser.providers.playwright_provider import PlaywrightProvider
    return PlaywrightProvider()


register_provider("fake", _build_fake)
register_provider("playwright", _build_playwright)


@dataclass
class BrowserSubsystem:
    """What the rest of the application sees (the Core stores it as an opaque subsystem)."""
    status: str                                   # disabled | unavailable | enabled
    reason: str = ""
    controller: BrowserController | None = None
    tool_names: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.controller is not None

    def halt(self, reason: str = "stopped by user") -> bool:
        if self.controller is None:
            return False
        self.controller.halt(reason)
        return True

    def resume(self) -> bool:
        if self.controller is None:
            return False
        self.controller.resume()
        return True

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason, "tools": self.tool_names}
        if self.controller is not None:
            info.update(self.controller.overview())
            if self.controller.halted:
                info["status"] = "halted"
        return info


def build_browser(settings: Settings, registry: ToolRegistry, engine: PermissionEngine) -> BrowserSubsystem:
    bs = settings.browser
    if not bs.enabled:
        return BrowserSubsystem("disabled", "browser agent is off (browser.enabled = false)")
    builder = _BUILDERS.get(bs.provider.lower())
    if builder is None:
        return BrowserSubsystem("unavailable", f"unknown browser provider {bs.provider!r}; available: {sorted(_BUILDERS)}")
    try:
        provider = builder(bs)
    except BrowserError as exc:
        log.warning("browser agent unavailable: %s", exc)
        return BrowserSubsystem("unavailable", str(exc))
    except Exception as exc:  # whatever a provider does, JARVIS still starts
        log.warning("browser agent unavailable: %s", type(exc).__name__)
        return BrowserSubsystem("unavailable", f"provider failed to initialise ({type(exc).__name__})")
    previous = engine.policy
    try:
        # baseline rules first: if they cannot be installed, the tool is not registered at all (fail closed)
        engine.update_policy(Policy(tuple(previous.rules) + tuple(baseline_rules(bs))), source="browser baseline")
        try:
            controller = BrowserController(provider, bs)
            names = register_browser_tools(registry, controller)
        except Exception:
            engine.update_policy(previous, source="browser rollback")  # no half-installed state
            raise
    except JarvisError as exc:
        log.warning("browser agent not enabled: %s", exc)
        return BrowserSubsystem("unavailable", f"could not install the safety rules or tool: {type(exc).__name__}: {exc}")
    if provider.name != "fake":
        atexit.register(controller.shutdown)  # never leave a browser process behind
    log.info("browser agent enabled (provider=%s)", provider.name)
    return BrowserSubsystem("enabled", f"provider {provider.name}", controller, names)
