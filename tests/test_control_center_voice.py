"""cc-voice-viz (Strang B, B4): Pegel-/Wellenanzeige und Sprachknoepfe der Weboberflaeche (Premium V2).
- Anzeige folgt ausschliesslich den voice_level- und state-Ereignissen (Ereignisse vom FakeUiBackend, DOM-Ersatz in Node: tests/support/cc_dom_harness.js).
- Das Mikrofon startet nur durch den Befehl start_voice (Knopfdruck); es gibt keine Audiodaten im Frontend (Asset-Pruefung, Permissions-Policy).
- Bei ausgeschalteten Effekten bleibt die Statusanzeige lesbar.
Nur Loopback bzw. kein Netzwerk."""
import http.client
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import jarvis.control_center as cc
from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend
from jarvis.ui_contract.schema import validate_event

WEB = Path(cc.__file__).parent / "web"
HARNESS = Path(__file__).parent / "support" / "cc_dom_harness.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node fehlt: DOM-Pruefung nicht moeglich (ein uebersprungener Test gilt nicht als bestanden)")


def text(name):
    return (WEB / name).read_text(encoding="utf-8")


# ---- Assets: keine Audiodaten im Frontend ---------------------------------------------------------------------------------------------------
AUDIO_APIS = ("getUserMedia", "mediaDevices", "AudioContext", "webkitAudioContext", "MediaRecorder", "createMediaStreamSource", "AudioWorklet",
              "SpeechRecognition", "webkitSpeechRecognition", "speechSynthesis", "new Audio", "createScriptProcessor", "decodeAudioData", "ArrayBuffer",
              "Float32Array", "Uint8Array", "Blob(", "FileReader", "RTCPeerConnection")


@pytest.mark.parametrize("name", ["index.html", "app.js", "styles.css"])
def test_assets_contain_no_audio_api_or_media_element(name):
    src = text(name)
    for bad in AUDIO_APIS:
        assert bad not in src, (name, bad)
    assert not re.search(r"<\s*(audio|video|source|track|embed|object|iframe)\b", src, re.I)
    assert not re.search(r"data:\s*(audio|video)|blob:|\.(wav|mp3|ogg|webm|m4a|flac|opus)\b", src, re.I)


def test_web_directory_holds_only_text_assets():
    names = sorted(p.name for p in WEB.iterdir())
    assert all(Path(n).suffix in {".html", ".js", ".css", ".json"} for n in names), names


def test_app_never_uses_randomness_or_timers_that_could_invent_levels():
    js = text("app.js")
    assert "Math.random" not in js
    assert re.findall(r"setInterval\(([^,)]*)", js) == ["updateRemaining"]  # nur der Restzeit-Zaehler der Rueckfrage, nichts mit Pegel


def test_start_voice_appears_exactly_once_and_only_in_the_button_handler():
    js = text("app.js")
    assert len(re.findall(r'"start_voice"', js)) == 1 and len(re.findall(r'"stop_voice"', js)) == 1
    assert re.search(r'el\("voice-start"\)\.addEventListener\("click",[^\n]*send\("start_voice", \{\}\)', js)
    assert re.search(r'el\("voice-stop"\)\.addEventListener\("click",[^\n]*send\("stop_voice", \{\}\)', js)


def test_html_voice_controls_exist_outside_the_two_views():
    html = text("index.html")
    for i in ("voice-start", "voice-stop", "voice-mic", "voice-state", "voice-level-text", "voice-meter", "voice-wave"):
        assert f'id="{i}"' in html, i
    assert html.index('id="voice-bar"') > html.index("</main>")  # in jedem UI-Modus gleich erreichbar
    assert not re.search(r"<\s*input[^>]*type=\"?file", html, re.I)


@pytest.fixture
def srv():
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    s.start()
    yield s
    s.stop()


def test_server_denies_microphone_and_camera_to_the_page(srv):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", f"/?t={srv.token}", headers={"Host": f"127.0.0.1:{srv.port}"})
    r = conn.getresponse()
    r.read()
    pp = r.getheader("Permissions-Policy") or ""
    conn.close()
    assert "microphone=()" in pp and "camera=()" in pp


# ---- DOM (Node) -----------------------------------------------------------------------------------------------------------------------------
_seq = [0]


def ev(type_, data):
    _seq[0] += 1
    e = {"v": "1.0", "seq": _seq[0], "ts": "2026-11-02T10:00:00Z", "type": type_, "data": data}
    validate_event(e)  # nur vertragsgueltige Ereignisse
    return {"ev": e}


def level(v, active=True):
    return ev("voice_level", {"level": v, "active": active})


def fake_events(*commands):
    """Echte Ereignisse des FakeUiBackend nach den Befehlen (ohne die Antworten)."""
    b = FakeUiBackend()
    for i, c in enumerate(commands):
        b.send({"v": "1.0", "id": f"c{i}", "type": c, "data": {}})
    return [{"ev": e} for e in b.events_since(0, 1000) if e["type"] in {"state", "voice_level", "hello"}]


def run(tmp_path, steps, **env):
    f = tmp_path / "scenario.json"
    f.write_text(json.dumps(steps), encoding="utf-8")
    out = subprocess.run([NODE, str(HARNESS), str(WEB), str(f)], capture_output=True, text=True, timeout=30, env={**os.environ, "JARVIS_HARNESS_REDUCED": "0", **env})
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def click(id_):
    return {"clickId": id_}


@needs_node
def test_microphone_command_is_never_sent_without_a_button_press(tmp_path):
    steps = [*fake_events("start_voice"), level(0.5), ev("state", {"state": "listening"}), {"effects": "off"}, {"toggle": True}, {"snap": "s"}]
    assert run(tmp_path, steps)["s"]["sent"] == []


@needs_node
def test_start_button_sends_exactly_start_voice_and_stop_button_stop_voice(tmp_path):
    snaps = run(tmp_path, [click("voice-start"), {"snap": "a"}, level(0.2), click("voice-stop"), {"snap": "b"}])
    assert [(c["type"], c["data"]) for c in snaps["a"]["sent"]] == [("start_voice", {})]
    assert [(c["type"], c["data"]) for c in snaps["b"]["sent"]] == [("start_voice", {}), ("stop_voice", {})]


@needs_node
def test_buttons_follow_the_reported_voice_state(tmp_path):
    snaps = run(tmp_path, [{"snap": "idle"}, level(0.3), {"snap": "on"}, level(0, active=False), {"snap": "off"},
                           ev("emergency", {"engaged": True, "reason": "t", "report": []}), {"snap": "emergency"}])
    p = lambda k, i: snaps[k]["props"][i]["disabled"]  # noqa: E731
    assert (p("idle", "voice-start"), p("idle", "voice-stop")) == (False, True)
    assert (p("on", "voice-start"), p("on", "voice-stop")) == (True, False)
    assert (p("off", "voice-start"), p("off", "voice-stop")) == (False, True)
    assert p("emergency", "voice-start") is True  # im Notaus kein Mikrofonstart (das Backend lehnt ihn ohnehin ab)


@needs_node
def test_meter_and_text_follow_voice_level_events(tmp_path):
    steps = [{"snap": "none"}]
    for i, v in enumerate((0.1, 0.8, 0.35)):
        steps += [level(v), {"snap": f"l{i}"}]
    snaps = run(tmp_path, steps)
    assert "kein Pegel" in snaps["none"]["text"]["voice-level-text"]
    assert [snaps[f"l{i}"]["props"]["voice-meter"]["value"] for i in range(3)] == [0.1, 0.8, 0.35]
    assert ["10 %" in snaps["l0"]["text"]["voice-level-text"], "80 %" in snaps["l1"]["text"]["voice-level-text"], "35 %" in snaps["l2"]["text"]["voice-level-text"]] == [True] * 3
    assert "an" in snaps["l1"]["text"]["voice-mic"]


@needs_node
def test_wave_is_redrawn_only_when_a_voice_level_event_arrives(tmp_path):
    frames = [16 * i for i in range(1, 40)]
    snaps = run(tmp_path, [level(0.4), {"snap": "a"}, {"frames": frames}, {"snap": "b"}, level(0.7), {"snap": "c"}])
    n = lambda k: len(snaps[k]["props"]["voice-wave"]["calls"])  # noqa: E731
    assert n("a") > 0
    assert n("b") == n("a")  # Zeitablauf allein bewegt die Welle nicht (keine erfundene Animation)
    assert n("c") > n("b")


@needs_node
def test_inactive_event_forces_level_zero_and_bad_levels_are_clamped(tmp_path):
    snaps = run(tmp_path, [level(0.9), level(0.9, active=False), {"snap": "off"}, ev("voice_level", {"level": 1, "active": True}), {"snap": "max"}])
    assert snaps["off"]["props"]["voice-meter"]["value"] == 0 and "aus" in snaps["off"]["text"]["voice-mic"]
    assert snaps["max"]["props"]["voice-meter"]["value"] == 1
    raw = {"ev": {"v": "1.0", "seq": 99, "ts": "x", "type": "voice_level", "data": {"level": 7, "active": True}}}  # kaputtes Ereignis: nie ueber 1
    snaps = run(tmp_path, [raw, {"snap": "s"}])
    assert snaps["s"]["props"]["voice-meter"]["value"] == 1


@needs_node
def test_connection_loss_resets_level_and_microphone_display(tmp_path):
    snaps = run(tmp_path, [level(0.6), {"disconnect": True}, {"snap": "lost"}])
    assert snaps["lost"]["props"]["voice-meter"]["value"] == 0
    assert "kein Pegel" in snaps["lost"]["text"]["voice-level-text"] and "unbekannt" in snaps["lost"]["text"]["voice-mic"]
    assert snaps["lost"]["props"]["voice-start"]["disabled"] is False  # der Mensch kann es erneut versuchen; das Backend entscheidet


@needs_node
@pytest.mark.parametrize("state,word", [("listening", "hoert zu"), ("processing", "verarbeitet"), ("speaking", "spricht")])
def test_voice_state_shows_listening_processing_speaking(tmp_path, state, word):
    snaps = run(tmp_path, [{"snap": "start"}, ev("state", {"state": state}), {"snap": "s"}])
    assert word not in snaps["start"]["text"]["voice-state"]
    assert word in snaps["s"]["text"]["voice-state"] and snaps["s"]["props"]["voice-state"]["dataset"].get("state", state) == state


@needs_node
@pytest.mark.parametrize("state", ["ready", "awaiting_confirmation", "error"])
def test_other_states_show_no_voice_state(tmp_path, state):
    snaps = run(tmp_path, [ev("state", {"state": "speaking"}), ev("state", {"state": state}), {"snap": "s"}])
    t = snaps["s"]["text"]["voice-state"]
    assert not any(w in t for w in ("hoert zu", "verarbeitet", "spricht"))


@needs_node
def test_flow_against_fake_backend_events(tmp_path):
    start = fake_events("start_voice")
    stop = fake_events("start_voice", "stop_voice")
    snaps = run(tmp_path, [*start, {"snap": "listening"}, level(0.55), {"snap": "level"}, *stop[len(start):], {"snap": "stopped"}])
    assert "hoert zu" in snaps["listening"]["text"]["voice-state"] and "an" in snaps["listening"]["text"]["voice-mic"]
    assert snaps["level"]["props"]["voice-meter"]["value"] == 0.55
    assert snaps["stopped"]["props"]["voice-meter"]["value"] == 0 and "aus" in snaps["stopped"]["text"]["voice-mic"]
    assert "hoert zu" not in snaps["stopped"]["text"]["voice-state"]
    assert snaps["stopped"]["sent"] == []


@needs_node
@pytest.mark.parametrize("env,effects", [({}, "off"), ({"JARVIS_HARNESS_REDUCED": "1"}, "off")])
def test_status_stays_readable_with_effects_off(tmp_path, env, effects):
    steps = [{"effects": "off"}, ev("state", {"state": "listening"}), level(0.62), {"frames": [16, 32, 48]}, {"snap": "s"}]
    s = run(tmp_path, steps, **env)["s"]
    assert s["effects"] == effects
    assert "hoert zu" in s["text"]["voice-state"] and "62 %" in s["text"]["voice-level-text"] and "an" in s["text"]["voice-mic"]
    assert s["props"]["voice-meter"]["value"] == 0.62
    assert s["sent"] == []
