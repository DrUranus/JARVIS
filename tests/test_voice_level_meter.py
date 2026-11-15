"""Pegelanzeige (S2-Abnahme): Aufnahmeschleife -> LevelMeter -> UI-Adapter -> Ereignis `voice_level`. Kein Mikrofon, kein Netzwerk, kein Tk."""
from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from jarvis.interface.gui_model import GuiController
from jarvis.interface.ui_events import ControllerUiBackend
from jarvis.permissions.confirmation import ConfirmationChoice
from jarvis.voice import meter as meter_mod
from jarvis.voice.devices import SoundDeviceSource
from jarvis.voice.meter import LevelMeter, level_from_rms


def chunk(amplitude: int, n: int = 1600) -> bytes:
    return struct.pack(f"<{n}h", *([amplitude, -amplitude] * (n // 2)))


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# ---- Zwischenspeicher ---------------------------------------------------------------------------------------------------------------------------
def test_level_from_rms_is_bounded_and_never_nan():
    assert level_from_rms(0) == 0.0 and level_from_rms(-5) == 0.0 and level_from_rms(float("nan")) == 0.0 and level_from_rms("x") == 0.0
    assert 0.0 < level_from_rms(1000) < 1.0 and level_from_rms(10**9) == 1.0


def test_a_stale_level_reads_as_zero_and_clear_resets():
    clock = Clock()
    m = LevelMeter(clock, max_age=0.5)
    m.push(0.7)
    assert m.read() == 0.7
    clock.t += 0.6
    assert m.read() == 0.0                                         # keine Aufnahme mehr: die Anzeige bleibt nicht haengen
    m.push(0.4)
    m.clear()
    assert m.read() == 0.0


# ---- Aufnahmeschleife meldet den Pegel ------------------------------------------------------------------------------------------------------------
class FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, frames):
        return self._chunks.pop(0), False


def fake_sd(chunks):
    return SimpleNamespace(RawInputStream=lambda **kw: FakeStream(chunks), query_devices=lambda: [{"name": "Test-Mikrofon", "max_input_channels": 1}],
                           default=SimpleNamespace(device=(0, 0)))


def make_source(monkeypatch, chunks, **kw):
    monkeypatch.setattr(SoundDeviceSource, "_import", staticmethod(lambda: fake_sd(chunks)))
    return SoundDeviceSource(threshold=500, silence_seconds=0.2, max_seconds=5, chunk_seconds=0.1, **kw)


def test_recording_reports_a_level_per_chunk_and_clears_it_afterwards(monkeypatch):
    seen: list[float] = []
    m = LevelMeter()
    monkeypatch.setattr(m, "push", lambda v: seen.append(v))
    monkeypatch.setattr(meter_mod, "METER", m)
    monkeypatch.setattr("jarvis.voice.devices.METER", m)
    src = make_source(monkeypatch, [chunk(0), chunk(3000), chunk(3000), chunk(0), chunk(0), chunk(0)])
    clip = src.record()
    assert clip is not None
    assert seen and max(seen) > 0.3 and min(seen) == 0.0           # leise Chunks 0, laute deutlich darueber
    assert m.read() == 0.0                                         # nach der Aufnahme wieder 0


def test_recording_with_the_vad_path_reports_levels_too(monkeypatch):
    seen: list[float] = []
    m = LevelMeter()
    monkeypatch.setattr(m, "push", lambda v: seen.append(v))
    monkeypatch.setattr("jarvis.voice.devices.METER", m)
    from jarvis.voice.vad import EnergyDetector
    src = make_source(monkeypatch, [chunk(3000)] * 4 + [chunk(0)] * 6, detector=EnergyDetector(500))
    assert src.record() is not None
    assert seen and max(seen) > 0.3


# ---- UI-Adapter sendet voice_level ------------------------------------------------------------------------------------------------------------------
def make_backend(monkeypatch, level_clock):
    ctl = GuiController(SimpleNamespace(), None)
    backend = ControllerUiBackend(ctl, choice_enum=ConfirmationChoice, clock=None, level_clock=level_clock)
    return ctl, backend


def levels(backend):
    return [e["data"] for e in backend.events_since(0, 1000) if e["type"] == "voice_level"]


def test_the_adapter_emits_measured_levels_while_the_voice_mode_is_active(monkeypatch):
    clock = Clock()
    m = LevelMeter(clock)
    monkeypatch.setattr("jarvis.interface.ui_events.METER", m)
    ctl, backend = make_backend(monkeypatch, clock)
    monkeypatch.setattr(GuiController, "voice_active", property(lambda self: True))
    backend.pump()
    assert levels(backend)[-1] == {"level": 0, "active": True}                  # Wechsel in den Sprachmodus wie bisher
    clock.t += 0.3
    m.push(0.52)
    backend.pump()
    assert levels(backend)[-1] == {"level": 0.5, "active": True}                # in 0,1-Schritten, damit der Ringpuffer nicht flutet
    clock.t += 0.05
    m.push(0.9)
    backend.pump()
    assert levels(backend)[-1]["level"] == 0.5                                  # zu schnell hintereinander: noch nichts Neues
    clock.t += 0.3
    m.push(0.9)
    backend.pump()
    assert levels(backend)[-1] == {"level": 0.9, "active": True}


def test_the_level_falls_back_to_zero_when_nothing_is_recorded_and_when_the_mode_ends(monkeypatch):
    clock = Clock()
    m = LevelMeter(clock)
    monkeypatch.setattr("jarvis.interface.ui_events.METER", m)
    ctl, backend = make_backend(monkeypatch, clock)
    active = {"v": True}
    monkeypatch.setattr(GuiController, "voice_active", property(lambda self: active["v"]))
    backend.pump()
    clock.t += 0.3
    m.push(0.8)
    backend.pump()
    assert levels(backend)[-1] == {"level": 0.8, "active": True}
    clock.t += 1.0                                                              # keine neue Aufnahme: der alte Wert ist veraltet
    backend.pump()
    assert levels(backend)[-1] == {"level": 0.0, "active": True}
    m.push(0.8)
    active["v"] = False
    backend.pump()
    assert levels(backend)[-1] == {"level": 0.0, "active": False}               # Sprachmodus aus: nie ein Pegel
    n = len(levels(backend))
    backend.pump()
    assert len(levels(backend)) == n                                            # unveraendert: kein Ereignis-Strom im Leerlauf
