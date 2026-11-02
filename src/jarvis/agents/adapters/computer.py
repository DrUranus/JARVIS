"""ComputerAgent: the computer-control tools as one agent. Every step names its tool: {"tool": "mouse", "action": "click", "x": 1, "y": 2}.

Operating tasks go through the UI tree first: `ui` (windows | tree | find, read-only) and `ui_act` (invoke | set_value | select | toggle | focus by UIA pattern).
Screenshot and coordinates are only a FALLBACK for a control that UI Automation cannot reach: a `ui_act` step may carry
    "fallback": {"tool": "mouse", "action": "click", "x": 1, "y": 2}      (or a short list of mouse/keyboard steps)
which runs only if that step failed because no control matched (`control_not_found`) or UIA is not available at all - never after a refusal, a halt, an ambiguous match
or an unconfirmed change. The fallback takes a screenshot first, stays YELLOW (every step is confirmed by the PermissionEngine) and is named in the result
(`fallback: "screenshot_coordinates"`, `unreachable_reason`, `fallback_for`). When UIA tools exist, a coordinate click is not an ordinary step. There is no loop here:
the orchestrator with its limits stays the only control loop."""
from __future__ import annotations

from typing import Any

from jarvis.agents import policy as P
from jarvis.agents.adapters.base import MAX_STEP_OUTPUT, ToolSpec, ToolStepAgent, _clip
from jarvis.agents.context import AgentContext
from jarvis.agents.errors import TaskCancelled, ToolAccessError
from jarvis.agents.result import AgentOutcome
from jarvis.agents.state import TaskStatus

_SCREEN = ("monitors", "screenshot", "compare", "windows", "active_window", "cursor", "forget")
_CLICKS = ("click", "double_click", "right_click")
_UI_ACT = ("invoke", "set_value", "select", "toggle", "focus")
MAX_FALLBACK_STEPS = 3
FALLBACK_KIND = "screenshot_coordinates"


class ComputerAgent(ToolStepAgent):
    id = "computer"
    name = "Computer Agent"
    description = ("Looks at the screen and operates windows, applications and controls (UI tree and UI Automation first; screenshot and coordinates only as a named "
                   "fallback) through the permission-checked computer tools.")
    capabilities = frozenset({P.COMPUTER_SCREEN, P.COMPUTER_INPUT})
    optional_tools = frozenset({"ui", "ui_act"})      # registered only with computer.uia_enabled / uia_actions_enabled; their absence does not disable the agent
    tools = {
        "screen": ToolSpec(frozenset({"action", "monitor", "a", "b"}), {a: P.COMPUTER_SCREEN for a in _SCREEN}),
        "screen_save": ToolSpec(frozenset({"id", "path"}), capability=P.COMPUTER_SCREEN),
        "mouse": ToolSpec(frozenset({"action", "x", "y", "monitor", "amount", "window"}), {a: P.COMPUTER_INPUT for a in ("move", "click", "double_click", "right_click", "scroll")}),
        "keyboard": ToolSpec(frozenset({"action", "key", "keys", "text", "window"}), {a: P.COMPUTER_INPUT for a in ("press", "hotkey", "type")}),
        "window": ToolSpec(frozenset({"action", "handle"}), {a: P.COMPUTER_INPUT for a in ("focus", "minimize", "maximize", "restore", "close")}),
        "app": ToolSpec(frozenset({"app", "args"}), capability=P.COMPUTER_INPUT),
        # UI Automation: present in the registry only when computer.uia_enabled / uia_actions_enabled (both off by default); otherwise "not available"
        "ui": ToolSpec(frozenset({"action", "window", "name_equals", "name_contains", "control_type", "automation_id", "enabled", "visible", "max_results", "max_depth",
                                  "max_nodes"}), {a: P.COMPUTER_SCREEN for a in ("windows", "tree", "find")}),
        "ui_act": ToolSpec(frozenset({"action", "window", "name_equals", "name_contains", "automation_id", "control_type", "value", "max_depth", "max_nodes"}),
                           {a: P.COMPUTER_INPUT for a in _UI_ACT}),
    }

    # -- planning: validate the optional fallback of a ui_act step ---------------------------------------------------------------------------
    def _take_extra(self, i: int, tool: str, args: dict[str, Any], ctx: AgentContext) -> tuple[Any, AgentOutcome | None]:
        if "fallback" not in args:
            if tool == "mouse" and args.get("action") in _CLICKS and ctx.tools is not None and ctx.tools.available("ui_act"):
                return None, AgentOutcome.failed(f"step {i}: a coordinate click is only a fallback when UI Automation tools exist; use ui_act with a fallback", code="invalid_input")
            return None, None
        raw = args.pop("fallback")
        if tool != "ui_act":
            return None, AgentOutcome.failed(f"step {i}: only ui_act steps may carry a fallback", code="invalid_input")
        steps = [raw] if isinstance(raw, dict) else raw
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_FALLBACK_STEPS or not all(isinstance(s, dict) for s in steps):
            return None, AgentOutcome.failed(f"step {i}: fallback must be a step object or a list of 1..{MAX_FALLBACK_STEPS} steps", code="invalid_input")
        if any(s.get("tool") not in ("mouse", "keyboard") for s in steps):
            return None, AgentOutcome.failed(f"step {i}: a fallback may only use the mouse and keyboard tools", code="invalid_input")
        if P.COMPUTER_SCREEN not in ctx.allowed_capabilities:
            return None, AgentOutcome.blocked(f"step {i}: the fallback needs the capability {P.COMPUTER_SCREEN!r} (screenshot), which this task does not allow", code="capability_not_allowed")
        planned = self._plan_list(steps, ctx, nested=True)
        if isinstance(planned, AgentOutcome):
            return None, AgentOutcome(planned.status, f"step {i} fallback: {planned.summary}", planned.output, planned.error, planned.error_code)
        return [(t, a) for t, a, _ in planned], None

    # -- running ---------------------------------------------------------------------------------------------------------------------------
    def _unreachable(self, tool: str, res: Any) -> str | None:
        if tool != "ui_act":
            return None
        if res is None:
            return "uia_unavailable"                      # the ui_act tool is not registered (UI Automation is off or has no provider)
        if getattr(res, "permission", None) is None and "[control_not_found]" in (getattr(res, "error", None) or ""):
            return "control_not_found"
        return None

    def _recover(self, i: int, extra: Any, reason: str, gateway: Any, ctx: AgentContext, results: list[dict[str, Any]]) -> AgentOutcome | None:
        calls = [("screen", {"action": "screenshot"})] + list(extra)
        for tool, args in calls:
            try:
                res = gateway.call(tool, **args) if gateway.available(tool) else None
            except TaskCancelled:
                return AgentOutcome(TaskStatus.CANCELLED, f"cancelled in the fallback of step {i}", {"steps": results}, None, "cancelled")
            except ToolAccessError as exc:
                return AgentOutcome.failed(str(exc), code="tool_access_denied", output={"steps": results})
            entry: dict[str, Any] = {"step": i, "fallback_for": i, "tool": tool, "action": args.get("action"), "ok": bool(res is not None and res.success)}
            if res is None:
                entry["error"] = "the tool is not available"
                results.append(entry)
                return AgentOutcome.failed(f"step {i}: the fallback tool {tool!r} is not available", code="tool_unavailable", output={"steps": results})
            if res.success:
                entry["output"] = _clip(res.output, MAX_STEP_OUTPUT)
                results.append(entry)
                if ctx.is_cancelled():
                    return AgentOutcome(TaskStatus.CANCELLED, f"cancelled during the fallback of step {i}", {"steps": results}, None, "cancelled")
                continue
            entry["error"] = _clip(res.error or "failed", 500)
            results.append(entry)
            return self._failure(i, res, results)
        return None

    def _annotate(self, results: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        used = sorted({s["fallback_for"] for s in results if "fallback_for" in s})
        if not used:
            return "", {}
        return (f"; fallback to screenshot and coordinates used for step(s) {', '.join(map(str, used))} (control not reachable through UI Automation)",
                {"fallback": FALLBACK_KIND, "fallback_steps": used})
