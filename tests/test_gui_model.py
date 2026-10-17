"""GUI logic without tkinter: states, background work, voice, status, closing. Runs on every platform (no display, no microphone, no audio)."""
import threading
import time
from types import SimpleNamespace

import pytest

from jarvis.errors import JarvisError, VoiceError
from jarvis.interface.gui_model import (STATUS_COMMANDS, CallEvent, ChatEvent, CloseEvent, GuiController, InputEvent, StateEvent, StateTracker,
                                        StatusEvent, SubmitResult, UiState)


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


class FakeCore:
    def __init__(self, handler=None, subsystems=None):
        self.handler = handler or (lambda text: SimpleNamespace(text=f"echo {text}"))
        self.subsystems = subsystems or {}
        self.threads = set()

    def handle(self, text):
        self.threads.add(threading.get_ident())
        return self.handler(text)


def collect(ctrl, until=None, timeout=5.0):
    """Drain events until `until(events)` is true."""
    events = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        events += ctrl.drain()
        if until is None or until(events):
            return events
        time.sleep(0.005)
    return events


def texts(events, sender=None):
    return [e.entry.text for e in events if isinstance(e, ChatEvent) and (sender is None or e.entry.sender == sender)]


def idle(ctrl):
    return wait_for(lambda: not ctrl.busy)


# ---- StateTracker --------------------------------------------------------------------------------------------------------------------------------
def test_tracker_starts_ready_and_prefers_the_most_specific_state():
    t = StateTracker()
    assert t.state is UiState.READY
    t.report("voice", UiState.LISTENING)
    assert t.state is UiState.LISTENING
    t.report("text", UiState.PROCESSING)
    assert t.state is UiState.PROCESSING
    t.report("voice", UiState.SPEAKING)
    assert t.state is UiState.SPEAKING
    t.confirmation(True)
    assert t.state is UiState.AWAITING_CONFIRMATION
    t.confirmation(False)
    assert t.state is UiState.SPEAKING
    t.report("voice", None)
    t.report("text", None)
    assert t.state is UiState.READY


def test_tracker_error_is_sticky_until_cleared_but_never_hides_real_activity():
    t = StateTracker()
    t.fail("kaputt")
    assert t.state is UiState.ERROR and t.error == "kaputt"
    t.report("text", UiState.PROCESSING)
    assert t.state is UiState.PROCESSING
    t.report("text", None)
    assert t.state is UiState.ERROR
    t.clear_error()
    assert t.state is UiState.READY and t.error == ""


def test_tracker_confirmation_counter_never_goes_negative_and_counts_several_questions():
    t = StateTracker()
    t.confirmation(False)
    assert t.state is UiState.READY
    t.confirmation(True)
    t.confirmation(True)
    t.confirmation(False)
    assert t.state is UiState.AWAITING_CONFIRMATION
    t.confirmation(False)
    assert t.state is UiState.READY


def test_tracker_notifies_only_on_change_and_survives_a_broken_observer():
    seen = []
    t = StateTracker(lambda s, d: seen.append((s, d)))
    t.report("text", UiState.PROCESSING)
    t.report("voice", UiState.PROCESSING)                  # the shown state does not change
    t.report("text", None)
    t.report("voice", None)
    assert [s for s, _ in seen] == [UiState.PROCESSING, UiState.READY]
    t2 = StateTracker(lambda s, d: 1 / 0)
    t2.report("text", UiState.PROCESSING)
    assert t2.state is UiState.PROCESSING


def test_every_state_has_a_german_label():
    assert [s.label for s in UiState] == ["Bereit", "Zuhören", "Verarbeiten", "Sprechen", "Wartet auf Bestätigung", "Fehler"]


# ---- text ------------------------------------------------------------------------------------------------------------------------------------
def test_submit_runs_in_the_background_and_reports_in_order():
    core = FakeCore()
    c = GuiController(core)
    assert c.submit("  hallo  ") is SubmitResult.STARTED
    ev = collect(c, lambda e: any(isinstance(x, InputEvent) and x.enabled for x in e[1:]))
    kinds = [type(e).__name__ + (":" + e.entry.sender if isinstance(e, ChatEvent) else "") for e in ev]
    assert kinds[0] == "ChatEvent:Du" and texts(ev, "Du") == ["hallo"]
    assert ev[1] == StateEvent(UiState.PROCESSING) and ev[2] == InputEvent(False, False, "Eine Anfrage läuft")
    assert texts(ev, "JARVIS") == ["echo hallo"]
    assert ev[-2] == StateEvent(UiState.READY) and ev[-1] == InputEvent(True)
    assert core.threads and threading.get_ident() not in core.threads          # never ran on the calling (GUI) thread


def test_empty_input_starts_nothing():
    c = GuiController(FakeCore())
    assert c.submit("   ") is SubmitResult.EMPTY and c.drain() == [] and not c.busy


def test_a_second_request_is_refused_while_one_runs():
    gate = threading.Event()
    c = GuiController(FakeCore(lambda t: (gate.wait(5), SimpleNamespace(text="fertig"))[1]))
    assert c.submit("eins") is SubmitResult.STARTED
    assert c.busy and c.submit("zwei") is SubmitResult.BUSY
    gate.set()
    assert idle(c)
    ev = collect(c, lambda e: "fertig" in texts(e, "JARVIS"))
    assert texts(ev, "Du") == ["eins"]                    # "zwei" was never accepted


def test_an_unexpected_exception_shows_a_generic_reply_sets_the_error_state_and_frees_the_input():
    def boom(_t):
        raise RuntimeError("geheimes Detail")
    c = GuiController(FakeCore(boom))
    c.submit("x")
    assert idle(c)
    ev = collect(c, lambda e: InputEvent(True) in e)
    reply = texts(ev, "JARVIS")[0]
    assert "Fehler" in reply and "geheimes Detail" not in reply          # details go to the log, not into the window
    assert c.tracker.state is UiState.ERROR and "RuntimeError" in c.tracker.error
    assert InputEvent(True) in ev
    c.core.handler = lambda t: SimpleNamespace(text="wieder ok")
    c.submit("y")
    assert idle(c)
    collect(c, lambda e: "wieder ok" in texts(e, "JARVIS"))
    assert c.tracker.state is UiState.READY                              # the next user action cleared the old error


def test_an_expected_jarvis_error_is_shown_as_text_without_the_error_state():
    def denied(_t):
        raise JarvisError("abgelehnt")
    c = GuiController(FakeCore(denied))
    c.submit("x")
    assert idle(c)
    ev = collect(c, lambda e: InputEvent(True) in e)
    assert texts(ev, "JARVIS") == ["Fehler: abgelehnt"] and c.tracker.state is UiState.READY


# ---- slash commands ----------------------------------------------------------------------------------------------------------------------------
def test_slash_commands_go_through_the_cli_command_runner_without_a_console():
    calls = []

    def runner(core, line, settings, output_fn, input_fn):
        calls.append(line)
        with pytest.raises(EOFError):
            input_fn("?")                                     # a command can never block on stdin
        return "Ausgabe"
    c = GuiController(FakeCore(), command_runner=runner)
    c.submit("/tasks")
    assert idle(c)
    assert texts(collect(c, lambda e: "Ausgabe" in texts(e, "JARVIS")), "JARVIS") == ["Ausgabe"] and calls == ["/tasks"]


def test_voice_and_exit_commands_are_handled_by_the_gui_not_the_core():
    calls = []
    c = GuiController(FakeCore(), command_runner=lambda *a: calls.append(a) or "x")
    assert c.submit("/exit") is SubmitResult.HANDLED
    assert any(isinstance(e, CloseEvent) for e in c.drain())
    assert c.submit("/voice") is SubmitResult.HANDLED          # no settings -> refused with a reason, still no core call
    assert calls == [] and any("nicht konfiguriert" in t for t in texts(c.drain(), "System"))


# ---- voice -------------------------------------------------------------------------------------------------------------------------------------
def settings(stt="mock"):
    return SimpleNamespace(voice=SimpleNamespace(stt_provider=stt))


class FakeVoice:
    """Stands in for VoiceSession: reports states the way the real one does and runs until stopped."""
    def __init__(self, on_state, display, script=("listening", "processing", "speaking", "idle", "listening")):
        self.on_state, self.display, self.script, self.started = on_state, display, script, threading.Event()

    def run(self, stop):
        self.display("Du: wie spät ist es")
        self.display("JARVIS: kurz nach zwölf")
        self.display("🔊 kurz nach zwölf")
        for s in self.script:
            self.on_state(s, "")
        self.started.set()
        stop.wait(5)
        self.on_state("idle", "")


def voice_ctrl(**kw):
    made = {}

    def factory(st, core, display, input_fn, on_state):
        made["session"] = FakeVoice(on_state, display)
        made["input_fn"] = input_fn
        return made["session"]
    return GuiController(FakeCore(), kw.pop("settings", settings()), voice_factory=kw.pop("factory", factory), **kw), made


def test_the_microphone_is_never_started_automatically():
    c, made = voice_ctrl()
    c.submit("hallo")
    assert idle(c) and "session" not in made and not c.voice_active


def test_voice_mode_reports_real_states_and_returns_to_ready():
    c, made = voice_ctrl()
    seen = []
    c.tracker._on_change = lambda s, d: seen.append(s)
    assert c.start_voice() == ""
    assert wait_for(lambda: "session" in made and made["session"].started.is_set())
    assert seen[:3] == [UiState.LISTENING, UiState.PROCESSING, UiState.SPEAKING] and c.voice_active
    c.stop_voice()
    assert wait_for(lambda: not c.voice_active)
    ev = collect(c, lambda e: InputEvent(True) in e)
    assert seen[-1] is UiState.READY and c.tracker.state is UiState.READY and InputEvent(True) in ev
    assert texts(ev, "Du") == ["wie spät ist es"] and texts(ev, "JARVIS") == ["kurz nach zwölf"]      # the speaker's console echo is dropped
    assert any("Mikrofon ist aus" in t for t in texts(ev, "System"))


def test_typing_is_refused_while_the_voice_mode_runs_and_core_handle_is_never_entered_twice():
    c, made = voice_ctrl()
    c.start_voice()
    assert wait_for(lambda: "session" in made)
    assert c.submit("tippen") is SubmitResult.VOICE_ACTIVE and c.core.threads == set()
    assert c.start_voice() == "Der Sprachmodus läuft bereits."
    c.stop_voice()
    assert wait_for(lambda: not c.voice_active)


def test_voice_that_is_not_possible_gives_a_reason_and_text_stays_usable():
    c, made = voice_ctrl(settings=settings("console"))
    reason = c.start_voice()
    assert "console" in reason and "Texteingabe bleibt aktiv" in reason and "session" not in made
    c2 = GuiController(FakeCore(), settings(), voice_factory=lambda *a: (_ for _ in ()).throw(VoiceError("kein Mikrofon")))
    assert c2.start_voice() == "Sprachmodus nicht verfügbar: kein Mikrofon – Texteingabe bleibt aktiv."
    c3 = GuiController(FakeCore(), settings(), voice_factory=lambda *a: (_ for _ in ()).throw(ImportError("sounddevice")))
    assert "ImportError" in c3.start_voice()
    for ctrl in (c, c2, c3):
        assert ctrl.submit("hallo") is SubmitResult.STARTED and idle(ctrl)


def test_voice_cannot_start_while_a_request_runs():
    gate = threading.Event()
    c, made = voice_ctrl()
    c.core.handler = lambda t: (gate.wait(5), SimpleNamespace(text="x"))[1]
    c.submit("lang")
    assert "Anfrage läuft" in c.start_voice() and "session" not in made
    gate.set()
    assert idle(c)


def test_a_voice_error_and_a_crash_are_shown_as_the_error_state():
    c, made = voice_ctrl()
    c.start_voice()
    assert wait_for(lambda: "session" in made and made["session"].started.is_set())
    made["session"].on_state("error", "Audio nicht verfügbar: weg")
    assert c.tracker.error == "Audio nicht verfügbar: weg"
    c.stop_voice()
    assert wait_for(lambda: not c.voice_active) and c.tracker.state is UiState.ERROR

    class Crashing:
        def run(self, stop):
            raise RuntimeError("abgestürzt")
    c2 = GuiController(FakeCore(), settings(), voice_factory=lambda *a: Crashing())
    c2.start_voice()
    assert wait_for(lambda: not c2.voice_active and c2.tracker.state is UiState.ERROR) and "RuntimeError" in c2.tracker.error


# ---- confirmation ---------------------------------------------------------------------------------------------------------------------------------
def test_waiting_for_a_confirmation_is_a_real_state():
    c = GuiController(FakeCore())
    c.confirmation_waiting(True)
    assert c.tracker.state is UiState.AWAITING_CONFIRMATION
    c.confirmation_waiting(False)
    assert c.tracker.state is UiState.READY
    assert [e.state for e in c.drain() if isinstance(e, StateEvent)] == [UiState.AWAITING_CONFIRMATION, UiState.READY]


# ---- status -----------------------------------------------------------------------------------------------------------------------------------
def test_status_lists_subsystems_and_only_the_read_only_commands():
    asked = []

    def runner(core, line, st, out, inp):
        asked.append(line)
        if line == "/goals":
            raise RuntimeError("engine kaputt")
        return f"Ausgabe von {line}"
    subs = {"computer": SimpleNamespace(status="disabled", reason="aus", available=False), "goals": SimpleNamespace(available=True),
            "x": SimpleNamespace()}
    c = GuiController(FakeCore(subsystems=subs), command_runner=runner)
    assert c.request_status()
    ev = collect(c, lambda e: any(isinstance(x, StatusEvent) for x in e))
    sections = dict(next(e for e in ev if isinstance(e, StatusEvent)).sections)
    assert "computer: disabled – aus" in sections["Subsysteme"] and "goals: aktiv" in sections["Subsysteme"] and "x: nicht verfügbar" in sections["Subsysteme"]
    assert sections["Aufgaben"] == "Ausgabe von /tasks" and "nicht abrufbar (RuntimeError" in sections["Ziele"]      # a failing section says so
    assert asked == [cmd for _, cmd in STATUS_COMMANDS] and all(cmd in ("/tasks", "/goals", "/permissions") for cmd in asked)


def test_only_one_status_collection_runs_at_a_time():
    gate = threading.Event()
    c = GuiController(FakeCore(), command_runner=lambda *a: (gate.wait(5), "x")[1])
    assert c.request_status() and not c.request_status()
    gate.set()
    collect(c, lambda e: any(isinstance(x, StatusEvent) for x in e))
    assert wait_for(c.request_status)


# ---- closing ------------------------------------------------------------------------------------------------------------------------------------
def test_after_close_nothing_new_starts_and_a_running_result_is_discarded():
    gate = threading.Event()
    c = GuiController(FakeCore(lambda t: (gate.wait(5), SimpleNamespace(text="zu spät"))[1]))
    c.submit("lang")
    c.drain()
    c.close()
    assert c.submit("neu") is SubmitResult.CLOSED and not c.request_status() and c.start_voice() == "Das Fenster wird geschlossen."
    gate.set()
    assert wait_for(lambda: not c._text_busy)
    time.sleep(0.05)
    assert c.drain() == []                                                # nothing is reported to a window that is gone
    with pytest.raises(RuntimeError):
        c.call_in_gui(print)


def test_close_halts_stoppable_subsystems_only_when_work_is_running():
    halted = []
    subs = {"computer": SimpleNamespace(halt=lambda reason: halted.append(("computer", reason))), "goals": SimpleNamespace(),
            "broken": SimpleNamespace(halt=lambda reason: 1 / 0)}
    idle_ctrl = GuiController(FakeCore(subsystems=subs))
    assert idle_ctrl.close() == [] and halted == []
    gate = threading.Event()
    busy = GuiController(FakeCore(lambda t: (gate.wait(5), SimpleNamespace(text="x"))[1], subsystems=subs))
    busy.submit("lang")
    notes = busy.close()
    assert halted == [("computer", "GUI closed")] and "computer angehalten" in notes and "broken: Anhalten fehlgeschlagen" in notes
    assert busy.close() == []                                             # closing twice does nothing
    gate.set()


def test_close_stops_the_voice_mode():
    c, made = voice_ctrl()
    c.start_voice()
    assert wait_for(lambda: "session" in made and made["session"].started.is_set())
    c.close()
    assert wait_for(lambda: not c.voice_active)


def test_call_in_gui_queues_work_for_the_gui_thread():
    c = GuiController(FakeCore())
    c.call_in_gui(print, "a", "b")
    ev = c.drain()
    assert ev == [CallEvent(print, ("a", "b"))]
