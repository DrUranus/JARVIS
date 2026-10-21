"""VoiceSession reports its real states (listening / processing / speaking / idle / error) and can be stopped between utterances. Fakes only."""
import threading

from jarvis.core import Response
from jarvis.errors import EndOfInput, STTError, TTSError, VoiceUnavailableError
from jarvis.voice import Listener, Speaker, VoiceSession


class Script(Listener):
    def __init__(self, items, log=None):
        self.items, self.log = list(items), log

    def listen(self):
        if self.log is not None:
            self.log.append("listen")
        if not self.items:
            raise EndOfInput("done")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Recorder(Speaker):
    def __init__(self, log, fail=None):
        self.log, self.fail = log, fail

    def say(self, text):
        self.log.append("say")
        if self.fail:
            raise self.fail


class Handler:
    def __init__(self, log):
        self.log = log

    def handle(self, text):
        self.log.append("handle")
        return Response(f"echo {text}")


def make(items, *, speaker_fail=None, stop=None):
    log, states = [], []
    session = VoiceSession(Handler(log), Script(items, log), Recorder(log, speaker_fail), display=lambda _l: None,
                           on_state=lambda s, d="": states.append((s, d)))
    return session, log, states


def names(states):
    return [s for s, _ in states]


def test_states_follow_listen_process_speak():
    session, log, states = make(["hallo"])
    assert session.run() == 1
    assert log == ["listen", "handle", "say", "listen"]
    assert names(states) == ["listening", "processing", "idle", "speaking", "idle", "listening", "idle"]


def test_no_observer_changes_nothing():
    log = []
    session = VoiceSession(Handler(log), Script(["hallo"], log), Recorder(log), display=lambda _l: None)
    assert session.run() == 1


def test_a_failing_observer_never_breaks_the_conversation():
    log = []

    def broken(state, detail=""):
        raise RuntimeError("observer bug")
    session = VoiceSession(Handler(log), Script(["hallo"], log), Recorder(log), display=lambda _l: None, on_state=broken)
    assert session.run() == 1 and "handle" in log


def test_errors_are_reported_with_their_text():
    session, _, states = make([STTError("kein Ton")])
    session.run(max_turns=1)
    assert ("error", "Spracherkennung fehlgeschlagen: kein Ton") in states
    session, _, states = make([VoiceUnavailableError("kein Mikrofon")])
    session.run()
    assert ("error", "Audio nicht verfügbar: kein Mikrofon") in states and names(states)[-1] == "idle"


def test_a_tts_failure_is_reported_and_the_state_returns_to_idle():
    session, _, states = make(["hallo"], speaker_fail=TTSError("Lautsprecher kaputt"))
    session.run()
    assert any(s == "error" and "Lautsprecher kaputt" in d for s, d in states)
    assert names(states)[-1] == "idle"


def test_stop_before_the_first_listen_does_not_touch_the_microphone():
    session, log, _ = make(["hallo"])
    stop = threading.Event()
    stop.set()
    assert session.run(stop=stop) == 0 and log == []


def test_stop_during_a_recording_discards_that_utterance():
    stop = threading.Event()
    log, states = [], []

    class StoppingListener(Listener):
        def listen(self):
            stop.set()                          # the user pressed "Sprache beenden" while this recording was running
            return "das darf nicht ausgeführt werden"
    session = VoiceSession(Handler(log), StoppingListener(), Recorder(log), display=lambda _l: None, on_state=lambda s, d="": states.append(s))
    assert session.run(stop=stop) == 0 and "handle" not in log and states[-1] == "idle"
