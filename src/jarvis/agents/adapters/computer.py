"""ComputerAgent: the six computer-control tools as one agent. Every step names its tool: {"tool": "mouse", "action": "click", "x": 1, "y": 2}."""
from __future__ import annotations

from jarvis.agents import policy as P
from jarvis.agents.adapters.base import ToolSpec, ToolStepAgent

_SCREEN = ("monitors", "screenshot", "compare", "windows", "active_window", "cursor", "forget")


class ComputerAgent(ToolStepAgent):
    id = "computer"
    name = "Computer Agent"
    description = "Looks at the screen and operates mouse, keyboard, windows and applications through the permission-checked computer tools."
    capabilities = frozenset({P.COMPUTER_SCREEN, P.COMPUTER_INPUT})
    tools = {
        "screen": ToolSpec(frozenset({"action", "monitor", "a", "b"}), {a: P.COMPUTER_SCREEN for a in _SCREEN}),
        "screen_save": ToolSpec(frozenset({"id", "path"}), capability=P.COMPUTER_SCREEN),
        "mouse": ToolSpec(frozenset({"action", "x", "y", "monitor", "amount", "window"}), {a: P.COMPUTER_INPUT for a in ("move", "click", "double_click", "right_click", "scroll")}),
        "keyboard": ToolSpec(frozenset({"action", "key", "keys", "text", "window"}), {a: P.COMPUTER_INPUT for a in ("press", "hotkey", "type")}),
        "window": ToolSpec(frozenset({"action", "handle"}), {a: P.COMPUTER_INPUT for a in ("focus", "minimize", "maximize", "restore", "close")}),
        "app": ToolSpec(frozenset({"app", "args"}), capability=P.COMPUTER_INPUT),
    }
