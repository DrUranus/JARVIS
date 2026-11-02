"""Builds the file-tools subsystem. Never raises for an unusable setup: JARVIS must start without it.

    settings.files -> FilesController (+ the PathGuard of the permission engine) -> tool in the ToolRegistry -> baseline rule in the engine

Status: disabled (config, the default) | unavailable (with the reason) | enabled | halted (emergency stop).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from jarvis.config import FilesSettings, Settings
from jarvis.errors import JarvisError
from jarvis.files import resources as res
from jarvis.files.controller import FilesController
from jarvis.files.errors import FilesError
from jarvis.files.tools import register_files_tools
from jarvis.permissions import PermissionEngine, Policy
from jarvis.tools import ToolRegistry

log = logging.getLogger("jarvis.files")


def baseline_rules(settings: FilesSettings) -> list:
    """Rules merged into the engine's policy at startup (visible in /permissions). `confirm` = ask every time, never offer a session permission;
    deny > confirm > allow, so a user `allow` rule cannot switch the question off: every organize step is confirmed on its own."""
    from jarvis.permissions import Effect, Rule
    return [Rule(id="files-baseline-organize-step-confirm", effect=Effect.CONFIRM, tool=res.TOOL, action="organize_step",
                 description="Every single file moved by an organize plan is confirmed one by one")]


@dataclass
class FilesSubsystem:
    """What the rest of the application sees (the Core stores it as an opaque subsystem)."""
    status: str                                   # disabled | unavailable | enabled
    reason: str = ""
    controller: FilesController | None = None
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


def build_files(settings: Settings, registry: ToolRegistry, engine: PermissionEngine) -> FilesSubsystem:
    fs = settings.files
    if not fs.enabled:
        return FilesSubsystem("disabled", "file tools are off (files.enabled = false)")
    roots = tuple(os.path.abspath(os.path.expanduser(r)) for r in (fs.roots or settings.effective_fs_roots))
    previous = engine.policy
    try:
        try:
            controller = FilesController(engine.guard, fs, roots=roots)
        except FilesError as exc:
            log.warning("file tools unavailable: %s", exc.message)
            return FilesSubsystem("unavailable", exc.message)
        # baseline rule first: if it cannot be installed, the tool is not registered at all (fail closed)
        engine.update_policy(Policy(tuple(previous.rules) + tuple(baseline_rules(fs))), source="files baseline")
        try:
            names = register_files_tools(registry, controller)
        except Exception:
            engine.update_policy(previous, source="files rollback")  # no half-installed state
            raise
    except JarvisError as exc:
        log.warning("file tools not enabled: %s", exc)
        return FilesSubsystem("unavailable", f"could not install the safety rule or tool: {type(exc).__name__}: {exc}")
    log.info("file tools enabled (%d root(s))", len(controller.roots))
    return FilesSubsystem("enabled", f"{len(controller.roots)} confirmed root(s)", controller, names)
