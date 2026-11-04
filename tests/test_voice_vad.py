"""VAD-Endpointing: synthetisches Audio, kein Mikrofon, kein Modell, kein Netzwerk."""
import ast
import struct
import sys
import types
from pathlib import Path

import pytest

from jarvis.config import ConfigError, Settings, VoiceSettings
from jarvis.errors import VoiceError, VoiceUnavailableError
from jarvis.voice import vad
from jarvis.voice.base import AudioSource
from jarvis.voice.devices import SoundDeviceSource
from jarvis.voice.factory import AUDIO_SOURCES, VAD_DETECTORS, build_listener
from jarvis.voice.vad import EnergyDetector, record_utterance

RATE = 16000
CHUNK = 0.1
N = int(RATE * CHUNK)
LOUD = struct.pack(f"<{N}h", *([3000, -3000] * (N // 2)))
QUIET = struct.pack(f"<{N}h", *([10, -10] * (N // 2)))
CLICK = struct.pack(f"<{N}h", *([3000, -3000] * 5 + [0] * (N - 10)))


def reader(pattern):
    """Liefert die Chunks der Reihe nach, danach endlos `pattern[-1]`; zaehlt die Aufrufe."""
    state = {"i": 0}

    def read():
        i = state["i"]
        state["i"] += 1
        return pattern[min(i, len(pattern) - 1)]
    read.state = state
    return read


def run(pattern, **kw):
    args = dict(sample_rate=RATE, chunk_seconds=CHUNK, silence_seconds=0.5, max_seconds=5.0,
                initial_wait_seconds=1.0, min_speech_seconds=0.2, preroll_seconds=0.2)
    args.update(kw)
    read = reader(pattern)
    return record_utterance(read, EnergyDetector(500), **args), read.state["i"]


def test_ends_after_pause_and_keeps_speech():
    clip, reads = run([QUIET] * 2 + [LOUD] * 5 + [QUIET] * 50)
    assert clip is not None and clip.sample_rate == RATE
    assert reads == 2 + 5 + 5                       # Stille 0,5 s nach der Sprache beendet die Aufnahme
    assert 0.5 + 0.2 <= clip.duration <= 0.5 + 0.2 + 0.5 + 0.01  # Sprache + Vorlauf + Nachlauf


def test_never_longer_than_max_record_seconds():
    clip, reads = run([LOUD] * 1000, max_seconds=1.0)
    assert clip is not None and clip.duration <= 1.0 + 1e-9
    assert reads <= 10


def test_max_applies_with_continuous_noise_below_speech_pauses():
    # Sprache mit kurzen Pausen (< silence_seconds) darf nie ueber das Maximum hinaus laufen
    pattern = ([LOUD] * 3 + [QUIET] * 2) * 100
    clip, reads = run(pattern, max_seconds=2.0)
    assert clip is not None and clip.duration <= 2.0 + 1e-9 and reads <= 20


def test_nobody_speaks_gives_none_after_initial_wait():
    clip, reads = run([QUIET] * 100)
    assert clip is None and reads == 10


def test_initial_wait_is_capped_by_max_seconds():
    clip, reads = run([QUIET] * 100, initial_wait_seconds=30.0, max_seconds=0.5)
    assert clip is None and reads <= 5


def test_short_click_is_not_speech():
    clip, _ = run([QUIET, CLICK] + [QUIET] * 100)
    assert clip is None


def test_short_pause_inside_speech_does_not_end():
    clip, _ = run([LOUD] * 3 + [QUIET] * 2 + [LOUD] * 3 + [QUIET] * 50)
    assert clip is not None and clip.duration >= 0.3 + 0.2 + 0.3


def test_guard_stops_recording_with_clear_error():
    reasons = iter([None, None, "Notaus: test"])
    with pytest.raises(VoiceUnavailableError, match="Notaus: test"):
        run([LOUD] * 100, guard=lambda: next(reasons, "Notaus: test"))


def test_guard_checked_before_first_read():
    read = reader([LOUD])
    with pytest.raises(VoiceUnavailableError, match="Sitzungsbudget"):
        record_utterance(read, EnergyDetector(500), sample_rate=RATE, chunk_seconds=CHUNK, silence_seconds=0.5,
                         max_seconds=5, guard=lambda: "Sitzungsbudget erschöpft")
    assert read.state["i"] == 0


def test_custom_detector_decides():
    class Odd:
        def __init__(self):
            self.n = 0

        def is_speech(self, pcm, sample_rate):
            self.n += 1
            return 3 <= self.n <= 6
    clip = record_utterance(reader([QUIET]), Odd(), sample_rate=RATE, chunk_seconds=CHUNK, silence_seconds=0.3,
                            max_seconds=5, initial_wait_seconds=1, min_speech_seconds=0.1, preroll_seconds=0)
    assert clip is not None and clip.duration == pytest.approx(0.4 + 0.3)


# ---- Quelle / Fabrik / Standard -------------------------------------------------------------------
def test_defaults_unchanged_and_off():
    v = VoiceSettings()
    assert v.vad_provider == "none" and v.stt_provider == "console"
    cfg = Path(__file__).resolve().parents[1] / "config" / "jarvis.toml"
    assert "vad_provider" not in cfg.read_text() or 'vad_provider = "none"' in cfg.read_text()


def test_registry_names_and_unknown():
    assert {"energy", "silero"} <= set(VAD_DETECTORS.names())
    with pytest.raises(VoiceError):
        VAD_DETECTORS.create("gibt-es-nicht", VoiceSettings())


def test_validate_rejects_negative_min_speech():
    s = Settings(voice=VoiceSettings(vad_min_speech_seconds=-1))
    with pytest.raises(ConfigError):
        s.validate()


def fake_sounddevice(chunks):
    it = iter(chunks)

    class Stream:
        def __init__(self, **kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, frames):
            return next(it, QUIET), False
    return types.SimpleNamespace(RawInputStream=Stream)


def make_source(monkeypatch, chunks, **kw):
    monkeypatch.setattr(SoundDeviceSource, "_import", staticmethod(lambda: fake_sounddevice(chunks)))
    return SoundDeviceSource(RATE, 500, 0.5, 2.0, **kw)


def test_source_with_detector_ends_on_pause(monkeypatch):
    src = make_source(monkeypatch, [QUIET] + [LOUD] * 4 + [QUIET] * 50, detector=EnergyDetector(500))
    clip = src.record()
    assert clip is not None and clip.duration <= 2.0


def test_source_without_detector_keeps_legacy_endpointer(monkeypatch):
    src = make_source(monkeypatch, [LOUD] * 3 + [QUIET] * 50)
    clip = src.record()
    assert clip is not None and clip.duration > 0


def test_build_listener_default_has_no_detector(monkeypatch):
    monkeypatch.setattr(SoundDeviceSource, "_import", staticmethod(lambda: fake_sounddevice([])))
    seen = {}
    real = AUDIO_SOURCES.create

    def spy(name, s):
        seen["src"] = real(name, s)
        return seen["src"]
    monkeypatch.setattr(AUDIO_SOURCES, "create", spy)
    build_listener(VoiceSettings(stt_provider="mock"))
    assert seen["src"]._detector is None


def test_build_listener_energy_detector_and_guard(monkeypatch):
    monkeypatch.setattr(SoundDeviceSource, "_import", staticmethod(lambda: fake_sounddevice([LOUD] * 100)))
    seen = {}
    real = AUDIO_SOURCES.create
    monkeypatch.setattr(AUDIO_SOURCES, "create", lambda n, s: seen.setdefault("src", real(n, s)))
    build_listener(VoiceSettings(stt_provider="mock", vad_provider="energy"), guard=lambda: "Notaus: x")
    src = seen["src"]
    assert isinstance(src._detector, EnergyDetector)
    with pytest.raises(VoiceUnavailableError, match="Notaus: x"):
        src.record()


# ---- Silero (optionales Extra, lazy) -----------------------------------------------------------------
def test_silero_missing_gives_clear_message(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", None)
    with pytest.raises(VoiceUnavailableError, match="stt-local"):
        vad.load_silero_detector()


def test_silero_adapter_uses_public_api_with_fake_library(monkeypatch):
    pkg = types.ModuleType("faster_whisper")
    mod = types.ModuleType("faster_whisper.vad")
    calls = []

    class VadOptions:
        def __init__(self, **kw):
            self.kw = kw

    def get_speech_timestamps(audio, vad_options=None, sampling_rate=16000, **kw):
        calls.append((len(audio), sampling_rate, vad_options.kw))
        return [{"start": 0, "end": 100}] if float(abs(audio).max()) > 0.05 else []
    mod.VadOptions, mod.get_speech_timestamps = VadOptions, get_speech_timestamps
    monkeypatch.setitem(sys.modules, "faster_whisper", pkg)
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", mod)
    det = vad.load_silero_detector(numpy_module=_FakeNumpy())
    assert det.is_speech(LOUD, RATE) is True
    assert det.is_speech(QUIET, RATE) is False
    with pytest.raises(VoiceError, match="16000"):
        det.is_speech(LOUD, 8000)
    assert calls and calls[0][1] == RATE and calls[0][0] == N


class _FakeArr(list):
    def astype(self, _):
        return self

    def __truediv__(self, d):
        return _FakeArr(v / d for v in self)

    def __abs__(self):
        return _FakeArr(abs(v) for v in self)

    def max(self):
        return max(self)


class _FakeNumpy:
    float32 = "float32"

    @staticmethod
    def frombuffer(pcm, dtype):
        n = len(pcm) // 2
        return _FakeArr(struct.unpack(f"<{n}h", pcm[: n * 2]))


# ---- Umfang: kein Hotword, kein Barge-in, kein Netzwerk, keine Pflichtabhaengigkeit ------------------------
def imports_of(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module.split(".")[0])
    return out


def test_vad_module_scope_structure():
    path = Path(vad.__file__)
    text = path.read_text(encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Attribute)}
    for forbidden in ("HotwordDetector", "HotwordGatedSource", "interrupt", "stop", "AudioPlayer", "Speaker"):
        assert forbidden not in names, forbidden
    banned = {"socket", "urllib", "http", "requests", "httpx", "ssl", "subprocess", "faster_whisper", "numpy", "onnxruntime"}
    # die Bibliotheken kommen nur lazy (innerhalb von Funktionen) vor, nie auf Modulebene
    module_level = set()
    for node in ast.parse(text).body:
        if isinstance(node, ast.Import):
            module_level |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_level.add(node.module.split(".")[0])
    assert not (module_level & banned)
    assert "hotword" not in {p.lower() for p in module_level}


def test_no_new_required_dependency():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert "dependencies = []" in text


# ---- Verdrahtung: Notaus und Sitzungsbudget (bootstrap.py) ---------------------------------------------
def _core(tmp_path):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    (tmp_path / "ws").mkdir(exist_ok=True)
    return build_core(load_settings(env={"JARVIS_WORKSPACE": str(tmp_path / "ws"), "JARVIS_LOG_DIR": str(tmp_path / "logs"),
                                         "JARVIS_MEMORY_PATH": str(tmp_path / "m.db")}))


def test_recording_guard_follows_emergency_stop(tmp_path):
    from jarvis.bootstrap import recording_guard
    core = _core(tmp_path)
    guard = recording_guard(core)
    assert guard() is None
    core.permissions.emergency.trigger("test", "t")
    assert "Notaus" in guard()


def test_recording_guard_follows_session_budget(tmp_path):
    from jarvis.bootstrap import recording_guard
    from jarvis.permissions.budget import SessionBudget
    core = _core(tmp_path)
    core.permissions._budget = SessionBudget(1, 3600)
    assert core.permissions._budget.try_book() is None
    assert "Sitzungsbudget" in recording_guard(core)()
