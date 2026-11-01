"""Builds the computer-control subsystem. Never raises for an unusable backend: JARVIS must start without it.

    settings.computer -> backend providers (lazy imports) -> ComputerController -> tools in the ToolRegistry
                      -> baseline policy rules in the PermissionEngine

Status: disabled (config) | unavailable (backend problem, with the reason) | enabled | halted (emergency stop).
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis.computer.backend import ComputerBackend
from jarvis.computer.controller import ComputerController
from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode
from jarvis.computer.policy import baseline_rules
from jarvis.computer.tools import register_computer_tools
from jarvis.config import ComputerSettings, Settings
from jarvis.errors import JarvisError
from jarvis.permissions import PermissionEngine, Policy
from jarvis.tools import ToolRegistry

log = logging.getLogger("jarvis.computer")

BackendBuilder = Callable[[ComputerSettings], ComputerBackend]
_BUILDERS: dict[str, BackendBuilder] = {}


def register_backend(name: str, builder: BackendBuilder) -> None:
    """Add a backend (e.g. a SendInput-based one, a remote-device one). Selected via computer.backend."""
    _BUILDERS[name.lower()] = builder


def _build_fake(settings: ComputerSettings) -> ComputerBackend:
    from jarvis.computer.providers.fake import FakeBackend
    return FakeBackend().bundle()


def _build_real(windows_provider: str) -> BackendBuilder:
    def build(settings: ComputerSettings) -> ComputerBackend:
        from jarvis.computer.providers.mss_screen import MssScreen
        from jarvis.computer.providers.pyautogui_input import PyAutoGuiKeyboard, PyAutoGuiMouse
        from jarvis.computer.providers.subprocess_apps import SubprocessLauncher
        screen, mouse, keyboard = MssScreen(), PyAutoGuiMouse(), PyAutoGuiKeyboard()
        if windows_provider == "win32":
            from jarvis.computer.providers.win32_windows import Win32Windows
            windows: Any = Win32Windows()
        else:
            from jarvis.computer.providers.xlib_windows import XlibWindows
            windows = XlibWindows()
        return ComputerBackend(windows_provider, screen, mouse, keyboard, windows, SubprocessLauncher())
    return build


register_backend("fake", _build_fake)
register_backend("windows", _build_real("win32"))
register_backend("x11", _build_real("x11"))


def create_backend(settings: ComputerSettings, platform: str | None = None) -> ComputerBackend:
    """Build and probe the configured backend. Raises ComputerUnavailableError with a clear reason."""
    name = settings.backend.lower()
    if name == "auto":
        name = "windows" if (platform or sys.platform) == "win32" else "x11"
    builder = _BUILDERS.get(name)
    if builder is None:
        raise ComputerUnavailableError(f"unknown computer backend {name!r}; available: {sorted(_BUILDERS)}")
    backend = builder(settings)
    if backend.screen is not None:  # prove that a display is really reachable before declaring the backend usable
        try:
            backend.screen.monitors()
        except ComputerUnavailableError:
            raise
        except ComputerError as exc:
            raise ComputerUnavailableError(exc.message, exc.code) from None
        except Exception as exc:
            raise ComputerUnavailableError(f"display probe failed ({type(exc).__name__})", ErrorCode.NO_DISPLAY) from None
    return backend


def _create_uia(settings: ComputerSettings, backend: ComputerBackend):
    """The read-only UI provider for `backend`: the deterministic fake for the fake backend, pywinauto (worker process) on Windows."""
    if backend.name == "fake":
        from jarvis.computer.providers.fake_uia import FakeUiaProvider
        return FakeUiaProvider()
    if backend.name != "win32":
        raise ComputerUnavailableError("UI Automation reading is only available on Windows")
    from jarvis.computer.providers.pywinauto_uia import create_uia_provider
    return create_uia_provider(max_calls=settings.uia_max_calls_per_session, call_timeout=settings.uia_call_timeout)


@dataclass
class ComputerSubsystem:
    """What the rest of the application sees (the Core stores it as an opaque subsystem)."""
    status: str                                   # disabled | unavailable | enabled
    reason: str = ""
    controller: ComputerController | None = None
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
            info.update(self.controller.describe())
            if self.controller.halted:
                info["status"] = "halted"
        return info


def build_computer(settings: Settings, registry: ToolRegistry, engine: PermissionEngine) -> ComputerSubsystem:
    cs = settings.computer
    if not cs.enabled:
        return ComputerSubsystem("disabled", "computer control is off (computer.enabled = false)")
    try:
        backend = create_backend(cs)
    except ComputerError as exc:
        log.warning("computer control unavailable: %s", exc)
        return ComputerSubsystem("unavailable", str(exc))
    except Exception as exc:  # whatever a backend does, JARVIS still starts
        log.warning("computer control unavailable: %s", type(exc).__name__)
        return ComputerSubsystem("unavailable", f"backend failed to initialise ({type(exc).__name__})")
    uia_note = ""
    if cs.uia_enabled:
        try:
            backend.ui = _create_uia(cs, backend)
        except Exception as exc:  # a missing library or platform never stops the rest of computer control
            message = exc.message if isinstance(exc, ComputerError) else f"{type(exc).__name__}"
            uia_note = f"; UI Automation unavailable: {message}"
            log.warning("UI Automation unavailable: %s", message)
    previous_policy = engine.policy
    try:
        # baseline rules first: if they cannot be installed, no computer tool is registered at all (fail closed)
        engine.update_policy(Policy(tuple(previous_policy.rules) + tuple(baseline_rules(cs))), source="computer baseline")
        try:
            controller = ComputerController(backend, cs)
            names = register_computer_tools(registry, controller)
        except Exception:
            engine.update_policy(previous_policy, source="computer rollback")  # no half-installed state
            raise
    except JarvisError as exc:
        log.warning("computer control not enabled: %s", exc)
        return ComputerSubsystem("unavailable", f"could not install the safety rules or tools: {type(exc).__name__}: {exc}")
    log.info("computer control enabled (backend=%s, capabilities=%s)", backend.name, backend.capabilities())
    return ComputerSubsystem("enabled", f"backend {backend.name}{uia_note}", controller, names)
