"""Sprachpipeline-Stabilitaet (Aufgabe 7): unerwartete Fehler in Handler, Mikrofon oder Lautsprecher beenden die Sitzung kontrolliert oder lassen sie weiterlaufen,
nie mit einem Traceback aus `run`; Zustaende enden immer in "idle"; Stop/Abbruch fuehrt keinen Befehl aus. Nur Fakes, kein Mikrofon, kein Netzwerk."""
import threading

import pytest

from jarvis.core import Response
from jarvis.errors import EndOfInput
from jarvis.voice import Listener, Speaker, VoiceSession


class Script(Listener):
    def __init__(self, items):
        self.items = list(items)

    def listen(self):
        if not self.items:
            raise EndOfInput("done")
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class Talker(Speaker):
    def __init__(self, fail=None):
        self.said, self.fail = [], fail

    def say(self, text):
        if self.fail:
            raise self.fail
        self.said.append(text)


class Boom:
    def __init__(self, fail_on=()):
        self.fail_on, self.seen = set(fail_on), []

    def handle(self, text):
        self.seen.append(text)
        if text in self.fail_on:
            raise RuntimeError("interner Fehler mit Details")
        return Response(f"ok {text}")


def run(items, handler=None, speaker=None, **kw):
    out, states = [], []
    session = VoiceSession(handler or Boom(), Script(items), speaker or Talker(), display=out.append, on_state=lambda s, d="": states.append((s, d)), **kw)
    turns = session.run()
    return turns, out, states


def test_a_failing_handler_is_reported_and_the_next_utterance_still_works():
    handler = Boom(fail_on={"kaputt"})
    turns, out, states = run(["kaputt", "danach"], handler)
    assert turns == 2 and handler.seen == ["kaputt", "danach"]
    assert any("Fehler" in line for line in out) and any("ok danach" in line for line in out)
    assert any(s == "error" for s, _d in states) and states[-1][0] == "idle"
    assert not any("interner Fehler mit Details" in line for line in out)               # Details nur im Log, nicht in der Ausgabe/Sprache


def test_a_listener_with_an_unexpected_device_error_ends_the_session_cleanly():
    turns, out, states = run(["eins", OSError("Geraet weg")])
    assert turns == 1 and any("nicht verfügbar" in line or "Sprachfehler" in line or "Audio" in line for line in out)
    assert any(s == "error" for s, _d in states) and states[-1][0] == "idle"


def test_a_speaker_with_an_unexpected_error_does_not_kill_the_conversation():
    talker = Talker(fail=RuntimeError("Treiberfehler"))
    turns, out, states = run(["eins", "zwei"], speaker=talker)
    assert turns == 2 and any("Sprachausgabe" in line for line in out)
    assert states[-1][0] == "idle"


def test_stop_set_while_processing_ends_after_the_current_utterance_without_a_new_command():
    stop = threading.Event()

    class StopsItself(Boom):
        def handle(self, text):
            stop.set()
            return super().handle(text)

    handler = StopsItself()
    session = VoiceSession(handler, Script(["eins", "zwei"]), Talker(), display=lambda _l: None)
    assert session.run(stop=stop) == 1 and handler.seen == ["eins"]


def test_an_utterance_recorded_when_stop_is_already_set_is_never_executed():
    stop = threading.Event()

    class Late(Script):
        def listen(self):
            stop.set()
            return super().listen()

    handler = Boom()
    session = VoiceSession(handler, Late(["befehl"]), Talker(), display=lambda _l: None)
    assert session.run(stop=stop) == 0 and handler.seen == []


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_empty_or_missing_transcripts_are_ignored_without_calling_the_handler(bad):
    handler = Boom()
    turns, _out, _states = run([bad, "echt"], handler)
    assert handler.seen == ["echt"] and turns == 1
