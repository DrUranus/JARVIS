"""Thin adapters that turn the existing tools (browser, coding, computer) into agents. They hold no controller and no provider: every step
is a call through `ctx.tools` (ToolGateway -> ToolRegistry -> PermissionEngine)."""
from jarvis.agents.adapters.base import ToolStepAgent
from jarvis.agents.adapters.browser import BrowserAgent
from jarvis.agents.adapters.coding import CodingAgent
from jarvis.agents.adapters.computer import ComputerAgent
from jarvis.agents.adapters.research import ResearchAgent

__all__ = ["ToolStepAgent", "BrowserAgent", "CodingAgent", "ComputerAgent", "ResearchAgent"]
