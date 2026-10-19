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
    assert [s.label for s in UiState] == ["Bereit", "Zuhören", "Verarbeiten", "Sprechen", "Wartet auf Bestätigung", "Fehler", "NOTAUS"]


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


# ---- emergency stop (the GUI triggers and mirrors the engine's latch) ---------------------------------------------------------------------------
from jarvis.interface.gui_model import EmergencyEvent  # noqa: E402
from jarvis.permissions import EmergencyStop, ResetResult  # noqa: E402


class EmergencyCore(FakeCore):
    def __init__(self, *a, reset_ok=True, **kw):
        super().__init__(*a, **kw)
        self.emergency = EmergencyStop()
        self.reset_ok, self.reset_calls = reset_ok, []
        self.permissions = SimpleNamespace(emergency=self.emergency, reset_emergency_stop=self._reset)

    def _reset(self, source="user"):
        self.reset_calls.append(source)
        return self.emergency.reset(lambda: self.reset_ok, source)


def test_the_emergency_button_flips_the_latch_at_once_even_while_a_request_hangs():
    gate = threading.Event()
    core = EmergencyCore(lambda t: (gate.wait(10), SimpleNamespace(text="x"))[1])
    c = GuiController(core)
    c.submit("haengt")
    assert c.busy
    start = time.monotonic()
    assert c.emergency_stop() is True
    assert core.emergency.engaged and time.monotonic() - start < 0.5          # not waiting for the hanging request
    assert c.tracker.state is UiState.EMERGENCY
    gate.set()


def test_while_the_emergency_stop_is_engaged_nothing_new_starts_and_input_is_locked():
    core = EmergencyCore()
    c = GuiController(core, settings())
    c.emergency_stop()
    assert c.submit("hallo") is SubmitResult.EMERGENCY and core.threads == set()
    assert "Notaus aktiv" in c.start_voice()
    ev = collect(c)
    inputs = [e for e in ev if isinstance(e, InputEvent)]
    assert inputs and inputs[-1].enabled is False and "NOTAUS" in inputs[-1].reason


def test_the_stop_report_reaches_the_chat_and_is_honest_about_the_gui_parts():
    core = EmergencyCore()
    denied = []
    c = GuiController(core, settings(), voice_factory=lambda st, co, d, i, on_state: FakeVoice(on_state, d))
    c.set_confirmation_denier(lambda: denied.append(1))
    assert c.start_voice() == ""
    assert wait_for(lambda: c.voice_active)
    c.emergency_stop()
    assert wait_for(lambda: not c.voice_active)
    ev = collect(c, lambda e: any(isinstance(x, EmergencyEvent) and "gui: requested" in x.text for x in e))
    final = [e for e in ev if isinstance(e, EmergencyEvent)][-1]
    assert final.engaged and "gui: requested" in final.text and "Wiedergabe lässt sich nicht unterbrechen" in final.text and denied == [1]
    assert any("NOTAUS aktiv" in t for t in texts(ev, "System"))


def test_a_running_request_is_reported_as_not_interruptible():
    gate = threading.Event()
    core = EmergencyCore(lambda t: (gate.wait(10), SimpleNamespace(text="x"))[1])
    c = GuiController(core)
    c.submit("lang")
    c.emergency_stop()
    ev = collect(c, lambda e: any(isinstance(x, EmergencyEvent) and "nicht unterbrochen" in x.text for x in e))
    assert any(isinstance(x, EmergencyEvent) and "nicht unterbrochen werden" in x.text for x in ev)
    gate.set()


def test_a_failing_component_shows_an_incomplete_stop_in_the_gui():
    core = EmergencyCore()
    core.emergency.register("computer", lambda r: 1 / 0)
    c = GuiController(core)
    c.emergency_stop()
    ev = collect(c, lambda e: any(isinstance(x, EmergencyEvent) and "computer: failed" in x.text for x in e))
    final = [x for x in ev if isinstance(x, EmergencyEvent)][-1]
    assert "UNVOLLSTÄNDIG" in final.text and "computer: failed" in final.text and core.emergency.engaged


def test_reset_goes_through_the_engine_and_only_an_authorised_reset_lifts_the_stop():
    core = EmergencyCore(reset_ok=False)
    c = GuiController(core)
    c.emergency_stop()
    assert c.reset_emergency() is True
    assert wait_for(lambda: core.reset_calls == ["gui"]) and wait_for(lambda: not c._reset_busy)
    assert core.emergency.engaged and c.tracker.state is UiState.EMERGENCY
    assert any("bleibt aktiv" in t for t in texts(collect(c), "System"))
    core.reset_ok = True
    c.reset_emergency()
    assert wait_for(lambda: not core.emergency.engaged)
    assert wait_for(lambda: c.tracker.state is UiState.READY)               # the listener runs right after the latch is cleared
    ev = collect(c, lambda e: InputEvent(True) in e)
    assert InputEvent(True) in ev and c.submit("wieder") is SubmitResult.STARTED
    assert idle(c)


def test_reset_is_refused_when_nothing_is_engaged_and_there_is_no_gui_only_stop():
    core = EmergencyCore()
    c = GuiController(core)
    assert c.reset_emergency() is False and core.reset_calls == []
    plain = GuiController(FakeCore())                          # a core without the central interface
    assert not plain.emergency_available and plain.emergency_stop() is False
    assert any("nicht verfügbar" in t for t in texts(plain.drain(), "System")) and plain.tracker.state is UiState.READY


def test_a_new_request_never_lifts_the_emergency_stop():
    core = EmergencyCore()
    c = GuiController(core)
    c.emergency_stop()
    for _ in range(3):
        assert c.submit("x") is SubmitResult.EMERGENCY
    assert core.emergency.engaged


# ---- activity: running work (read-only) and the cancel buttons (Phase 14, sub-goal 2) -----------------------------------------------------------
import ast  # noqa: E402
from pathlib import Path  # noqa: E402

from jarvis.agents.state import TaskStatus as AgentStatus  # noqa: E402
from jarvis.goals.state import GoalStatus  # noqa: E402
from jarvis.interface.gui_model import ActivityEvent, ActivityItem, CancelResult  # noqa: E402
from jarvis.self_repair.state import RepairStatus  # noqa: E402
from jarvis.tasks.manager import TaskManager  # noqa: E402
from jarvis.tasks.task import Task  # noqa: E402


def report(accepted, status, message="msg"):
    return SimpleNamespace(accepted=accepted, status=status, message=message)


class ActCore:
    """A core with fake engines. Every call is recorded, so a test can prove which interface a button reached."""
    def __init__(self, goals=(), agent_tasks=(), repairs=(), plans=(), *, off=(), unsupported=()):
        self.calls = []
        self.threads = set()
        self.goal_items = list(goals)
        self.task_items = list(agent_tasks)
        self.repair_items = list(repairs)
        self.cancel_answers = {}
        outer = self

        class Orch:
            registry = SimpleNamespace(has=lambda a: True, get=lambda a: SimpleNamespace(supports_cancellation=a not in unsupported))

            def list(self, limit=None):
                outer.calls.append("orch.list")
                return [SimpleNamespace(task_id=t, agent_id=a, status=st, summary=s) for t, a, st, s in outer.task_items]

            def cancel(self, task_id):
                outer.calls.append(f"orch.cancel:{task_id}")
                outer.threads.add(threading.get_ident())
                return outer.cancel_answers.get(task_id, report(True, AgentStatus.CANCELLED))
        self.subsystems = {}
        if "goals" not in off:
            self.subsystems["goals"] = SimpleNamespace(engine=object())
        if "agents" not in off:
            self.subsystems["agents"] = SimpleNamespace(orchestrator=Orch())
        if "self_repair" not in off:
            self.subsystems["self_repair"] = SimpleNamespace(engine=object())
        self.tasks = TaskManager()
        for t in plans:
            self.tasks.add(t)

    def list_goals(self, limit=None):
        self.calls.append("list_goals")
        return [SimpleNamespace(goal_id=g, objective=o, status=st) for g, o, st in self.goal_items]

    def cancel_goal(self, goal_id):
        self.calls.append(f"cancel_goal:{goal_id}")
        self.threads.add(threading.get_ident())
        return self.cancel_answers.get(goal_id, report(True, GoalStatus.CANCELLED))

    def list_repairs(self, limit=None):
        self.calls.append("list_repairs")
        return [SimpleNamespace(run_id=r, objective=o, status=st) for r, o, st in self.repair_items]

    def cancel_repair(self, run_id):
        self.calls.append(f"cancel_repair:{run_id}")
        self.threads.add(threading.get_ident())
        return self.cancel_answers.get(run_id, report(True, RepairStatus.CANCELLED))

    def handle(self, text):                                         # pragma: no cover - the activity code must never get here
        raise AssertionError("activity code called core.handle")


def busy_core(**kw):
    return ActCore(goals=[("g-run", "Marktanalyse\nfür   Q3", GoalStatus.RUNNING), ("g-done", "fertig", GoalStatus.SUCCEEDED), ("g-wait", "wartet", GoalStatus.WAITING)],
                   agent_tasks=[("t-run", "research", AgentStatus.RUNNING, "liest Seiten"), ("t-end", "coding", AgentStatus.FAILED, "x"),
                                ("t-pend", "coding", AgentStatus.PENDING, "")],
                   repairs=[("r-run", "Tests reparieren", RepairStatus.PLANNING), ("r-end", "alt", RepairStatus.CANCELLED)],
                   plans=[Task("Plan A")], **kw)


def test_activity_lists_only_unfinished_work_of_every_kind_and_shortens_the_text():
    c = GuiController(busy_core(unsupported=("coding",)))
    snap = c.collect_activity()
    by = {(i.kind, i.ident): i for i in snap.items}
    assert set(by) == {("goal", "g-run"), ("goal", "g-wait"), ("agent_task", "t-run"), ("agent_task", "t-pend"), ("repair", "r-run"), ("plan", next(iter(c.core.tasks.list())).id)}
    assert by[("goal", "g-run")].text == "Marktanalyse für Q3" and by[("goal", "g-run")].status == "RUNNING"            # whitespace collapsed
    assert by[("agent_task", "t-pend")].note == "dieser Agent unterstützt keinen Abbruch" and by[("agent_task", "t-run")].note == ""
    assert "nichts führt ihn aus" in by[("plan", next(iter(c.core.tasks.list())).id)].note
    assert snap.problems == () and snap.inactive == ()


def test_activity_never_hides_a_source_that_can_not_be_read():
    core = busy_core()
    core.list_goals = lambda limit=None: (_ for _ in ()).throw(RuntimeError("engine kaputt"))
    snap = GuiController(core).collect_activity()
    assert any(p.startswith("Ziele: nicht lesbar (RuntimeError") for p in snap.problems)
    assert {i.kind for i in snap.items} == {"agent_task", "repair", "plan"}                  # the other sources still show


def test_switched_off_subsystems_are_named_not_treated_as_errors():
    snap = GuiController(ActCore(off=("goals", "agents", "self_repair"))).collect_activity()
    assert snap.items == () and snap.problems == () and snap.inactive == ("Ziele", "Agenten-Tasks", "Reparaturläufe")
    snap = GuiController(FakeCore()).collect_activity()                                         # a core without any of it
    assert snap.items == () and "Pläne" in snap.inactive


def test_each_kind_reaches_exactly_its_own_cancel_interface_and_nothing_else():
    core = busy_core()
    c = GuiController(core)
    plan_id = next(iter(core.tasks.list())).id
    assert c.cancel_activity("goal", "g-run").outcome == "cancelled" and core.calls == ["cancel_goal:g-run"]
    core.calls.clear()
    assert c.cancel_activity("agent_task", "t-run").outcome == "cancelled" and core.calls == ["orch.cancel:t-run"]
    core.calls.clear()
    assert c.cancel_activity("repair", "r-run").outcome == "cancelled" and core.calls == ["cancel_repair:r-run"]
    core.calls.clear()
    assert c.cancel_activity("plan", plan_id).outcome == "cancelled" and core.calls == [] and core.tasks.get(plan_id).status.value == "CANCELLED"


def test_unknown_kind_or_id_is_refused_without_any_call():
    core = busy_core()
    c = GuiController(core)
    for kind, ident in (("run_goal", "g"), ("goal", ""), ("goal", "x" * 200), ("", "g"), ("agent_task; drop", "t")):
        r = c.cancel_activity(kind, ident)
        assert r.outcome == "refused" and core.calls == []


def test_the_message_follows_the_real_answer_of_the_interface():
    core = busy_core()
    c = GuiController(core)
    core.cancel_answers["g-run"] = report(True, GoalStatus.RUNNING, "cancellation requested")                      # cooperative
    core.cancel_answers["t-run"] = report(False, AgentStatus.RUNNING, "this agent does not support cancellation")  # unsupported
    core.cancel_answers["r-run"] = report(False, RepairStatus.SUCCEEDED, "the run is already SUCCEEDED")            # already over
    r1, r2, r3 = c.cancel_activity("goal", "g-run"), c.cancel_activity("agent_task", "t-run"), c.cancel_activity("repair", "r-run")
    assert (r1.outcome, r2.outcome, r3.outcome) == ("requested", "refused", "refused")
    assert "kooperativ" in r1.text and "Abbruch angefordert" in r1.text and "Abgebrochen –" not in r1.text            # never "cancelled" for a mere request
    assert "Nicht abgebrochen" in r2.text and "does not support cancellation" in r2.text
    assert "Nicht abgebrochen" in r3.text and "already SUCCEEDED" in r3.text
    core.cancel_goal = lambda gid: (_ for _ in ()).throw(RuntimeError("boom"))
    r4 = c.cancel_activity("goal", "g-run")
    assert r4.outcome == "error" and "Abbruch fehlgeschlagen" in r4.text and "RuntimeError" in r4.text
    plan_id = next(iter(core.tasks.list())).id
    core.tasks.cancel(plan_id)
    already = c.cancel_activity("plan", plan_id)                                                                   # an already finished plan is refused, not "cancelled" again
    assert already.outcome == "refused" and "bereits beendet" in already.text
    assert c.cancel_activity("plan", "unbekannt").outcome == "error"                                               # an unknown id: the manager's error is shown
    assert c.cancel_activity("agent_task", "t-run").outcome == "refused"


def test_with_the_agent_layer_off_a_task_cancel_is_refused_without_a_call():
    core = busy_core(off=("agents",))
    assert GuiController(core).cancel_activity("agent_task", "t-run").outcome == "refused" and "orch.cancel:t-run" not in core.calls


def test_cancelling_works_while_the_emergency_stop_is_engaged_and_starts_nothing():
    core = busy_core()
    core.emergency = EmergencyStop()
    core.permissions = SimpleNamespace(emergency=core.emergency, reset_emergency_stop=lambda s="x": ResetResult(False, "no"))
    c = GuiController(core)
    c.emergency_stop()
    assert core.emergency.engaged
    assert c.cancel_activity("goal", "g-run").outcome == "cancelled" and core.calls[-1] == "cancel_goal:g-run"
    assert c.request_cancel("repair", "r-run") is True
    assert wait_for(lambda: "cancel_repair:r-run" in core.calls)
    assert core.emergency.engaged and not any(x.startswith(("run", "create", "start")) for x in core.calls)          # still stopped, nothing was started


def test_the_cancel_button_runs_in_a_worker_reports_in_the_chat_and_refreshes_the_list():
    core = busy_core()
    c = GuiController(core)
    assert c.request_cancel("goal", "g-run") is True
    ev = collect(c, lambda e: any(isinstance(x, ActivityEvent) for x in e) and any("Ziel g-run: Abgebrochen" in t for t in texts(e, "System")))
    assert any("Ziel g-run: Abgebrochen" in t for t in texts(ev, "System")) and any(isinstance(x, ActivityEvent) for x in ev)
    assert core.threads and threading.get_ident() not in core.threads                                              # never on the GUI thread


def test_a_second_click_on_the_same_item_is_ignored_while_the_first_cancel_is_in_flight():
    gate = threading.Event()
    core = busy_core()
    core.cancel_goal = lambda gid: (gate.wait(5), report(True, GoalStatus.CANCELLED))[1]
    c = GuiController(core)
    assert c.request_cancel("goal", "g-run") and not c.request_cancel("goal", "g-run")
    assert c.request_cancel("goal", "g-wait")                                                                      # another item is independent
    gate.set()


def test_one_activity_collection_at_a_time_and_none_after_closing():
    gate = threading.Event()
    core = busy_core()
    original = core.list_goals
    core.list_goals = lambda limit=None: (gate.wait(5), original(limit))[1]
    c = GuiController(core)
    assert c.request_activity() and not c.request_activity()
    gate.set()
    ev = collect(c, lambda e: any(isinstance(x, ActivityEvent) for x in e))
    assert len([x for x in ev if isinstance(x, ActivityEvent)]) == 1
    assert wait_for(c.request_activity)
    c.close()
    assert not c.request_activity() and not c.request_cancel("goal", "g-run")


def test_the_activity_code_only_lists_and_cancels():
    """Structure: inside collect_activity / cancel_activity / _act_* no attribute that starts, creates, resumes, approves or runs anything is touched."""
    forbidden = {"run", "run_goal", "run_repair", "create", "create_goal", "create_repair", "submit", "start", "resume", "enable", "disable", "reset", "plan", "handle",
                 "execute", "authorize", "approve", "activate", "remember", "forget", "set_confirmation_provider", "halt"}
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src" / "jarvis" / "interface" / "gui_model.py").read_text(encoding="utf-8"))
    scanned = 0
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and (n.name in ("collect_activity", "cancel_activity") or n.name.startswith("_act_"))):
        scanned += 1
        used = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        assert not used & forbidden, f"{fn.name} touches {used & forbidden}"
    assert scanned >= 8


def test_the_real_core_shows_a_stored_plan_and_the_default_has_everything_else_off():
    from jarvis.core import JarvisCore
    from jarvis.llm.mock import MockProvider
    core = JarvisCore(MockProvider())
    core.tasks.add(Task("Webseite bauen"))
    c = GuiController(core)
    snap = c.collect_activity()
    assert [(i.kind, i.text) for i in snap.items] == [("plan", "Webseite bauen")] and set(snap.inactive) == {"Ziele", "Agenten-Tasks", "Reparaturläufe"}
    assert c.cancel_activity("plan", snap.items[0].ident).outcome == "cancelled" and c.collect_activity().items == ()
