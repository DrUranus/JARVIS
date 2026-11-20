"""Sprachmodus beenden (S2-Abnahme 2026-11-18): ein laufendes Warten auf Sprache wird sofort abgebrochen statt bis zu `max_record_seconds` (15 s) zu dauern.
Kein Mikrofon, kein Netzwerk. Das Abbrechen verwirft die Aufnahme (kein Audio wird weitergegeben) und aendert weder Notaus noch Berechtigungen."""
from __future__ import annotations

import struct
import threading
import time
from types import SimpleNamespace

import pytest

from jarvis.voice.base import AudioClip, AudioSource, Listener
from jarvis.voice.composed import SpeechListener
from jarvis.voice.devices import SoundDeviceSource
from jarvis.voice.hotword import HotwordGatedSource
from jarvis.voice.session import VoiceSession
from jarvis.voice.vad import EnergyDetector

SILENCE = struct.pack("<1600h", *([0] * 1600))


class QuietStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, frames):
        time.sleep(0.02)                                           # ein Chunk Stille, nie Sprache: ohne Abbruch wartet die Aufnahme bis max_seconds
        return SILENCE, False


def make_source(monkeypatch, **kw):
    sd = SimpleNamespace(RawInputStream=lambda **k: QuietStream(), query_devices=lambda: [{"name": "Test", "max_input_channels": 1}], default=SimpleNamespace(device=(0, 0)))
    monkeypatch.setattr(SoundDeviceSource, "_import", staticmethod(lambda: sd))
    return SoundDeviceSource(threshold=500, silence_seconds=0.2, max_seconds=15, chunk_seconds=0.1, **kw)


@pytest.mark.parametrize("vad", [False, True])
def test_cancel_ends_a_running_recording_quickly_and_returns_nothing(monkeypatch, vad):
    src = make_source(monkeypatch, detector=EnergyDetector(500) if vad else None)
    out: list = []
    t = threading.Thread(target=lambda: out.append(src.record()))
    start = time.monotonic()
    t.start()
    time.sleep(0.3)
    src.cancel()
    t.join(3)
    assert not t.is_alive() and out == [None]                      # nichts wird weitergegeben
    assert time.monotonic() - start < 2.5                          # nicht erst nach max_seconds (15 s) bzw. dem 5-s-Warten der VAD


def test_base_source_cancel_is_a_noop_and_never_raises():
    class S(AudioSource):
        def record(self):
            return None
    S().cancel()


def test_cancel_is_forwarded_through_the_hotword_gate_and_the_listener():
    calls = []

    class Src(AudioSource):
        def record(self):
            return None

        def cancel(self):
            calls.append("src")

    SpeechListener(HotwordGatedSource(Src(), SimpleNamespace(detect=lambda c: False)), SimpleNamespace(transcribe=lambda *a: "")).cancel()
    assert calls == ["src"]


def test_voice_session_cancel_listening_cancels_the_listener_and_tolerates_listeners_without_cancel():
    seen = []

    class L(Listener):
        def listen(self):
            return None

        def cancel(self):
            seen.append(1)

    class Plain(Listener):
        def listen(self):
            return None

    speaker = SimpleNamespace(say=lambda t: None, stop=lambda: None)
    VoiceSession(lambda text: "", L(), speaker).cancel_listening()
    VoiceSession(lambda text: "", Plain(), speaker).cancel_listening()      # kein Fehler
    assert seen == [1]


def test_controller_stop_voice_interrupts_the_running_session():
    from jarvis.interface.gui_model import GuiController
    interrupted = threading.Event()

    class FakeSession:
        def run(self, stop=None, **kw):
            stop.wait(5)

        def cancel_listening(self):
            interrupted.set()

    ctl = GuiController(core=SimpleNamespace(), settings=SimpleNamespace(voice=SimpleNamespace(stt_provider="local")), voice_factory=lambda *a, **k: FakeSession()) \
        if "voice_factory" in GuiController.__init__.__code__.co_varnames else None
    if ctl is None:
        pytest.skip("GuiController ohne voice_factory")
    assert ctl.start_voice() == ""
    ctl.stop_voice()
    assert interrupted.wait(2)
    ctl.close()


# ---- Sprachausgabe waehrend „Sprache beenden“ (Livebefund 2026-11-20) ----------------------------------------------------------------------------
class BlockingSpeaker:
    """say() blockiert wie die echte Windows-Ausgabe, bis stop() kommt (Barge-in)."""

    def __init__(self):
        self.started, self.stopped, self.said = threading.Event(), threading.Event(), []
        self._cut = threading.Event()

    def say(self, text):
        self.said.append(text)
        self.started.set()
        self._cut.wait(10)

    def stop(self):
        self.stopped.set()
        self._cut.set()


class OneShotListener(Listener):
    def __init__(self, text):
        self._text, self._done, self._cancel = text, False, threading.Event()

    def listen(self):
        if not self._done:
            self._done = True
            return self._text
        self._cancel.wait(10)
        return None

    def cancel(self):
        self._cancel.set()


def make_controller(handler, speaker, text="Hallo"):
    from jarvis.interface.gui_model import GuiController
    factory = lambda s, c, d, i, st: VoiceSession(handler, OneShotListener(text), speaker, display=lambda t: None, on_state=st)   # noqa: E731
    core = SimpleNamespace(permissions=SimpleNamespace(emergency=SimpleNamespace(engaged=False, register=lambda *a, **k: None, add_listener=lambda *a, **k: None)))
    return GuiController(core, SimpleNamespace(voice=SimpleNamespace(stt_provider="local")), voice_factory=factory)


class Handler:
    def __init__(self, gate=None):
        self.gate = gate

    def handle(self, text):
        from jarvis.core.core import Response
        if self.gate is not None:
            self.gate.wait(10)
        return Response("eine sehr lange Antwort", None)


def wait_until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def test_stop_voice_during_speech_cuts_the_speech_and_ends_the_session_quickly():
    speaker = BlockingSpeaker()
    ctl = make_controller(Handler(), speaker)
    assert ctl.start_voice() == "" and speaker.started.wait(3)
    t0 = time.monotonic()
    ctl.stop_voice()
    assert speaker.stopped.wait(1) and wait_until(lambda: not ctl.voice_active, 2)
    assert time.monotonic() - t0 < 2.5
    ctl.close()


def test_a_reply_that_arrives_after_stop_is_never_spoken():
    gate, speaker = threading.Event(), BlockingSpeaker()
    ctl = make_controller(Handler(gate), speaker)
    assert ctl.start_voice() == ""
    time.sleep(0.3)                                                # Antwort wird noch erzeugt
    ctl.stop_voice()
    gate.set()                                                     # die alte Antwort ist jetzt fertig
    assert wait_until(lambda: not ctl.voice_active, 3)
    assert speaker.said == []                                      # nichts von der alten Antwort wird nachgesprochen
    ctl.close()


def test_repeated_start_and_stop_during_speech_never_hangs_or_leaks_the_flag():
    for _ in range(4):
        speaker = BlockingSpeaker()
        ctl = make_controller(Handler(), speaker)
        assert ctl.start_voice() == "" and speaker.started.wait(3)
        ctl.stop_voice()
        assert wait_until(lambda: not ctl.voice_active, 3)
        ctl.close()
