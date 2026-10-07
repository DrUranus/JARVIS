"""Builds the coding subsystem. Never raises for an unusable provider: JARVIS must start without it.

    settings.coding -> provider -> CodingController (+ the LLM abstraction of the Core) -> tool in the ToolRegistry
                    -> baseline policy rules in the PermissionEngine

Status: disabled (config) | unavailable (with the reason) | enabled | halted (emergency stop).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis.coding.backend import CodingProvider
from jarvis.coding.controller import CodingController
from jarvis.coding.errors import CodingError
from jarvis.coding.policy import baseline_rules
from jarvis.coding.tools import register_coding_tools
from jarvis.config import CodingSettings, Settings
from jarvis.errors import JarvisError
from jarvis.permissions import PermissionEngine, Policy
from jarvis.tools import ToolRegistry

log = logging.getLogger("jarvis.coding")

ProviderBuilder = Callable[[CodingSettings], CodingProvider]
_BUILDERS: dict[str, ProviderBuilder] = {}


def register_provider(name: str, builder: ProviderBuilder) -> None:
    """Add a provider (e.g. a container/sandbox based one). Selected via coding.provider."""
    _BUILDERS[name.lower()] = builder


def _build_local(settings: CodingSettings) -> CodingProvider:
    from jarvis.coding.providers.local import LocalProvider
    return LocalProvider()


def _build_fake(settings: CodingSettings) -> CodingProvider:
    from jarvis.coding.providers.fake import FakeCodingProvider
    return FakeCodingProvider()


register_provider("local", _build_local)
register_provider("fake", _build_fake)


@dataclass
class CodingSubsystem:
    """What the rest of the application sees (the Core stores it as an opaque subsystem)."""
    status: str                                   # disabled | unavailable | enabled
    reason: str = ""
    controller: CodingController | None = None
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

    def stop(self) -> bool:
        return self.controller.stop() if self.controller is not None else False

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason, "tools": self.tool_names}
        if self.controller is not None:
            info.update(self.controller.overview())
            if self.controller.halted:
                info["status"] = "halted"
        return info


def build_coding(settings: Settings, registry: ToolRegistry, engine: PermissionEngine, llm: Any = None) -> CodingSubsystem:
    cs = settings.coding
    if not cs.enabled:
        return CodingSubsystem("disabled", "coding agent is off (coding.enabled = false)")
    builder = _BUILDERS.get(cs.provider.lower())
    if builder is None:
        return CodingSubsystem("unavailable", f"unknown coding provider {cs.provider!r}; available: {sorted(_BUILDERS)}")
    try:
        provider = builder(cs)
    except CodingError as exc:
        log.warning("coding agent unavailable: %s", exc)
        return CodingSubsystem("unavailable", str(exc))
    except Exception as exc:  # whatever a provider does, JARVIS still starts
        log.warning("coding agent unavailable: %s", type(exc).__name__)
        return CodingSubsystem("unavailable", f"provider failed to initialise ({type(exc).__name__})")
    roots = tuple(os.path.abspath(r) for r in (cs.workspace_roots or settings.effective_fs_roots))
    previous = engine.policy
    try:
        # baseline rules first: if they cannot be installed, the tool is not registered at all (fail closed)
        engine.update_policy(Policy(tuple(previous.rules) + tuple(baseline_rules(cs))), source="coding baseline")
        try:
            label = getattr(llm, "name", "") if llm is not None else ""
            controller = CodingController(provider, cs, workspace_roots=roots, llm=llm, llm_label=label,
                                          llm_is_local=label in ("mock",))
            names = register_coding_tools(registry, controller)
        except Exception:
            engine.update_policy(previous, source="coding rollback")  # no half-installed state
            raise
    except JarvisError as exc:
        log.warning("coding agent not enabled: %s", exc)
        return CodingSubsystem("unavailable", f"could not install the safety rules or tool: {type(exc).__name__}: {exc}")
    log.info("coding agent enabled (provider=%s)", provider.name)
    return CodingSubsystem("enabled", f"provider {provider.name}", controller, names)
