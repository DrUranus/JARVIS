"""Barge-in und lokaler Hotword-Baustein: nur Fakes, kein Mikrofon, kein Netzwerk."""
import pytest

from jarvis.config import VoiceSettings
from jarvis.core import Response, ResponseKind
from jarvis.errors import EndOfInput
from jarvis.voice import AudioClip, Listener, VoiceSession, build_listener, register_hotword_detector
from jarvis.voice.base import AudioPlayer, HotwordDetector, Speaker
from jarvis.voice.composed import SpeechListener, TTSSpeaker
from jarvis.voice.hotword import HotwordGatedSource
from jarvis.voice.mock import MockAudioPlayer, MockAudioSource, MockHotwordDetector, MockSTT, MockTTS
from jarvis.voice.openai_provider import OpenAITTS


class Handler:
    def __init__(self):
        self.calls = []

    def handle(self, text):
        self.calls.append(text)
        return Response(ResponseKind.CHAT, "ok")


class Scripted(Listener):
    def __init__(self, items):
        self.items = list(items)

    def listen(self):
        if not self.items:
            raise EndOfInput("done")
        return self.items.pop(0)


class RecSpeaker(Speaker):
    def __init__(self):
        self.said, self.stops = [], 0

    def say(self, text):
        self.said.append(text)

    def stop(self):
        self.stops += 1


def test_player_stop_default_is_noop_and_fake_records_stop():
    class Bare(AudioPlayer):
        def play(self, clip):
            pass
    Bare().stop()                                    # Abwaertskompatibel: kein Fehler
    p = MockAudioPlayer()
    p.play(AudioClip(b"\x01\x00" * 10))
    p.stop()
    assert p.stops == 1


def test_barge_in_stops_playback_through_the_chain():
    player = MockAudioPlayer()
    tts = OpenAITTS.__new__(OpenAITTS)               # nur die Stop-Kette pruefen, kein Netzwerk
    tts._player = player
    TTSSpeaker(tts).stop()
    assert player.stops == 1


def test_session_interrupt_stops_speaker():
    sp = RecSpeaker()
    s = VoiceSession(Handler(), Scripted([]), sp, display=lambda _t: None)
    s.interrupt()
    assert sp.stops == 1


def test_interrupt_never_runs_the_handler():
    h, sp = Handler(), RecSpeaker()
    VoiceSession(h, Scripted([]), sp, display=lambda _t: None).interrupt()
    assert h.calls == []


def test_ttsspeaker_stop_without_provider_support_is_safe():
    TTSSpeaker(MockTTS()).stop()


def test_hotword_gate_blocks_until_detected_and_is_swappable():
    src = MockAudioSource(count=3)
    det = MockHotwordDetector([False, True])
    gated = HotwordGatedSource(src, det)
    assert gated.record() is None                    # nichts erkannt -> kein Audio weitergereicht
    assert gated.record() is None                    # Hotword-Clip selbst wird nicht weitergegeben
    assert gated.record() is not None                # naechste Aufnahme ist der Befehl
    assert det.seen == 2


def test_hotword_gate_propagates_end_of_input():
    gated = HotwordGatedSource(MockAudioSource(count=0), MockHotwordDetector([]))
    with pytest.raises(EndOfInput):
        gated.record()


def test_hotword_detector_registry_builds_listener_without_cloud():
    register_hotword_detector("fake-test", lambda s: MockHotwordDetector([True]))
    from jarvis.voice import register_audio_source, register_stt
    register_audio_source("fake-src", lambda s: MockAudioSource(count=2))
    register_stt("fake-stt", lambda s: MockSTT(["hallo"]))
    lst = build_listener(VoiceSettings(stt_provider="fake-stt", audio_input="fake-src", hotword_detector="fake-test"))
    assert isinstance(lst, SpeechListener)
    assert lst.listen() is None                      # Hotword erkannt, noch kein Befehl
    assert lst.listen() == "hallo"


def test_default_has_no_hotword_gate():
    assert VoiceSettings().hotword_detector == "none"


def test_hotword_alone_never_triggers_handler():
    h = Handler()
    gated = HotwordGatedSource(MockAudioSource(count=1), MockHotwordDetector([True]))
    s = VoiceSession(h, SpeechListener(gated, MockSTT(["hallo"])), RecSpeaker(), display=lambda _t: None)
    assert s.run() == 0                              # Hotword erkannt, aber kein Befehl -> keine Aeusserung, kein handle()
    assert h.calls == []


def test_bare_wake_word_does_not_run_handler_or_action():
    h = Handler()
    s = VoiceSession(h, Scripted(["Jarvis"]), RecSpeaker(), require_wake_word=True, display=lambda _t: None)
    s.run()
    assert h.calls == []


def test_wake_word_never_executes_confirmation_gated_action(tmp_path):
    """Handler fuehrt ueber ToolRegistry.execute eine YELLOW-Aktion aus. Wake-Word allein ruft ihn nie auf;
    der eigentliche Befehl laeuft nur mit Bestaetigung (hier: verweigert -> nichts passiert)."""
    from jarvis.permissions import ActionSpec, DenyAllConfirmation, ResourceType
    from jarvis.tools import ToolParameter, ToolRegistry, ToolResult
    from jarvis.tools.base import ProtectedTool
    from secutil import Y, make_engine

    class Writer(ProtectedTool):
        name, description, permission = "writer", "pretend writer", Y
        parameters = (ToolParameter("path", "target"),)

        def __init__(self):
            self.performed = []

        def describe_action(self, **kw):
            return ActionSpec(action="write", resource=kw["path"], resource_type=ResourceType.PATH)

        def _perform(self, **kw):
            self.performed.append(kw["path"])
            return ToolResult.ok("written")

    w = Writer()
    reg = ToolRegistry(make_engine(tmp_path, confirmation=DenyAllConfirmation())[0])
    reg.register(w)

    class ToolHandler:
        calls = 0

        def handle(self, text):
            ToolHandler.calls += 1
            r = reg.execute("writer", path="a.txt")
            return Response(ResponseKind.CHAT, r.error or r.output)

    # nur Wake-Word (bare) und ein Hotword-Treffer ohne Befehl: Handler wird nie aufgerufen
    VoiceSession(ToolHandler(), Scripted(["jarvis", None]), RecSpeaker(), require_wake_word=True, display=lambda _t: None).run()
    assert ToolHandler.calls == 0 and w.performed == []
    # mit Befehl: geht durch die Engine, Bestaetigung verweigert -> keine Aktion
    VoiceSession(ToolHandler(), Scripted(["jarvis", "schreibe etwas"]), RecSpeaker(), require_wake_word=True, display=lambda _t: None).run()
    assert ToolHandler.calls == 1 and w.performed == []
