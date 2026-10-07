"""BrowserAgent: the `browser` tool as an agent. Steps are tool calls such as {"action": "goto", "url": "https://example.com"}."""
from __future__ import annotations

from jarvis.agents import policy as P
from jarvis.agents.adapters.base import ToolSpec, ToolStepAgent

_READ = ("status", "pages", "active", "info", "text", "links", "forms", "find")
_INTERACT = ("start", "stop", "new", "activate", "close", "goto", "back", "forward", "reload", "click", "fill", "select", "check", "submit",
             "upload", "download")
_ACTIONS = {**{a: P.BROWSER_READ for a in _READ}, **{a: P.BROWSER_INTERACT for a in _INTERACT}}
_PARAMS = frozenset({"action", "url", "page", "session", "element", "text", "value", "checked", "path", "role", "query", "limit"})


class BrowserAgent(ToolStepAgent):
    id = "browser"
    name = "Browser Agent"
    description = "Opens and reads web pages and interacts with them step by step through the permission-checked browser tool."
    capabilities = frozenset({P.BROWSER_READ, P.BROWSER_INTERACT})
    tools = {"browser": ToolSpec(_PARAMS, _ACTIONS)}
