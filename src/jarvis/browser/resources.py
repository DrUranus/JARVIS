"""Resource URIs: what the permission engine (and the user, and policy rules) see for each browser action.

    browser://session/<sid>                       start / stop of the browser
    browser://page/<sid>/<pid>@<host>             one tab (host of the page it shows)
    browser://element/<sid>/<pid>/<eid>@<host>    one element of one tab

Navigation uses the engine's own DOMAIN resource type (the URL; the engine reduces it to a normalised host), so the
usual host rules apply ("example.com", "*.example.com"). Downloads and uploads use PATH resources and therefore go
through the PathGuard like every other file access. Policy rules for the URIs above are plain engine globs, e.g.
resources = ["browser://element/*@*.example.com"] (resource_type "other"). Typed text is NEVER part of a resource.
"""
from __future__ import annotations

import re

TOOL = "browser"
_UNSAFE = re.compile(r"[^\w.\-:]")


def _clean(text: str, limit: int = 80) -> str:
    return _UNSAFE.sub("_", text.strip())[:limit] or "unknown"


def session_resource(sid: str) -> str:
    return f"browser://session/{_clean(sid, 40)}"


def page_resource(sid: str, pid: str, host: str) -> str:
    return f"browser://page/{_clean(sid, 40)}/{_clean(pid, 40)}@{_clean(host, 253)}"


def element_resource(sid: str, pid: str, eid: str, host: str) -> str:
    return f"browser://element/{_clean(sid, 40)}/{_clean(pid, 40)}/{_clean(eid, 40)}@{_clean(host, 253)}"
