"""Shared rig for the coding-agent tests: real PermissionEngine + real ToolRegistry + a (fake or local) provider."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from jarvis.coding import CodingController, Plan
from jarvis.coding.policy import baseline_rules
from jarvis.coding.providers.fake import FakeCodingProvider
from jarvis.coding.providers.local import LocalProvider
from jarvis.coding.tools import register_coding_tools
from jarvis.config import CodingSettings
from jarvis.permissions import (ConfirmationChoice, PermissionEngine, PermissionLevel, PermissionRequest, Policy, ScriptedConfirmation)
from jarvis.tools import ToolRegistry
from secutil import make_engine

ONCE, SESSION, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.ALLOW_SESSION, ConfirmationChoice.DENY
G, Y, R = PermissionLevel.GREEN, PermissionLevel.YELLOW, PermissionLevel.RED

PYPROJECT = '[project]\nname = "demo"\nversion = "0.1"\ndependencies = []\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
CALC = "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"
TEST_CALC = "from calc import add, mul\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n"


@dataclass
class Rig:
    engine: PermissionEngine
    sink: Any
    ws: Path             # the permission engine's allowed root (and the coding workspace root)
    prompts: ScriptedConfirmation
    registry: ToolRegistry
    provider: Any
    controller: CodingController
    settings: CodingSettings
    project: Path        # <ws>/proj

    def run(self, **kw: Any):
        return self.registry.execute("coding", **kw)

    def ok(self, **kw: Any) -> Any:
        out = self.run(**kw)
        assert out.success, (kw, out.error)
        return out.output

    def start(self, workspace: str | None = None) -> dict[str, Any]:
        return self.ok(action="start", workspace=workspace or str(self.project))

    def audit_blob(self) -> str:
        return json.dumps([e.to_dict() for e in self.sink.events])

    def prompt_blob(self) -> str:
        return "\n".join(r.to_text() + json.dumps(dict(r.context)) for r in self.prompts.requests)

    def file(self, rel: str) -> Path:
        return self.project / rel


def seed(provider: Any, project: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = project / rel
        if isinstance(provider, FakeCodingProvider):
            provider.put(str(p), text)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")


def make_rig(tmp_path: Path, answers=(), *, real: bool = False, files: dict[str, str] | None = None, llm: Any = None,
             baseline: bool = True, **settings_kw: Any) -> Rig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = ScriptedConfirmation(answers)
    engine, sink, ws = make_engine(tmp_path, confirmation=prompts)
    ws = Path(os.path.realpath(ws))
    project = ws / "proj"
    provider: Any = LocalProvider() if real else FakeCodingProvider()
    if real:
        project.mkdir(exist_ok=True)
    elif isinstance(provider, FakeCodingProvider):
        provider.dirs.update({str(ws), str(project)})
    seed(provider, project, files if files is not None else {"pyproject.toml": PYPROJECT, "calc.py": CALC, "tests/test_calc.py": TEST_CALC})
    settings = CodingSettings(enabled=True, provider="local" if real else "fake", **settings_kw)
    controller = CodingController(provider, settings, workspace_roots=(str(ws),), llm=llm, llm_label=getattr(llm, "name", ""),
                                  llm_is_local=getattr(llm, "name", "") == "mock")
    if baseline:
        engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
    registry = ToolRegistry(engine)
    register_coding_tools(registry, controller)
    return Rig(engine, sink, ws, prompts, registry, provider, controller, settings, project)


@contextmanager
def approved(engine: PermissionEngine, plan: Plan) -> Iterator[None]:
    req = PermissionRequest(tool=plan.tool, action=plan.action, level=plan.level, resource=plan.resource,
                            resource_type=plan.resource_type, reason=plan.reason)
    decision = engine.authorize(req)
    assert decision.allowed, decision
    with engine.execution_scope(req, decision):
        yield
