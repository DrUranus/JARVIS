"""ToolStepAgent: runs a list of structured steps, each one a single tool call through the gateway.

    input = {"steps": [{"action": "goto", "url": "https://example.com"}, {"action": "text"}]}      (for a one-tool agent)
    input = {"steps": [{"tool": "mouse", "action": "click", "x": 1, "y": 2}]}                        (for the computer agent)

A step must (1) name an action this agent knows, (2) need only capabilities the TASK allows (least privilege: a task that asks for
`coding.read` cannot write), and (3) use only parameters the tool documents. Then it is handed to the tool - where the permission
engine decides. The first failing step ends the task: a denied step is BLOCKED, any other failure FAILED, a cancel request CANCELLED.
Nothing here can confirm, force or skip a permission."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext
from jarvis.agents.errors import TaskCancelled, ToolAccessError
from jarvis.agents.models import AgentTask
from jarvis.agents.state import TaskStatus
from jarvis.agents.result import AgentOutcome

MAX_STEPS = 50
MAX_STEP_OUTPUT = 4000


def _clip(value: Any, limit: int = MAX_STEP_OUTPUT) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, dict):
        return {str(k): _clip(v, limit) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_clip(v, limit) for v in list(value)[:50]]
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:limit]


@dataclass(frozen=True)
class ToolSpec:
    """What one tool accepts from an agent: its parameters and which capability each action needs."""
    params: frozenset[str]
    actions: Mapping[str, str] | None = None   # action -> capability (tools with an `action` parameter)
    capability: str | None = None              # fixed capability (tools without an `action` parameter)


class ToolStepAgent(Agent):
    """Subclasses define `tools` (tool name -> ToolSpec); `tool_names` is derived from it. With a single tool, steps need no "tool" key."""

    tools: Mapping[str, ToolSpec] = {}
    interruptible_actions: frozenset[str] = frozenset()  # actions long enough that a cancel should also stop the running tool call

    def __init__(self, *, interrupt: Any = None) -> None:
        super().__init__()
        self.tool_names = frozenset(self.tools)
        self._interrupt = interrupt  # optional: the subsystem's own halt, used only to stop work that is already running
        self._active_action: str | None = None

    def cancel(self, task_id: str) -> None:
        if self._interrupt is not None and self._active_action in self.interruptible_actions:
            self._interrupt()

    # -- hooks for adapters with conditional steps (default: none) -------------------------------------------------------------------------
    def _take_extra(self, i: int, tool: str, args: dict[str, Any], ctx: AgentContext) -> tuple[Any, AgentOutcome | None]:
        """May remove adapter-specific keys from `args` (before the parameter check) and return them as the step's `extra`; an AgentOutcome ends the planning."""
        return None, None

    def _unreachable(self, tool: str, res: Any) -> str | None:
        """Does this failure (res None: tool not available) mean 'the target cannot be reached this way'? Only then a step's `extra` is used."""
        return None

    def _recover(self, i: int, extra: Any, reason: str, gateway: Any, ctx: AgentContext, results: list[dict[str, Any]]) -> AgentOutcome | None:
        """Run the step's `extra` after an unreachable failure; return an AgentOutcome to end the task, None to go on."""
        return None

    def _annotate(self, results: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        """(suffix for the summary, extra output keys) for a finished task."""
        return "", {}

    def _plan_list(self, steps: list[Any], ctx: AgentContext, *, nested: bool = False) -> list[tuple[str, dict[str, Any], Any]] | AgentOutcome:
        only = next(iter(self.tools)) if len(self.tools) == 1 else None
        planned: list[tuple[str, dict[str, Any], Any]] = []
        for i, step in enumerate(steps, 1):
            args = dict(step)
            tool = args.pop("tool", only)
            spec = self.tools.get(tool) if isinstance(tool, str) else None
            if spec is None:
                return AgentOutcome.failed(f"step {i}: the tool {str(tool)[:30]!r} does not belong to this agent", code="invalid_input")
            extra, stop = (None, None) if nested else self._take_extra(i, tool, args, ctx)
            if stop is not None:
                return stop
            if spec.actions is not None:
                action = args.get("action")
                if not isinstance(action, str) or action not in spec.actions:
                    return AgentOutcome.failed(f"step {i}: unknown action {str(action)[:30]!r} for {tool}", code="invalid_input")
                cap = spec.actions[action]
            else:
                cap = spec.capability or ""
            if cap not in ctx.allowed_capabilities:
                return AgentOutcome.blocked(f"step {i}: {tool} {args.get('action', '')} needs the capability {cap!r}, which this task does not allow".replace("  ", " "),
                                            code="capability_not_allowed")
            unknown = set(args) - spec.params
            if unknown:
                return AgentOutcome.failed(f"step {i}: unknown parameters {sorted(unknown)}", code="invalid_input")
            planned.append((tool, args, extra))
        return planned

    def _plan_steps(self, task: AgentTask, ctx: AgentContext) -> list[tuple[str, dict[str, Any], Any]] | AgentOutcome:
        steps = task.input.get("steps")
        if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS or not all(isinstance(s, dict) for s in steps):
            return AgentOutcome.failed(f"input.steps must be a list of 1..{MAX_STEPS} step objects", code="invalid_input")
        return self._plan_list(steps, ctx)

    def _failure(self, i: int, res: Any, results: list[dict[str, Any]]) -> AgentOutcome:
        """The outcome of a failed tool result (the entry is already in `results`)."""
        denied = getattr(res.permission, "status", None) is not None and not getattr(res.permission, "allowed", True)
        if denied:  # the permission engine said no (RED, user declined, lockdown ...): that is BLOCKED, not a crash
            return AgentOutcome.blocked(f"step {i} was refused by the permission system: {_clip(res.error or 'denied', 300)}",
                                        code="permission_denied", output={"steps": results})
        if (isinstance(res.output, dict) and res.output.get("code") == "failsafe") or "[failsafe]" in (res.error or ""):
            return AgentOutcome.blocked(f"step {i}: the subsystem is halted", code="halted", output={"steps": results})
        return AgentOutcome.failed(f"step {i} failed: {_clip(res.error or 'failed', 300)}", code="step_failed", output={"steps": results})

    def perform(self, task: AgentTask, ctx: AgentContext) -> AgentOutcome:
        plan = self._plan_steps(task, ctx)
        if isinstance(plan, AgentOutcome):
            return plan
        gateway = ctx.tools
        if gateway is None:
            return AgentOutcome.failed("no tool access was given to this agent", code="no_tools")
        results: list[dict[str, Any]] = []
        for i, (tool, args, extra) in enumerate(plan, 1):
            res = None
            reason: str | None = None
            try:
                if not gateway.available(tool):
                    reason = self._unreachable(tool, None) if extra is not None else None
                    if reason is None:
                        return AgentOutcome.failed(f"step {i}: the tool {tool!r} is not available (its subsystem is not enabled)", code="tool_unavailable",
                                                   output={"steps": results})
                else:
                    self._active_action = args.get("action")
                    try:
                        res = gateway.call(tool, **args)
                    finally:
                        self._active_action = None
            except TaskCancelled:
                return AgentOutcome(TaskStatus.CANCELLED, f"cancelled after {len(results)} step(s)", {"steps": results}, None, "cancelled")
            except ToolAccessError as exc:
                return AgentOutcome.failed(str(exc), code="tool_access_denied", output={"steps": results})
            entry = {"step": i, "tool": tool, "action": args.get("action"), "ok": bool(res.success) if res is not None else False}
            if res is not None and res.success:
                entry["output"] = _clip(res.output)
                results.append(entry)
                if ctx.is_cancelled():  # cancelled while this step ran (it may have been cut short): stop here, report what is known
                    return AgentOutcome(TaskStatus.CANCELLED, f"cancelled during step {i} of {len(plan)} (its result is included)", {"steps": results}, None, "cancelled")
                continue
            entry["error"] = _clip(res.error or "failed", 500) if res is not None else "the tool is not available"
            if res is not None and extra is not None:
                reason = self._unreachable(tool, res)
            if reason is not None:
                entry["unreachable_reason"] = reason
                results.append(entry)
                stop = self._recover(i, extra, reason, gateway, ctx, results)
                if stop is not None:
                    return stop
                continue
            results.append(entry)
            return self._failure(i, res, results)
        suffix, more = self._annotate(results)
        return AgentOutcome.ok(f"{len(results)} step(s) done{suffix}", {"steps": results, **more})
