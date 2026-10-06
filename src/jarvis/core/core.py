"""JARVIS Core: input -> context -> (route) -> planner or LLM -> structured response."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from jarvis.errors import JarvisError
from jarvis.core.context import Context
from jarvis.llm.base import LLMProvider, LLMRequest
from jarvis.planning.planner import Planner
from jarvis.tasks.manager import TaskManager
from jarvis.tasks.task import Task
from jarvis.tools.registry import ToolRegistry

log = logging.getLogger("jarvis.core")

_GOAL_RE = re.compile(
    r"^\s*(?:jarvis[,:]?\s+)?(erstelle|erstell|baue|bau|programmiere|schreibe|entwickle|implementiere|"
    r"analysiere|verbessere|recherchiere|create|build|write|develop|implement|analy[sz]e|improve|research|make)\b",
    re.IGNORECASE,
)


class ResponseKind(str, Enum):
    CHAT = "chat"
    PLAN = "plan"
    ERROR = "error"


@dataclass
class Response:
    text: str
    kind: ResponseKind = ResponseKind.CHAT
    task: Task | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.kind is not ResponseKind.ERROR


def looks_like_goal(text: str) -> bool:
    """Simple routing heuristic; the Phase 8 Decision Engine replaces this."""
    return bool(_GOAL_RE.match(text))


def format_plan(task: Task) -> str:
    lines = [f"Plan für: {task.description}  [Task {task.id}]"]
    for i, sub in enumerate(task.subtasks, 1):
        extra = f"  (tools: {', '.join(sub.required_tools)})" if sub.required_tools else ""
        lines.append(f"  {i}. {sub.description}{extra}")
    lines.append("Ausführung folgt in einer späteren Phase; der Plan ist als Task gespeichert.")
    return "\n".join(lines)


class JarvisCore:
    """All collaborators are injected, so each can be swapped or mocked."""

    def __init__(self, provider: LLMProvider, tools: ToolRegistry | None = None,
                 tasks: TaskManager | None = None, context: Context | None = None,
                 planner: Planner | None = None) -> None:
        self.provider = provider
        self.tools = tools or ToolRegistry()
        self.tasks = tasks or TaskManager()
        self.context = context or Context()
        self.planner = planner or Planner(provider, self.tools)

    def handle(self, user_input: str) -> Response:
        text = user_input.strip()
        if not text:
            return Response("", ResponseKind.CHAT)
        try:
            return self.plan(text) if looks_like_goal(text) else self.chat(text)
        except JarvisError as exc:
            log.error("request failed: %s", exc)
            return Response(f"Das hat nicht geklappt: {exc}", ResponseKind.ERROR, error=str(exc))
        except Exception as exc:  # last line of defence; the dialog must survive
            log.exception("unexpected failure")
            return Response(f"Unerwarteter Fehler: {type(exc).__name__}: {exc}",
                            ResponseKind.ERROR, error=str(exc))

    def chat(self, text: str) -> Response:
        self.context.add_user(text)
        try:
            reply = self.provider.complete(LLMRequest(self.context.build())).content
        except JarvisError:
            self.context.pop_last_user()  # keep history consistent after a failed turn
            raise
        self.context.add_assistant(reply)
        return Response(reply, ResponseKind.CHAT)

    def plan(self, goal: str) -> Response:
        task = self.planner.plan(goal)
        self.tasks.add(task)
        text = format_plan(task)
        self.context.add_user(goal)
        self.context.add_assistant(text)
        return Response(text, ResponseKind.PLAN, task=task)
