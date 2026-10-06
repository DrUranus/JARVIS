"""Tool interface. Tools are self-describing so an LLM/planner can choose them."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from jarvis.permissions import PermissionLevel


@dataclass(frozen=True)
class ToolParameter:
    name: str
    description: str
    type: str = "string"
    required: bool = True


@dataclass(frozen=True)
class ToolResult:
    success: bool
    output: Any = None
    error: str | None = None

    @classmethod
    def ok(cls, output: Any = None) -> "ToolResult":
        return cls(True, output)

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        return cls(False, None, error)


class Tool(ABC):
    name: str
    description: str
    parameters: tuple[ToolParameter, ...] = ()
    permission: PermissionLevel = PermissionLevel.GREEN

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool. Expected failures should return ToolResult.fail."""

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name, "description": self.description, "permission": self.permission.value,
            "parameters": [p.__dict__.copy() for p in self.parameters],
        }
