"""Dynamic tool registry and the only sanctioned way to execute a tool.

    execute -> describe call -> PermissionRequest -> PermissionEngine.authorize -> (approved scope) -> tool.run

Execution never raises: every failure (including every denial) becomes a ToolResult.fail.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from jarvis.errors import PermissionDeniedError, ToolError
from jarvis.permissions import (ActionSpec, DecisionStatus, PermissionEngine, PermissionLevel, PermissionRequest,
                                args_fingerprint, max_level)
from jarvis.tools.base import ProtectedTool, Tool, ToolResult

log = logging.getLogger("jarvis.tools")


class ToolRegistry:
    def __init__(self, permissions: PermissionEngine | None = None) -> None:
        """Without an engine a bare registry uses the lenient `PermissionEngine.legacy()` (Phase-1 semantics,
        still routed through the engine). The application passes a strict, configured engine."""
        self._tools: dict[str, Tool] = {}
        self._permissions: PermissionEngine = permissions or PermissionEngine.legacy()

    @property
    def permissions(self) -> PermissionEngine:
        """Read-only: the engine of a registry cannot be swapped for a laxer one after construction."""
        return self._permissions

    @classmethod
    def strict(cls, **engine_options: Any) -> "ToolRegistry":
        """Registry with a default-deny engine: undeclared tools count as YELLOW, non-GREEN tools must be
        ProtectedTool, no filesystem roots, nobody to ask (YELLOW needs a configured confirmation provider)."""
        return cls(PermissionEngine(**engine_options))

    def register(self, tool: Tool, replace: bool = False) -> None:
        name = getattr(tool, "name", None)
        if not name:
            raise ToolError("tool must define a non-empty name")
        if name in self._tools and not replace:
            raise ToolError(f"tool already registered: {name}")
        level = getattr(tool, "permission", None)
        problem = self._tool_problem(tool, level)
        if problem:
            raise ToolError(f"cannot register {name!r}: {problem}")
        self._tools[name] = tool
        self._permissions.note_tool_registered(name, level)

    def _tool_problem(self, tool: Tool, level: PermissionLevel | None) -> str | None:
        if isinstance(tool, ProtectedTool) and tool.is_tampered():
            return "ProtectedTool.run was replaced; the permission check cannot be bypassed this way"
        return self._permissions.tool_problem(level, isinstance(tool, ProtectedTool))

    def unregister(self, name: str) -> None:
        if self._tools.pop(name, None) is None:
            raise ToolError(f"unknown tool: {name}")

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(f"unknown tool: {name}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe_all(self) -> list[dict[str, Any]]:
        return [self._tools[n].describe() for n in self.names()]

    def execute(self, name: str, confirmed: bool = False, **kwargs: Any) -> ToolResult:
        """Run a tool through the permission engine.

        `confirmed=True` is the legacy Phase-1 flag ("the caller already asked the user"). Only lenient legacy
        engines honour it; the application's engine ignores it (and audits that), so no code path can
        self-confirm a YELLOW action.
        """
        engine = self._permissions
        try:
            tool = self.get(name)
        except ToolError as exc:
            return ToolResult.fail(str(exc))
        missing = [p.name for p in tool.parameters if p.required and p.name not in kwargs]
        if missing:
            return ToolResult.fail(f"missing parameters for {name!r}: {', '.join(missing)}")

        declared = getattr(tool, "permission", None)
        problem = self._tool_problem(tool, declared)  # re-checked on every call: levels/run can be changed later
        if problem:
            return ToolResult.fail(f"permission denied for tool {name!r}: {problem}")
        level = declared if declared is not None else engine.undeclared_level

        try:
            spec = tool.describe_action(**kwargs)
            if not isinstance(spec, ActionSpec):
                raise TypeError("describe_action must return an ActionSpec")
            request = PermissionRequest(
                tool=name, action=spec.action, level=max_level(level, spec.level or level), resource=spec.resource,
                resource_type=spec.resource_type, reason=spec.reason, context=dict(spec.context),
                args_fingerprint=args_fingerprint(name, kwargs))
        except Exception as exc:  # a tool that cannot describe its action cannot be judged: deny
            log.warning("tool %s could not describe its action: %s", name, type(exc).__name__)
            return ToolResult.fail(f"invalid permission request for tool {name!r}: "
                                   f"{engine.redact(f'{type(exc).__name__}: {exc}')}")

        decision = engine.authorize(request, caller_confirmed=confirmed)
        if not decision.allowed:
            label = {DecisionStatus.CONFIRMATION_REQUIRED: "confirmation required",
                     DecisionStatus.INVALID_REQUEST: "invalid permission request",
                     DecisionStatus.POLICY_ERROR: "security error",
                     DecisionStatus.INTERNAL_ERROR: "security error"}.get(decision.status, "permission denied")
            return ToolResult(False, None, f"{label} for tool {name!r}: {decision.reason}", decision)

        try:
            with engine.execution_scope(request, decision):
                result = tool.run(**kwargs)
        except PermissionDeniedError as exc:
            return ToolResult(False, None, f"permission denied for tool {name!r}: {engine.redact(str(exc))}", decision)
        except Exception as exc:  # tools are untrusted plug-ins; isolate failures, never leak secrets
            safe = engine.redact(f"{type(exc).__name__}: {exc}")
            log.error("tool %s crashed: %s", name, safe)  # no traceback: its message line could carry secrets
            result = ToolResult.fail(safe)
        if not isinstance(result, ToolResult):
            result = ToolResult.fail(f"tool {name!r} returned an invalid result")
        elif not result.success and result.error:
            result = dataclasses.replace(result, error=engine.redact(result.error))
        engine.record_execution(request, decision, result.success, result.error)
        return dataclasses.replace(result, permission=result.permission or decision)
