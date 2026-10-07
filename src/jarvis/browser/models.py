"""Plain data exchanged between the controller and a browser provider. No library types leak through here."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LaunchOptions:
    headless: bool = True
    browser: str = "chromium"          # chromium | chrome | msedge
    executable_path: str = ""
    navigation_timeout: float = 15.0   # seconds
    action_timeout: float = 5.0
    max_pages: int = 5
    max_download_bytes: int = 50_000_000
    viewport: tuple[int, int] = (1280, 800)


@dataclass(frozen=True)
class PageInfo:
    url: str = field(repr=False)   # raw URL as the browser reports it; the controller sanitises it before it is shown anywhere
    title: str = field(default="", repr=False)


@dataclass(frozen=True)
class ElementInfo:
    """What a provider knows about one interactive element (never its value: field contents are not read)."""
    locator: str                 # opaque provider token; only meaningful for the page snapshot it came from
    tag: str                     # a | button | input | select | textarea | summary | ...
    role: str = ""               # link | button | textbox | checkbox | radio | combobox | ...
    name: str = field(default="", repr=False)   # accessible name (aria-label / label / text / alt / placeholder)
    type: str = ""               # input type
    href: str = field(default="", repr=False)   # resolved link target (may carry tokens: never in a repr)
    dom_id: str = ""
    dom_name: str = ""
    form: int | None = None      # index of the enclosing form on the page
    form_action: str = field(default="", repr=False)  # resolved action URL of that form
    visible: bool = True
    enabled: bool = True
    checked: bool | None = None
    has_value: bool = False      # whether a text field currently holds something (the value itself is never exposed)
    options: tuple[str, ...] = ()  # <select> option labels
    sensitive: bool = False      # password / one-time-code / payment-card field
    in_login_form: bool = False  # its form (or, without a form, its page) contains a visible password field
    required: bool = False

    def fingerprint(self) -> str:
        """Identity of the LOGICAL element. Two snapshots describe the same element only if all of these agree."""
        parts = (self.tag, self.role, self.name, self.type, self.dom_id, self.dom_name, self.href.split("#")[0].split("?")[0])
        return hashlib.sha256("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()[:24]


@dataclass(frozen=True)
class PageSnapshot:
    info: PageInfo
    text: str = field(repr=False)
    elements: tuple[ElementInfo, ...] = field(repr=False)
    forms: int = 0
    has_password_field: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class ElementRef:
    """What the controller remembers about an element it showed to the caller (identity for later actions)."""
    eid: str
    session_id: str
    page_id: str
    url_key: str = field(repr=False)  # scheme://host/path of the page when the element was discovered (no query / fragment)
    locator: str
    fingerprint: str
    tag: str
    role: str
    name: str = field(repr=False)
    type: str
    sensitive: bool = False


@dataclass(frozen=True)
class DownloadResult:
    suggested_name: str
    size: int
    path: str = field(repr=False, default="")  # the provider's private temporary file


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def describe_element(ref: ElementRef) -> dict[str, Any]:
    return {"element": ref.eid, "tag": ref.tag, "role": ref.role, "name": clip(ref.name, 120), "type": ref.type}
