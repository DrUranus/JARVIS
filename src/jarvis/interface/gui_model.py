"""GUI logic without any toolkit: states, chat log, background work and read-only status (Phase 11).

Nothing in here imports tkinter, so every rule below is tested on every platform. The Tk view (`gui.py`) only draws what this controller reports.

Rules this module enforces:
* Worker threads (text, voice, status) never touch widgets. They put events into a queue that the GUI thread drains.
* A state is shown only when a component REPORTS it: the text worker (processing), the voice session (listening / processing / speaking), the confirmation
  provider (waiting for confirmation) or a failure. Nothing is animated or invented.
* The microphone is started only by an explicit `start_voice()` call (a button), never automatically. While the voice mode runs, typed input is refused (one
  conversation at a time) so that `core.handle` is never entered from two threads.
* After `close()` nothing new starts; the result of a task that is still running is discarded and stoppable subsystems are halted.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from jarvis.errors import JarvisError, VoiceError

log = logging.getLogger("jarvis.interface.gui")

MAX_CHAT_ENTRIES = 1000
MAX_ERROR_TEXT = 300
# read-only commands that feed the status panel (never anything that starts, changes or approves something)
STATUS_COMMANDS = (("Aufgaben", "/tasks"), ("Ziele", "/goals"), ("Berechtigungen", "/permissions"))


KIND_LABELS = {"goal": "Ziel", "agent_task": "Agenten-Task", "repair": "Reparaturlauf", "plan": "Plan"}
_FINISHED = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "TIMEOUT", "COMPLETED"})     # status names (all engines) that mean "over"
ACTIVITY_LIMIT = 50


class UiState(str, Enum):
    READY = "ready"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    ERROR = "error"
    EMERGENCY = "emergency"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {UiState.READY: "Bereit", UiState.LISTENING: "Zuhören", UiState.PROCESSING: "Verarbeiten", UiState.SPEAKING: "Sprechen",
           UiState.AWAITING_CONFIRMATION: "Wartet auf Bestätigung", UiState.ERROR: "Fehler", UiState.EMERGENCY: "NOTAUS"}
_VOICE_TO_UI = {"listening": UiState.LISTENING, "processing": UiState.PROCESSING, "speaking": UiState.SPEAKING}


class StateTracker:
    """Combines what the components report into the one state that is shown. Thread-safe.

    Sources: "text" and "voice" report an activity state (or None = idle); "confirm" counts open confirmation questions; an error stays until the next user action.
    The emergency stop (mirrors the latch in the permission engine) beats everything.
    Priority when several apply: emergency > confirmation > speaking > processing > listening > error > ready."""

    _ORDER = (UiState.AWAITING_CONFIRMATION, UiState.SPEAKING, UiState.PROCESSING, UiState.LISTENING)

    def __init__(self, on_change: Callable[[UiState, str], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._activity: dict[str, UiState | None] = {}
        self._confirmations = 0
        self._emergency = False
        self._error = ""
        self._on_change = on_change
        self._current = UiState.READY

    @property
    def state(self) -> UiState:
        with self._lock:
            return self._compute()

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    def _compute(self) -> UiState:
        if self._emergency:
            return UiState.EMERGENCY
        active = {s for s in self._activity.values() if s is not None}
        if self._confirmations > 0:
            active.add(UiState.AWAITING_CONFIRMATION)
        for st in self._ORDER:
            if st in active:
                return st
        return UiState.ERROR if self._error else UiState.READY

    def _publish(self) -> None:
        with self._lock:
            new, detail = self._compute(), self._error
            changed = new is not self._current or new is UiState.ERROR
            self._current = new
        if changed and self._on_change is not None:
            try:
                self._on_change(new, detail if new is UiState.ERROR else "")
            except Exception:
                log.exception("state observer failed")

    def report(self, source: str, state: UiState | None) -> None:
        with self._lock:
            self._activity[source] = state
        self._publish()

    def confirmation(self, waiting: bool) -> None:
        with self._lock:
            self._confirmations = max(0, self._confirmations + (1 if waiting else -1))
        self._publish()

    def set_emergency(self, engaged: bool) -> None:
        with self._lock:
            self._emergency = bool(engaged)
        self._publish()

    def fail(self, message: str) -> None:
        with self._lock:
            self._error = (message or "Unbekannter Fehler")[:MAX_ERROR_TEXT]
        self._publish()

    def clear_error(self) -> None:
        with self._lock:
            had, self._error = bool(self._error), ""
        if had:
            self._publish()


@dataclass(frozen=True)
class ChatEntry:
    sender: str                     # "Du" | "JARVIS" | "System"
    text: str
    at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ChatEvent:
    entry: ChatEntry


@dataclass(frozen=True)
class StateEvent:
    state: UiState
    detail: str = ""


@dataclass(frozen=True)
class InputEvent:
    """Whether typing is currently possible (and why not)."""
    enabled: bool
    voice_active: bool = False
    reason: str = ""


@dataclass(frozen=True)
class StatusEvent:
    sections: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ActivityItem:
    """One piece of work that has not finished: a goal, an agent task, a repair run or a stored plan (a plan is only a record, nothing executes it)."""
    kind: str                       # "goal" | "agent_task" | "repair" | "plan"
    ident: str
    status: str
    text: str
    note: str = ""                  # known limits before cancelling (for example: the agent does not support cancellation)


@dataclass(frozen=True)
class ActivitySnapshot:
    items: tuple[ActivityItem, ...] = ()
    problems: tuple[str, ...] = ()  # sources that could not be read (shown, never hidden)
    inactive: tuple[str, ...] = ()  # sources that are switched off (the default for goals, agents and self-repair)


@dataclass(frozen=True)
class ActivityEvent:
    snapshot: ActivitySnapshot


@dataclass(frozen=True)
class CancelResult:
    """What a cancel call REALLY answered: cancelled (the work is over), requested (cooperative: it may still run), refused (the interface said no, with its
    reason) or error (the call failed)."""
    kind: str
    ident: str
    outcome: str
    message: str

    @property
    def text(self) -> str:
        head = {"cancelled": "Abgebrochen", "requested": "Abbruch angefordert (kooperativ – die Arbeit kann noch laufen, bis der Agent ihn bemerkt)",
                "refused": "Nicht abgebrochen", "error": "Abbruch fehlgeschlagen"}[self.outcome]
        return f"{KIND_LABELS.get(self.kind, self.kind)} {self.ident}: {head}" + (f" – {self.message}" if self.message else "")


@dataclass(frozen=True)
class CallEvent:
    """Something a non-GUI thread wants to run on the GUI thread (used by the confirmation provider)."""
    fn: Callable[..., Any]
    args: tuple = ()


@dataclass(frozen=True)
class EmergencyEvent:
    """The emergency stop changed (engaged / report updated / reset). `text` is for the chat, `engaged` drives the buttons."""
    engaged: bool
    text: str = ""


@dataclass(frozen=True)
class CloseEvent:
    """The user typed /exit."""


def _no_input(prompt: str = "") -> str:
    raise EOFError("the GUI has no console to ask on")


class SubmitResult(str, Enum):
    STARTED = "started"
    EMPTY = "empty"
    BUSY = "busy"
    VOICE_ACTIVE = "voice_active"
    CLOSED = "closed"
    HANDLED = "handled"             # a GUI-level command (/voice, /exit) was executed without the core
    EMERGENCY = "emergency"         # the emergency stop is engaged: nothing new starts


class GuiController:
    def __init__(self, core: Any, settings: Any = None, *, voice_factory: Callable[..., Any] | None = None,
                 command_runner: Callable[..., str | None] | None = None) -> None:
        self.core, self.settings = core, settings
        self._voice_factory = voice_factory
        self._command_runner = command_runner
        self._events: queue.Queue[Any] = queue.Queue()
        self._lock = threading.RLock()
        self._closed = False
        self._text_busy = False
        self._voice_running = False
        self._voice_stop = threading.Event()
        self._status_busy = False
        self.chat: deque[ChatEntry] = deque(maxlen=MAX_CHAT_ENTRIES)
        self.tracker = StateTracker(self._on_state)
        self._deny_confirmations: Callable[[], Any] | None = None     # set by the view: answers open confirmation dialogs with DENY
        self._stop_busy = False
        self._reset_busy = False
        self._activity_busy = False
        self._cancelling: set[tuple[str, str]] = set()
        # The emergency stop belongs to the permission engine (the central control point); the GUI only triggers and mirrors it. Without it there is no
        # button: a GUI-only stop that merely changes the display would be dangerous.
        self._emergency = getattr(getattr(core, "permissions", None), "emergency", None)
        if self._emergency is not None:
            self._emergency.register("gui", self._emergency_stop_gui)
            self._emergency.add_listener(self._on_emergency)
            if self._emergency.engaged:
                self.tracker.set_emergency(True)

    # -- events (the only bridge to the GUI thread) -----------------------------------------------------------------
    def _emit(self, event: Any) -> None:
        self._events.put(event)

    def drain(self) -> list[Any]:
        """Called by the GUI thread: everything reported since the last call, in order."""
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def call_in_gui(self, fn: Callable[..., Any], *args: Any) -> None:
        """Thread-safe 'run this on the GUI thread' (raises when the GUI is already closed so that callers can deny)."""
        if self._closed:
            raise RuntimeError("the GUI is closed")
        self._emit(CallEvent(fn, args))

    def _on_state(self, state: UiState, detail: str) -> None:
        self._emit(StateEvent(state, detail))

    def say(self, sender: str, text: str) -> None:
        entry = ChatEntry(sender, text)
        self.chat.append(entry)
        self._emit(ChatEvent(entry))

    # -- properties ----------------------------------------------------------------------------------------------------
    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def voice_active(self) -> bool:
        return self._voice_running

    @property
    def busy(self) -> bool:
        """A task or the voice mode is running (closing the window then needs a decision)."""
        return self._text_busy or self.voice_active

    def _input_state(self) -> InputEvent:
        if self.emergency_engaged:
            return InputEvent(False, self.voice_active, "NOTAUS aktiv – Eingabe gesperrt, bis er ausdrücklich aufgehoben wird")
        if self.voice_active:
            return InputEvent(False, True, "Sprachmodus aktiv – zum Tippen beenden")
        if self._text_busy:
            return InputEvent(False, False, "Eine Anfrage läuft")
        return InputEvent(True)

    # -- text -------------------------------------------------------------------------------------------------------------
    def submit(self, text: str) -> SubmitResult:
        text = (text or "").strip()
        if not text:
            return SubmitResult.EMPTY
        with self._lock:
            if self._closed:
                return SubmitResult.CLOSED
            if self.emergency_engaged:
                self.say("System", "Notaus aktiv: keine neuen Anfragen, bis er aufgehoben wird.")
                return SubmitResult.EMERGENCY
            if self.voice_active:
                self.say("System", "Der Sprachmodus ist aktiv. Beende ihn, um zu tippen.")
                return SubmitResult.VOICE_ACTIVE
            if self._text_busy:
                return SubmitResult.BUSY
            command, _, arg = text.partition(" ")
            if command == "/voice":
                self.say("Du", text)
                reason = self.start_voice()
                if reason:
                    self.say("System", reason)
                return SubmitResult.HANDLED
            if command in ("/exit", "/quit"):
                self._emit(CloseEvent())
                return SubmitResult.HANDLED
            self._text_busy = True
        self.tracker.clear_error()
        self.say("Du", text)
        self.tracker.report("text", UiState.PROCESSING)
        self._emit(self._input_state())
        threading.Thread(target=self._work_text, args=(text,), name="jarvis-gui-text", daemon=True).start()
        return SubmitResult.STARTED

    def _work_text(self, text: str) -> None:
        reply, failure = "", ""
        try:
            if text.startswith("/"):
                out = self._run_command(text)
                reply = out if out is not None else "Beenden ist über das Fenster möglich."
            else:
                result = self.core.handle(text)
                reply = getattr(result, "text", str(result))
        except JarvisError as exc:
            reply = f"Fehler: {exc}"
        except Exception as exc:                                    # the reply is generic; details go to the log
            log.exception("GUI request failed")
            reply = "Bei der Verarbeitung ist ein Fehler aufgetreten. Weitere Details stehen im Anwendungsprotokoll."
            failure = f"{type(exc).__name__} bei der Verarbeitung"
        finally:
            with self._lock:
                self._text_busy = False
        if self._closed:
            return                                                  # the window is gone: nothing to show, nothing to report
        self.say("JARVIS", reply)
        self.tracker.report("text", None)
        if failure:
            self.tracker.fail(failure)
        self._emit(self._input_state())

    def _run_command(self, line: str) -> str | None:
        runner = self._command_runner
        if runner is None:
            from jarvis.interface.cli import run_command
            runner = run_command
        return runner(self.core, line, self.settings, lambda _t: None, _no_input)

    # -- voice --------------------------------------------------------------------------------------------------------------
    def start_voice(self) -> str:
        """Start the voice mode on an explicit user request. Returns "" on success, otherwise the reason it can not run (the GUI stays usable by text)."""
        with self._lock:
            if self._closed:
                return "Das Fenster wird geschlossen."
            if self.emergency_engaged:
                return "Notaus aktiv: das Mikrofon bleibt aus, bis er aufgehoben wird."
            if self.voice_active:
                return "Der Sprachmodus läuft bereits."
            if self._text_busy:
                return "Eine Anfrage läuft noch – bitte warten."
            if self.settings is None:
                return "Sprachmodus nicht konfiguriert."
            if str(self.settings.voice.stt_provider).lower() == "console":
                return ("Sprachmodus nicht verfügbar: voice.stt_provider ist „console“ (nur für die Konsole). "
                        "Für die GUI wird eine echte Spracherkennung gebraucht (z. B. stt_provider = \"openai\" mit Mikrofon) – Texteingabe bleibt aktiv.")
            factory = self._voice_factory
            if factory is None:
                from jarvis.bootstrap import build_voice_session
                factory = build_voice_session
            try:
                session = factory(self.settings, self.core, self._voice_line, _no_input, self._voice_state)
            except VoiceError as exc:
                return f"Sprachmodus nicht verfügbar: {exc} – Texteingabe bleibt aktiv."
            except JarvisError as exc:
                return f"Sprachmodus konnte nicht gestartet werden: {exc}"
            except Exception as exc:
                log.exception("voice session could not be built")
                return f"Sprachmodus konnte nicht gestartet werden ({type(exc).__name__}) – Texteingabe bleibt aktiv."
            self.tracker.clear_error()
            self._voice_stop.clear()
            self._voice_running = True
            threading.Thread(target=self._work_voice, args=(session,), name="jarvis-gui-voice", daemon=True).start()
        self.say("System", "Sprachmodus gestartet. Das Mikrofon ist jetzt aktiv.")
        self._emit(self._input_state())
        return ""

    def stop_voice(self) -> None:
        if self.voice_active:
            self._voice_stop.set()
            self.say("System", "Sprachmodus wird beendet (nach der laufenden Aufnahme).")

    def _work_voice(self, session: Any) -> None:
        try:
            session.run(stop=self._voice_stop)
        except Exception as exc:
            log.exception("voice session crashed")
            if not self._closed:
                self.tracker.fail(f"Sprachmodus abgebrochen ({type(exc).__name__})")
        finally:
            self._voice_running = False
            self.tracker.report("voice", None)
        if not self._closed:
            self.say("System", "Sprachmodus beendet. Das Mikrofon ist aus.")
            self._emit(self._input_state())

    def _voice_state(self, state: str, detail: str = "") -> None:
        if self._closed:
            return
        if state == "error":
            self.tracker.fail(detail or "Sprachfehler")
            return
        self.tracker.report("voice", _VOICE_TO_UI.get(state))       # "idle" -> None

    def _voice_line(self, line: str) -> None:
        """Lines of the voice session. Spoken output was already shown as the JARVIS line, so the speaker's console echo is dropped."""
        if self._closed or line.startswith("🔊"):
            return
        for prefix, sender in (("Du: ", "Du"), ("JARVIS: ", "JARVIS")):
            if line.startswith(prefix):
                self.say(sender, line[len(prefix):])
                return
        self.say("System", line)

    # -- emergency stop ------------------------------------------------------------------------------------------------------------
    @property
    def emergency_available(self) -> bool:
        return self._emergency is not None

    @property
    def emergency_engaged(self) -> bool:
        return bool(self._emergency is not None and self._emergency.engaged)

    def set_confirmation_denier(self, fn: Callable[[], Any]) -> None:
        self._deny_confirmations = fn

    def emergency_stop(self, reason: str = "Notaus per GUI") -> bool:
        """The button. The latch is flipped HERE, synchronously and without waiting (works while a request hangs); stopping the components then runs in a
        background thread under the stop deadline, and its report arrives as an EmergencyEvent. False when no emergency stop is available."""
        em = self._emergency
        if em is None:
            self.say("System", "Notaus nicht verfügbar (der Core hat keine zentrale Notaus-Schnittstelle).")
            return False
        em.engage(reason, "gui")                                   # immediate; also reports to _on_emergency
        with self._lock:
            if self._stop_busy:
                return True
            self._stop_busy = True
        threading.Thread(target=self._work_stop, name="jarvis-gui-stop", daemon=True).start()
        return True

    def _work_stop(self) -> None:
        try:
            self._emergency.run_stoppers()                         # reports through the listener when done
        except Exception:
            log.exception("emergency stoppers crashed")
            self.say("System", "NOTAUS aktiv, aber das Anhalten der Komponenten ist fehlgeschlagen – siehe Anwendungsprotokoll. Der Stopp ist NICHT vollständig.")
        finally:
            with self._lock:
                self._stop_busy = False

    def _emergency_stop_gui(self, reason: str) -> Any:
        """The GUI's own part of the stop (registered with the emergency stop): refuse typing (done by the state), answer open confirmation dialogs with DENY, ask
        the voice mode to end. A request that is already inside `core.handle` can not be interrupted: it only finds every tool call denied."""
        from jarvis.permissions.emergency import StopOutcome, StopResult
        notes, outcome = [], StopOutcome.NOTHING
        if self._deny_confirmations is not None:
            self._deny_confirmations()
            notes.append("offene Bestätigungen abgelehnt")
        if self.voice_active:
            self._voice_stop.set()
            notes.append("Sprachmodus beendet nach der laufenden Aufnahme (Wiedergabe lässt sich nicht unterbrechen)")
            outcome = StopOutcome.REQUESTED
        if self._text_busy:
            notes.append("eine laufende Anfrage kann nicht unterbrochen werden; alle Tool-Aufrufe sind gesperrt")
            outcome = StopOutcome.REQUESTED
        if outcome is StopOutcome.NOTHING and notes:
            outcome = StopOutcome.STOPPED
        return StopResult(outcome, "; ".join(notes))

    def _on_emergency(self, engaged: bool, report: Any) -> None:
        """Listener of the emergency stop: may run on any thread, so it only updates the tracker and queues events."""
        engaged = bool(self._emergency is not None and self._emergency.engaged)      # the latch is the truth, never the (possibly late) argument
        self.tracker.set_emergency(engaged)
        if self._closed:
            return
        self._emit(self._input_state())
        text = report.summary() if (engaged and report is not None) else ("Notaus aufgehoben." if not engaged else "")
        self._emit(EmergencyEvent(engaged, text))
        if text:
            entry = ChatEntry("System", text)
            self.chat.append(entry)
            self._emit(ChatEvent(entry))

    def reset_emergency(self) -> bool:
        """Ask for the reset. The permission engine asks the user (confirmation dialog); this runs in a worker so the GUI thread stays free to show it."""
        if self._emergency is None or not self._emergency.engaged:
            return False
        with self._lock:
            if self._reset_busy or self._closed:
                return False
            self._reset_busy = True
        threading.Thread(target=self._work_reset, name="jarvis-gui-reset", daemon=True).start()
        return True

    def _work_reset(self) -> None:
        try:
            res = self.core.permissions.reset_emergency_stop("gui")
            if not self._closed and not res.ok:
                self.say("System", f"Notaus bleibt aktiv: {res.detail}")
            elif not self._closed and res.problems:
                self.say("System", "Notaus aufgehoben, aber: " + "; ".join(res.problems))
        except Exception:
            log.exception("emergency reset crashed")
            self.say("System", "Der Notaus bleibt aktiv (Reset fehlgeschlagen).")
        finally:
            with self._lock:
                self._reset_busy = False

    # -- confirmation (reported by the provider) ----------------------------------------------------------------------------
    def confirmation_waiting(self, waiting: bool) -> None:
        self.tracker.confirmation(waiting)

    # -- status (read-only) ----------------------------------------------------------------------------------------------------
    def request_status(self) -> bool:
        """Collect the status in a worker thread and report it as a StatusEvent. False if a collection is already running or the GUI is closed."""
        with self._lock:
            if self._closed or self._status_busy:
                return False
            self._status_busy = True
        threading.Thread(target=self._work_status, name="jarvis-gui-status", daemon=True).start()
        return True

    def _work_status(self) -> None:
        try:
            sections = self.collect_status()
            if not self._closed:
                self._emit(StatusEvent(tuple(sections)))
        finally:
            with self._lock:
                self._status_busy = False

    def collect_status(self) -> list[tuple[str, str]]:
        """Subsystem states plus the output of the read-only commands in STATUS_COMMANDS. A section that fails says so instead of being left out."""
        sections: list[tuple[str, str]] = []
        lines = []
        for name, sub in sorted(getattr(self.core, "subsystems", {}).items()):
            try:
                status = getattr(sub, "status", None) or ("aktiv" if getattr(sub, "available", False) else "nicht verfügbar")
                reason = getattr(sub, "reason", "")
                lines.append(f"  {name}: {status}" + (f" – {reason}" if reason else ""))
            except Exception as exc:
                lines.append(f"  {name}: nicht lesbar ({type(exc).__name__})")
        sections.append(("Subsysteme", "\n".join(lines) or "keine"))
        for title, command in STATUS_COMMANDS:
            try:
                out = self._run_command(command)
                sections.append((title, (out or "").strip() or "–"))
            except Exception as exc:
                sections.append((title, f"nicht abrufbar ({type(exc).__name__}: {exc})"))
        return sections

    # -- activity: running work, read-only, and the cancel buttons --------------------------------------------------------------------
    # Everything in collect_activity / cancel_activity / _act_* only LISTS and CANCELS. Nothing here starts, creates, resumes or approves anything
    # (a structure test checks the names), and cancelling stays possible while the emergency stop is engaged: stopping is always allowed.
    def request_activity(self) -> bool:
        """Collect the snapshot in a worker thread and report it as an ActivityEvent. False if one is running or the GUI is closed."""
        with self._lock:
            if self._closed or self._activity_busy:
                return False
            self._activity_busy = True
        threading.Thread(target=self._work_activity, name="jarvis-gui-activity", daemon=True).start()
        return True

    def _work_activity(self) -> None:
        try:
            snap = self.collect_activity()
            if not self._closed:
                self._emit(ActivityEvent(snap))
        finally:
            with self._lock:
                self._activity_busy = False

    def collect_activity(self) -> ActivitySnapshot:
        items: list[ActivityItem] = []
        problems: list[str] = []
        inactive: list[str] = []
        for label, reader in (("Ziele", self._act_goals), ("Agenten-Tasks", self._act_agent_tasks), ("Reparaturläufe", self._act_repairs), ("Pläne", self._act_plans)):
            try:
                found, off = reader()
            except Exception as exc:
                problems.append(f"{label}: nicht lesbar ({type(exc).__name__}: {str(exc)[:80]})")
                continue
            if off:
                inactive.append(label)
            items.extend(found[:ACTIVITY_LIMIT])
        return ActivitySnapshot(tuple(items), tuple(problems), tuple(inactive))

    @staticmethod
    def _act_short(text: Any, limit: int = 90) -> str:
        return " ".join(str(text or "").split())[:limit]

    def _act_open(self, status: Any) -> bool:
        return str(getattr(status, "value", status)).upper() not in _FINISHED

    def _act_goals(self) -> tuple[list[ActivityItem], bool]:
        engine = getattr(self.core.subsystems.get("goals"), "engine", None)
        if engine is None:
            return [], True
        return [ActivityItem("goal", g.goal_id, str(g.status.value), self._act_short(g.objective)) for g in self.core.list_goals(limit=ACTIVITY_LIMIT * 2)
                if self._act_open(g.status)], False

    def _act_agent_tasks(self) -> tuple[list[ActivityItem], bool]:
        sub = self.core.subsystems.get("agents")
        orch = getattr(sub, "orchestrator", None)
        if orch is None:
            return [], True
        out = []
        for r in orch.list(limit=ACTIVITY_LIMIT * 2):
            if not self._act_open(r.status):
                continue
            note = ""
            try:
                agent = orch.registry.get(r.agent_id) if r.agent_id and orch.registry.has(r.agent_id) else None
                if agent is not None and not agent.supports_cancellation:
                    note = "dieser Agent unterstützt keinen Abbruch"
            except Exception:
                note = ""
            out.append(ActivityItem("agent_task", r.task_id, str(r.status.value), self._act_short(f"{r.agent_id or '?'}: {r.summary or r.task_id}"), note))
        return out, False

    def _act_repairs(self) -> tuple[list[ActivityItem], bool]:
        engine = getattr(self.core.subsystems.get("self_repair"), "engine", None)
        if engine is None:
            return [], True
        return [ActivityItem("repair", r.run_id, str(r.status.value), self._act_short(r.objective)) for r in self.core.list_repairs(limit=ACTIVITY_LIMIT * 2)
                if self._act_open(r.status)], False

    def _act_plans(self) -> tuple[list[ActivityItem], bool]:
        tasks = getattr(self.core, "tasks", None)
        if tasks is None:
            return [], True
        return [ActivityItem("plan", t.id, str(t.status.value), self._act_short(t.description), "nur ein gespeicherter Plan – nichts führt ihn aus")
                for t in tasks.open_tasks()], False

    def request_cancel(self, kind: str, ident: str) -> bool:
        """The cancel button: runs cancel_activity in a worker, tells the chat what the interface really answered and refreshes the list."""
        key = (kind, ident)
        with self._lock:
            if self._closed or key in self._cancelling:
                return False
            self._cancelling.add(key)
        threading.Thread(target=self._work_cancel, args=(kind, ident), name="jarvis-gui-cancel", daemon=True).start()
        return True

    def _work_cancel(self, kind: str, ident: str) -> None:
        try:
            result = self.cancel_activity(kind, ident)
            if not self._closed:
                self.say("System", result.text)
        finally:
            with self._lock:
                self._cancelling.discard((kind, ident))
        self.request_activity()

    def cancel_activity(self, kind: str, ident: str) -> CancelResult:
        """Call exactly the one cancel interface that belongs to `kind` and report its REAL answer. Unknown kinds or ids are refused without a call."""
        if kind not in KIND_LABELS or not isinstance(ident, str) or not ident or len(ident) > 80:
            return CancelResult(str(kind)[:20], str(ident)[:40], "refused", "unbekannte Art oder ungültige ID")
        try:
            if kind == "goal":
                return self._act_report(kind, ident, self.core.cancel_goal(ident))
            if kind == "agent_task":
                orch = getattr(self.core.subsystems.get("agents"), "orchestrator", None)
                if orch is None:
                    return CancelResult(kind, ident, "refused", "Multi-Agent ist deaktiviert")
                return self._act_report(kind, ident, orch.cancel(ident))
            if kind == "repair":
                return self._act_report(kind, ident, self.core.cancel_repair(ident))
            current = self.core.tasks.get(ident)                                   # kind == "plan": a stored plan, nothing runs
            if not self._act_open(current.status):
                return CancelResult(kind, ident, "refused", f"bereits beendet (Status {getattr(current.status, 'value', current.status)})")
            task = self.core.tasks.cancel(ident)
            done = str(getattr(task.status, "value", task.status)).upper() == "CANCELLED"
            return CancelResult(kind, ident, "cancelled" if done else "refused", "" if done else f"Status ist {getattr(task.status, 'value', task.status)}")
        except Exception as exc:
            return CancelResult(kind, ident, "error", f"{type(exc).__name__}: {str(exc)[:120]}")

    def _act_report(self, kind: str, ident: str, report: Any) -> CancelResult:
        """Translate the answer of goals / orchestrator / repair engine (accepted, status, message) without improving it."""
        accepted = bool(getattr(report, "accepted", False))
        status = getattr(report, "status", None)
        message = self._act_short(getattr(report, "message", ""), 160)
        if not accepted:
            return CancelResult(kind, ident, "refused", message or "die Schnittstelle hat den Abbruch nicht angenommen")
        if status is not None and not self._act_open(status):
            return CancelResult(kind, ident, "cancelled", message)
        return CancelResult(kind, ident, "requested", message)

    # -- closing ----------------------------------------------------------------------------------------------------------------
    def close(self) -> list[str]:
        """Nothing new starts after this. The voice mode is told to stop, a running request keeps its thread but its result is discarded, and subsystems that
        offer an emergency stop (`halt`) are halted when work was still running. Returns what was done (for the log / a message)."""
        with self._lock:
            if self._closed:
                return []
            self._closed = True
            running = self._text_busy or self.voice_active
        done = []
        self._voice_stop.set()
        if running:
            for name, sub in sorted(getattr(self.core, "subsystems", {}).items()):
                halt = getattr(sub, "halt", None)
                if callable(halt):
                    try:
                        halt("GUI closed")
                        done.append(f"{name} angehalten")
                    except Exception as exc:
                        log.warning("halt of %s failed: %s", name, exc)
                        done.append(f"{name}: Anhalten fehlgeschlagen")
        return done
