"""ComputerController: the session object for screen, mouse, keyboard, windows and applications.

Design rules (security first):
* Every action is a `Plan` (tool, action, resource URI, level, reason). Planning only READS state to describe the
  target; nothing happens until `execute(plan)`.
* `execute` demands an `ExecutionGrant` from the PermissionEngine that matches the plan's tool, action AND resource.
  Without one it raises NOT_AUTHORIZED; if the screen/window state changed since the approval (the resource string
  differs) it raises TARGET_CHANGED. The controller can therefore not be used to skip permissions, not even by code
  that holds a reference to it. It has no `confirmed=` shortcut and no switch to turn the check off.
* RED plans (protected windows, terminals, Windows-key combinations, blocked executables...) are refused even if a
  grant existed (defence in depth; the engine already denies RED).
* Providers are private to the controller. Typed text, screen content and arguments never reach logs or errors.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import logging
import os
import secrets
import sys
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from jarvis.computer import resources as res
from jarvis.computer import validation as val
from jarvis.computer.backend import ComputerBackend
from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.models import CursorPosition, FrameDiff, Monitor, Screenshot, WindowInfo
from jarvis.computer.safety import ComputerSafety, Verdict
from jarvis.computer.screenshots import ScreenshotStore, encode_png, frame_diff
from jarvis.config import ComputerSettings
from jarvis.permissions import ActionSpec, PermissionLevel, ResourceType, current_grant

log = logging.getLogger("jarvis.computer")

DEFAULT_WINDOWS_APPS = {
    "notepad": r"%SystemRoot%\System32\notepad.exe",
    "calculator": r"%SystemRoot%\System32\calc.exe",
    "paint": r"%SystemRoot%\System32\mspaint.exe",
}
MOUSE_ACTIONS = ("move", "click", "double_click", "right_click", "scroll")
KEYBOARD_ACTIONS = ("press", "hotkey", "type")
WINDOW_ACTIONS = ("focus", "minimize", "maximize", "restore", "close")
SCREEN_ACTIONS = ("monitors", "screenshot", "compare", "windows", "active_window", "cursor", "forget")
_INPUT_TOOLS = (res.TOOL_MOUSE, res.TOOL_KEYBOARD, res.TOOL_WINDOW, res.TOOL_APP)
RED = PermissionLevel.RED
YELLOW = PermissionLevel.YELLOW
GREEN = PermissionLevel.GREEN


@dataclass(frozen=True)
class Plan:
    """What an action would do, described precisely. Executing it needs a matching approval."""
    tool: str
    action: str
    resource: str
    level: PermissionLevel
    reason: str = ""
    context: Mapping[str, str] = field(default_factory=dict, repr=False)  # holds titles and text previews: never in a repr
    _run: Callable[[], Any] = field(default=lambda: None, repr=False, compare=False)
    _sig: str = field(default="", repr=False, compare=False)  # HMAC from the creating controller (see _sign)

    @property
    def blocked(self) -> bool:
        return self.level is RED

    def to_spec(self) -> ActionSpec:
        """For the tool's describe_action: the engine sees exactly this resource, level and explanation."""
        return ActionSpec(action=self.action, resource=self.resource, resource_type=ResourceType.OTHER,
                          level=self.level, reason=self.reason, context=dict(self.context))


def text_preview(text: str, limit: int = 40) -> str:
    shown = text[:limit].replace("\n", "⏎").replace("\t", "⇥")
    return shown + ("…" if len(text) > limit else "")


def safe_label(text: str, limit: int = 60) -> str:
    """OS- and config-provided text shown to the user: control/format characters (newlines, bidi overrides...) become
    spaces so a window title cannot forge lines such as 'Risiko: GREEN' in a confirmation prompt."""
    cleaned = "".join(" " if unicodedata.category(c).startswith("C") else c for c in text)
    return " ".join(cleaned.split())[:limit]


def _target_label(w: WindowInfo | None) -> str:
    # the title is quoted: it is DATA from another program and must not read like part of the prompt
    return "unbekannt" if w is None else f"„{safe_label(w.title)}“ ({safe_label(w.process, 40) or '?'})"


class ComputerController:
    def __init__(self, backend: ComputerBackend, settings: ComputerSettings | None = None, *,
                 safety: ComputerSafety | None = None, store: ScreenshotStore | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 own_pids: Sequence[int] | None = None) -> None:
        self._backend = backend  # private on purpose: nothing outside this class can drive a provider
        self.settings = settings or ComputerSettings()
        self._safety = safety or ComputerSafety(self.settings.blocked_processes, self.settings.blocked_titles,
                                                own_pids if own_pids is not None else (os.getpid(), os.getppid()))
        self.screenshots = store or ScreenshotStore(self.settings.screenshot_max_items)
        self._clock, self._sleep = clock, sleep
        self._lock = threading.RLock()  # one physical mouse and keyboard: actions never interleave
        self._halted: str | None = None
        self._recent: deque[float] = deque()
        self._key = secrets.token_bytes(32)  # signs the plans this controller creates; never leaves the object

    # -- status / kill switch -----------------------------------------------------------------------------------
    @property
    def safety(self) -> ComputerSafety:
        """Read-only: the classifier of protected targets cannot be swapped for a laxer one after construction."""
        return self._safety

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def halted(self) -> str | None:
        return self._halted

    def halt(self, reason: str = "stopped by user") -> None:
        """Emergency stop: every further action fails with `failsafe` until resume()."""
        self._halted = reason

    def resume(self) -> None:
        self._halted = None

    def describe(self) -> dict[str, Any]:
        return {"backend": self._backend.name, "capabilities": self._backend.capabilities(),
                "halted": self._halted, "apps": sorted(self.effective_apps()),
                "default_monitor": self.settings.default_monitor,
                "stored_screenshots": self.screenshots.ids(), "limits": {
                    "max_text_length": self.settings.max_text_length, "max_scroll": self.settings.max_scroll,
                    "max_actions_per_minute": self.settings.max_actions_per_minute}}

    # -- provider access ---------------------------------------------------------------------------------------------
    def _provider(self, name: str) -> Any:
        p = getattr(self._backend, name)
        if p is None:
            raise ComputerError(ErrorCode.UNSUPPORTED, f"backend '{self._backend.name}' has no {name} support")
        return p

    @staticmethod
    def _call(fn: Callable[..., Any], *args: Any) -> Any:
        """Run a provider call: ComputerError passes through, anything else becomes a structured error
        (type name only: library messages can contain typed characters or screen content)."""
        try:
            return fn(*args)
        except ComputerError:
            raise
        except Exception as exc:
            raise ComputerError(ErrorCode.BACKEND_ERROR, f"backend failure ({type(exc).__name__})") from None

    def _monitors(self) -> list[Monitor]:
        monitors = self._call(self._provider("screen").monitors)
        if not monitors:
            raise ComputerError(ErrorCode.NO_DISPLAY, "no monitors available")
        return monitors

    def _monitor(self, index: Any, monitors: Sequence[Monitor]) -> Monitor:
        if index is None:  # only a NOT given monitor may fall back (default unplugged -> primary); an explicit one never does
            index = self.settings.default_monitor if self.settings.default_monitor < len(monitors) else 0
        return val.validate_monitor(index, monitors)

    def effective_apps(self) -> dict[str, str]:
        apps: dict[str, str] = {}
        if sys.platform == "win32" and self.settings.use_default_apps:
            apps.update(DEFAULT_WINDOWS_APPS)
        apps.update({k.casefold(): v for k, v in self.settings.apps.items()})
        return apps

    # -- plan integrity ----------------------------------------------------------------------------------------------
    def _sign(self, plan: Plan) -> str:
        """HMAC over what the approval is about (tool, action, resource, level) AND the identity of the function that
        will run. A plan whose fields were changed (dataclasses.replace), built by hand, or whose action was swapped
        for another plan's no longer verifies, so an approval for one thing can never carry out another."""
        ctx = "\x1e".join(f"{k}\x1d{v}" for k, v in sorted(plan.context.items()))
        msg = "\x1f".join((plan.tool, plan.action, plan.resource, plan.level.value, plan.reason, ctx, str(id(plan._run)))).encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def _seal(self, plan: Plan) -> Plan:
        return dataclasses.replace(plan, _sig=self._sign(plan))

    # -- authorisation + execution -------------------------------------------------------------------------------------
    def _require(self, tool: str, action: str, resource: str | None) -> Any:
        grant = current_grant()
        if grant is None:
            raise ComputerError(ErrorCode.NOT_AUTHORIZED, "computer actions must run through the permission engine")
        if grant.tool != tool or grant.action != action:
            raise ComputerError(ErrorCode.NOT_AUTHORIZED, "the approval was issued for a different operation")
        if resource is not None and grant.resource != resource:
            raise ComputerError(ErrorCode.TARGET_CHANGED, "the target changed since it was approved; nothing was done")
        return grant

    def _admit(self, tool: str) -> None:
        if self._halted is not None:
            raise ComputerError(ErrorCode.FAILSAFE, f"computer control is halted ({self._halted}); resume it explicitly")
        limit = self.settings.max_actions_per_minute
        if limit and tool in _INPUT_TOOLS:
            now = self._clock()
            while self._recent and now - self._recent[0] > 60:
                self._recent.popleft()
            if len(self._recent) >= limit:
                raise ComputerError(ErrorCode.RATE_LIMITED, f"more than {limit} actions per minute; slowing down")
            self._recent.append(now)

    def execute(self, plan: Plan) -> Any:
        """Run a planned action. Needs a matching ExecutionGrant; refuses RED plans; serialised."""
        if not isinstance(plan, Plan) or not plan._sig or not hmac.compare_digest(plan._sig, self._sign(plan)):
            raise ComputerError(ErrorCode.NOT_AUTHORIZED, "this plan was not created by this controller or was modified")
        self._require(plan.tool, plan.action, plan.resource)
        if plan.blocked:
            raise ComputerError(ErrorCode.BLOCKED_TARGET, plan.reason or "blocked target")
        with self._lock:
            self._admit(plan.tool)
            log.debug("computer %s %s", plan.action, plan.resource)  # never the context: it holds titles / text previews
            result = plan._run()
            if plan.tool in _INPUT_TOOLS and self.settings.action_delay:
                self._sleep(self.settings.action_delay)
            return result

    # ==================================================================================================================
    # planning (read-only classification) - one method per tool
    # ==================================================================================================================
    def plan_screen(self, action: Any, *, monitor: Any = None, a: Any = None, b: Any = None) -> Plan:
        if action not in SCREEN_ACTIONS:
            raise ComputerError(ErrorCode.INVALID_INPUT, f"unknown screen action; use one of {list(SCREEN_ACTIONS)}")

        def plan(resource: str, run: Callable[[], Any], reason: str, **ctx: str) -> Plan:
            return self._seal(Plan(res.TOOL_SCREEN, action, resource, GREEN, reason, ctx, run))

        if action == "monitors":
            return plan(res.screen_info_resource("monitors"), self._run_monitors, "Monitore auflisten")
        if action == "screenshot":
            monitors = self._monitors()
            target: Monitor | None = None
            if isinstance(monitor, str) and monitor.strip().casefold() == "all":
                width = max(m.left + m.width for m in monitors) - min(m.left for m in monitors)
                height = max(m.top + m.height for m in monitors) - min(m.top for m in monitors)
                idx: int | None = None
            else:
                target = self._monitor(monitor, monitors)
                width, height, idx = target.width, target.height, target.index
            if width * height > self.settings.screenshot_max_pixels:
                raise ComputerError(ErrorCode.INVALID_INPUT, "the screenshot would exceed screenshot_max_pixels")
            return plan(res.screen_resource(idx), lambda: self._run_screenshot(target, idx),
                        "Screenshot aufnehmen (bleibt im Speicher)", groesse=f"{width}x{height}")
        if action == "compare":
            sa, sb = self.screenshots.get(str(a)), self.screenshots.get(str(b))
            return plan(f"screen://compare/{sa.id}..{sb.id}", lambda: frame_diff(sa, sb).info(),
                        "Zwei gespeicherte Screenshots vergleichen")
        if action == "windows":
            return plan(res.screen_info_resource("windows"), self._run_windows, "Sichtbare Fenster auflisten")
        if action == "active_window":
            return plan(res.screen_info_resource("active-window"), self._run_active_window, "Aktives Fenster ermitteln")
        if action == "cursor":
            return plan(res.screen_info_resource("cursor"), self._run_cursor, "Mausposition ermitteln")
        return plan(res.screen_info_resource("screenshots"), lambda: {"forgotten": self.screenshots.clear()},
                    "Gespeicherte Screenshots verwerfen")

    def plan_mouse(self, action: Any, x: Any = None, y: Any = None, *, monitor: Any = None, amount: Any = None,
                   window: Any = None) -> Plan:
        if action not in MOUSE_ACTIONS:
            raise ComputerError(ErrorCode.INVALID_INPUT, f"unknown mouse action; use one of {list(MOUSE_ACTIONS)}")
        monitors = self._monitors()
        steps_wanted = val.validate_scroll(amount, self.settings.max_scroll) if action == "scroll" else 0
        planned_window: WindowInfo | None = None
        if window is not None:  # targeted mode: x/y are relative to this window; it is brought to the front and re-verified
            if monitor is not None:
                raise ComputerError(ErrorCode.INVALID_INPUT, "use either 'window' (x/y relative to the window) or 'monitor'")
            planned_window = self._known_window(window)
            if planned_window.minimized:
                raise ComputerError(ErrorCode.INVALID_INPUT, "the target window is minimized; restore it first (window action=restore)")
            wx, wy = val.validate_point(x, y, Monitor(-1, 0, 0, planned_window.width, planned_window.height))
            ax, ay = planned_window.left + wx, planned_window.top + wy
            mon = next((m for m in monitors if m.left <= ax < m.left + m.width and m.top <= ay < m.top + m.height), None)
            if mon is None:
                raise ComputerError(ErrorCode.INVALID_COORDINATES, "that point of the window is not on any monitor")
            px, py = ax - mon.left, ay - mon.top
            target = planned_window
        else:
            mon = self._monitor(monitor, monitors)
            px, py = val.validate_point(x, y, mon)
            ax, ay = mon.left + px, mon.top + py
            target = self._window_at(ax, ay)
        steps = steps_wanted
        verdict = self._safety.window_input_verdict(target)
        ctx = {"monitor": f"{mon.index} ({mon.width}x{mon.height})", "ziel": _target_label(target)}
        if planned_window is not None:
            ctx["fenster"] = f"{planned_window.handle} (wird vorher in den Vordergrund geholt und erneut geprüft)"
        if action == "scroll":
            ctx["schritte"] = str(steps)
        pointer = self._provider("mouse")

        def run() -> dict[str, Any]:
            if planned_window is not None:
                self._bring_to_front(planned_window, geometry=True)
                covering = self._window_at(ax, ay)  # positive proof that the approved window is what is under the pointer
                if covering is None or covering.handle != planned_window.handle:
                    raise ComputerError(ErrorCode.TARGET_CHANGED, "the target window is not what is under that point; nothing was done")
            self._recheck_target(ax, ay)
            if action == "move":
                self._call(pointer.move, ax, ay)
            elif action == "scroll":
                self._call(pointer.scroll, ax, ay, steps)
            else:
                button, clicks = {"click": ("left", 1), "double_click": ("left", 2), "right_click": ("right", 1)}[action]
                self._call(pointer.click, ax, ay, button, clicks)
            return {"action": action, "monitor": mon.index, "x": px, "y": py}

        return self._seal(Plan(res.TOOL_MOUSE, action, res.mouse_resource(mon.index, px, py), verdict.level,
                               verdict.reason or f"Maus: {action}", ctx, run))

    def plan_keyboard(self, action: Any, *, key: Any = None, keys: Any = None, text: Any = None, window: Any = None) -> Plan:
        if action not in KEYBOARD_ACTIONS:
            raise ComputerError(ErrorCode.INVALID_INPUT, f"unknown keyboard action; use one of {list(KEYBOARD_ACTIONS)}")
        keyboard = self._provider("keyboard")
        # Key/combination checks come first and need no window: a forbidden combination is a (audited) RED denial even
        # when there is no active window, instead of an unrelated 'no window' error.
        if action == "press":
            k = val.normalize_key(key)
            verdict = self._safety.key_verdict(k)
        elif action == "hotkey":
            ks = val.parse_hotkey(keys, self.settings.max_hotkey_keys)
            verdict = self._safety.hotkey_verdict(ks)
        else:
            t = val.validate_text(text, self.settings.max_text_length)
            verdict = Verdict(YELLOW)
        targeted = window is not None  # input for a specific window: brought to the front and re-verified before every input
        try:
            active: WindowInfo | None = self._known_window(window) if targeted else self._require_active_window()
        except ComputerError as exc:
            if not (verdict.blocked and exc.code is ErrorCode.WINDOW_NOT_FOUND):
                raise
            active = None  # forbidden anyway; no target needed to say so
        target = (active.process or "unknown") if active else "none"
        window_verdict = self._safety.window_input_verdict(active)
        ctx = {"ziel": _target_label(active)}
        if targeted and active is not None:
            ctx["fenster"] = f"{active.handle} (wird vorher in den Vordergrund geholt und erneut geprüft)"
        if action == "press":
            resource = res.key_resource(k, target)
            ctx["taste"] = k
            reason, run_call = f"Taste {k} drücken", (lambda: self._call(keyboard.press, k))
            result: dict[str, Any] = {"action": "press", "key": k}
        elif action == "hotkey":
            resource = res.hotkey_resource(ks, target)
            ctx["tasten"] = "+".join(ks)
            reason, run_call = f"Tastenkombination {'+'.join(ks)}", (lambda: self._call(keyboard.hotkey, ks))
            result = {"action": "hotkey", "keys": list(ks)}
        else:
            resource = res.text_resource(target)
            ctx["zeichen"] = str(len(t))
            if self.settings.show_text_preview:
                ctx["vorschau"] = text_preview(t)  # shown at the confirmation prompt only; never logged or audited
            reason = "Text eingeben"
            run_call = lambda: self._type_verified(keyboard, t, active)  # noqa: E731
            result = {"action": "type", "characters": len(t)}
        level = RED if RED in (verdict.level, window_verdict.level) else YELLOW
        why = window_verdict.reason or verdict.reason or reason

        def run() -> dict[str, Any]:
            if active is None:  # only reachable for RED plans, which execute() refuses before this point
                raise ComputerError(ErrorCode.BLOCKED_TARGET, "no target window")
            if targeted:
                self._bring_to_front(active)
            else:
                self._recheck_active(active)
            run_call()
            return result

        return self._seal(Plan(res.TOOL_KEYBOARD, action, resource, level, why, ctx, run))

    def plan_window(self, action: Any, handle: Any) -> Plan:
        if action not in WINDOW_ACTIONS:
            raise ComputerError(ErrorCode.INVALID_INPUT, f"unknown window action; use one of {list(WINDOW_ACTIONS)}")
        h = val.as_int(handle, "handle")
        windows = self._provider("windows")
        w = next((x for x in self._call(windows.list_windows) if x.handle == h), None)
        if w is None:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, f"window {h} does not exist or is not visible")
        verdict = self._safety.window_close_verdict(w) if action == "close" else Verdict(YELLOW)
        method = {"focus": windows.focus, "minimize": windows.minimize, "maximize": windows.maximize,
                  "restore": windows.restore, "close": windows.close}[action]
        ctx = {"fenster": _target_label(w), "handle": str(h)}
        return self._seal(Plan(res.TOOL_WINDOW, action, res.window_resource(h, w.process), verdict.level,
                               verdict.reason or f"Fenster: {action}", ctx,
                               lambda: (self._call(method, h), {"action": action, "handle": h})[1]))

    def plan_app(self, app: Any, args: Any = None) -> Plan:
        argv = val.validate_app_args(args)
        launcher = self._provider("apps")
        name = self._app_name(app)
        alias_path = self.effective_apps().get(name.casefold())
        raw = alias_path if alias_path is not None else (name if self.settings.allow_unlisted_apps and os.path.isabs(name) else None)
        if raw is None:  # an agent asking for an unlisted program is a security-relevant event: RED + audited denial
            return self._seal(Plan(res.TOOL_APP, "launch", f"app://unlisted/{res._clean(name)}", RED,
                                   f"'{safe_label(name, 40)}' is not an allowed application (computer.apps)",
                                   {"anwendung": safe_label(name, 80)}))
        exe = os.path.realpath(os.path.expandvars(os.path.expanduser(raw)))
        verdict = self._safety.executable_verdict(exe)
        if not verdict.blocked:  # the alias name itself must not smuggle a blocked program either
            verdict = self._safety.executable_verdict(raw)
        # blocked programs are judged (RED) by name, independent of platform specifics such as the ".exe" suffix
        if not verdict.blocked:
            if not os.path.isfile(exe):
                raise ComputerError(ErrorCode.LAUNCH_FAILED, f"executable for '{name[:40]}' was not found")
            if not self._is_launchable(exe):
                raise ComputerError(ErrorCode.LAUNCH_FAILED, "the target is not an executable program")
        ctx = {"anwendung": safe_label(name, 80), "programm": safe_label(exe, 200)}
        if argv:
            ctx["argumente"] = safe_label(" ".join(argv), 200)
        return self._seal(Plan(res.TOOL_APP, "launch", res.app_resource(exe, argv), verdict.level,
                               verdict.reason or f"Anwendung starten: {safe_label(name, 40)}", ctx,
                               lambda: self._launch(launcher, exe, argv)))

    # -- helpers for planning / running -------------------------------------------------------------------------------
    @staticmethod
    def _app_name(app: Any) -> str:
        if not isinstance(app, str) or not app.strip() or len(app) > 260 or any(ord(c) < 32 or ord(c) == 127 for c in app):
            raise ComputerError(ErrorCode.INVALID_INPUT, "app must be a non-empty name or absolute path without control characters")
        return app.strip()

    @staticmethod
    def _is_launchable(exe: str) -> bool:
        if sys.platform == "win32":
            return exe.lower().endswith(".exe")
        return os.access(exe, os.X_OK)

    def _launch(self, launcher: Any, exe: str, argv: tuple[str, ...]) -> dict[str, Any]:
        result = self._call(launcher.launch, exe, list(argv))
        return {"pid": result.pid, "executable": result.executable}

    def _window_at(self, x: int, y: int) -> WindowInfo | None:
        """Window under an absolute point, or None if the backend cannot tell (documented limitation)."""
        windows = self._backend.windows
        if windows is None:
            return None
        try:
            return windows.window_at(x, y)
        except ComputerError as exc:
            if exc.code is ErrorCode.UNSUPPORTED:
                return None
            raise
        except Exception as exc:
            raise ComputerError(ErrorCode.BACKEND_ERROR, f"backend failure ({type(exc).__name__})") from None

    def _require_active_window(self) -> WindowInfo:
        """Keyboard input is only ever sent to a known, inspected target window."""
        w = self._call(self._provider("windows").active_window)
        if w is None:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, "there is no active window to receive keyboard input")
        return w

    def _recheck_target(self, ax: int, ay: int) -> None:
        reason = self._safety.window_blocked_reason(self._window_at(ax, ay))
        if reason:
            raise ComputerError(ErrorCode.BLOCKED_TARGET, reason)

    def _recheck_active(self, planned: WindowInfo) -> None:
        """Right before every input: the active window must still be the one that was approved (same handle AND same
        process: a recycled handle is a different window), and not a blocked one."""
        now = self._require_active_window()
        reason = self._safety.window_blocked_reason(now)
        if reason:
            raise ComputerError(ErrorCode.BLOCKED_TARGET, reason)
        if now.handle != planned.handle or not self._same_program(now, planned):
            raise ComputerError(ErrorCode.TARGET_CHANGED, "the active window changed after approval; nothing was typed")

    @staticmethod
    def _same_program(a: WindowInfo, b: WindowInfo) -> bool:
        return a.pid == b.pid and a.process.casefold() == b.process.casefold()

    def _find_window(self, handle: int) -> WindowInfo | None:
        return next((w for w in self._call(self._provider("windows").list_windows) if w.handle == handle), None)

    def _known_window(self, handle: Any) -> WindowInfo:
        """Planning: the explicitly named target window must exist right now."""
        h = val.as_int(handle, "window")
        w = self._find_window(h)
        if w is None:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, f"window {h} does not exist or is not visible")
        return w

    def _bring_to_front(self, planned: WindowInfo, *, geometry: bool = False) -> WindowInfo:
        """Targeted input, step by step: (1) the approved window must still exist, be the same program, be unblocked
        (and, for pointer input, not have moved); (2) it is focused through the window provider; (3) the foreground
        window is read back and must BE that window. Any mismatch aborts before a single event is sent."""
        now = self._find_window(planned.handle)
        if now is None:
            raise ComputerError(ErrorCode.WINDOW_NOT_FOUND, "the target window no longer exists; nothing was sent")
        if not self._same_program(now, planned):
            raise ComputerError(ErrorCode.TARGET_CHANGED, "the target window now belongs to another program; nothing was sent")
        reason = self._safety.window_blocked_reason(now)
        if reason:
            raise ComputerError(ErrorCode.BLOCKED_TARGET, reason)
        if geometry and (now.left, now.top, now.width, now.height) != (planned.left, planned.top, planned.width, planned.height):
            raise ComputerError(ErrorCode.TARGET_CHANGED, "the target window moved or was resized after approval; nothing was done")
        if now.minimized or not now.active:
            self._call(self._provider("windows").focus, planned.handle)
            self._sleep(0.02)  # let the window manager settle before the read-back
        self._recheck_active(planned)
        return now

    TYPE_CHUNK = 16

    def _type_verified(self, keyboard: Any, text: str, planned: WindowInfo) -> None:
        """Typing in short chunks; the active window is re-verified before EVERY chunk, so a window switch in the middle
        of a long text stops the input instead of continuing in another program."""
        for i in range(0, len(text), self.TYPE_CHUNK):
            self._recheck_active(planned)
            self._call(keyboard.type_text, text[i:i + self.TYPE_CHUNK], self.settings.type_interval)

    # -- run functions for the read-only screen actions ----------------------------------------------------------------
    def _run_monitors(self) -> list[dict[str, Any]]:
        return [{"index": m.index, "left": m.left, "top": m.top, "width": m.width, "height": m.height,
                 "primary": m.primary, "name": m.name} for m in self._monitors()]

    def _run_screenshot(self, monitor: Monitor | None, index: int | None) -> dict[str, Any]:
        frame = self._call(self._provider("screen").capture, monitor)
        shot = self.screenshots.add(Screenshot.from_frame(frame, index))
        log.info("screenshot captured id=%s monitor=%s size=%dx%d bytes=%d", shot.id,
                 "all" if index is None else index, shot.width, shot.height, shot.size_bytes)  # metadata only, never pixels
        return shot.info()

    def _run_windows(self) -> list[dict[str, Any]]:
        return [w.describe() for w in self._call(self._provider("windows").list_windows)]

    def _run_active_window(self) -> dict[str, Any] | None:
        w = self._call(self._provider("windows").active_window)
        return w.describe() if w else None

    def _run_cursor(self) -> dict[str, Any]:
        ax, ay = self._call(self._provider("mouse").position)
        for m in self._monitors():
            if m.left <= ax < m.left + m.width and m.top <= ay < m.top + m.height:
                return {"monitor": m.index, "x": ax - m.left, "y": ay - m.top}
        return {"monitor": None, "x": ax, "y": ay}

    # ==================================================================================================================
    # screenshot saving (an explicit, confirmed file write)
    # ==================================================================================================================
    def check_save(self, shot_id: Any, path: Any) -> Screenshot:
        """Describe-time validation for screen_save (no file is touched)."""
        shot = self.screenshots.get(str(shot_id))
        if not isinstance(path, str) or not path.lower().endswith(".png"):
            raise ComputerError(ErrorCode.INVALID_INPUT, "screenshots are saved as .png files")
        return shot

    def save_screenshot(self, shot_id: Any) -> dict[str, Any]:
        """Write a stored screenshot as PNG to the path the PermissionEngine approved (the grant's real path).
        Never overwrites; never follows a symlink at the final component."""
        grant = self._require(res.TOOL_SCREEN_SAVE, "save", None)
        dest = grant.resource
        if not dest or not dest.lower().endswith(".png"):
            raise ComputerError(ErrorCode.NOT_AUTHORIZED, "no approved .png destination")
        shot = self.screenshots.get(str(shot_id))
        png = encode_png(shot.width, shot.height, shot.data)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(dest, flags, 0o600)
        except FileExistsError:
            raise ComputerError(ErrorCode.INVALID_INPUT, "the file already exists (screenshots are never overwritten)") from None
        except FileNotFoundError:
            raise ComputerError(ErrorCode.INVALID_INPUT, "the target directory does not exist") from None
        except OSError as exc:
            raise ComputerError(ErrorCode.BACKEND_ERROR, f"could not create the file ({type(exc).__name__})") from None
        with os.fdopen(fd, "wb") as f:
            f.write(png)
        log.info("screenshot %s saved (%d bytes)", shot.id, len(png))
        return {"path": dest, "bytes": len(png), "screenshot": shot.id}

    # ==================================================================================================================
    # convenience API (each is plan + execute, so each still needs an approved scope)
    # ==================================================================================================================
    def monitors(self) -> list[dict[str, Any]]:
        return self.execute(self.plan_screen("monitors"))

    def screenshot(self, monitor: Any = None) -> dict[str, Any]:
        return self.execute(self.plan_screen("screenshot", monitor=monitor))

    def compare(self, a: str, b: str) -> dict[str, Any]:
        return self.execute(self.plan_screen("compare", a=a, b=b))

    def windows(self) -> list[dict[str, Any]]:
        return self.execute(self.plan_screen("windows"))

    def active_window(self) -> dict[str, Any] | None:
        return self.execute(self.plan_screen("active_window"))

    def cursor(self) -> dict[str, Any]:
        return self.execute(self.plan_screen("cursor"))

    def mouse_move(self, x: int, y: int, monitor: Any = None) -> dict[str, Any]:
        return self.execute(self.plan_mouse("move", x, y, monitor=monitor))

    def click(self, x: int, y: int, monitor: Any = None) -> dict[str, Any]:
        return self.execute(self.plan_mouse("click", x, y, monitor=monitor))

    def double_click(self, x: int, y: int, monitor: Any = None) -> dict[str, Any]:
        return self.execute(self.plan_mouse("double_click", x, y, monitor=monitor))

    def right_click(self, x: int, y: int, monitor: Any = None) -> dict[str, Any]:
        return self.execute(self.plan_mouse("right_click", x, y, monitor=monitor))

    def scroll(self, amount: int, x: int, y: int, monitor: Any = None) -> dict[str, Any]:
        return self.execute(self.plan_mouse("scroll", x, y, monitor=monitor, amount=amount))

    def key_press(self, key: str) -> dict[str, Any]:
        return self.execute(self.plan_keyboard("press", key=key))

    def hotkey(self, keys: Any) -> dict[str, Any]:
        return self.execute(self.plan_keyboard("hotkey", keys=keys))

    def type_text(self, text: str) -> dict[str, Any]:
        return self.execute(self.plan_keyboard("type", text=text))

    type = type_text  # spec-style name: controller.type("...")

    def focus_window(self, handle: int) -> dict[str, Any]:
        return self.execute(self.plan_window("focus", handle))

    def minimize_window(self, handle: int) -> dict[str, Any]:
        return self.execute(self.plan_window("minimize", handle))

    def maximize_window(self, handle: int) -> dict[str, Any]:
        return self.execute(self.plan_window("maximize", handle))

    def restore_window(self, handle: int) -> dict[str, Any]:
        return self.execute(self.plan_window("restore", handle))

    def close_window(self, handle: int) -> dict[str, Any]:
        return self.execute(self.plan_window("close", handle))

    def launch_application(self, app: str, args: Sequence[str] | None = None) -> dict[str, Any]:
        return self.execute(self.plan_app(app, args))
