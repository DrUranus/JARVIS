
import threading

import pytest

pytest.importorskip("tkinter")                  # without Tk (some Linux Pythons) the module is skipped instead of failing to import

from jarvis.interface.gui import GUIConfirmationProvider  # noqa: E402
from jarvis.permissions.confirmation import (
    ConfirmationChoice,
    ConfirmationRequest,
)
from jarvis.permissions.levels import PermissionLevel


def make_request(session_allowed=True):
    return ConfirmationRequest(
        request_id="gui-test-1",
        tool="filesystem",
        action="write",
        level=PermissionLevel.YELLOW,
        resource="/ws/test.txt",
        reason="Test der GUI-Bestätigung",
        context={},
        session_allowed=session_allowed,
    )


def test_gui_provider_denies_when_closing():
    provider = GUIConfirmationProvider.__new__(GUIConfirmationProvider)
    provider._lock = threading.Lock()
    provider._pending = {}
    provider._closing = True
    provider.timeout = 1.0

    result = provider.confirm(make_request())

    assert result is ConfirmationChoice.DENY
    assert provider._pending == {}

def test_gui_provider_denies_when_dialog_cannot_be_scheduled():
    class BrokenRoot:
        def after(self, *args, **kwargs):
            raise RuntimeError("GUI ist nicht verfügbar")

    provider = GUIConfirmationProvider(BrokenRoot(), timeout=1.0)

    result = provider.confirm(make_request())

    assert result is ConfirmationChoice.DENY
    assert provider._pending == {}
    
def test_gui_provider_denies_on_timeout():
    class FakeRoot:
        def after(self, *args, **kwargs):
            pass

    provider = GUIConfirmationProvider(FakeRoot(), timeout=0.01)

    result = provider.confirm(make_request())

    assert result is ConfirmationChoice.DENY
    assert provider._pending == {}
    
def test_gui_provider_resolve_keeps_first_decision():
    provider = GUIConfirmationProvider.__new__(GUIConfirmationProvider)
    provider._lock = threading.Lock()
    provider._pending = {}
    provider._closing = False
    provider.timeout = 1.0

    record = {
        "event": threading.Event(),
        "choice": ConfirmationChoice.DENY,
        "dialog": None,
    }

    provider._resolve(record, ConfirmationChoice.ALLOW_ONCE)
    provider._resolve(record, ConfirmationChoice.DENY)

    assert record["choice"] is ConfirmationChoice.ALLOW_ONCE
    assert record["event"].is_set()

def test_gui_provider_does_not_offer_session_allow_when_disallowed(monkeypatch):
    import jarvis.interface.gui as gui_module

    created_buttons = []

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            created_buttons.append(kwargs)
        def pack(self, *args, **kwargs):
            pass
        def invoke(self):
            self.kwargs["command"]()
        def grid(self, *args, **kwargs):
            pass


    class FakeDialog:
        def title(self, *args): pass
        def transient(self, *args): pass
        def resizable(self, *args): pass
        def geometry(self, *args): pass
        def minsize(self, *args): pass
        def protocol(self, *args): pass
        def bind(self, *args): pass
        def focus_set(self): pass
        def winfo_exists(self):
            return True
        def destroy(self):
            pass

    class FakeFrame:
        def pack(self, *args, **kwargs): pass
        def grid(self, *args, **kwargs): pass
        def columnconfigure(self, *args, **kwargs): pass
        def rowconfigure(self, *args, **kwargs): pass

    class FakeText(FakeFrame):
        def insert(self, *args, **kwargs): pass
        def configure(self, *args, **kwargs): pass

    monkeypatch.setattr(gui_module.tk, "Toplevel", lambda *a, **k: FakeDialog())
    monkeypatch.setattr(gui_module.ttk, "Frame", lambda *a, **k: FakeFrame())
    monkeypatch.setattr(gui_module.ttk, "Label", FakeWidget)
    monkeypatch.setattr(gui_module.ttk, "Button", FakeWidget)
    monkeypatch.setattr(gui_module.tk, "Text", lambda *a, **k: FakeText())

    provider = GUIConfirmationProvider.__new__(GUIConfirmationProvider)
    provider.root = object()
    provider._lock = threading.Lock()
    provider._pending = {}
    provider._closing = False

    record = {
        "event": threading.Event(),
        "choice": ConfirmationChoice.DENY,
        "dialog": None,
    }

    provider._show_dialog(make_request(session_allowed=False), record)

    button_texts = [button.get("text") for button in created_buttons]
    assert "Ablehnen" in button_texts
    assert "Einmal erlauben" in button_texts
    assert "Für Sitzung erlauben" not in button_texts
    
def test_gui_provider_once_button_resolves_allow_once(monkeypatch):
    import jarvis.interface.gui as gui_module

    buttons = []

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            if "command" in kwargs:
                buttons.append(self)

        def pack(self, *args, **kwargs):
            pass

        def grid(self, *args, **kwargs):
            pass

        def invoke(self):
            self.kwargs["command"]()

    
    class FakeDialog:
        def title(self, *args): pass
        def transient(self, *args): pass
        def resizable(self, *args): pass
        def geometry(self, *args): pass
        def minsize(self, *args): pass
        def protocol(self, *args): pass
        def bind(self, *args): pass
        def focus_set(self): pass

        def winfo_exists(self):
            return True

        def destroy(self):
            pass


    class FakeFrame:
        def pack(self, *args, **kwargs): pass
        def grid(self, *args, **kwargs): pass
        def columnconfigure(self, *args, **kwargs): pass
        def rowconfigure(self, *args, **kwargs): pass

    class FakeText(FakeFrame):
        def insert(self, *args, **kwargs): pass
        def configure(self, *args, **kwargs): pass

    monkeypatch.setattr(gui_module.tk, "Toplevel", lambda *a, **k: FakeDialog())
    monkeypatch.setattr(gui_module.ttk, "Frame", lambda *a, **k: FakeFrame())
    monkeypatch.setattr(gui_module.ttk, "Label", FakeWidget)
    monkeypatch.setattr(gui_module.ttk, "Button", FakeWidget)
    monkeypatch.setattr(gui_module.tk, "Text", lambda *a, **k: FakeText())

    provider = GUIConfirmationProvider.__new__(GUIConfirmationProvider)
    provider.root = object()
    provider._lock = threading.Lock()
    provider._pending = {}
    provider._closing = False

    record = {
        "event": threading.Event(),
        "choice": ConfirmationChoice.DENY,
        "dialog": None,
    }

    provider._show_dialog(make_request(session_allowed=False), record)

    once_button = next(
        button for button in buttons
        if button.kwargs.get("text") == "Einmal erlauben"
    )
    once_button.invoke()

    assert record["choice"] is ConfirmationChoice.ALLOW_ONCE
    assert record["event"].is_set()
    assert record["dialog"] is None





