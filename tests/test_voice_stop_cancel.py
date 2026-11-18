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
