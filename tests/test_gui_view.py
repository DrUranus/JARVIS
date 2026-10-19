"""The real Tk window (gui.py). Needs tkinter and a display: skipped otherwise (Linux CI without X, a Python without Tk). The Windows CI job runs these
for real. What is NOT covered here: how the window looks, a real microphone, real speakers, and a human clicking - see docs/TESTING.md (manual checks)."""
import gc
import os
import threading
import time
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from jarvis.errors import VoiceError  # noqa: E402
from jarvis.interface.gui import GUIConfirmationProvider, JarvisGUI  # noqa: E402
from jarvis.interface.gui_model import GuiController, UiState  # noqa: E402
from jarvis.permissions.confirmation import ConfirmationChoice, ConfirmationRequest  # noqa: E402
from jarvis.permissions.levels import PermissionLevel  # noqa: E402


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:
        if os.environ.get("JARVIS_GUI_TESTS_REQUIRED") == "1":       # set by the Windows CI job: a Tk that does not start there is a finding, not a skip
            raise
        pytest.skip(f"no usable display for Tk ({exc})")
    r.withdraw()
    gc.disable()                      # a Tk object freed by the garbage collector on a WORKER thread aborts the interpreter (Tcl_AsyncDelete): collect only on this thread
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass
    gc.enable()
    gc.collect()


def pump(root, cond, timeout=5.0):
    """Run the Tk event loop in small steps until `cond()` (the real GUI thread does this in mainloop)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            root.update()
        except tk.TclError:
            return cond()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def alive(root):
    try:
        return bool(root.winfo_exists())
    except tk.TclError:
        return False


class Core:
    def __init__(self, handler=None, subsystems=None):
        self.handler = handler or (lambda t: SimpleNamespace(text=f"echo {t}"))
        self.subsystems = subsystems or {}
        self.threads = set()

    def handle(self, text):
        self.threads.add(threading.get_ident())
        return self.handler(text)


def chat(gui):
    return gui.output.get("1.0", "end-1c")


def make(root, core=None, **kw):
    return JarvisGUI(root, core or Core(), **kw)


def widgets(w):
    yield w
    for c in w.winfo_children():
        yield from widgets(c)


def find_button(top, text):
    return next(w for w in widgets(top) if isinstance(w, ttk.Button) and w.cget("text") == text)


def request():
    return ConfirmationRequest(request_id="v-1", tool="filesystem", action="write", level=PermissionLevel.YELLOW, resource="/ws/x.txt",
                               reason="Test", context={}, session_allowed=True)


def test_the_window_opens_shows_ready_and_closes(root):
    gui = make(root)
    assert pump(root, lambda: "Die GUI ist verbunden" in chat(gui))
    assert gui.state_label.cget("text") == "Bereit"
    gui._on_close()
    assert not alive(root) and gui.controller.closed


def test_sending_text_shows_processing_then_the_reply_and_ready(root):
    gate = threading.Event()
    core = Core(lambda t: (gate.wait(5), SimpleNamespace(text="Antwort"))[1])
    gui = make(root, core)
    gui.input_field.insert(0, "Hallo")
    gui._send_message()
    assert pump(root, lambda: gui.state_label.cget("text") == "Verarbeiten")
    assert str(gui.send_button.cget("state")) == "disabled" and str(gui.input_field.cget("state")) == "disabled" and gui.input_field.get() == ""
    gate.set()
    assert pump(root, lambda: "Antwort" in chat(gui) and gui.state_label.cget("text") == "Bereit")
    assert "Du\nHallo" in chat(gui) and str(gui.send_button.cget("state")) == "normal"
    gui._on_close()


def test_widgets_are_only_touched_from_the_gui_thread(root):
    gui = make(root, Core(lambda t: SimpleNamespace(text="ok")))
    main, seen = threading.get_ident(), []
    for name in ("_append_entry", "_apply_state", "_apply_input", "_set_status_text"):
        original = getattr(gui, name)

        def wrapper(*a, _o=original, **k):
            seen.append(threading.get_ident())
            return _o(*a, **k)
        setattr(gui, name, wrapper)
    gui.input_field.insert(0, "x")
    gui._send_message()
    gui._refresh_status()
    assert pump(root, lambda: "ok" in chat(gui) and "Subsysteme" in gui.status_text.get("1.0", "end"))
    assert seen and set(seen) == {main} and main not in gui.core.threads
    gui._on_close()


def test_an_error_is_shown_as_the_error_state_with_its_reason(root):
    def boom(_t):
        raise RuntimeError("intern")
    gui = make(root, Core(boom))
    gui.input_field.insert(0, "x")
    gui._send_message()
    assert pump(root, lambda: gui.state_label.cget("text") == "Fehler")
    assert "RuntimeError" in gui.hint.cget("text") and "intern" not in chat(gui) and str(gui.send_button.cget("state")) == "normal"
    gui._on_close()


def test_closing_during_a_request_asks_first_and_keeps_the_window_when_declined(root):
    gate = threading.Event()
    halted = []
    core = Core(lambda t: (gate.wait(5), SimpleNamespace(text="spät"))[1], {"computer": SimpleNamespace(halt=lambda r: halted.append(r))})
    answers = iter([False, True])
    gui = make(root, core, confirm_close=lambda: next(answers))
    gui.input_field.insert(0, "lang")
    gui._send_message()
    assert pump(root, lambda: gui.controller.busy)
    gui._on_close()
    assert alive(root) and not gui.controller.closed and halted == []
    gui._on_close()
    assert not alive(root) and gui.controller.closed and halted == ["GUI closed"]
    gate.set()
    time.sleep(0.1)                                           # the late result must not raise anywhere (the window is gone)


def test_slash_exit_closes_the_window(root):
    gui = make(root)
    gui.input_field.insert(0, "/exit")
    gui._send_message()
    pump(root, lambda: not alive(root), timeout=3)
    assert not alive(root)


def test_a_confirmation_dialog_is_a_real_state_and_the_answer_reaches_the_asking_thread(root):
    gui = make(root)
    result = {}
    t = threading.Thread(target=lambda: result.update(choice=gui.confirmation_provider.confirm(request())), daemon=True)
    t.start()
    assert pump(root, lambda: gui.state_label.cget("text") == "Wartet auf Bestätigung")
    dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
    find_button(dialog, "Einmal erlauben").invoke()
    t.join(5)
    assert result["choice"] is ConfirmationChoice.ALLOW_ONCE
    assert pump(root, lambda: gui.state_label.cget("text") == "Bereit")
    gui._on_close()


def test_closing_the_window_denies_an_open_confirmation(root):
    gui = make(root)
    result = {}
    t = threading.Thread(target=lambda: result.update(choice=gui.confirmation_provider.confirm(request())), daemon=True)
    t.start()
    assert pump(root, lambda: gui.state_label.cget("text") == "Wartet auf Bestätigung")
    gui._on_close()
    t.join(5)
    assert result["choice"] is ConfirmationChoice.DENY


def test_the_provider_still_works_with_the_default_root_dispatch(root):
    """Without a dispatcher the provider uses Tk's `after`, which only works while a real mainloop runs (it raises 'main thread is not in main loop'
    under update()); the window always passes its own dispatcher, this is the fallback."""
    provider = GUIConfirmationProvider(root, timeout=5)
    result = {}
    t = threading.Thread(target=lambda: result.update(choice=provider.confirm(request())), daemon=True)
    t.start()

    def check():
        dialogs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if dialogs:
            find_button(dialogs[0], "Ablehnen").invoke()
            root.after(50, root.quit)
        else:
            root.after(20, check)
    root.after(50, check)
    root.after(8000, root.quit)
    root.mainloop()
    t.join(5)
    assert result["choice"] is ConfirmationChoice.DENY


def settings(stt):
    return SimpleNamespace(voice=SimpleNamespace(stt_provider=stt))


def test_voice_button_explains_why_voice_is_not_available_and_text_keeps_working(root):
    gui = make(root, Core(), settings=settings("console"), controller=None)
    gui.voice_button.invoke()
    assert pump(root, lambda: "console" in chat(gui)) and gui.state_label.cget("text") == "Bereit"
    gui.input_field.insert(0, "weiter")
    gui._send_message()
    assert pump(root, lambda: "echo weiter" in chat(gui))
    gui._on_close()


def test_voice_mode_through_the_window_shows_listening_and_can_be_stopped(root):
    class Session:
        def __init__(self, on_state):
            self.on_state = on_state

        def run(self, stop):
            self.on_state("listening", "")
            stop.wait(5)
            self.on_state("idle", "")

    ctrl = GuiController(Core(), settings("mock"), voice_factory=lambda st, core, display, inp, on_state: Session(on_state))
    gui = make(root, controller=ctrl, settings=settings("mock"))
    gui.voice_button.invoke()
    assert pump(root, lambda: gui.state_label.cget("text") == "Zuhören" and gui.voice_button.cget("text") == "Sprache beenden")
    assert str(gui.send_button.cget("state")) == "disabled"            # typing is off while the microphone mode runs
    gui.voice_button.invoke()
    assert pump(root, lambda: gui.state_label.cget("text") == "Bereit" and gui.voice_button.cget("text") == "Sprache starten")
    assert str(gui.send_button.cget("state")) == "normal"
    gui._on_close()


def test_a_missing_voice_device_is_reported_without_breaking_the_window(root):
    ctrl = GuiController(Core(), settings("mock"), voice_factory=lambda *a: (_ for _ in ()).throw(VoiceError("kein Mikrofon")))
    gui = make(root, controller=ctrl, settings=settings("mock"))
    gui.voice_button.invoke()
    assert pump(root, lambda: "kein Mikrofon" in chat(gui)) and gui.state_label.cget("text") == "Bereit"
    gui._on_close()


def test_the_status_tab_shows_subsystems_and_read_only_sections(root):
    subs = {"computer": SimpleNamespace(status="disabled", reason="aus")}
    ctrl = GuiController(Core(subsystems=subs), command_runner=lambda c, line, *a: f"Ausgabe {line}")
    gui = make(root, controller=ctrl)
    gui._refresh_status()
    assert pump(root, lambda: "computer: disabled – aus" in gui.status_text.get("1.0", "end"))
    body = gui.status_text.get("1.0", "end")
    assert "Ausgabe /tasks" in body and "Ausgabe /goals" in body and "Ausgabe /permissions" in body
    gui._on_close()


def test_state_styles_exist_for_every_state():
    from jarvis.interface.gui import STATE_STYLE
    assert set(STATE_STYLE) == set(UiState)


# ---- emergency stop through the real window and a REAL permission engine ----------------------------------------------------------------------
def engine_core(handler=None):
    from jarvis.permissions import PermissionEngine
    core = Core(handler)
    core.permissions = PermissionEngine()
    return core


def test_the_emergency_button_locks_the_window_and_only_the_confirmed_reset_unlocks_it(root):
    core = engine_core()
    gui = make(root, core)
    core.permissions.set_confirmation_provider(gui.confirmation_provider, source="test")
    assert str(gui.emergency_button.cget("state")) == "normal" and str(gui.reset_button.cget("state")) == "disabled"
    gui.emergency_button.invoke()
    assert core.permissions.emergency.engaged                                   # the real latch, not just the display
    assert pump(root, lambda: gui.state_label.cget("text") == "NOTAUS" and str(gui.send_button.cget("state")) == "disabled")
    assert str(gui.input_field.cget("state")) == "disabled" and str(gui.voice_button.cget("state")) == "disabled"
    assert str(gui.reset_button.cget("state")) == "normal" and "NOTAUS" in gui.hint.cget("text")
    assert pump(root, lambda: "NOTAUS aktiv" in chat(gui))
    assert gui.controller.submit("hallo").value == "emergency" and core.threads == set()
    # reset: the engine asks through the GUI's confirmation dialog; "Ablehnen" keeps the stop
    gui.reset_button.invoke()
    assert pump(root, lambda: any(isinstance(w, tk.Toplevel) for w in root.winfo_children()))
    dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
    find_button(dialog, "Ablehnen").invoke()
    assert pump(root, lambda: "Notaus bleibt aktiv" in chat(gui)) and core.permissions.emergency.engaged
    assert pump(root, lambda: not gui.controller._reset_busy)
    gui.reset_button.invoke()
    assert pump(root, lambda: any(isinstance(w, tk.Toplevel) for w in root.winfo_children()))
    dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
    assert sorted(w.cget("text") for w in widgets(dialog) if isinstance(w, ttk.Button)) == ["Ablehnen", "Einmal erlauben"]      # no "for the session" option
    find_button(dialog, "Einmal erlauben").invoke()
    assert pump(root, lambda: not core.permissions.emergency.engaged and gui.state_label.cget("text") == "Bereit")
    assert pump(root, lambda: str(gui.send_button.cget("state")) == "normal" and str(gui.reset_button.cget("state")) == "disabled")
    gui._on_close()


def test_the_emergency_button_works_while_a_request_hangs_and_denies_an_open_confirmation(root):
    gate = threading.Event()
    core = engine_core(lambda t: (gate.wait(10), SimpleNamespace(text="spät"))[1])
    gui = make(root, core, confirm_close=lambda: True)
    gui.input_field.insert(0, "lang")
    gui._send_message()
    assert pump(root, lambda: gui.controller.busy)
    result = {}
    t = threading.Thread(target=lambda: result.update(choice=gui.confirmation_provider.confirm(request())), daemon=True)
    t.start()
    assert pump(root, lambda: gui.state_label.cget("text") == "Wartet auf Bestätigung")
    gui.emergency_button.invoke()
    assert pump(root, lambda: gui.state_label.cget("text") == "NOTAUS")
    t.join(5)
    assert result["choice"] is ConfirmationChoice.DENY
    assert pump(root, lambda: "nicht unterbrochen werden" in chat(gui))        # honest: the request itself can not be interrupted
    gate.set()
    gui._on_close()


def test_without_a_central_emergency_stop_the_button_is_disabled(root):
    gui = make(root, Core())
    assert str(gui.emergency_button.cget("state")) == "disabled"
    gui._on_close()


# ---- running work in the status tab (Phase 14, sub-goal 2) ---------------------------------------------------------------------------------------
from test_gui_model import ActCore, busy_core  # noqa: E402


def activity_texts(gui):
    out = []
    for row in gui.activity_rows:
        out.append(" | ".join(str(w.cget("text")) for w in row.winfo_children() if isinstance(w, ttk.Label)))
    return out


def cancel_button(gui, ident):
    for row in gui.activity_rows:
        if any(isinstance(w, ttk.Label) and str(w.cget("text")).startswith(ident) for w in row.winfo_children()):
            return next(w for w in row.winfo_children() if isinstance(w, ttk.Button))
    raise AssertionError(f"no row for {ident}")


def test_the_status_tab_lists_unfinished_work_with_one_cancel_button_each(root):
    core = busy_core(unsupported=("coding",))
    gui = make(root, controller=GuiController(core))
    gui._refresh_status()
    assert pump(root, lambda: len(gui.activity_rows) == 6)
    rows = "\n".join(activity_texts(gui))
    assert "Ziel · RUNNING" in rows and "g-run  Marktanalyse für Q3" in rows and "Agenten-Task · PENDING" in rows and "Reparaturlauf · PLANNING" in rows and "Plan · PENDING" in rows
    assert "dieser Agent unterstützt keinen Abbruch" in rows and "g-done" not in rows and "t-end" not in rows                      # finished work is not listed
    assert [w.cget("text") for r in gui.activity_rows for w in r.winfo_children() if isinstance(w, ttk.Button)] == ["Abbrechen"] * 6
    gui._on_close()


def test_the_cancel_button_calls_only_its_own_interface_shows_the_real_answer_and_refreshes(root):
    core = busy_core()
    gui = make(root, controller=GuiController(core))
    gui._refresh_status()
    assert pump(root, lambda: len(gui.activity_rows) == 6)
    core.calls.clear()
    core.goal_items = [g for g in core.goal_items if g[0] != "g-run"]                                                        # what the engine will report afterwards
    cancel_button(gui, "g-run").invoke()
    assert pump(root, lambda: "Ziel g-run: Abgebrochen" in chat(gui) or "Ziel g-run: Abgebrochen" in gui.status_text.get("1.0", "end"))
    assert pump(root, lambda: len(gui.activity_rows) == 5 and "cancel_goal:g-run" in core.calls)
    assert [c for c in core.calls if c.startswith(("cancel", "orch.cancel"))] == ["cancel_goal:g-run"]                          # no other cancel was touched
    gui._on_close()


def test_a_refused_cancel_is_shown_as_refused_and_the_row_stays(root):
    from jarvis.agents.state import TaskStatus as AgentStatus
    core = busy_core()
    core.cancel_answers["t-run"] = SimpleNamespace(accepted=False, status=AgentStatus.RUNNING, message="this agent does not support cancellation")
    gui = make(root, controller=GuiController(core))
    gui._refresh_status()
    assert pump(root, lambda: len(gui.activity_rows) == 6)
    cancel_button(gui, "t-run").invoke()
    assert pump(root, lambda: "Nicht abgebrochen" in chat(gui) and "does not support cancellation" in chat(gui))
    assert "Abgebrochen –" not in chat(gui) and pump(root, lambda: len(gui.activity_rows) == 6)
    gui._on_close()


def test_the_empty_list_explains_itself_and_unreadable_sources_are_shown(root):
    gui = make(root, controller=GuiController(ActCore(off=("goals", "agents", "self_repair"))))
    gui._refresh_status()
    assert pump(root, lambda: "Keine laufende Arbeit." in gui.activity_hint.cget("text"))
    assert "Ausgeschaltet (Standard): Ziele, Agenten-Tasks, Reparaturläufe." in gui.activity_hint.cget("text") and gui.activity_rows == []
    core = ActCore()
    core.list_goals = lambda limit=None: (_ for _ in ()).throw(RuntimeError("kaputt"))
    gui2 = make(tk.Toplevel(root), controller=GuiController(core))
    gui2._refresh_status()
    assert pump(root, lambda: "Ziele: nicht lesbar (RuntimeError" in gui2.activity_hint.cget("text"))
    gui2._on_close()
    gui._on_close()


def test_the_activity_widgets_are_only_touched_from_the_gui_thread(root):
    core = busy_core()
    gui = make(root, controller=GuiController(core))
    main, seen = threading.get_ident(), []
    original = gui._render_activity

    def wrapper(snap):
        seen.append(threading.get_ident())
        return original(snap)
    gui._render_activity = wrapper
    gui._refresh_status()
    assert pump(root, lambda: len(gui.activity_rows) == 6)
    cancel_button(gui, "r-run").invoke()
    assert pump(root, lambda: "cancel_repair:r-run" in core.calls) and pump(root, lambda: len(seen) >= 2)
    assert seen and set(seen) == {main} and main not in core.threads                                                        # render on the GUI thread, cancel in a worker
    gui._on_close()


def test_cancelling_from_the_window_still_works_while_the_emergency_stop_is_engaged(root):
    core = busy_core()
    from jarvis.permissions import EmergencyStop, ResetResult
    core.emergency = EmergencyStop()
    core.permissions = SimpleNamespace(emergency=core.emergency, reset_emergency_stop=lambda s="x": ResetResult(False, "no"))
    gui = make(root, controller=GuiController(core))
    gui._refresh_status()
    assert pump(root, lambda: len(gui.activity_rows) == 6)
    gui.emergency_button.invoke()
    assert pump(root, lambda: gui.state_label.cget("text") == "NOTAUS")
    cancel_button(gui, "r-run").invoke()
    assert pump(root, lambda: "cancel_repair:r-run" in core.calls) and core.emergency.engaged
    gui._on_close()
