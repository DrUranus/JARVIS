"""Read-only Windows UI-Automation provider on pywinauto 0.6.9 (backlog step `uia-provider-readonly`; library vetting: docs/integrations/windows-uia.md).

Design (docs/uia-compat-results.md):
- All UIA calls happen in ONE worker process (`uia_worker`), in its main thread, which owns the connection. This process never imports pywinauto, so the COM threading
  mode of JARVIS (tkinter, comtypes) stays untouched and a hanging UIA call can only hang the worker, which is stopped after `call_timeout`.
- Only reading: list windows, describe a tree, find elements. No input, no click, no focus change, no value of any control, no process control of other programs
  (the only process this module ever stops is its own worker).
- Off by default (`computer.uia_enabled = false`); the emergency stop (`halt`) refuses every call and stops the worker; the session budget (`max_calls`) is never reset.
- Everything the worker returns is validated again here (`UiElement`, `bound_tree`): password fields carry no value, depth/nodes/text stay bounded.
"""
from __future__ import annotations

import importlib.util
import json
import queue
import subprocess
import sys
import threading
from typing import Any

from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode
from jarvis.computer.models import WindowInfo
from jarvis.computer.uia import (HARD_MAX_DEPTH, HARD_MAX_NODES, ControlType, UiElement, UiFindResult, UiLimits, UiQuery, UiRect, UiSnapshot, UiTreeProvider,
                                 bound_tree, find_in_tree)

WORKER_MODULE = "jarvis.computer.providers.uia_worker"
MAX_LINE_BYTES = 4_000_000
HARD_MAX_CALLS, HARD_MAX_TIMEOUT = 10_000, 600.0
MAX_RAW_NODES = 5000          # what a (misbehaving) worker may send at most; the tree is then cut to the limits


def _fail(code: ErrorCode, message: str) -> ComputerError:
    return ComputerError(code, message)


def _convert(raw: Any, depth: int, counter: list[int]) -> UiElement:
    counter[0] += 1
    if counter[0] > MAX_RAW_NODES or depth > HARD_MAX_DEPTH + 1 or not isinstance(raw, dict):
        raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker returned an invalid tree")
    rect = raw["rect"]
    if not isinstance(rect, list) or len(rect) != 4:
        raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker returned an invalid tree")
    kids = raw["children"]
    if not isinstance(kids, list):
        raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker returned an invalid tree")
    return UiElement(runtime_id=raw["runtime_id"], name=raw["name"], control_type=ControlType.from_name(raw["control_type"]), automation_id=raw["automation_id"],
                     class_name=raw["class_name"], rect=UiRect(*rect), enabled=raw["enabled"], visible=raw["visible"], is_password=raw["is_password"],
                     value=raw.get("value") if isinstance(raw.get("value"), str) else None,      # dropped by UiElement for password fields
                     children=tuple(_convert(k, depth + 1, counter) for k in kids))


class PywinautoUiaProvider(UiTreeProvider):
    name = "pywinauto-uia"

    def __init__(self, *, max_calls: int = 200, call_timeout: float = 20.0, worker_command: list[str] | None = None) -> None:
        if isinstance(max_calls, bool) or not isinstance(max_calls, int) or not 1 <= max_calls <= HARD_MAX_CALLS:
            raise _fail(ErrorCode.INVALID_INPUT, f"max_calls must be an integer between 1 and {HARD_MAX_CALLS}")
        if isinstance(call_timeout, bool) or not isinstance(call_timeout, (int, float)) or not 0 < call_timeout <= HARD_MAX_TIMEOUT:
            raise _fail(ErrorCode.INVALID_INPUT, f"call_timeout must be greater than 0 and at most {HARD_MAX_TIMEOUT:g} seconds")
        self._max_calls, self._timeout = max_calls, float(call_timeout)
        self._command = list(worker_command) if worker_command else [sys.executable, "-u", "-m", WORKER_MODULE]
        self._lock = threading.Lock()          # one request at a time: the worker has exactly one owner thread
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._halted: str | None = None
        self._calls = 0
        self._started = 0
        self._next_id = 0

    # -- status -------------------------------------------------------------------------------------------------------------------------------
    @property
    def calls_used(self) -> int:
        return self._calls

    @property
    def worker_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def workers_started(self) -> int:
        return self._started

    # -- emergency stop / lifecycle -----------------------------------------------------------------------------------------------------------
    def halt(self, reason: str = "stopped by user") -> None:
        """Refuse every further call and stop the worker. The session budget is not reset by halt/resume."""
        self._halted = reason
        self._stop_worker()

    def resume(self) -> None:
        self._halted = None

    def shutdown(self) -> None:
        self._stop_worker()

    def _stop_worker(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()          # our own worker process only
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:      # noqa: BLE001
            pass
        for stream in (proc.stdin, proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except Exception:      # noqa: BLE001
                pass

    # -- worker I/O ---------------------------------------------------------------------------------------------------------------------------
    def _start_worker(self) -> None:
        try:
            proc = subprocess.Popen(self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                    bufsize=1)
        except OSError as exc:
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, f"the UI worker could not be started ({type(exc).__name__})") from None
        lines: queue.Queue[str | None] = queue.Queue()
        self._lines, self._proc = lines, proc
        self._started += 1

        def pump() -> None:
            try:
                assert proc.stdout is not None
                for line in iter(lambda: proc.stdout.readline(MAX_LINE_BYTES + 1), ""):      # type: ignore[union-attr]
                    lines.put(line)
                    if len(line) > MAX_LINE_BYTES:
                        break
            except Exception:      # noqa: BLE001
                pass
            lines.put(None)

        threading.Thread(target=pump, name="uia-worker-reader", daemon=True).start()

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._halted is not None:
                raise _fail(ErrorCode.FAILSAFE, f"UI access is halted ({self._halted}); resume it explicitly")
            if self._calls >= self._max_calls:
                raise _fail(ErrorCode.RATE_LIMITED, f"session budget for UI reads used up ({self._max_calls} calls)")
            self._calls += 1
            if not self.worker_running:
                self._stop_worker()
                self._start_worker()
            self._next_id += 1
            request_id = self._next_id
            assert self._proc is not None and self._proc.stdin is not None
            try:
                self._proc.stdin.write(json.dumps({**payload, "id": request_id}) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError):
                self._stop_worker()
                raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker is not reachable") from None
            while True:
                try:
                    line = self._lines.get(timeout=self._timeout)
                except queue.Empty:
                    self._stop_worker()
                    raise _fail(ErrorCode.BACKEND_ERROR, f"timeout: the UI worker did not answer within {self._timeout:g} s and was stopped") from None
                if line is None or len(line) > MAX_LINE_BYTES:
                    self._stop_worker()
                    raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker ended or sent an invalid answer")
                try:
                    answer = json.loads(line)
                except ValueError:
                    self._stop_worker()
                    raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker sent an invalid answer") from None
                if not isinstance(answer, dict):
                    self._stop_worker()
                    raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker sent an invalid answer")
                if answer.get("id") not in (request_id, None):
                    continue          # stale answer of an earlier request
                if answer.get("ok") is True:
                    return answer
                code = str(answer.get("code"))
                if code == ErrorCode.WINDOW_NOT_FOUND.value:
                    raise _fail(ErrorCode.WINDOW_NOT_FOUND, "no such window")
                if code == ErrorCode.BACKEND_UNAVAILABLE.value:
                    self._stop_worker()
                    raise ComputerUnavailableError("the UI worker cannot load pywinauto; install it with: pip install -e .[uia]")
                if code == ErrorCode.INVALID_INPUT.value:
                    raise _fail(ErrorCode.INVALID_INPUT, "the UI worker rejected the request")
                raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker failed")

    @staticmethod
    def _handle(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _fail(ErrorCode.INVALID_INPUT, "window handle must be a non-negative integer")
        return value

    # -- reading ------------------------------------------------------------------------------------------------------------------------------
    def list_windows(self) -> list[WindowInfo]:
        """Visible top-level windows with a title (handles as in `WindowInfo.handle`)."""
        answer = self._request({"op": "windows"})
        out: list[WindowInfo] = []
        try:
            for w in answer["windows"][:200]:
                out.append(WindowInfo(handle=int(w["handle"]), title=str(w["title"])[:300], process="", pid=int(w.get("pid", 0)), class_name=str(w.get("class_name", ""))[:200]))
        except (KeyError, TypeError, ValueError):
            raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker returned an invalid window list") from None
        return out

    def _tree(self, handle: int, limits: UiLimits) -> UiElement:
        answer = self._request({"op": "tree", "handle": handle, "max_depth": limits.max_depth, "max_nodes": limits.max_nodes, "max_text": limits.max_text})
        try:
            return _convert(answer["tree"], 0, [0])
        except (ComputerError, KeyError, TypeError, ValueError):
            raise _fail(ErrorCode.BACKEND_ERROR, "the UI worker returned an invalid tree") from None

    def describe(self, window_handle: int, limits: UiLimits) -> UiSnapshot:
        tree, nodes, cut = bound_tree(self._tree(self._handle(window_handle), limits), limits)
        return UiSnapshot(window_handle, tree, nodes, cut, limits)

    def find(self, window_handle: int, query: UiQuery, limits: UiLimits) -> UiFindResult:
        return find_in_tree(self._tree(self._handle(window_handle), limits), query, limits)


def create_uia_provider(*, max_calls: int = 200, call_timeout: float = 20.0) -> PywinautoUiaProvider:
    """Build the provider or raise ComputerUnavailableError with a clear reason. Never imports pywinauto itself (only checks that it is installed)."""
    if sys.platform != "win32":
        raise ComputerUnavailableError("UI Automation reading is only available on Windows")
    if importlib.util.find_spec("pywinauto") is None:
        raise ComputerUnavailableError("pywinauto is not installed; UI Automation needs the optional extra: pip install -e .[uia]")
    return PywinautoUiaProvider(max_calls=max_calls, call_timeout=call_timeout)
