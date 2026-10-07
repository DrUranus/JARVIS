"""Capability names, limits and the validation rules shared by the models. Capabilities say which agent is *suitable* for a
task; they never grant anything - every real action still goes through ToolRegistry and PermissionEngine."""
from __future__ import annotations

import re

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,31}$")
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

BROWSER_READ, BROWSER_INTERACT = "browser.read", "browser.interact"
CODING_READ, CODING_WRITE, CODING_TEST, CODING_PLAN = "coding.read", "coding.write", "coding.test", "coding.plan"
COMPUTER_SCREEN, COMPUTER_INPUT = "computer.screen", "computer.input"
RESEARCH_WEB = "research.web"
BUSINESS_ANALYZE, FINANCE_ANALYZE = "business.analyze", "finance.analyze"

KNOWN_CAPABILITIES = frozenset({BROWSER_READ, BROWSER_INTERACT, CODING_READ, CODING_WRITE, CODING_TEST, CODING_PLAN, COMPUTER_SCREEN,
                                COMPUTER_INPUT, RESEARCH_WEB, BUSINESS_ANALYZE, FINANCE_ANALYZE})

MAX_OBJECTIVE = 2000
MAX_INPUT_BYTES = 100_000
MAX_INPUT_DEPTH = 8
MAX_METADATA_ITEMS = 20
MAX_TIMEOUT = 3600.0
MAX_TEXT = 20_000
RESERVED_TOOL_ARGS = frozenset({"confirmed", "confirm", "force", "bypass", "skip_permissions", "unsafe", "grant", "approval"})


def valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(ID_RE.match(value))


def valid_agent_id(value: object) -> bool:
    return isinstance(value, str) and bool(AGENT_ID_RE.match(value))


def valid_capability(value: object) -> bool:
    return isinstance(value, str) and bool(CAPABILITY_RE.match(value))
