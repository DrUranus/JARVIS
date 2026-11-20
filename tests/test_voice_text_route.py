"""Sprachauftraege laufen durch dieselbe Auftragsverarbeitung wie der Textchat (F-V-1): Recherche-/Dateisaetze werden zum Ziel der Goal Engine (mit Freigabedialog),
alles andere geht wie bisher an `core.handle`. Keine zweite Ausfuehrungslogik: derselbe `_research_route` und `_run_command` der Oberflaeche. Kein Netz, kein Mikrofon."""
from types import SimpleNamespace

from jarvis.core.core import Response, ResponseKind
from jarvis.interface import gui_model
from jarvis.interface.gui_model import GuiController, VoiceTextHandler


class Core:
    def __init__(self, engaged=False):
        self.handled = []
        self.permissions = SimpleNamespace(emergency=SimpleNamespace(engaged=engaged, register=lambda *a, **k: None, add_listener=lambda *a, **k: None))
        self.subsystems = {}

    def handle(self, text):
        self.handled.append(text)
        return Response("chat:" + text, ResponseKind.CHAT)


def make(routed=None, engaged=False):
    core, ran = Core(engaged), []
    h = VoiceTextHandler(core, lambda t: routed, lambda line: ran.append(line) or "ziel:" + line)
    return h, core, ran


def test_a_routed_sentence_becomes_a_goal_through_the_text_chat_path():
    h, core, ran = make(routed="/goal Erstelle die Datei a.txt mit dem Inhalt: x")
    r = h.handle("Erstelle die Datei a.txt mit dem Inhalt: x")
    assert ran == ["/goal Erstelle die Datei a.txt mit dem Inhalt: x"] and core.handled == []
    assert r.text.startswith("ziel:") and r.kind is ResponseKind.CHAT


def test_an_unrouted_sentence_goes_to_core_handle_as_before():
    h, core, ran = make(routed=None)
    assert h.handle("Wie spaet ist es").text == "chat:Wie spaet ist es" and ran == [] and core.handled == ["Wie spaet ist es"]


def test_emergency_stop_never_reaches_the_goal_path():
    h, core, ran = make(routed="/goal x", engaged=True)
    h.handle("Erstelle die Datei a.txt mit dem Inhalt: x")
    assert ran == [] and core.handled == ["Erstelle die Datei a.txt mit dem Inhalt: x"]       # core.handle antwortet mit der Notaus-Meldung


def test_a_slash_command_by_voice_is_never_run_as_a_command():
    h, core, ran = make(routed="/goal x")
    h.handle("/notaus reset")
    assert ran == [] and core.handled == ["/notaus reset"]


def test_start_voice_uses_the_same_handler_as_the_text_chat(monkeypatch):
    seen = {}

    class S:
        def run(self, stop=None, **kw):
            stop.wait(1)

        def cancel_listening(self):
            pass

    def fake_build(settings, core, display, input_fn, on_state, handler=None):
        seen["handler"] = handler
        return S()

    monkeypatch.setattr("jarvis.bootstrap.build_voice_session", fake_build)
    ctl = GuiController(Core(), SimpleNamespace(voice=SimpleNamespace(stt_provider="local")))
    assert ctl.start_voice() == ""
    assert isinstance(seen["handler"], VoiceTextHandler)
    ctl.stop_voice()
    ctl.close()
