"""Konformitaetspruefung fuer JARVIS-Agenten (V2 Vorbereitung, Bereich A): EINE wiederverwendbare Funktion `check_agent(agent)`, die jeder Agent bestehen muss - die eingebauten
heute, die noch fehlenden Agenten des separaten V2-Agentenprojekts (A9-Uebergabe) bei ihrer Einbindung. Sie ruft den Agenten nur mit Attrappen auf: ein Gateway, das jeden Werkzeugaufruf
als Fehler meldet (zaehlt ihn), keine Dateien, kein Netz. Rueckgabe: Liste von Befunden (leer = konform)."""
from __future__ import annotations

import json
import threading
from typing import Any

from jarvis.agents import policy as AP
from jarvis.agents.agent import Agent, validate_agent
from jarvis.agents.context import AgentContext
from jarvis.agents.errors import InvalidAgentError, TaskCancelled
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentOutcome
from jarvis.agents.state import AgentStatus


class SpyGateway:
    """Steht fuer `ctx.tools`: kennt keine Werkzeuge und zaehlt jeden Versuch."""

    allowed_tools: frozenset[str] = frozenset()

    def __init__(self) -> None:
        self.calls: list[str] = []

    def available(self, tool: str) -> bool:
        return False

    def call(self, tool: str, **kwargs: Any) -> Any:
        self.calls.append(str(tool))
        raise AssertionError(f"tool call {tool!r} without permission")


def context(allowed: frozenset[str], gw: SpyGateway, cancelled: bool = False) -> AgentContext:
    ev = threading.Event()
    if cancelled:
        ev.set()
    return AgentContext("task-1", "x", {}, allowed, (), {}, {}, gw, ev)       # type: ignore[arg-type]


def check_agent(agent: Agent) -> list[str]:
    problems: list[str] = []
    try:
        validate_agent(agent)
    except InvalidAgentError as exc:
        return [f"validate_agent: {exc}"]
    if not agent.capabilities <= AP.KNOWN_CAPABILITIES:
        problems.append(f"unknown capabilities {sorted(agent.capabilities - AP.KNOWN_CAPABILITIES)}: add them to policy.KNOWN_CAPABILITIES (a reviewed contract change)")
    if getattr(agent, "optional_tools", frozenset()) - agent.tool_names:
        problems.append("optional_tools must be a subset of tool_names")
    if agent.status is not AgentStatus.AVAILABLE:
        problems.append(f"a freshly built agent must be AVAILABLE, not {agent.status.value}")
    try:
        json.dumps(agent.describe())
    except Exception:                                            # noqa: BLE001
        problems.append("describe() must be JSON-serialisable")
    try:
        agent.cancel("unknown-task")
    except Exception as exc:                                     # noqa: BLE001
        problems.append(f"cancel() on an unknown task must not raise ({type(exc).__name__})")
    caps = frozenset(agent.capabilities)
    cases = {"capability not granted": (AgentTask("x", agent_id=agent.id, input={"kind": "x"}), frozenset({"files.read"} - caps) or frozenset({"browser.read"} - caps)),
             "empty input": (AgentTask("x", agent_id=agent.id, input={}), caps),
             "unknown kind": (AgentTask("x", agent_id=agent.id, input={"kind": "format_disk", "action": "x"}), caps),
             "external-action kind": (AgentTask("x", agent_id=agent.id, input={"kind": "send_email", "to": "x@example.com"}), caps)}
    for name, (task, allowed) in cases.items():
        gw = SpyGateway()
        try:
            out = agent.perform(task, context(allowed, gw))
        except TaskCancelled:
            out = AgentOutcome.cancelled()
        except Exception as exc:                                  # noqa: BLE001
            problems.append(f"{name}: perform() must report problems as an outcome, it raised {type(exc).__name__}")
            continue
        if not isinstance(out, AgentOutcome):
            problems.append(f"{name}: perform() must return an AgentOutcome")
        elif name != "empty input" and out.status.value == "SUCCEEDED" and name in ("capability not granted", "external-action kind"):
            problems.append(f"{name}: must not succeed")
        if gw.calls:
            problems.append(f"{name}: used the tool gateway ({gw.calls[:3]}) although nothing was granted/valid")
    if getattr(agent, "produces", frozenset()):
        from jarvis.agents.artifacts import KINDS
        if not agent.produces <= set(KINDS):
            problems.append("produces names unknown artifact kinds")
    return problems
