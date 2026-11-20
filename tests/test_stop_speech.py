"""„Antwort stoppen“ (`stop_speech`, rein additiver UI-Vertragsbefehl): bricht NUR die laufende Sprachausgabe ab (vorhandenes `interrupt()`), der Sprachmodus bleibt
aktiv; die noch nicht gesprochene Antwort der laufenden Anfrage wird verworfen. Keine Rechte, kein Werkzeug, kein Eingriff in Notaus oder PermissionEngine."""
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import jarvis.control_center as cc
from jarvis.core.core import Response
from jarvis.ui_contract import COMMAND_TYPES, FakeUiBackend, validate_command
from jarvis.voice.base import Listener
from jarvis.voice.session import VoiceSession

WEB = Path(cc.__file__).parent / "web"
SCHEMA = Path(cc.__file__).parents[1] / "ui_contract" / "schema"


def cmd(type_, data=None, cid="s1"):
    return {"v": "1.0", "id": cid, "type": type_, "data": data or {}}


# ---- Vertrag: additiv, geschlossen, streng ------------------------------------------------------------------------------------------------------
def test_stop_speech_is_a_known_empty_command_and_extra_data_is_rejected():
    assert "stop_speech" in COMMAND_TYPES and validate_command(cmd("stop_speech"))["type"] == "stop_speech"
    with pytest.raises(Exception):
        validate_command(cmd("stop_speech", {"x": 1}))


def test_the_json_schema_file_lists_stop_speech_next_to_the_existing_commands():
    text = (SCHEMA / "ui-commands.schema.json").read_text(encoding="utf-8")
    consts = re.findall(r'"const": "(\w+)"', text)
    assert "stop_speech" in consts and "stop_voice" in consts and "start_voice" in consts


def test_fake_backend_answers_stop_speech_only_while_voice_runs():
    b = FakeUiBackend()
    assert b.send(cmd("stop_speech"))["data"]["code"] == "not_active"
    assert b.send(cmd("start_voice", cid="v1"))["data"]["ok"]
    assert b.send(cmd("stop_speech", cid="v2"))["data"]["ok"]
    assert b.send(cmd("stop_voice", cid="v3"))["data"]["ok"] is True          # die Sitzung lief nach „Antwort stoppen“ weiter


# ---- Session: nur Ausgabe, Modus bleibt, späte Antwort wird verworfen --------------------------------------------------------------------------------
class Speaker:
    def __init__(self):
        self.say_started, self.stopped, self.said, self._cut = threading.Event(), 0, [], threading.Event()

    def say(self, text):
        self.said.append(text)
        self.say_started.set()
        self._cut.wait(5)
        self._cut.clear()

    def stop(self):
        self.stopped += 1
        self._cut.set()


class Script(Listener):
    def __init__(self, items):
        self.items, self.gate = list(items), threading.Event()

    def listen(self):
        if self.items:
            return self.items.pop(0)
        self.gate.wait(5)
        return None

    def cancel(self):
        self.gate.set()


def run_session(handler, listener, speaker):
    s = VoiceSession(SimpleNamespace(handle=handler), listener, speaker, display=lambda t: None)
    stop = threading.Event()
    th = threading.Thread(target=lambda: s.run(stop=stop))
    th.start()
    return s, stop, th


def test_stop_speaking_cuts_the_speech_and_the_session_keeps_listening_for_the_next_sentence():
    sp, ln = Speaker(), Script(["erste Frage"])
    s, stop, th = run_session(lambda t: Response("Antwort auf " + t, None), ln, sp)
    assert sp.say_started.wait(3)
    s.stop_speaking()
    time.sleep(0.3)
    assert sp.stopped >= 1 and th.is_alive()                                  # Sprachmodus lebt weiter
    sp.say_started.clear()
    ln.items.append("zweite Frage")
    ln.gate.set()
    assert sp.say_started.wait(3) and sp.said[-1] == "Antwort auf zweite Frage"   # die naechste Anfrage wird normal gesprochen
    stop.set()
    s.stop_speaking()
    ln.cancel()
    th.join(3)
    assert not th.is_alive()


def test_a_reply_finishing_after_stop_speaking_is_not_spoken_but_the_next_one_is():
    gate, sp = threading.Event(), Speaker()

    def handle(text):
        if text == "langsam":
            gate.wait(5)
        return Response("A:" + text, None)

    ln = Script(["langsam"])
    s, stop, th = run_session(handle, ln, sp)
    time.sleep(0.3)
    s.stop_speaking()                                                          # Antwort noch in Arbeit
    gate.set()
    time.sleep(0.4)
    assert sp.said == []                                                       # die alte Antwort wird nicht nachgesprochen
    ln.items.append("schnell")
    ln.gate.set()
    assert sp.say_started.wait(3) and sp.said == ["A:schnell"]                 # die naechste Anfrage spricht wieder
    stop.set()
    s.stop_speaking()
    ln.cancel()
    th.join(3)


# ---- Controller ---------------------------------------------------------------------------------------------------------------------------------------
def make_ctl(factory=None):
    from jarvis.interface.gui_model import GuiController
    emergency = SimpleNamespace(engaged=False, register=lambda *a, **k: None, add_listener=lambda *a, **k: None)
    core = SimpleNamespace(permissions=SimpleNamespace(emergency=emergency))
    return GuiController(core, SimpleNamespace(voice=SimpleNamespace(stt_provider="local")), voice_factory=factory), emergency


def test_controller_stop_speech_only_stops_the_speech_and_keeps_voice_active():
    calls = []

    class FakeSession:
        def run(self, stop=None, **kw):
            stop.wait(5)

        def stop_speaking(self):
            calls.append("stop_speaking")

        def interrupt(self):
            calls.append("interrupt")

        def cancel_listening(self):
            calls.append("cancel_listening")

    ctl, emergency = make_ctl(lambda *a, **k: FakeSession())
    assert ctl.start_voice() == ""
    ctl.stop_speech()
    assert calls == ["stop_speaking"] and ctl.voice_active and emergency.engaged is False
    ctl.stop_voice()
    ctl.close()


def test_stop_speech_without_voice_is_a_noop():
    ctl, _ = make_ctl()
    ctl.stop_speech()
    assert not ctl.voice_active
    ctl.close()


def test_adapter_routes_stop_speech_to_the_controller_and_refuses_it_during_the_emergency():
    from jarvis.interface.ui_events import ControllerUiBackend
    seen = []
    ctl = SimpleNamespace(voice_active=True, emergency_engaged=False, stop_speech=lambda: seen.append(1))
    # nur der Befehlsweg: der Adapter ruft genau stop_speech des Controllers (kein stop_voice, kein Rechte-Weg)
    handler = ControllerUiBackend._do_stop_speech
    log = SimpleNamespace(ack=lambda cid, ok, code="ok", msg="": {"ok": ok, "code": code})
    obj = SimpleNamespace(_ctl=ctl, _log=log)
    assert handler(obj, "c1", {}) == {"ok": True, "code": "ok"} and seen == [1]
    obj._ctl.voice_active = False
    assert handler(obj, "c2", {})["code"] == "not_active" and seen == [1]
    from jarvis.interface import ui_events
    assert "stop_speech" not in ui_events._ALLOWED_IN_EMERGENCY               # bei Notaus wie alle anderen Befehle gesperrt


# ---- Oberflaeche ---------------------------------------------------------------------------------------------------------------------------------------
def test_ui_has_the_button_and_it_sends_only_the_request():
    html, js = (WEB / "index.html").read_text(encoding="utf-8"), (WEB / "app.js").read_text(encoding="utf-8")
    assert 'id="speech-stop"' in html and "Antwort stoppen" in html
    assert re.search(r'el\("speech-stop"\)\.addEventListener\("click",\s*\(\)\s*=>\s*send\("stop_speech",\s*\{\}\)\)', js)
    assert js.count("stop_speech") == 1
    assert re.search(r'el\("speech-stop"\)\.disabled\s*=\s*voiceActive\s*!==\s*true', js)
