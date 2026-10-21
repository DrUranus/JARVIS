"""URL classification: which addresses the browser agent may visit, and how a URL is shown without leaking secrets.

Only http(s) pages (and about:blank) are ever opened. Everything that could read local files, run script from the
address bar, reach internal network services or leave the browser (file:, javascript:, data:, chrome:, view-source:,
ftp:, mailto: ...) is RED. Private/loopback/link-local addresses and single-label or internal-looking host names are RED
unless the user listed that exact host in `browser.private_hosts_allowed`; cloud metadata endpoints are RED always.
DNS is deliberately not resolved here (a name that resolves to a private address is not detected; see the README).
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from jarvis.errors import InvalidRequestError
from jarvis.permissions import PermissionLevel
from jarvis.permissions.resources import host_matches, normalize_host

GREEN, YELLOW, RED = PermissionLevel.GREEN, PermissionLevel.YELLOW, PermissionLevel.RED
BLANK = "about:blank"
MAX_URL = 2048
ALWAYS_BLOCKED_HOSTS = ("metadata.google.internal", "metadata", "instance-data", "100.100.100.200")
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet", ".localdomain")
_SENSITIVE_QUERY = re.compile(r"pass|pwd|secret|token|key|auth|session|sid|code|sig|credential|bearer", re.I)


@dataclass(frozen=True)
class UrlVerdict:
    level: PermissionLevel
    reason: str = ""
    host: str = ""          # normalised host ("" for about:blank)
    shown: str = ""         # sanitised URL for prompts/audit/results

    @property
    def blocked(self) -> bool:
        return self.level is RED


def is_private_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return "." not in host or host == "localhost" or host.endswith(_INTERNAL_SUFFIXES)
    return not ip.is_global or ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast


def _always_blocked(host: str) -> bool:
    if host in ALWAYS_BLOCKED_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_link_local or str(ip) in ALWAYS_BLOCKED_HOSTS or (ip.version == 6 and str(ip).startswith("fd00:ec2"))


def safe_url(url: str, limit: int = 160) -> str:
    """scheme://host[:port]/path - no credentials, no query values, no fragment."""
    if url == BLANK:
        return BLANK
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        port = f":{p.port}" if p.port else ""
    except ValueError:
        return "(invalid URL)"
    if not p.scheme or not host:
        return f"({p.scheme or 'unknown'} URL)"
    shown = f"{p.scheme}://{host}{port}{p.path}"
    if p.query:
        keys = [k.split("=")[0] for k in p.query.split("&") if k]
        shown += "?" + "&".join(f"{k}=…" for k in keys[:6]) + ("&…" if len(keys) > 6 else "")
    return shown if len(shown) <= limit else shown[:limit - 1] + "…"


def url_key(url: str) -> str:
    """Identity of a document for 'is this still the same page': scheme://host:port/path."""
    try:
        p = urlsplit(url)
        return f"{p.scheme}://{(p.hostname or '').lower()}{':' + str(p.port) if p.port else ''}{p.path}"
    except ValueError:
        return ""


class UrlPolicy:
    def __init__(self, trusted_hosts=(), blocked_hosts=(), private_hosts_allowed=()) -> None:
        self._trusted = tuple(h.strip().lower() for h in trusted_hosts)
        self._blocked = tuple(h.strip().lower() for h in blocked_hosts)
        self._private_ok = tuple(h.strip().lower() for h in private_hosts_allowed)

    def classify(self, url: object, *, navigation: bool = True) -> UrlVerdict:
        """GREEN: trusted host | YELLOW: any other public http(s) page | RED: everything forbidden."""
        if not isinstance(url, str) or not url.strip():
            return UrlVerdict(RED, "empty or invalid URL")
        u = url.strip()
        if len(u) > MAX_URL or any(ord(c) < 32 or ord(c) == 127 for c in u):
            return UrlVerdict(RED, "URL too long or contains control characters")
        if u == BLANK:
            return UrlVerdict(GREEN, "", "", BLANK)
        try:
            p = urlsplit(u)
            host_raw = p.hostname
            _ = p.port
        except ValueError:
            return UrlVerdict(RED, "malformed URL")
        scheme = p.scheme.lower()
        if scheme not in ("http", "https"):
            return UrlVerdict(RED, f"scheme {scheme or '(none)'!r} is never opened by the browser agent (only http/https)")
        if p.username is not None or p.password is not None:
            return UrlVerdict(RED, "URLs with embedded credentials are refused")
        if not host_raw:
            return UrlVerdict(RED, "URL has no host")
        try:
            host = normalize_host(host_raw)
        except InvalidRequestError as exc:
            return UrlVerdict(RED, f"invalid host: {exc}")
        shown = safe_url(u)
        if _always_blocked(host):
            return UrlVerdict(RED, "cloud metadata / link-local addresses are never visited", host, shown)
        if any(host_matches(b, host) for b in self._blocked):
            return UrlVerdict(RED, "this host is blocked (browser.blocked_hosts)", host, shown)
        if is_private_host(host) and host not in self._private_ok:
            return UrlVerdict(RED, "internal / private-network addresses are not visited "
                                   "(list the exact host in browser.private_hosts_allowed to allow it)", host, shown)
        if any(host_matches(t, host) for t in self._trusted):
            return UrlVerdict(GREEN, "", host, shown)
        return UrlVerdict(YELLOW, "", host, shown)

    def allowed_for_browser(self, url: str, is_navigation: bool) -> bool:
        """The check the provider enforces inside the browser engine for every request."""
        if url == BLANK:
            return True
        if not is_navigation and url.split(":", 1)[0].lower() in ("data", "blob"):
            return True  # inline images/fonts; never as a top-level page
        return not self.classify(url).blocked
