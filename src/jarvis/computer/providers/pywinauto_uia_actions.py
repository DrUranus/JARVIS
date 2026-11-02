"""UI-Automation ACTION provider on pywinauto 0.6.9 (backlog step `uia-actions`; library vetting: docs/integrations/windows-uia.md).

Same design as the read-only provider (`pywinauto_uia`): ONE worker process (`uia_act_worker`) owns the UIA connection, this process never imports pywinauto, a hanging call
only hangs the worker (stopped after `call_timeout`). The process plumbing is reused from `PywinautoUiaProvider`; this class only adds the two operations and keeps its
public surface to `read_state`, `perform` and the lifecycle (`halt`, `resume`, `shutdown`).

- Only control patterns (Invoke, Value, SelectionItem, Toggle, SetFocus). No coordinates, no keyboard or mouse events, no process control of other programs.
- Off by default (`computer.uia_actions_enabled = false`); `halt` (emergency stop) refuses every call and stops the worker; the session budget (`max_calls`, every
  read_state and perform counts) is never reset by halt/resume.
- Everything the worker returns is validated again here; a password field has no value.
"""
from __future__ import annotations

import importlib.util
import sys
from typing import Any

from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode
from jarvis.computer.providers.pywinauto_uia import PywinautoUiaProvider
from jarvis.computer.uia_actions import UiAction, UiActionProvider, UiState, UiTarget

ACT_WORKER_MODULE = "jarvis.computer.providers.uia_act_worker"


class PywinautoUiaActionProvider(UiActionProvider):
    name = "pywinauto-uia-actions"

    def __init__(self, *, max_calls: int = 200, call_timeout: float = 20.0, worker_command: list[str] | None = None) -> None:
        command = list(worker_command) if worker_command else [sys.executable, "-u", "-m", ACT_WORKER_MODULE]
        self._link = PywinautoUiaProvider(max_calls=max_calls, call_timeout=call_timeout, worker_command=command)      # validates the limits

    # -- status / lifecycle -------------------------------------------------------------------------------------------------------------------
    @property
    def calls_used(self) -> int:
        return self._link.calls_used

    @property
    def worker_running(self) -> bool:
        return self._link.worker_running

    @property
    def workers_started(self) -> int:
        return self._link.workers_started

    def halt(self, reason: str = "stopped by user") -> None:
        self._link.halt(reason)

    def resume(self) -> None:
        self._link.resume()

    def shutdown(self) -> None:
        self._link.shutdown()

    # -- the two operations -------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _payload(op: str, window_handle: Any, target: UiTarget) -> dict[str, Any]:
        if isinstance(window_handle, bool) or not isinstance(window_handle, int) or window_handle < 0:
            raise ComputerError(ErrorCode.INVALID_INPUT, "window handle must be a non-negative integer")
        if not isinstance(target, UiTarget):
            raise ComputerError(ErrorCode.INVALID_INPUT, "target must be a UiTarget")
        return {"op": op, "handle": window_handle, "path": target.runtime_id, "name": target.name, "control_type": target.control_type.value,
                "automation_id": target.automation_id}

    def read_state(self, window_handle: int, target: UiTarget) -> UiState:
        answer = self._link._request(self._payload("state", window_handle, target))
        raw = answer.get("state")
        try:
            return UiState(enabled=raw["enabled"], visible=raw["visible"], is_password=raw["is_password"], patterns=frozenset(raw["patterns"]),
                           value=raw["value"] if isinstance(raw.get("value"), str) else None,
                           read_only=raw["read_only"] if isinstance(raw.get("read_only"), bool) else None, toggle_state=raw.get("toggle_state"),
                           selected=raw["selected"] if isinstance(raw.get("selected"), bool) else None,
                           has_focus=raw["has_focus"] if isinstance(raw.get("has_focus"), bool) else None)
        except (ComputerError, KeyError, TypeError, ValueError, AttributeError):
            raise ComputerError(ErrorCode.BACKEND_ERROR, "the UI worker returned an invalid state") from None

    def perform(self, window_handle: int, target: UiTarget, action: UiAction, value: str | None = None) -> None:
        action = UiAction.parse(action)
        if (action is UiAction.SET_VALUE) != (value is not None) or (value is not None and not isinstance(value, str)):
            raise ComputerError(ErrorCode.INVALID_INPUT, "value is required for set_value and not allowed otherwise")
        self._link._request({**self._payload("act", window_handle, target), "action": action.value, "value": value})


def create_uia_action_provider(*, max_calls: int = 200, call_timeout: float = 20.0) -> PywinautoUiaActionProvider:
    """Build the provider or raise ComputerUnavailableError with a clear reason. Never imports pywinauto itself (only checks that it is installed)."""
    if sys.platform != "win32":
        raise ComputerUnavailableError("UI Automation actions are only available on Windows")
    if importlib.util.find_spec("pywinauto") is None:
        raise ComputerUnavailableError("pywinauto is not installed; UI Automation needs the optional extra: pip install -e .[uia]")
    return PywinautoUiaActionProvider(max_calls=max_calls, call_timeout=call_timeout)
