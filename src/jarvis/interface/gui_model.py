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


class UiState(str, Enum):
    READY = "ready"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    ERROR = "error"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {UiState.READY: "Bereit", UiState.LISTENING: "Zuhören", UiState.PROCESSING: "Verarbeiten", UiState.SPEAKING: "Sprechen",
           UiState.AWAITING_CONFIRMATION: "Wartet auf Bestätigung", UiState.ERROR: "Fehler"}
_VOICE_TO_UI = {"listening": UiState.LISTENING, "processing": UiState.PROCESSING, "speaking": UiState.SPEAKING}


class StateTracker:
    """Combines what the components report into the one state that is shown. Thread-safe.

    Sources: "text" and "voice" report an activity state (or None = idle); "confirm" counts open confirmation questions; an error stays until the next user action.
    Priority when several apply: confirmation > speaking > processing > listening > error > ready."""

    _ORDER = (UiState.AWAITING_CONFIRMATION, UiState.SPEAKING, UiState.PROCESSING, UiState.LISTENING)

    def __init__(self, on_change: Callable[[UiState, str], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._activity: dict[str, UiState | None] = {}
        self._confirmations = 0
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
class CallEvent:
    """Something a non-GUI thread wants to run on the GUI thread (used by the confirmation provider)."""
    fn: Callable[..., Any]
    args: tuple = ()


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
