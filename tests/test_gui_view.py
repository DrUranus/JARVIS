"""The real Tk window (gui.py). Needs tkinter and a display: skipped otherwise (Linux CI without X, a Python without Tk). The Windows CI job runs these
for real. What is NOT covered here: how the window looks, a real microphone, real speakers, and a human clicking - see docs/TESTING.md (manual checks)."""
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
        pytest.skip(f"no usable display for Tk ({exc})")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


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
