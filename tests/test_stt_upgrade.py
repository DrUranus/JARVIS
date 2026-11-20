"""Speech Recognition Upgrade V1: Provider-Kette (local / auto / openai), Fallback, Cloud nur mit ausdruecklicher Aktivierung, OpenAI gpt-transcribe (Formularfelder,
Fehlertexte), Mikrofon-Auswahl, behutsame Nachbearbeitung, riskante Sprachbefehle. Kein Netzwerk, kein Mikrofon, kein echtes Modell."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jarvis.config import ConfigError, VoiceSettings, load_settings
from jarvis.errors import STTError, VoiceUnavailableError
from jarvis.voice import openai_provider as oa
from jarvis.voice.audio_device import input_devices, resolve_input_device
from jarvis.voice.base import AudioClip, STTProvider
from jarvis.voice.factory import STT_PROVIDERS, build_stt_chain, stt_hints
from jarvis.voice.local_stt import LocalWhisperSTT, _FasterWhisperEngine, language_arg
from jarvis.voice.postprocess import is_risky, normalize_transcript, split_confirmation
from jarvis.voice.session import VoiceSession
from jarvis.voice.stt_strategy import FallbackSTT, STTHalted

CLIP = AudioClip(b"\x01\x00" * 1600, 16000)


class Fake(STTProvider):
    def __init__(self, name, text="", error=None, cloud=False):
        self.name, self._text, self._error, self.cloud, self.calls = name, text, error, cloud, 0

    def transcribe(self, clip, language=None):
        self.calls += 1
        if self._error:
            raise self._error
        return self._text


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network access in a test")
    monkeypatch.setattr(oa, "http_post", boom)


def model_dir(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return str(d)


# ---- Kette und Fallback ------------------------------------------------------------------------------------------------------------------------
def test_chain_uses_the_next_provider_when_one_fails_and_keeps_the_original_text():
    a, b = Fake("local", error=STTError("Modell kaputt")), Fake("local-fallback", text="hallo welt")
    chain = FallbackSTT([a, b], labels=["local", "local-fallback"])
    assert chain.transcribe(CLIP, "de") == "hallo welt"
    assert chain.last.provider == "local-fallback" and chain.last.text == "hallo welt" and chain.last.skipped == ("local",) and chain.last.cloud is False


def test_chain_reports_every_failure_in_plain_words_when_all_fail():
    chain = FallbackSTT([Fake("local", error=STTError("Modell fehlt")), Fake("openai", error=VoiceUnavailableError("offline"))], labels=["local", "openai"])
    with pytest.raises(STTError) as exc:
        chain.transcribe(CLIP)
    assert "local: " in str(exc.value) and "Modell fehlt" in str(exc.value) and "openai: " in str(exc.value) and "offline" in str(exc.value)


def test_a_halt_stops_the_chain_and_never_falls_back_to_the_cloud():
    local, cloud = Fake("local", text="x"), Fake("openai", text="y", cloud=True)
    chain = FallbackSTT([local, cloud], labels=["local", "openai"], guard=lambda: "Notaus aktiv")
    with pytest.raises(STTHalted):
        chain.transcribe(CLIP)
    assert local.calls == 0 and cloud.calls == 0
    halted_local = Fake("local", error=STTHalted("gestoppt"))
    cloud2 = Fake("openai", text="y", cloud=True)
    with pytest.raises(STTHalted):
        FallbackSTT([halted_local, cloud2]).transcribe(CLIP)
    assert cloud2.calls == 0                                                      # auch ein Halt im lokalen Provider schaltet nie auf die Cloud um


def test_the_local_provider_raises_halted_when_the_guard_says_stop(tmp_path):
    stt = LocalWhisperSTT(model_dir(tmp_path, "m"), engine_loader=lambda p: None, guard=lambda: "Notaus")
    with pytest.raises(STTHalted):
        stt.transcribe(CLIP)


# ---- Strategie: local / auto / openai --------------------------------------------------------------------------------------------------------------
def test_local_with_one_model_stays_a_plain_provider(tmp_path):
    s = VoiceSettings(stt_provider="local", stt_model_dir=model_dir(tmp_path, "main"))
    assert isinstance(STT_PROVIDERS.create("local", s), LocalWhisperSTT)


def test_local_with_a_fallback_model_builds_a_chain_without_cloud(tmp_path):
    s = VoiceSettings(stt_provider="local", stt_model_dir=model_dir(tmp_path, "main"), stt_fallback_model_dir=model_dir(tmp_path, "base"),
                      stt_cloud_enabled=True, api_key="k")
    chain = STT_PROVIDERS.create("local", s)
    assert isinstance(chain, FallbackSTT) and [getattr(p, "cloud", None) for p in chain._providers] == [False, False]      # local nie mit Cloud


def test_auto_never_includes_the_cloud_unless_explicitly_enabled(tmp_path):
    s = VoiceSettings(stt_provider="auto", stt_model_dir=model_dir(tmp_path, "main"), stt_fallback_model_dir=model_dir(tmp_path, "base"), api_key="k")
    chain = build_stt_chain(s, cloud=True)
    assert all(not getattr(p, "cloud", False) for p in chain._providers) and s.stt_cloud_enabled is False


def test_auto_adds_the_cloud_last_only_with_the_switch_and_a_key(tmp_path):
    base = dict(stt_provider="auto", stt_model_dir=model_dir(tmp_path, "main"), stt_cloud_enabled=True)
    with_key = build_stt_chain(VoiceSettings(**base, api_key="k"), cloud=True)
    assert [type(p).__name__ for p in with_key._providers] == ["LocalWhisperSTT", "OpenAISTT"] and with_key._providers[-1].cloud is True
    without_key = build_stt_chain(VoiceSettings(**base), cloud=True)                 # Schalter an, aber kein Schluessel: keine Cloud, keine Ausnahme
    assert not any(getattr(p, "cloud", False) for p in getattr(without_key, "_providers", [without_key]))


def test_auto_without_any_usable_provider_explains_what_to_set():
    with pytest.raises(STTError) as exc:
        build_stt_chain(VoiceSettings(stt_provider="auto"), cloud=True)
    assert "stt_model_dir" in str(exc.value)


def test_a_missing_main_model_falls_back_to_the_second_one(tmp_path):
    s = VoiceSettings(stt_provider="local", stt_model_dir=str(tmp_path / "gibt-es-nicht"), stt_fallback_model_dir=model_dir(tmp_path, "base"))
    assert isinstance(build_stt_chain(s, cloud=False), LocalWhisperSTT)               # nur das Rueckfallmodell ist da: es wird benutzt


def test_auto_with_the_cloud_off_makes_no_request_even_if_all_local_models_fail(tmp_path):
    class Bad(LocalWhisperSTT):
        def transcribe(self, clip, language=None):
            raise STTError("kaputt")
    chain = FallbackSTT([Bad(model_dir(tmp_path, "m"))])
    with pytest.raises(STTError):
        chain.transcribe(CLIP)                                                        # no_network (autouse) bricht bei jedem http_post ab


# ---- OpenAI gpt-transcribe -----------------------------------------------------------------------------------------------------------------------
def fields_of(stt, language="de"):
    return stt._fields(language)


def test_gpt_transcribe_sends_languages_keywords_and_prompt_but_not_language():
    stt = oa.OpenAISTT("k", "gpt-transcribe", keywords=("JARVIS", "NEXUS", "bad<term>", "zwei\nzeilen", "  "), prompt="  Sprachsteuerung fuer JARVIS.  ")
    f = fields_of(stt)
    assert ("languages[]", "de") in f and ("keywords[]", "JARVIS") in f and ("keywords[]", "NEXUS") in f and ("prompt", "Sprachsteuerung fuer JARVIS.") in f
    assert not any(k == "language" for k, _ in f)
    assert [v for k, v in f if k == "keywords[]"] == ["JARVIS", "NEXUS"]              # < > und Zeilenumbrueche wuerden die ganze Anfrage ablehnen: nie senden
    assert ("model", "gpt-transcribe") in f


def test_older_models_and_auto_language_use_the_right_fields():
    assert ("language", "de") in fields_of(oa.OpenAISTT("k", "whisper-1"))
    assert not any(k in ("language", "languages[]") for k, _ in fields_of(oa.OpenAISTT("k", "gpt-transcribe"), "auto"))   # auto: Modell erkennt selbst


def test_the_default_cloud_model_is_gpt_transcribe_not_whisper():
    assert VoiceSettings().stt_model == "gpt-transcribe" and VoiceSettings().stt_cloud_enabled is False


def test_openai_request_is_multipart_with_repeated_fields(monkeypatch):
    seen = {}

    def fake(url, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body, timeout=timeout)
        return json.dumps({"text": " Hallo JARVIS ", "languages": [{"code": "de"}]}).encode()
    monkeypatch.setattr(oa, "http_post", fake)
    out = oa.OpenAISTT("sk-test-key", "gpt-transcribe", keywords=("JARVIS",), timeout=7).transcribe(CLIP, "de")
    assert out == "Hallo JARVIS" and seen["url"].endswith("/audio/transcriptions") and seen["timeout"] == 7
    assert b'name="languages[]"' in seen["body"] and b'name="keywords[]"' in seen["body"] and b'name="file"; filename="speech.wav"' in seen["body"]


@pytest.mark.parametrize("raised,expected", [("HTTP 401: x", "Schluessel ungueltig"), ("HTTP 429: x", "Limit oder Guthaben"), ("HTTP 404: x", "Modell oder Adresse"),
                                             ("HTTP 503: x", "gestoert"), ("timed out", "Zeitlimit"), ("getaddrinfo failed", "Netzwerk")])
def test_openai_errors_are_explained_and_never_contain_the_key(monkeypatch, raised, expected):
    def fail(*a, **k):
        raise OSError(raised)
    monkeypatch.setattr(oa, "http_post", fail)
    with pytest.raises(STTError) as exc:
        oa.OpenAISTT("sk-geheim-123", "gpt-transcribe").transcribe(CLIP, "de")
    assert expected in str(exc.value) and "sk-geheim-123" not in str(exc.value)


def test_openai_without_a_key_is_refused():
    with pytest.raises(STTError, match="OPENAI_API_KEY"):
        oa.OpenAISTT(None)


def test_stt_hints_contain_only_spellings():
    assert stt_hints(VoiceSettings(stt_keywords=("JARVIS", "NEXUS"), stt_prompt="Deutsch mit englischen Programmnamen")) == "Deutsch mit englischen Programmnamen Begriffe: JARVIS, NEXUS."
    assert stt_hints(VoiceSettings(stt_keywords=(), stt_prompt=None)) is None


# ---- Lokale Modelle: Sprache und Hinweise -------------------------------------------------------------------------------------------------------------
def test_language_auto_lets_the_model_detect_the_language():
    assert language_arg("auto") is None and language_arg("") is None and language_arg(None) is None and language_arg("de") == "de"


def test_the_local_engine_passes_language_and_hints_to_the_model(monkeypatch):
    import sys

    class Arr:                                                    # numpy-Ersatz: die Linux-CI installiert nur ".[dev]" (kein numpy)
        def astype(self, _):
            return self

        def __truediv__(self, _):
            return self
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(frombuffer=lambda raw, dtype=None: Arr(), float32=None))
    captured = {}

    class Model:
        def transcribe(self, audio, **kw):
            captured.update(kw)
            return [SimpleNamespace(text=" Hallo ")], SimpleNamespace(language="de")
    engine = _FasterWhisperEngine(Model(), "Begriffe: JARVIS.")
    segments, lang = engine.transcribe(CLIP, "auto")
    assert list(segments) == [" Hallo "] and lang == "de"
    assert captured["language"] is None and captured["initial_prompt"] == "Begriffe: JARVIS." and captured["vad_filter"] is True


# ---- Mikrofon-Auswahl -----------------------------------------------------------------------------------------------------------------------------
def fake_sd(devices, default=0):
    return SimpleNamespace(query_devices=lambda: devices, default=SimpleNamespace(device=(default, 0)))


DEVS = [{"name": "Lautsprecher", "max_input_channels": 0}, {"name": "Headset Microphone (Razer)", "max_input_channels": 1}, {"name": "Mikrofon (Auna Mic)", "max_input_channels": 1}]


def test_default_device_means_the_windows_default_and_is_checked():
    assert resolve_input_device(fake_sd(DEVS, default=1), None) is None and resolve_input_device(fake_sd(DEVS, default=1), "default") is None
    with pytest.raises(VoiceUnavailableError, match="Standard-Mikrofon"):
        resolve_input_device(fake_sd(DEVS, default=-1), None)
    with pytest.raises(VoiceUnavailableError, match="Standard-Mikrofon"):
        resolve_input_device(fake_sd(DEVS, default=0), None)                          # Standardgeraet ist ein Lautsprecher ohne Eingang


def test_device_by_index_and_by_name_part():
    assert resolve_input_device(fake_sd(DEVS), 2) == 2 and resolve_input_device(fake_sd(DEVS), "1") == 1
    assert resolve_input_device(fake_sd(DEVS), "auna") == 2 and resolve_input_device(fake_sd(DEVS), "RAZER") == 1
    assert [i for i, _ in input_devices(fake_sd(DEVS))] == [1, 2]


def test_unavailable_devices_give_a_message_with_the_available_ones():
    with pytest.raises(VoiceUnavailableError) as exc:
        resolve_input_device(fake_sd(DEVS), "Blue Yeti")
    assert "Blue Yeti" in str(exc.value) and "Razer" in str(exc.value) and "Auna" in str(exc.value)
    with pytest.raises(VoiceUnavailableError, match="Index 7"):
        resolve_input_device(fake_sd(DEVS), 7)
    with pytest.raises(VoiceUnavailableError, match="Kein Mikrofon"):
        resolve_input_device(fake_sd([{"name": "Lautsprecher", "max_input_channels": 0}]), None)


def test_the_source_resolves_the_device_for_every_recording_and_reports_a_missing_one(monkeypatch):
    from jarvis.voice.devices import SoundDeviceSource
    seen = []

    class Stream:
        def __init__(self, **kw):
            seen.append(kw["device"])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, frames):
            return b"\x00\x00" * frames, False
    sd = SimpleNamespace(RawInputStream=Stream, query_devices=lambda: DEVS, default=SimpleNamespace(device=(1, 0)))
    monkeypatch.setattr(SoundDeviceSource, "_import", staticmethod(lambda: sd))
    SoundDeviceSource(device="auna", max_seconds=0.3, silence_seconds=0.1, chunk_seconds=0.1).record()
    SoundDeviceSource(device=None, max_seconds=0.3, silence_seconds=0.1, chunk_seconds=0.1).record()
    assert seen == [2, None]                                                          # kein fest kodierter Index mehr
    with pytest.raises(VoiceUnavailableError, match="Blue Yeti"):
        SoundDeviceSource(device="Blue Yeti", max_seconds=0.3, chunk_seconds=0.1).record()


# ---- Nachbearbeitung und riskante Sprachbefehle -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("heard,expected", [("Dscharvis, wie spät ist es", "JARVIS, wie spät ist es"), ("tscharvis hallo", "JARVIS hallo"), ("öffne nexxus", "öffne NEXUS"),
                                            ("Hey Javis, öffne das Nexus Dashboard", "Hey JARVIS, öffne das NEXUS Dashboard"), ("Hallo   Welt ", "Hallo Welt"), ("Erstelle den Ordner Größenübung", "Erstelle den Ordner Größenübung")])
def test_normalize_fixes_only_known_mishearings_of_the_own_names(heard, expected):
    assert normalize_transcript(heard) == expected


def test_normalize_invents_nothing_else():
    text = "Lösche alle Dateien im Ordner Projekte und überweise Geld"
    assert normalize_transcript(text) == text


@pytest.mark.parametrize("text,risky", [("Lösche die Datei a.txt", True), ("Entferne den Ordner", True), ("Überweise 100 Euro", True), ("Delete everything", True),
                                        ("Fahre den Computer herunter", True), ("Lies die Datei a.txt", False), ("Wie spät ist es", False), ("Erstelle den Ordner Archiv", False)])
def test_risky_voice_commands_are_detected(text, risky):
    assert is_risky(text) is risky


def test_split_confirmation():
    assert split_confirmation("Bestätige lösche a.txt") == (True, "lösche a.txt") and split_confirmation("bestaetige, lösche a.txt") == (True, "lösche a.txt")
    assert split_confirmation("Lösche a.txt") == (False, "Lösche a.txt")


class Core:
    def __init__(self):
        self.handled = []

    def handle(self, text):
        self.handled.append(text)
        from jarvis.core.core import Response
        return Response("ok")


class Listener:
    def listen(self):
        return None


class Speaker:
    def say(self, text):
        pass

    def stop(self):
        pass


def make_session():
    core, shown = Core(), []
    return core, shown, VoiceSession(core, Listener(), Speaker(), display=shown.append, speak_responses=False)


def test_a_risky_voice_command_is_asked_back_and_not_executed():
    core, shown, session = make_session()
    assert session.process("Lösche die Datei a.txt") is True
    assert core.handled == [] and any("riskanten Anweisung" in line and "Bestätige" in line for line in shown)


def test_a_confirmed_risky_command_is_passed_on_without_the_confirmation_word():
    core, shown, session = make_session()
    session.process("Bestätige lösche die Datei a.txt")
    assert core.handled == ["lösche die Datei a.txt"]                                 # die Berechtigungspruefung/der Freigabedialog folgt wie immer


def test_normal_voice_commands_are_unchanged():
    core, shown, session = make_session()
    session.process("Wie spät ist es")
    assert core.handled == ["Wie spät ist es"]


# ---- Konfiguration --------------------------------------------------------------------------------------------------------------------------------
def test_config_defaults_never_send_audio_anywhere():
    v = load_settings(env={}).voice
    assert v.stt_provider == "console" and v.stt_cloud_enabled is False and v.audio_device is None


def test_config_rejects_unknown_providers_and_unsafe_keywords():
    with pytest.raises(ConfigError, match="stt_provider"):
        load_settings(env={"JARVIS_VOICE_STT_PROVIDER": "cloud"})
    with pytest.raises(ConfigError, match="stt_keywords"):
        VoiceSettings(stt_keywords=("a<b",))
        load_settings(env={"JARVIS_VOICE_STT_KEYWORDS": "ok" + chr(10) + "bad<x>"})


def test_the_api_key_is_taken_from_the_environment_only_for_a_cloud_that_was_chosen():
    env = {"OPENAI_API_KEY": "sk-env"}
    assert load_settings(env={**env, "JARVIS_VOICE_STT_PROVIDER": "auto"}).voice.api_key is None                       # auto ohne Schalter: Schluessel bleibt unberuehrt
    assert load_settings(env={**env, "JARVIS_VOICE_STT_PROVIDER": "auto", "JARVIS_VOICE_STT_CLOUD_ENABLED": "true"}).voice.api_key == "sk-env"
    assert load_settings(env={**env, "JARVIS_VOICE_STT_PROVIDER": "openai"}).voice.api_key == "sk-env"
    assert load_settings(env={**env, "JARVIS_VOICE_STT_PROVIDER": "local"}).voice.api_key is None


# ---- NEXUS-Anzeige und Struktur -----------------------------------------------------------------------------------------------------------------------
def test_the_setup_view_says_honestly_where_the_speech_is_recognised():
    from jarvis.control_center.setup_view import _stt_summary
    assert "Audio verlässt den PC nie" in _stt_summary(VoiceSettings(stt_provider="local", stt_model_dir="C:/m/whisper-small", stt_fallback_model_dir="C:/m/whisper-base"))
    auto_off = _stt_summary(VoiceSettings(stt_provider="auto", stt_model_dir="C:/m/whisper-small"))
    assert "Cloud AUS" in auto_off and "kein Audio im Internet" in auto_off and "whisper-small" in auto_off
    assert "Audio darf an OpenAI gesendet werden" in _stt_summary(VoiceSettings(stt_provider="auto", stt_model_dir="C:/m/x", stt_cloud_enabled=True))
    assert "Audio wird an OpenAI gesendet" in _stt_summary(VoiceSettings(stt_provider="openai"))


def test_only_the_openai_module_may_import_a_network_library():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "voice"
    banned = {"urllib", "http", "requests", "socket", "ssl", "httpx", "aiohttp", "websockets"}
    for name in ("stt_strategy.py", "audio_device.py", "postprocess.py", "meter.py", "local_stt.py", "composed.py", "session.py", "devices.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not (mods & banned), (name, mods & banned)


# ---- OpenAI-Schnittstelle laut offizieller Doku (gelesen, kein Request) ----------------------------------------------------------------------------------
def test_gpt_transcribe_sends_no_response_format_older_models_do():
    assert not any(k == "response_format" for k, _ in oa.OpenAISTT("k", "gpt-transcribe")._fields("de"))
    assert ("response_format", "json") in oa.OpenAISTT("k", "whisper-1")._fields("de")


@pytest.mark.parametrize("language", ["deutsch", "de_DE", "d", "german"])
def test_an_invalid_language_code_is_refused_before_anything_is_sent(language):
    with pytest.raises(STTError, match="Sprachcode"):
        oa.OpenAISTT("k", "gpt-transcribe")._fields(language)


@pytest.mark.parametrize("language", ["de", "EN", "zh-cn", "auto", None, ""])
def test_valid_language_codes_pass(language):
    oa.OpenAISTT("k", "gpt-transcribe")._fields(language)


def test_an_upload_over_25_mb_is_refused_locally(monkeypatch):
    monkeypatch.setattr(oa, "MAX_UPLOAD_BYTES", 100)
    with pytest.raises(STTError, match="25 MB"):
        oa.OpenAISTT("k").transcribe(CLIP, "de")
