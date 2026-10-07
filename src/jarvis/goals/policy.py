"""Limits and rules of the goal layer. Nothing here grants anything: a goal can only ask agents (through the orchestrator) to do what
the permission engine allows anyway."""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

from jarvis.agents import policy as AP
from jarvis.agents.state import TaskStatus

valid_id = AP.valid_id
valid_capability = AP.valid_capability
KNOWN_CAPABILITIES = AP.KNOWN_CAPABILITIES
RESERVED_KEYS = AP.RESERVED_TOOL_ARGS     # confirmed/force/bypass/skip_permissions ... may appear nowhere in a step or in the user context

MAX_OBJECTIVE = 2000
MAX_STEPS_HARD = 50           # no configuration can raise the number of steps above this
MAX_DEPTH_HARD = 20           # longest dependency chain
MAX_ATTEMPTS_HARD = 5
MAX_TIMEOUT = 86_400.0
MAX_STEP_TIMEOUT = 3600.0
MAX_SUMMARY = 500
MAX_OUTPUT_CHARS = 8_000      # stored per step result
MAX_INPUT_BYTES = 100_000
MAX_JSON_DEPTH = 8
MAX_METADATA_ITEMS = 20
MAX_CONTEXT_ITEMS = 10
EVALUATE = "evaluate"         # input marker of a step that the goal layer checks itself (no agent, no tool)

# Why an agent task failed decides whether a retry makes sense. Everything not listed here is NOT retried (fail closed).
RETRYABLE_CODES = frozenset({"timeout", "agent_crashed", "executor_failed", "queue_full", "step_failed"})
FATAL_CODES = frozenset({"permission_denied", "halted", "capability_not_allowed", "capability_missing", "unknown_agent", "no_suitable_agent",
                         "agent_disabled", "agent_failed", "invalid_input", "tool_unavailable", "tool_access_denied", "no_tools",
                         "unknown_dependency"})

# Keys of the user's explicit context the planner understands. Anything else is refused: no hidden channel into the plan.
CONTEXT_KEYS = frozenset({"url", "workspace", "runner", "edits", "memory_query", "test_args", "read_paths", "template", "research", "business", "finance"})

# Phase 10: explicitly chosen analysis templates (context key `template`); never guessed from chat. Each step carries `input.kind` for its agent.
ANALYSIS_TEMPLATES = ("research_web", "market_analysis", "competitor_analysis", "business_analysis", "business_plan", "financial_analysis", "company_analysis",
                      "paper_trade_analysis")
ANALYSIS_KINDS = frozenset({"research_web", "market_analysis", "competitor_analysis", "business_plan", "business_analysis", "marketing_draft", "lead_list",
                            "financial_analysis", "company_analysis", "risk_analysis", "scenario_analysis", "portfolio_analysis", "paper_trade_analysis"})


def is_retryable(status: TaskStatus, code: str | None) -> bool:
    return status is TaskStatus.FAILED and code in RETRYABLE_CODES and code not in FATAL_CODES


def find_reserved(value: Any, depth: int = 0) -> str | None:
    """The first reserved bypass-style key anywhere inside plain data (None if clean)."""
    if depth > MAX_JSON_DEPTH + 2:
        return "nesting"
    if isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in RESERVED_KEYS:
                return k
            hit = find_reserved(v, depth + 1)
            if hit:
                return hit
    elif isinstance(value, (list, tuple)):
        for v in value:
            hit = find_reserved(v, depth + 1)
            if hit:
                return hit
    return None


def check_plain(value: Any, what: str, depth: int = 0) -> None:
    """JSON-like data only (the same rule as for agent tasks); raises ValueError."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"{what} is nested too deeply")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{what} contains a non-finite number")
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            check_plain(v, what, depth + 1)
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"{what} keys must be text")
            check_plain(v, what, depth + 1)
        return
    raise ValueError(f"{what} may only contain plain data (got {type(value).__name__})")


def plain_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: plain_copy(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_copy(v) for v in value]
    return value


def clip(text: Any, limit: int) -> str:
    s = text if isinstance(text, str) else str(text)
    return s if len(s) <= limit else s[: max(0, limit - 1)] + "…"


def limit_output(value: Any, max_chars: int = MAX_OUTPUT_CHARS) -> Any:
    try:
        blob = json.dumps(value)
    except (TypeError, ValueError):
        return {"unserialisable": True}
    if len(blob) <= max_chars:
        return value
    return {"truncated": True, "preview": blob[: max_chars // 4]}


_URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]{0,2000}$", re.IGNORECASE)


def valid_url(value: object) -> bool:
    return isinstance(value, str) and bool(_URL_RE.match(value))
