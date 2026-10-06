"""Shared rig for the computer-control tests: fake backend + real PermissionEngine + real ToolRegistry."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from jarvis.computer import ComputerController, Plan
from jarvis.computer.policy import baseline_rules
from jarvis.computer.providers.fake import FakeBackend
from jarvis.computer.tools import register_computer_tools
from jarvis.config import ComputerSettings
from jarvis.permissions import (ConfirmationChoice, PermissionEngine, PermissionLevel, PermissionRequest, Policy,
                                ResourceType, ScriptedConfirmation)
from jarvis.tools import ToolRegistry
from secutil import make_engine

ONCE, SESSION, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.ALLOW_SESSION, ConfirmationChoice.DENY
G, Y, R = PermissionLevel.GREEN, PermissionLevel.YELLOW, PermissionLevel.RED


@dataclass
class Rig:
    engine: PermissionEngine
    sink: Any
    ws: Path
    prompts: ScriptedConfirmation
    registry: ToolRegistry
    fb: FakeBackend
    controller: ComputerController
    settings: ComputerSettings
    app_path: str

    def run(self, tool: str, **kw: Any):
        return self.registry.execute(tool, **kw)

    def audit_blob(self) -> str:
        return json.dumps([e.to_dict() for e in self.sink.events])

    def prompt_blob(self) -> str:
        return "\n".join(r.to_text() + json.dumps(dict(r.context)) for r in self.prompts.requests)


def make_executable(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return str(path)


def make_rig(tmp_path: Path, answers=(), *, baseline: bool = True, notepad: bool = True, **settings_kw: Any) -> Rig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = ScriptedConfirmation(answers)
    engine, sink, ws = make_engine(tmp_path, confirmation=prompts)
    app_path = make_executable(tmp_path / "bin" / "fakenote.exe")
    apps = {"notepad": app_path, **settings_kw.pop("apps", {})}
    settings_kw.setdefault("action_delay", 0.0)
    settings = ComputerSettings(enabled=True, apps=apps, **settings_kw)
    fb = FakeBackend()
    if notepad:
        fb.add_window("Untitled - Notepad", "notepad.exe", left=0, top=0, width=40, height=30, active=True)
    controller = ComputerController(fb.bundle(), settings, sleep=lambda s: None, own_pids=())
    if baseline:
        engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
    registry = ToolRegistry(engine)
    register_computer_tools(registry, controller)
    return Rig(engine, sink, ws, prompts, registry, fb, controller, settings, app_path)


@contextmanager
def approved(engine: PermissionEngine, plan: Plan) -> Iterator[None]:
    """Mint a real, engine-issued approval for `plan` (used to exercise the controller directly)."""
    req = PermissionRequest(tool=plan.tool, action=plan.action, level=plan.level, resource=plan.resource,
                            resource_type=ResourceType.OTHER, reason=plan.reason)
    decision = engine.authorize(req)
    assert decision.allowed, decision
    with engine.execution_scope(req, decision):
        yield
