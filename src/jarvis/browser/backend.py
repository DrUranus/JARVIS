"""Provider interfaces of the browser agent. The core and the controller know only these; a concrete automation
library (Playwright, or something else later) lives in `providers/` and is imported lazily by the factory."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from jarvis.browser.models import DownloadResult, ElementInfo, LaunchOptions, PageInfo, PageSnapshot

# Decides whether the browser may request a URL at all (navigations, redirects and sub-resources). Installed by the
# controller when a session starts, enforced by the provider inside the browser engine: a redirect or a page script
# cannot lead somewhere the controller would have refused.
UrlGuard = Callable[[str, bool], bool]   # (url, is_navigation) -> allowed


class BrowserPage(ABC):
    """One tab. Providers return plain data; the controller decides whether anything may happen."""

    @property
    @abstractmethod
    def key(self) -> str:
        """Stable identity of this tab inside its session (never reused after the tab is closed)."""

    @abstractmethod
    def info(self) -> PageInfo: ...

    @abstractmethod
    def is_closed(self) -> bool: ...

    @abstractmethod
    def goto(self, url: str, timeout: float) -> PageInfo: ...

    @abstractmethod
    def back(self, timeout: float) -> PageInfo: ...

    @abstractmethod
    def forward(self, timeout: float) -> PageInfo: ...

    @abstractmethod
    def reload(self, timeout: float) -> PageInfo: ...

    @abstractmethod
    def bring_to_front(self) -> None: ...

    @abstractmethod
    def snapshot(self, max_text: int, max_elements: int) -> PageSnapshot:
        """Visible text and the interactive elements, in document order. Locators are valid for this snapshot only
        in the sense that the controller re-describes the element before acting on it."""

    @abstractmethod
    def describe(self, locator: str) -> ElementInfo | None:
        """The element behind `locator` as it is RIGHT NOW, or None if there is nothing there."""

    @abstractmethod
    def click(self, locator: str, timeout: float) -> None: ...

    @abstractmethod
    def fill(self, locator: str, text: str, timeout: float) -> None: ...

    @abstractmethod
    def select(self, locator: str, option: str, timeout: float) -> None: ...

    @abstractmethod
    def check(self, locator: str, checked: bool, timeout: float) -> None: ...

    @abstractmethod
    def submit(self, locator: str, timeout: float) -> None: ...

    @abstractmethod
    def set_file(self, locator: str, path: str, timeout: float) -> None: ...

    @abstractmethod
    def download(self, locator: str, directory: str, max_bytes: int, timeout: float) -> DownloadResult:
        """Click the element and capture the download it triggers into the (private) `directory`."""

    @abstractmethod
    def blocked_downloads(self) -> int:
        """How many downloads this page started that nobody asked for (they are cancelled)."""

    @abstractmethod
    def close(self) -> None: ...


class BrowserSession(ABC):
    """A running browser with one fresh, isolated, non-persistent profile."""

    @abstractmethod
    def new_page(self) -> BrowserPage: ...

    @abstractmethod
    def pages(self) -> list[BrowserPage]:
        """Open tabs, including popups opened by pages."""

    @abstractmethod
    def is_alive(self) -> bool: ...

    @abstractmethod
    def close(self) -> None: ...


class BrowserProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def start(self, options: LaunchOptions, guard: UrlGuard) -> BrowserSession:
        """Launch a browser. Raises BrowserUnavailableError if the library or the browser binary is missing."""
