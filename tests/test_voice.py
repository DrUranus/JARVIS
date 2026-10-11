"""Voice layer tests: only fakes, no microphone, audio device or network."""
import json
import struct

import pytest

from jarvis.config import VoiceSettings, load_settings
from jarvis.core import JarvisCore, Response, ResponseKind
from jarvis.errors import (ConfigError, EndOfInput, STTError, TTSError, VoiceError, VoiceUnavailableError)
from jarvis.llm.mock import MockProvider
from jarvis.voice import (AudioClip, Listener, Speaker, VoiceSession, build_listener, build_speaker,
                          register_audio_source, register_stt, register_tts)
from jarvis.voice import openai_provider as oa
from jarvis.voice.base import rms
from jarvis.voice.composed import SpeechListener, TTSSpeaker
from jarvis.voice.console import ConsoleListener, ConsoleSpeaker
from jarvis.voice.devices import Endpointer, SoundDeviceSource, SystemPlayer
from jarvis.voice.mock import MockAudioPlayer, MockAudioSource, MockSTT, MockTTS
from jarvis.voice.session import speech_text
from jarvis.voice.system_tts import SystemTTS


class ScriptedListener(Listener):
    def __init__(self, items):
        self.items = list(items)

    def listen(self):
        if not self.items:
            raise EndOfInput("done")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RecSpeaker(Speaker):
    def __init__(self, fail=None):
        self.said, self.fail = [], fail

    def say(self, text):
        if self.fail:
            raise self.fail
        self.said.append(text)


def make(listener_items, **kw):
    out: list[str] = []
    speaker = kw.pop("speaker", None) or RecSpeaker()
    core = kw.pop("core", None) or JarvisCore(MockProvider())
    s = VoiceSession(core, ScriptedListener(listener_items), speaker, display=out.append, **kw)
    return s, speaker, out


# ---- config -----------------------------------------------------------------------------------
def test_voice_defaults_need_no_hardware():
    v = load_settings(env={}).voice
    assert v.stt_provider == "console" and v.tts_provider == "console" and v.api_key is None


def test_voice_env_and_file(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[voice]\nwake_word = "computer"\nsilence_seconds = 2.5\nrequire_wake_word = true\n')
    v = load_settings(f, env={"JARVIS_VOICE_LANGUAGE": "en", "JARVIS_VOICE_SPEAK_RESPONSES": "false"}).voice
    assert (v.wake_word, v.silence_seconds, v.require_wake_word, v.language, v.speak_responses) == \
           ("computer", 2.5, True, "en", False)


def test_voice_api_key_only_from_env_and_hidden():
    s = load_settings(env={"JARVIS_VOICE_STT_PROVIDER": "openai", "OPENAI_API_KEY": "sk-x"})
    assert s.voice.api_key == "sk-x" and "sk-x" not in repr(s)
    assert load_settings(env={"OPENAI_API_KEY": "sk-x"}).voice.api_key is None  # not needed -> not copied


@pytest.mark.parametrize("env", [{"JARVIS_VOICE_SAMPLE_RATE": "0"}, {"JARVIS_VOICE_WAKE_WORD": " "},
                                 {"JARVIS_VOICE_SILENCE_THRESHOLD": "-1"}, {"JARVIS_VOICE_TIMEOUT": "x"}])
def test_voice_invalid_config(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


# ---- audio basics -----------------------------------------------------------------------------
def test_wav_roundtrip_and_rms():
    pcm = struct.pack("<4h", 100, -100, 100, -100)
    clip = AudioClip(pcm, 8000)
    assert AudioClip.from_wav(clip.to_wav()) == clip
    assert clip.duration == pytest.approx(4 / 8000)
    assert rms(pcm) == pytest.approx(100) and rms(b"") == 0


def test_endpointer():
    ep = Endpointer(threshold=100, silence_seconds=0.3, max_seconds=5, initial_wait_seconds=1)
    assert not ep.feed(10, 0.1) and not ep.heard_speech
    assert not ep.feed(500, 0.1) and ep.heard_speech
    assert not ep.feed(10, 0.1) and not ep.feed(10, 0.1)
    assert ep.feed(10, 0.1)  # 0.3 s quiet after speech
    ep = Endpointer(100, 0.3, 5, 1)
    assert [ep.feed(1, 0.5) for _ in range(2)] == [False, True]  # nobody spoke
    ep = Endpointer(100, 10, 0.25, 1)
    assert [ep.feed(500, 0.1) for _ in range(3)] == [False, False, True]  # max length


# ---- composed listener / speaker ------------------------------------------------------------------
def test_speech_listener_transcribes_with_language():
    stt = MockSTT(["hallo welt"])
    assert SpeechListener(MockAudioSource(1), stt, "de").listen() == "hallo welt"
    assert stt.languages == ["de"] and len(stt.clips) == 1


def test_speech_listener_silence_and_empty_transcript():
    class Silent(MockAudioSource):
        def record(self):
            return None
    assert SpeechListener(Silent(), MockSTT(["x"])).listen() is None
    assert SpeechListener(MockAudioSource(1), MockSTT([""])).listen() is None
    with pytest.raises(EndOfInput):
        SpeechListener(MockAudioSource(0), MockSTT()).listen()


def test_tts_speaker_delegates():
    tts = MockTTS()
    TTSSpeaker(tts).say("hi")
    assert tts.spoken == ["hi"]


def test_console_io():
    lines = iter(["  hallo  ", ""])
    c = ConsoleListener(lambda p: next(lines))
    assert c.listen() == "hallo" and c.listen() is None

    def eof(p):
        raise EOFError
    with pytest.raises(EndOfInput):
        ConsoleListener(eof).listen()
    out = []
    ConsoleSpeaker(out.append).say("x")
    assert out == ["🔊 x"]


# ---- session ----------------------------------------------------------------------------------
def test_session_roundtrip_through_core():
    s, spk, out = make(["Hallo JARVIS"])
    assert s.run() == 1
    assert spk.said == ["Hallo. Ich bin bereit."]
    assert "Du: Hallo JARVIS" in out and "JARVIS: Hallo. Ich bin bereit." in out


def test_session_is_decoupled_from_core(core):
    """Any object with handle(text) -> Response works (future memory/agent cores)."""
    class Fake:
        def handle(self, text):
            return Response(f"echo {text}")
    s, spk, _ = make(["abc"], core=Fake())
    s.run()
    assert spk.said == ["echo abc"]


def test_plan_is_summarised_for_speech_but_shown_in_full(core):
    s, spk, out = make(["Erstelle ein CSV-Tool"], core=core)
    s.run()
    assert "Plan mit 3 Schritten" in spk.said[0]
    assert any("Code schreiben" in line for line in out)
    r = core.handle("Erstelle noch eins")
    assert speech_text(r) != r.text and speech_text(Response("x")) == "x"


def test_wake_word_required():
    s, spk, out = make(["Hallo", "Jarvis, hallo", "JARVIS", "Hallo", "Hallo"], require_wake_word=True)
    s.run()
    # 1st ignored, 2nd handled, 3rd bare -> "Ja?", 4th handled without wake word, 5th ignored again
    assert spk.said == ["Hallo. Ich bin bereit.", "Ja?", "Hallo. Ich bin bereit."]


def test_bare_wake_word_without_requirement_answers_ja():
    s, spk, _ = make(["jarvis"])
    s.run()
    assert spk.said == ["Ja?"]


def test_wake_word_prefix_is_stripped_before_core():
    seen = []

    class H:
        def handle(self, t):
            seen.append(t)
            return Response("ok")
    make(["Jarvis, was ist offen?"], core=H())[0].run()
    assert seen == ["was ist offen?"]


@pytest.mark.parametrize("phrase", ["exit", "Beenden.", "Tschüss!", "jarvis stop"])
def test_exit_phrases_end_session(phrase):
    s, spk, _ = make([phrase, "Hallo"])
    assert s.run() == 1
    assert spk.said == ["Sprachmodus beendet."]


def test_silence_is_skipped_and_empty_ignored():
    s, spk, _ = make([None, "  ", "Hallo"])
    assert s.run() == 1  # silence and blank transcripts are not turns
    assert spk.said == ["Hallo. Ich bin bereit."]


def test_max_turns():
    s, spk, _ = make(["Hallo", "Hallo", "Hallo"])
    assert s.run(max_turns=2) == 2 and len(spk.said) == 2


def test_stt_errors_are_survived_then_abort():
    s, spk, out = make([STTError("net"), "Hallo"])
    assert s.run() == 1 and spk.said == ["Hallo. Ich bin bereit."]
    s, spk, out = make([STTError("1"), STTError("2"), STTError("3"), "Hallo"])
    assert s.run() == 0 and spk.said == [] and any("Zu viele Fehler" in o for o in out)


def test_failure_counter_resets_after_success():
    s, spk, _ = make([STTError("a"), STTError("b"), "Hallo", STTError("c"), STTError("d"), "Hallo"])
    assert s.run() == 2


def test_unavailable_microphone_ends_session_gracefully():
    s, _, out = make([VoiceUnavailableError("no mic"), "Hallo"])
    assert s.run() == 0 and any("Audio nicht verfügbar: no mic" in o for o in out)
    s, _, out = make([VoiceError("odd")])
    assert s.run() == 0 and any("Sprachfehler" in o for o in out)


def test_unavailable_speaker_degrades_to_text_once():
    spk = RecSpeaker(fail=VoiceUnavailableError("no audio out"))
    s, _, out = make(["Hallo", "Hallo"], speaker=spk)
    assert s.run() == 2
    assert sum("Sprachausgabe nicht verfügbar" in o for o in out) == 1  # not retried
    assert out.count("JARVIS: Hallo. Ich bin bereit.") == 2  # text still delivered


def test_tts_error_does_not_kill_session():
    spk = RecSpeaker(fail=TTSError("boom"))
    s, _, out = make(["Hallo", "Hallo"], speaker=spk)
    assert s.run() == 2 and sum("Sprachausgabe fehlgeschlagen" in o for o in out) == 2


def test_speak_responses_off():
    s, spk, out = make(["Hallo"], speak_responses=False)
    s.run()
    assert spk.said == [] and "JARVIS: Hallo. Ich bin bereit." in out


def test_core_error_response_is_spoken_not_raised():
    from jarvis.errors import LLMError

    def boom(r):
        raise LLMError("offline")
    s, spk, _ = make(["Hallo"], core=JarvisCore(MockProvider(responder=boom)))
    s.run()
    assert "offline" in spk.said[0]


# ---- factory / registries -----------------------------------------------------------------------
def test_factory_console_defaults():
    assert isinstance(build_listener(VoiceSettings()), ConsoleListener)
    assert isinstance(build_speaker(VoiceSettings()), ConsoleSpeaker)


def test_factory_custom_registration():
    register_stt("custom-stt", lambda s: MockSTT(["custom"]))
    register_audio_source("custom-mic", lambda s: MockAudioSource(1))
    register_tts("custom-tts", lambda s: MockTTS())
    lst = build_listener(VoiceSettings(stt_provider="custom-stt", audio_input="custom-mic"))
    assert lst.listen() == "custom"
    assert isinstance(build_speaker(VoiceSettings(tts_provider="custom-tts")), TTSSpeaker)


def test_factory_unknown_names():
    with pytest.raises(VoiceError, match="unknown STT"):
        build_listener(VoiceSettings(stt_provider="nope"))
    with pytest.raises(VoiceError, match="unknown audio input"):
        build_listener(VoiceSettings(stt_provider="mock", audio_input="nope"))
    with pytest.raises(VoiceError):
        build_speaker(VoiceSettings(tts_provider="nope"))


def test_missing_microphone_library_is_voice_unavailable(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "sounddevice":
            raise ImportError("simulated: not installed")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(VoiceUnavailableError):
        SoundDeviceSource()
    with pytest.raises(VoiceUnavailableError):
        build_listener(VoiceSettings(stt_provider="mock"))


def test_openai_providers_require_key():
    with pytest.raises(STTError):
        build_listener(VoiceSettings(stt_provider="openai", audio_input="mock"))
    with pytest.raises(TTSError):
        build_speaker(VoiceSettings(tts_provider="openai", audio_output="mock"))


# ---- OpenAI providers (network stubbed) -----------------------------------------------------------
def test_openai_stt_request_and_parse(monkeypatch):
    seen = {}

    def fake(url, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body)
        return json.dumps({"text": " Hallo Welt "}).encode()

    monkeypatch.setattr(oa, "http_post", fake)
    stt = oa.OpenAISTT("k", "whisper-1")
    assert stt.transcribe(AudioClip(b"\x00\x00" * 10), "de") == "Hallo Welt"
    assert seen["url"].endswith("/audio/transcriptions")
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert seen["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="language"' in seen["body"] and b"RIFF" in seen["body"]


@pytest.mark.parametrize("reply", [b"not json", b'{"nope": 1}'])
def test_openai_stt_bad_reply(monkeypatch, reply):
    monkeypatch.setattr(oa, "http_post", lambda *a: reply)
    with pytest.raises(STTError):
        oa.OpenAISTT("k").transcribe(AudioClip(b"\x00\x00"))


def test_openai_stt_network_error(monkeypatch):
    def fail(*a):
        raise OSError("down")
    monkeypatch.setattr(oa, "http_post", fail)
    with pytest.raises(STTError, match="down"):
        oa.OpenAISTT("k").transcribe(AudioClip(b"\x00\x00"))


def test_openai_tts_synthesises_and_plays(monkeypatch):
    wav = AudioClip(b"\x01\x00" * 20, 22050).to_wav()
    seen = {}

    def fake(url, headers, body, timeout):
        seen.update(url=url, payload=json.loads(body))
        return wav

    monkeypatch.setattr(oa, "http_post", fake)
    player = MockAudioPlayer()
    oa.OpenAITTS("k", player, voice="nova").speak("Hallo")
    assert seen["payload"]["input"] == "Hallo" and seen["payload"]["voice"] == "nova"
    assert player.played[0].sample_rate == 22050


def test_openai_tts_failures(monkeypatch):
    monkeypatch.setattr(oa, "http_post", lambda *a: b"garbage")
    with pytest.raises(TTSError):
        oa.OpenAITTS("k", MockAudioPlayer()).speak("x")

    def fail(*a):
        raise OSError("down")
    monkeypatch.setattr(oa, "http_post", fail)
    with pytest.raises(TTSError):
        oa.OpenAITTS("k", MockAudioPlayer()).speak("x")


# ---- system devices --------------------------------------------------------------------------------
def test_system_tts_missing_command(monkeypatch):
    monkeypatch.setattr("jarvis.voice.system_tts.shutil.which", lambda n: None)
    with pytest.raises(VoiceUnavailableError):
        SystemTTS()


def test_system_tts_runs_command(monkeypatch):
    calls = []
    monkeypatch.setattr("jarvis.voice.system_tts.subprocess.run", lambda cmd, **kw: calls.append(cmd))
    SystemTTS("espeak-ng -v de").speak("Hallo")
    assert calls == [["espeak-ng", "-v", "de", "Hallo"]]


def test_system_tts_missing_binary_at_runtime():
    with pytest.raises(VoiceUnavailableError):
        SystemTTS("definitely-not-a-real-binary-xyz").speak("hi")


def test_system_player_without_player(monkeypatch):
    monkeypatch.setattr("jarvis.voice.devices.shutil.which", lambda n: None)

    if __import__("os").name == "nt":
        import numpy as np
        import sounddevice as sd

        played = []
        monkeypatch.setattr(sd, "play", lambda samples, samplerate, blocking: played.append(
            (samples, samplerate, blocking)
        ))

        SystemPlayer().play(AudioClip(struct.pack("<h", 100), 16000))

        assert len(played) == 1
        assert played[0][1:] == (16000, True)
    else:
        with pytest.raises(VoiceUnavailableError):
            SystemPlayer().play(AudioClip(b"\x00\x00"))
