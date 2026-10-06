"""Resource kinds and normalisation of non-path resources (hosts)."""
from __future__ import annotations

import ipaddress
import re
from enum import Enum
from urllib.parse import urlsplit

from jarvis.errors import InvalidRequestError


class ResourceType(str, Enum):
    NONE = "none"      # the action has no resource (e.g. "tell me the time")
    PATH = "path"      # filesystem path: checked against allowed roots / denied paths
    DOMAIN = "domain"  # host name or URL: normalised to a lowercase host
    OTHER = "other"    # opaque identifier (account, command line, order id...)


_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def normalize_host(value: str) -> str:
    """'HTTPS://Docs.Python.org:443/x' -> 'docs.python.org'. Raises InvalidRequestError on anything odd
    (credentials in the URL, spaces, empty labels...). IP literals are returned in canonical form."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("domain resource must be a non-empty string")
    v = value.strip()
    if "://" in v:
        try:
            parts = urlsplit(v)
            host = parts.hostname
            if parts.username is not None or parts.password is not None:
                raise InvalidRequestError("URLs with embedded credentials are not accepted as resources")
        except ValueError as exc:
            raise InvalidRequestError(f"invalid URL: {exc}") from exc
        if not host:
            raise InvalidRequestError("URL has no host")
    else:
        host = v
    if any(c in host for c in " /\\@?#\x00") or any(ord(c) < 32 for c in host):
        raise InvalidRequestError("invalid characters in host")
    host = host.rstrip(".").lower()
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidRequestError("invalid internationalised host name") from exc
    if not host or len(host) > 253 or not all(_LABEL.match(lbl) for lbl in host.split(".")):
        raise InvalidRequestError("invalid host name")
    return host


def host_matches(pattern: str, host: str) -> bool:
    """'example.com' = exactly that host; '*.example.com' = any proper subdomain (not the apex)."""
    pattern = pattern.strip().lower().rstrip(".")
    if pattern.startswith("*."):
        return host.endswith("." + pattern[2:]) and len(host) > len(pattern) - 1
    return host == pattern
