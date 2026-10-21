"""Fake browser for tests and library-free development: a tiny scripted 'web' and pages that behave like tabs.

No network, no real browser. Form values typed into fields ARE recorded (so tests can assert on them) - which is
exactly why this class is only used in tests/development, never as a production provider.
"""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from jarvis.browser.backend import BrowserPage, BrowserProvider, BrowserSession, UrlGuard
from jarvis.browser.errors import BrowserError, BrowserErrorCode, BrowserUnavailableError
from jarvis.browser.models import DownloadResult, ElementInfo, LaunchOptions, PageInfo, PageSnapshot


@dataclass
class FakeDoc:
    url: str
    title: str = ""
    text: str = ""
    elements: list[ElementInfo] = field(default_factory=list)
    nav: dict[str, str] = field(default_factory=dict)            # locator -> url opened by click/submit
    popups: dict[str, str] = field(default_factory=dict)         # locator -> url opened in a NEW tab by click
    downloads: dict[str, tuple[str, bytes]] = field(default_factory=dict)  # locator -> (suggested name, content)
    forms: int = 0

    def with_locators(self) -> "FakeDoc":
        self.elements = [replace(e, locator=str(i)) for i, e in enumerate(self.elements)]
        return self


def el(tag: str, role: str = "", name: str = "", **kw: Any) -> ElementInfo:
    return ElementInfo(locator="", tag=tag, role=role or {"a": "link", "button": "button", "select": "combobox",
                                                         "textarea": "textbox"}.get(tag, "textbox" if tag == "input" else tag),
                       name=name, **kw)


class FakeWeb:
    def __init__(self) -> None:
        self.docs: dict[str, FakeDoc] = {}
        self.redirects: dict[str, str] = {}
        self.slow: set[str] = set()

    def add(self, doc: FakeDoc) -> FakeDoc:
        self.docs[doc.url] = doc.with_locators()
        return doc

    def fetch(self, url: str) -> FakeDoc:
        return self.docs.get(url) or FakeDoc(url, "404", "not found").with_locators()


class FakePage(BrowserPage):
    def __init__(self, session: "FakeSession", key: str) -> None:
        self._s, self._key = session, key
        self.url = "about:blank"
        self.history: list[str] = ["about:blank"]
        self.pos = 0
        self.closed = False
        self.values: dict[str, str] = {}
        self.checked: dict[str, bool] = {}
        self.blocked = 0
        self.doc = FakeDoc("about:blank").with_locators()

    # -- helpers ----------------------------------------------------------------------------------------------------
    def _hit(self, name: str, *args: Any) -> None:
        self._s.p.calls.append((name, args))
        fault = self._s.p._faults.pop(name, None)
        if fault is not None:
            raise fault
        if self.closed:
            raise BrowserError(BrowserErrorCode.PAGE_NOT_FOUND, "page closed")

    def _load(self, url: str, push: bool = True) -> None:
        seen = 0
        while True:
            if not self._s.guard(url, True):
                raise BrowserError(BrowserErrorCode.BLOCKED_TARGET, "request blocked by policy")
            if url in self._s.web.slow:
                raise TimeoutError("navigation timeout")
            nxt = self._s.web.redirects.get(url)
            if nxt is None or seen > 5:
                break
            url, seen = nxt, seen + 1
        self.url, self.doc = url, self._s.web.fetch(url)
        self.values, self.checked = {}, {}
        if push:
            self.history = self.history[: self.pos + 1] + [url]
            self.pos += 1

    @property
    def key(self) -> str:
        return self._key

    def info(self) -> PageInfo:
        self._hit("page.info")
        return PageInfo(self.url, self.doc.title)

    def is_closed(self) -> bool:
        return self.closed

    def goto(self, url: str, timeout: float) -> PageInfo:
        self._hit("page.goto", url)
        self._load(url)
        return self.info()

    def _step(self, delta: int, name: str) -> PageInfo:
        self._hit(name)
        if 0 <= self.pos + delta < len(self.history):
            self.pos += delta
            self._load(self.history[self.pos], push=False)
        return self.info()

    def back(self, timeout: float) -> PageInfo:
        return self._step(-1, "page.back")

    def forward(self, timeout: float) -> PageInfo:
        return self._step(1, "page.forward")

    def reload(self, timeout: float) -> PageInfo:
        self._hit("page.reload")
        self._load(self.url, push=False)
        return self.info()

    def bring_to_front(self) -> None:
        self._hit("page.front")

    def _current(self, locator: str) -> ElementInfo | None:
        for e in self.doc.elements:
            if e.locator == locator:
                return replace(e, has_value=bool(self.values.get(locator)) or e.has_value,
                               checked=self.checked.get(locator, e.checked))
        return None

    def snapshot(self, max_text: int, max_elements: int) -> PageSnapshot:
        self._hit("page.snapshot")
        els = tuple(self._current(e.locator) for e in self.doc.elements[:max_elements])  # type: ignore[misc]
        pw = any(e.sensitive and e.type == "password" for e in self.doc.elements)
        return PageSnapshot(PageInfo(self.url, self.doc.title), self.doc.text[:max_text], els, self.doc.forms, pw,
                            len(self.doc.text) > max_text)

    def describe(self, locator: str) -> ElementInfo | None:
        self._hit("page.describe", locator)
        return self._current(locator)

    def _act(self, locator: str, name: str) -> ElementInfo:
        self._hit(name, locator)
        cur = self._current(locator)
        if cur is None:
            raise BrowserError(BrowserErrorCode.ELEMENT_NOT_FOUND, "no such element")
        return cur

    def _follow(self, locator: str) -> None:
        if locator in self.doc.downloads:
            self.blocked += 1
        elif locator in self.doc.popups:
            self._s.open_popup(self.doc.popups[locator])
        elif locator in self.doc.nav:
            self._load(self.doc.nav[locator])

    def click(self, locator: str, timeout: float) -> None:
        self._act(locator, "page.click")
        self._follow(locator)

    def fill(self, locator: str, text: str, timeout: float) -> None:
        self._act(locator, "page.fill")
        self.values[locator] = text
        self._s.p.typed.append(text)

    def select(self, locator: str, option: str, timeout: float) -> None:
        self._act(locator, "page.select")
        self.values[locator] = option

    def check(self, locator: str, checked: bool, timeout: float) -> None:
        self._act(locator, "page.check")
        self.checked[locator] = checked

    def submit(self, locator: str, timeout: float) -> None:
        self._act(locator, "page.submit")
        self._follow(locator)

    def set_file(self, locator: str, path: str, timeout: float) -> None:
        self._act(locator, "page.set_file")
        self.values[locator] = os.path.basename(path)
        self._s.p.uploaded.append(path)

    def download(self, locator: str, directory: str, max_bytes: int, timeout: float) -> DownloadResult:
        self._act(locator, "page.download")
        if locator not in self.doc.downloads:
            raise BrowserError(BrowserErrorCode.DOWNLOAD_FAILED, "that element did not start a download")
        name, data = self.doc.downloads[locator]
        path = os.path.join(directory, "dl-" + str(next(self._s.p._ids)))
        with open(path, "wb") as f:
            f.write(data)
        return DownloadResult(name, len(data), path)

    def blocked_downloads(self) -> int:
        return self.blocked

    def close(self) -> None:
        self._hit("page.close")
        self.closed = True


class FakeSession(BrowserSession):
    def __init__(self, provider: "FakeBrowserProvider", options: LaunchOptions, guard: UrlGuard) -> None:
        self.p, self.options, self.guard, self.web = provider, options, guard, provider.web
        self.alive = True
        self._pages: list[FakePage] = []

    def open_popup(self, url: str) -> FakePage:
        page = self._new()
        page._load(url)
        return page

    def _new(self) -> FakePage:
        page = FakePage(self, f"k{next(self.p._ids)}")
        self._pages.append(page)
        return page

    def new_page(self) -> BrowserPage:
        self.p.calls.append(("session.new_page", ()))
        return self._new()

    def pages(self) -> list[BrowserPage]:
        return [p for p in self._pages if not p.closed]

    def is_alive(self) -> bool:
        return self.alive

    def close(self) -> None:
        self.p.calls.append(("session.close", ()))
        self.alive = False
        for p in self._pages:
            p.closed = True


class FakeBrowserProvider(BrowserProvider):
    name = "fake"

    def __init__(self, web: FakeWeb | None = None) -> None:
        self.web = web or FakeWeb()
        self.calls: list[tuple[str, tuple]] = []
        self.typed: list[str] = []
        self.uploaded: list[str] = []
        self.sessions: list[FakeSession] = []
        self.unavailable: str | None = None
        self._faults: dict[str, BaseException] = {}
        self._ids = itertools.count(1)

    def fail_next(self, method: str, error: BaseException) -> None:
        self._faults[method] = error

    def calls_named(self, prefix: str) -> list[tuple[str, tuple]]:
        return [c for c in self.calls if c[0].startswith(prefix)]

    def start(self, options: LaunchOptions, guard: UrlGuard) -> BrowserSession:
        self.calls.append(("provider.start", ()))
        if self.unavailable:
            raise BrowserUnavailableError(self.unavailable)
        s = FakeSession(self, options, guard)
        self.sessions.append(s)
        return s
