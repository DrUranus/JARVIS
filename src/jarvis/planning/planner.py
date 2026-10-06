"""Planner: turns a goal into a Task with subtasks.

Strategy: ask the LLM for a JSON plan; if the reply is unusable, fall back to a
generic template so the user always gets a plan (never "too complex").
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from jarvis.errors import LLMError, PlanningError
from jarvis.llm.base import LLMProvider, LLMRequest, Message
from jarvis.tasks.task import Task, TaskStatus
from jarvis.tools.registry import ToolRegistry

log = logging.getLogger("jarvis.planner")

PLAN_PROMPT = """You are the planning module of JARVIS. Break the user's goal into 3-8 concrete,
ordered steps. Reply with JSON only, in this exact shape:
{{"steps": [{{"description": "...", "tools": ["tool_name"], "agents": ["agent_name"]}}]}}
Available tools: {tools}
Known agent roles: research, coding, testing, browser, design, business, security.
Use only listed tools; leave lists empty when none apply. Reply in the user's language."""

FALLBACK_STEPS = [
    "Anforderungen analysieren",
    "Lösungsansatz und Struktur entwerfen",
    "Umsetzung durchführen",
    "Ergebnis testen",
    "Fehler beheben und erneut testen",
    "Ergebnis zusammenfassen und zurückgeben",
]


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise PlanningError("no JSON object in LLM reply")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise PlanningError(f"invalid JSON in LLM reply: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanningError("plan JSON must be an object")
    return data


class Planner:
    def __init__(self, provider: LLMProvider, tools: ToolRegistry | None = None) -> None:
        self._provider = provider
        self._tools = tools or ToolRegistry()

    def _parse(self, reply: str) -> list[dict[str, Any]]:
        steps = _extract_json(reply).get("steps")
        if not isinstance(steps, list) or not steps:
            raise PlanningError("plan has no steps")
        out = []
        for s in steps:
            desc = s if isinstance(s, str) else (s or {}).get("description") if isinstance(s, dict) else None
            if not isinstance(desc, str) or not desc.strip():
                raise PlanningError("plan step without description")
            d = s if isinstance(s, dict) else {}
            out.append({
                "description": desc.strip(),
                "tools": [t for t in d.get("tools", []) if isinstance(t, str)],
                "agents": [a for a in d.get("agents", []) if isinstance(a, str)],
            })
        return out

    def plan(self, goal: str, priority: int = 5, context: str = "") -> Task:
        goal = goal.strip()
        if not goal:
            raise PlanningError("cannot plan an empty goal")
        task = Task(description=goal, priority=priority)
        task.transition(TaskStatus.PLANNING)

        used_fallback = False
        try:
            system = PLAN_PROMPT.format(tools=", ".join(self._tools.names()) or "none")
            if context:
                system += "\n\n" + context
            reply = self._provider.complete(
                LLMRequest([Message.system(system), Message.user(goal)])
            ).content
            steps = self._parse(reply)
        except (LLMError, PlanningError) as exc:
            log.warning("falling back to template plan: %s", exc)
            steps = [{"description": d, "tools": [], "agents": []} for d in FALLBACK_STEPS]
            used_fallback = True

        known = set(self._tools.names())
        for s in steps:
            tools = [t for t in s["tools"] if t in known]
            task.add_subtask(s["description"], priority=priority,
                             required_tools=tools, required_agents=s["agents"])
        task.required_tools = sorted({t for sub in task.subtasks for t in sub.required_tools})
        task.required_agents = sorted({a for sub in task.subtasks for a in sub.required_agents})
        task.result = {"plan_source": "fallback" if used_fallback else "llm"}
        task.transition(TaskStatus.WAITING)  # plan ready, awaiting execution (Phase 6+/8)
        return task
