"""Which addresses the research agent may even TRY to read. This is a first filter in front of the browser tool, never a replacement: the browser
controller and the permission engine still judge every navigation (and may refuse more). It never allows more than the browser allows - internal
hosts are only usable when the user listed the exact host in browser.private_hosts_allowed, which the composition root mirrors here.

Refused: anything but http(s) (javascript:, data:, file:, ftp:, mailto: ...), credentials inside the URL, internal / private / loopback / link-local
addresses and names (also obfuscated forms like 2130706433 or 0x7f.1), cloud-metadata hosts, hosts outside an allow-list or inside an exclusion list.
DNS is deliberately not resolved here (a public name that points to a private address is not detected by this layer; the browser layer has the same limit).
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_URL = 2048
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet", ".localdomain", ".home.arpa")
_METADATA = frozenset({"metadata.google.internal", "metadata", "instance-data", "100.100.100.200", "169.254.169.254", "fd00:ec2::254"})
_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|msclkid|mc_eid|igshid|ref_src)$", re.I)
_SENSITIVE = re.compile(r"pass|pwd|secret|token|key|auth|session|sid|credential|bearer|signature|^sig$|^code$", re.I)


@dataclass(frozen=True)
class UrlDecision:
    ok: bool
    url: str = ""          # canonical URL to visit (only when ok)
    reason: str = ""
    host: str = ""

    @property
    def key(self) -> str:
        """Identity for de-duplication: the canonical URL without a leading 'www.'."""
        if not self.url:
            return ""
        p = urlsplit(self.url)
        host = p.hostname or ""
        host = host[4:] if host.startswith("www.") else host
        return urlunsplit((p.scheme, host + (f":{p.port}" if p.port else ""), p.path, p.query, ""))


def _host_matches(host: str, domain: str) -> bool:
    d = domain.strip().lower().lstrip(".")
    return bool(d) and (host == d or host.endswith("." + d))


def normalize_domains(domains: object, what: str = "domains") -> tuple[str, ...]:
    if domains is None:
        return ()
    if not isinstance(domains, (list, tuple)) or len(domains) > 50:
        raise ValueError(f"{what} must be a list of at most 50 host names")
    out = []
    for d in domains:
        if not isinstance(d, str) or not re.fullmatch(r"[A-Za-z0-9.\-]{1,253}", d.strip()) or ".." in d:
            raise ValueError(f"{what} contains an invalid host name")
        out.append(d.strip().lower().lstrip("."))
    return tuple(dict.fromkeys(out))


class ResearchUrlPolicy:
    def __init__(self, allowed_domains: tuple[str, ...] = (), excluded_domains: tuple[str, ...] = (), private_hosts_allowed: tuple[str, ...] = ()) -> None:
        self.allowed = tuple(allowed_domains)
        self.excluded = tuple(excluded_domains)
        self._private_ok = frozenset(h.strip().lower() for h in private_hosts_allowed)      # exact hosts only, mirrored from browser.private_hosts_allowed

    def check(self, raw: object) -> UrlDecision:
        if not isinstance(raw, str) or not raw.strip():
            return UrlDecision(False, reason="not a URL")
        url = raw.strip()
        if len(url) > MAX_URL or any(ord(c) < 33 or ord(c) == 127 for c in url):
            return UrlDecision(False, reason="malformed URL (length or control characters/whitespace)")
        if "\\" in url:      # browsers read a backslash as '/': 'https://good.example\@evil.test' means different things to different parsers
            return UrlDecision(False, reason="URLs containing a backslash are ambiguous and refused")
        try:
            p = urlsplit(url)
            host = (p.hostname or "").lower().rstrip(".")
            port = p.port
        except ValueError:
            return UrlDecision(False, reason="malformed URL")
        scheme = p.scheme.lower()
        if scheme not in ("http", "https"):
            return UrlDecision(False, reason=f"only http(s) pages are read (not {scheme or 'a relative address'}:)")
        if not host:
            return UrlDecision(False, reason="the URL has no host")
        if p.username is not None or p.password is not None or "@" in p.netloc:
            return UrlDecision(False, reason="URLs with credentials are never used", host=host)
        if host in _METADATA:
            return UrlDecision(False, reason="cloud metadata hosts are never read", host=host)
        private = self._private_reason(host)
        if private and host not in self._private_ok:
            return UrlDecision(False, reason=private, host=host)
        if private and host in self._private_ok and host in _METADATA:
            return UrlDecision(False, reason="cloud metadata hosts are never read", host=host)
        if any(_host_matches(host, d) for d in self.excluded):
            return UrlDecision(False, reason="the host is on the exclusion list", host=host)
        if self.allowed and not any(_host_matches(host, d) for d in self.allowed):
            return UrlDecision(False, reason="the host is not on the allow-list", host=host)
        return UrlDecision(True, self.canonical(scheme, host, port, p.path, p.query), "", host)

    @staticmethod
    def _private_reason(host: str) -> str:
        h = host.strip("[]")
        try:
            ip = ipaddress.ip_address(h)
        except ValueError:
            if re.fullmatch(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*", h, re.I):
                return "numeric host spellings are refused"           # 2130706433, 0x7f.1, 127.1 ... (a valid dotted quad is handled above)
            if "." not in h or h == "localhost" or h.endswith(_INTERNAL_SUFFIXES):
                return "internal or single-label host names are refused"
            return ""
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        if str(ip) in _METADATA or ip.is_link_local:
            return "link-local and metadata addresses are refused"
        if not ip.is_global or ip.is_loopback or ip.is_private or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return "internal, private or loopback addresses are refused"
        return ""

    @staticmethod
    def canonical(scheme: str, host: str, port: int | None, path: str, query: str) -> str:
        default = {"http": 80, "https": 443}[scheme]
        netloc = host if port in (None, default) else f"{host}:{port}"
        if ":" in host and not host.startswith("["):
            netloc = f"[{host}]" + ("" if port in (None, default) else f":{port}")
        kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if not _TRACKING.match(k) and not _SENSITIVE.search(k)]
        return urlunsplit((scheme, netloc, path or "/", urlencode(kept), ""))
