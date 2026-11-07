"""Builds the office subsystem. Never raises for an unusable setup: JARVIS must start without it (and without the optional libraries).

    settings.office -> OfficeController (+ the PathGuard of the permission engine) -> tool in the ToolRegistry -> baseline rule in the engine

Status: disabled (config, the default) | unavailable (with the reason) | enabled | halted (emergency stop).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Sequence

from jarvis.config import OfficeSettings, Settings
from jarvis.errors import JarvisError
from jarvis.files.errors import FilesError
from jarvis.office import resources as res
from jarvis.office.controller import OfficeController, missing_libraries
from jarvis.office.tools import register_office_tools
from jarvis.tools import ToolRegistry

log = logging.getLogger("jarvis.office")


RULE_ID = "office-baseline-create-confirm"      # the rule itself (effect CONFIRM for tool "office", action "create") is built in bootstrap.py


@dataclass
class OfficeSubsystem:
    """What the rest of the application sees (the Core stores it as an opaque subsystem)."""
    status: str                                   # disabled | unavailable | enabled
    reason: str = ""
    controller: OfficeController | None = None
    tool_names: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.controller is not None

    def halt(self, reason: str = "stopped by user") -> bool:
        if self.controller is None:
            return False
        self.controller.halt(reason)
        return True

    def resume(self) -> bool:
        if self.controller is None:
            return False
        self.controller.resume()
        return True

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason, "tools": self.tool_names}
        if self.controller is not None:
            info.update(self.controller.overview())
            if self.controller.halted:
                info["status"] = "halted"
        return info


def build_office(settings: Settings, registry: ToolRegistry, engine: Any, *, baseline_rules: Sequence[Any]) -> OfficeSubsystem:
    """`baseline_rules`: rules merged into the engine's policy first (bootstrap passes the \"confirm every new file\" rule). Without a usable rule the tool is not registered."""
    of = settings.office
    if not of.enabled:
        return OfficeSubsystem("disabled", "office files are off (office.enabled = false)")
    roots = tuple(os.path.abspath(os.path.expanduser(r)) for r in (of.roots or settings.effective_fs_roots))
    previous = engine.policy
    try:
        try:
            controller = OfficeController(engine.guard, of, roots=roots)
        except FilesError as exc:
            log.warning("office tool unavailable: %s", exc.message)
            return OfficeSubsystem("unavailable", exc.message)
        # baseline rule first: if it cannot be installed, the tool is not registered at all (fail closed)
        if not any(getattr(r, "id", None) == RULE_ID for r in baseline_rules):
            raise JarvisError(f"the baseline rule {RULE_ID} is missing")
        engine.update_policy(type(previous)(tuple(previous.rules) + tuple(baseline_rules)), source="office baseline")
        try:
            names = register_office_tools(registry, controller)
        except Exception:
            engine.update_policy(previous, source="office rollback")  # no half-installed state
            raise
    except JarvisError as exc:
        log.warning("office tool not enabled: %s", exc)
        return OfficeSubsystem("unavailable", f"could not install the safety rule or tool: {type(exc).__name__}: {exc}")
    missing = missing_libraries()
    note = f"{len(controller.roots)} confirmed root(s)" + (f"; office libraries missing ({', '.join(missing)}): pip install \"jarvis-ai[office]\"" if missing else "")
    log.info("office tool enabled (%d root(s)%s)", len(controller.roots), ", libraries missing" if missing else "")
    return OfficeSubsystem("enabled", note, controller, names)
