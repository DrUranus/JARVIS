"""Lokaler STT-Provider: nur Fake-Modelle, kein echtes Modell, kein Netzwerk."""
import ast
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from jarvis.config import VoiceSettings
from jarvis.errors import STTError, VoiceError, VoiceUnavailableError
from jarvis.voice import local_stt
from jarvis.voice.base import AudioClip, STTProvider
from jarvis.voice.factory import STT_PROVIDERS, build_listener
from jarvis.voice.local_stt import LocalWhisperSTT

CLIP = AudioClip(b"\x01\x00" * 1600, 16000)


class FakeEngine:
    def __init__(self, segments=("Hallo", "Welt"), language="de", delay=0.0):
        self.segments, self.language, self.delay, self.calls = list(segments), language, delay, []

    def transcribe(self, clip, language):
        self.calls.append((len(clip.pcm), language))
        if self.delay:
            time.sleep(self.delay)
        return iter(self.segments), self.language


def make(tmp_path, engine=None, **kw):
    engine = engine or FakeEngine()
    return LocalWhisperSTT(str(tmp_path), engine_loader=lambda path: engine, **kw), engine


def test_is_stt_provider_and_default_unchanged():
    assert issubclass(LocalWhisperSTT, STTProvider)
    assert VoiceSettings().stt_provider == "console"
    assert VoiceSettings().stt_model_dir is None
    assert "local" in STT_PROVIDERS.names()


def test_segments_joined_and_language_passed(tmp_path):
    stt, engine = make(tmp_path, FakeEngine([" Guten ", "Morgen ", ""]))
    assert stt.transcribe(CLIP, "de") == "Guten Morgen"
    assert engine.calls == [(len(CLIP.pcm), "de")]
    assert stt.last_language == "de"


def test_language_none_means_autodetect(tmp_path):
    stt, engine = make(tmp_path, FakeEngine(["Hello"], language="en"))
    assert stt.transcribe(CLIP, None) == "Hello"
    assert engine.calls[0][1] is None and stt.last_language == "en"


def test_empty_recording_returns_empty_without_loading(tmp_path):
    loaded = []
    stt = LocalWhisperSTT(str(tmp_path), engine_loader=lambda p: loaded.append(p) or FakeEngine())
    assert stt.transcribe(AudioClip(b"", 16000), "de") == ""
    assert loaded == []


def test_no_segments_gives_empty_text(tmp_path):
    stt, _ = make(tmp_path, FakeEngine([]))
    assert stt.transcribe(CLIP, "de") == ""


def test_model_loaded_lazily_once(tmp_path):
    loaded = []
    stt = LocalWhisperSTT(str(tmp_path), engine_loader=lambda p: loaded.append(p) or FakeEngine())
    assert loaded == []
    stt.transcribe(CLIP, "de")
    stt.transcribe(CLIP, "de")
    assert loaded == [str(tmp_path)]


def test_missing_model_dir_clear_message(tmp_path):
    with pytest.raises(STTError, match="stt_model_dir") as e:
        LocalWhisperSTT(str(tmp_path / "gibtsnicht"), engine_loader=lambda p: FakeEngine())
    assert "gibtsnicht" in str(e.value) and "kein automatischer Download" in str(e.value)


def test_unset_model_dir_clear_message():
    with pytest.raises(STTError, match="stt_model_dir"):
        STT_PROVIDERS.create("local", VoiceSettings(stt_provider="local"))


def test_model_dir_is_file_rejected(tmp_path):
    f = tmp_path / "datei"
    f.write_text("x")
    with pytest.raises(STTError, match="kein Verzeichnis"):
        LocalWhisperSTT(str(f), engine_loader=lambda p: FakeEngine())


def test_missing_library_is_clear_voice_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    stt = LocalWhisperSTT(str(tmp_path))
    with pytest.raises(VoiceUnavailableError, match=r"stt-local"):
        stt.transcribe(CLIP, "de")


def test_timeout_gives_clear_message(tmp_path):
    gate = threading.Event()

    class Slow(FakeEngine):
        def transcribe(self, clip, language):
            gate.wait(5)
            return super().transcribe(clip, language)

    stt, _ = make(tmp_path, Slow(), timeout=0.05)
    try:
        with pytest.raises(STTError, match="Zeitlimit"):
            stt.transcribe(CLIP, "de")
    finally:
        gate.set()


def test_engine_error_becomes_stt_error(tmp_path):
    class Boom(FakeEngine):
        def transcribe(self, clip, language):
            raise RuntimeError("kaputt")

    stt, _ = make(tmp_path, Boom())
    with pytest.raises(STTError, match="kaputt"):
        stt.transcribe(CLIP, "de")


def test_wrong_sample_rate_rejected(tmp_path):
    stt, engine = make(tmp_path)
    with pytest.raises(STTError, match="16000"):
        stt.transcribe(AudioClip(b"\x00\x00" * 10, 44100), "de")
    assert engine.calls == []


def test_guard_blocks_before_any_work(tmp_path):
    """Notaus/Sitzungsbudget: ein Waechter, der einen Grund liefert, stoppt vor Modell und Audio."""
    loaded = []
    stt = LocalWhisperSTT(str(tmp_path), engine_loader=lambda p: loaded.append(p) or FakeEngine(),
                          guard=lambda: "Notaus aktiv")
    with pytest.raises(STTError, match="Notaus aktiv"):
        stt.transcribe(CLIP, "de")
    assert loaded == []


def test_factory_builds_listener_with_local_provider(tmp_path):
    s = VoiceSettings(stt_provider="local", stt_model_dir=str(tmp_path), audio_input="mock")
    prov = STT_PROVIDERS.create("local", s)
    assert isinstance(prov, LocalWhisperSTT) and prov.name == "local"
    assert build_listener(s) is not None  # baut ohne Mikrofon-/Modellzugriff


def test_default_engine_uses_local_files_only_and_model_dir(tmp_path, monkeypatch):
    """Kein Download: das Modell wird nur aus dem Verzeichnis geladen, Offline-Flags gesetzt."""
    seen = {}

    class FakeWhisperModel:
        def __init__(self, path, **kw):
            seen["path"], seen["kw"] = path, kw

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    local_stt.load_faster_whisper(str(tmp_path), device="cpu", compute_type="int8")
    assert seen["path"] == str(tmp_path)
    assert seen["kw"]["local_files_only"] is True
    assert seen["kw"]["device"] == "cpu" and seen["kw"]["compute_type"] == "int8"
    import os
    assert os.environ["HF_HUB_OFFLINE"] == "1"


def test_no_network_imports_structurally():
    """Strukturtest: das Modul darf keine Netzwerk-/Download-Bibliothek importieren."""
    tree = ast.parse(Path(local_stt.__file__).read_text(encoding="utf-8"))
    forbidden = {"socket", "urllib", "http", "requests", "httpx", "huggingface_hub", "ssl", "ftplib", "subprocess"}
    for n in ast.walk(tree):
        names = [a.name for a in n.names] if isinstance(n, ast.Import) else \
            [n.module or ""] if isinstance(n, ast.ImportFrom) else []
        for name in names:
            assert name.split(".")[0] not in forbidden, name
    src = Path(local_stt.__file__).read_text(encoding="utf-8")
    assert "download_root" not in src and "snapshot_download" not in src


def test_pyproject_keeps_no_required_dependencies_and_optional_extra():
    text = Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in text
    line = next(l for l in text.splitlines() if l.startswith("stt-local"))
    assert "faster-whisper>=" in line


def test_package_import_does_not_import_library():
    src = Path(local_stt.__file__).read_text(encoding="utf-8")
    top = [l for l in src.splitlines() if l.startswith(("import faster", "from faster"))]
    assert top == []
