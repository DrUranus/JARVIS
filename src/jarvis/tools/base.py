"""Tool interface. Tools are self-describing so an LLM/planner can choose them.

Permissions: a tool never talks to the permission engine. It only *describes* a call (`describe_action`); the
ToolRegistry builds the request, the engine decides, and only then does `run` happen. Tools that are not GREEN
derive from `ProtectedTool`, whose `run()` refuses to execute outside an engine-approved scope.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from jarvis.permissions import ActionSpec, PermissionLevel
from jarvis.permissions.grants import verify_execution


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
    permission: Any = None  # the PermissionDecision behind a denial / the approval behind an execution

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
    # Declared risk of the tool. None = undeclared: strict registries treat that as YELLOW (fail closed).
    permission: PermissionLevel | None = None

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool. Expected failures should return ToolResult.fail. Call it only through
        ToolRegistry.execute, which performs the permission check."""

    def describe_action(self, **kwargs: Any) -> ActionSpec:
        """Describe what this concrete call would do (action, resource, reason). Override for tools that touch
        files, hosts or accounts. The engine can raise the level but a tool can never lower it below its
        declared `permission`."""
        return ActionSpec(action="run")

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "permission": self.permission.value if self.permission else "undeclared",
            "parameters": [p.__dict__.copy() for p in self.parameters],
        }


class ProtectedTool(Tool):
    """Base for tools with consequences. Implement `_perform`; `run` is sealed and verifies, on every call,
    that the permission engine approved exactly this call (same tool, same arguments, single use)."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.run is not ProtectedTool.run:  # also catches overrides inherited from a mixin
            raise TypeError(f"{cls.__name__}: ProtectedTool subclasses implement _perform(), never run()")

    def run(self, **kwargs: Any) -> ToolResult:
        verify_execution(self.name, kwargs)  # raises PermissionDeniedError without an engine-issued grant
        return self._perform(**kwargs)

    def is_tampered(self) -> bool:
        """True if `run` was replaced on this instance or class (the registry then refuses to use the tool)."""
        return "run" in getattr(self, "__dict__", {}) or type(self).run is not ProtectedTool.run

    @abstractmethod
    def _perform(self, **kwargs: Any) -> ToolResult:
        """The actual work. Reached only after the permission engine approved this call."""
