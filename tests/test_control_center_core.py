"""cc-ai-core (Strang B, B2): animierter Kern der Weboberflaeche (Canvas 2D, Premium V2).
- Tabelle web/core_states.json: jeder Zustand des Vertrags ist abgebildet, alle Werte sind begrenzt, Farben passen zur Vorgabe.
- Assets: keine externen Ressourcen, prefers-reduced-motion wird beachtet, Effekte abschaltbar, Notaus sichtbar rot.
- Anzeige: nur ein vom Backend gemeldeter Zustand (DOM-Ersatz in Node, tests/support/cc_dom_harness.js). Kein externes Netzwerk."""
import colorsys
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
from jarvis.ui_contract.schema import STATES

WEB = Path(cc.__file__).parent / "web"
HARNESS = Path(__file__).parent / "support" / "cc_dom_harness.js"
NODE = shutil.which("node")
pytestmark_node = pytest.mark.skipif(NODE is None, reason="node fehlt: DOM-Pruefung nicht moeglich (ein uebersprungener Test gilt nicht als bestanden)")

# Grenzen (unabhaengig von app.js; app.js klemmt zusaetzlich auf dieselben Werte).
LIMITS = {"glow": (0.0, 1.0), "pulse_hz": (0.0, 2.0), "pulse_amp": (0.0, 0.08), "spin": (0.0, 2.0), "rings": (0, 3), "particles": (0, 24),
          "level_gain": (0.0, 0.2), "flash_hz": (0.0, 3.0)}
FIELDS = {"label", "color", *LIMITS}
# Farbton (Grad) je Zustand: ready gruen, listening blau, processing violett, speaking tuerkis, awaiting_confirmation goldgelb, error/emergency rot.
HUES = {"ready": (100, 150), "listening": (200, 230), "processing": (255, 285), "speaking": (165, 190), "awaiting_confirmation": (40, 52),
        "error": (-8, 8), "emergency": (-8, 8)}


def table():
    return json.loads((WEB / "core_states.json").read_text(encoding="utf-8"))


def hue(color):
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360, s, v


# ---- Tabelle ------------------------------------------------------------------------------------------------------------------------------
def test_table_maps_every_contract_state_and_nothing_else():
    t = table()
    assert set(t) == {"schema", "states", "neutral"}
    assert t["schema"] == 1
    assert list(t["states"]) == list(STATES)  # genau die Zustaende des Vertrags, in dieser Reihenfolge


@pytest.mark.parametrize("state", [*STATES, "neutral"])
def test_every_row_is_complete_and_bounded(state):
    t = table()
    row = t["neutral"] if state == "neutral" else t["states"][state]
    assert set(row) == FIELDS
    assert isinstance(row["label"], str) and 1 <= len(row["label"]) <= 40
    assert re.fullmatch(r"#[0-9a-f]{6}", row["color"])
    for key, (lo, hi) in LIMITS.items():
        v = row[key]
        assert isinstance(v, (int, float)) and not isinstance(v, bool), key
        assert lo <= v <= hi, (state, key, v)
    assert isinstance(row["rings"], int) and isinstance(row["particles"], int)


@pytest.mark.parametrize("state", STATES)
def test_colors_follow_the_specification(state):
    lo, hi = HUES[state]
    h, s, v = hue(table()["states"][state]["color"])
    h = h - 360 if lo < 0 and h > 180 else h  # Rot liegt um 0 Grad
    assert lo <= h <= hi, (state, h)
    assert s >= 0.55 and v >= 0.75, (state, s, v)  # kraeftig und hell genug


def test_emergency_is_visibly_red_and_stronger_than_error():
    t = table()["states"]
    assert t["emergency"]["glow"] >= t["error"]["glow"]
    assert t["emergency"]["flash_hz"] > 0  # Blinken nur im vollen Effektmodus (app.js), nie bei reduzierter Bewegung
    assert hue(t["emergency"]["color"])[1] >= 0.85


def test_neutral_look_is_grey_and_motionless():
    n = table()["neutral"]
    assert hue(n["color"])[1] <= 0.35
    assert n["pulse_amp"] == 0 and n["spin"] == 0 and n["rings"] == 0 and n["particles"] == 0 and n["flash_hz"] == 0 and n["level_gain"] == 0


def test_level_only_moves_listening_and_speaking():
    states = table()["states"]
    assert {k for k, v in states.items() if v["level_gain"] > 0} <= {"listening", "speaking"}


# ---- Assets ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["index.html", "app.js", "styles.css", "core_states.json"])
def test_no_external_resources(name):
    src = (WEB / name).read_text(encoding="utf-8")
    assert not re.search(r"(https?:)?//[A-Za-z0-9.-]+\.[a-z]{2,}", src.replace("</", "")), name
    assert "cdn" not in src.lower() and "three" not in src.lower().replace("three states", "")


def test_reduced_motion_is_honoured_and_effects_can_be_switched_off():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "(prefers-reduced-motion: reduce)" in js and "(prefers-reduced-motion: reduce)" in css
    m = re.search(r'<select id="effects"[^>]*>(.*?)</select>', html, re.S)
    assert m and re.findall(r'value="(\w+)"', m.group(1)) == ["full", "reduced", "off"]
    assert 'id="effects-note"' in html


def test_effects_switch_and_low_performance_are_purely_local():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    for fn in ("setEffects", "monitorFrame"):
        m = re.search(r"function " + fn + r"\(.*?\n\}", js, re.S)
        assert m, fn
        for forbidden in ("send(", "fetch(", "EventSource", "emergency", "confirm", "permission"):
            assert forbidden not in m.group(0), (fn, forbidden)


def test_app_never_invents_a_state():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<body[^>]*data-state="none"', html)
    assert "bereit" not in html
    # setState wird nur aus Backend-Ereignissen und beim Verbindungsverlust (null) aufgerufen, nie mit einem festen Zustand
    calls = re.findall(r"setState\(([^)]*)\)", js)
    allowed = ("state", "d.state", "null", "currentState", '"emergency"')  # "emergency" nur im Ereignis `emergency` (siehe unten)
    assert all(c.split(",")[0].strip() in allowed for c in calls if c), calls
    assert not re.search(r'setState\("(ready|listening|processing|speaking|awaiting_confirmation|error)"', js)
    assert 'setState("emergency"' in js  # nur im Ereignis `emergency` mit engaged == true


def test_emergency_is_red_in_css_and_button_stays_visible():
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    assert re.search(r'body\[data-state="emergency"\][^{]*\{[^}]*(#ff[0-3][0-9a-f]{3}|#[ef][0-9a-f]0{4}|red)', css, re.I)
    assert not re.search(r'data-state="emergency"\][^{]*#emergency[^{]*\{[^}]*display\s*:\s*none', css)


# ---- Server -----------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def srv():
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    s.start()
    yield s
    s.stop()


def get(srv, path, token=True):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", path + (f"?t={srv.token}" if token else ""), headers={"Host": f"127.0.0.1:{srv.port}"})
    r = conn.getresponse()
    out = (r.status, r.getheader("Content-Type"), r.read())
    conn.close()
    return out


def test_server_serves_the_table_only_with_token(srv):
    status, ctype, body = get(srv, "/core_states.json")
    assert status == 200 and ctype.startswith("application/json")
    assert json.loads(body) == table()
    status, _, body = get(srv, "/core_states.json", token=False)
    assert status == 401 and b"states" not in body


# ---- Anzeige (Node + DOM-Ersatz) ---------------------------------------------------------------------------------------------------------
_seq = [0]


def ev(type_, data):
    _seq[0] += 1
    return {"ev": {"v": "1.0", "seq": _seq[0], "ts": "2026-11-02T10:00:00Z", "type": type_, "data": data}}


def run(tmp_path, steps, **env):
    f = tmp_path / "scenario.json"
    f.write_text(json.dumps(steps), encoding="utf-8")
    full_env = {**os.environ, **env}
    out = subprocess.run([NODE, str(HARNESS), str(WEB), str(f)], capture_output=True, text=True, timeout=30, env=full_env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def uses(snap, color):
    r, g, b = rgb(color)
    return any(c.lower().startswith(("rgba(%d,%d,%d" % (r, g, b), "rgba(%d, %d, %d" % (r, g, b))) or c.lower() == color for c in snap["drawn"])


@pytestmark_node
def test_nothing_is_shown_until_the_backend_reports_a_state(tmp_path):
    snaps = run(tmp_path, [{"snap": "start"}, ev("chat", {"sender": "user", "text": "hallo"}), {"snap": "after_chat"},
                           ev("state", {"state": "listening"}), {"snap": "listening"}])
    assert snaps["start"]["state"] == "none" and snaps["after_chat"]["state"] == "none"
    assert snaps["start"]["text"]["state-label"] != "bereit" and "kein Zustand" in snaps["start"]["text"]["state-label"]
    n = table()["neutral"]["color"]
    assert uses(snaps["start"], n) and not uses(snaps["start"], table()["states"]["ready"]["color"])
    assert snaps["listening"]["state"] == "listening"


@pytestmark_node
@pytest.mark.parametrize("state", STATES)
def test_each_reported_state_is_drawn_with_its_table_color(tmp_path, state):
    steps = [{"snap": "x"}, ev("state", {"state": state}), {"snap": "s"}]
    snaps = run(tmp_path, steps)
    assert snaps["s"]["state"] == state
    assert uses(snaps["s"], table()["states"][state]["color"])
    assert table()["states"][state]["label"] in snaps["s"]["text"]["state-label"]


@pytestmark_node
def test_unknown_state_is_not_shown_and_connection_loss_clears_the_state(tmp_path):
    snaps = run(tmp_path, [ev("state", {"state": "processing"}), ev("state", {"state": "bogus"}), {"snap": "bogus"},
                           ev("state", {"state": "speaking"}), {"disconnect": True}, {"snap": "lost"}])
    assert snaps["bogus"]["state"] == "none"  # nichts erfinden, auch kein "error"
    assert snaps["lost"]["state"] == "none"  # nach Verbindungsverlust ist der letzte Zustand unbekannt


@pytestmark_node
def test_emergency_event_shows_emergency_and_it_is_not_invented_when_released(tmp_path):
    snaps = run(tmp_path, [ev("emergency", {"engaged": True, "reason": "test", "report": []}), {"snap": "on"},
                           ev("emergency", {"engaged": False, "reason": "", "report": []}), {"snap": "off"}])
    assert snaps["on"]["state"] == "emergency" and uses(snaps["on"], table()["states"]["emergency"]["color"])
    assert snaps["off"]["state"] == "emergency"  # bleibt, bis das Backend einen neuen `state` meldet (kein erfundenes "ready")


@pytestmark_node
def test_without_table_the_state_is_still_reported_but_drawn_neutral(tmp_path):
    snaps = run(tmp_path, [ev("state", {"state": "error"}), {"snap": "s"}], JARVIS_HARNESS_NO_TABLE="1")
    assert snaps["s"]["state"] == "error"
    assert "error" in snaps["s"]["text"]["state-label"].lower() or "Fehler" in snaps["s"]["text"]["state-label"]


@pytestmark_node
def test_reduced_motion_preference_forces_static_and_cannot_be_overridden(tmp_path):
    snaps = run(tmp_path, [{"snap": "a"}, {"effects": "full"}, {"snap": "b"}], JARVIS_HARNESS_REDUCED="1")
    assert snaps["a"]["effects"] == "off" and snaps["b"]["effects"] == "off"


@pytestmark_node
def test_effects_can_be_switched_and_low_performance_reduces_them(tmp_path):
    env = {"JARVIS_HARNESS_REDUCED": "0"}
    snaps = run(tmp_path, [{"snap": "start"}, {"effects": "reduced"}, {"snap": "r"}, {"effects": "off"}, {"snap": "o"}, {"effects": "full"}, {"snap": "f"}], **env)
    assert [snaps[k]["effects"] for k in ("start", "r", "o", "f")] == ["full", "reduced", "off", "full"]
    fast = [16 * i for i in range(1, 200)]
    snaps = run(tmp_path, [{"frames": fast}, {"snap": "fast"}], **env)
    assert snaps["fast"]["effects"] == "full"  # gute Leistung: nichts wird reduziert
    slow = [100 * i for i in range(1, 80)]
    snaps = run(tmp_path, [{"frames": slow}, {"snap": "slow"}], **env)
    assert snaps["slow"]["effects"] == "reduced"
    assert snaps["slow"]["text"]["effects-note"] != ""  # sichtbar erklaert
    snaps = run(tmp_path, [{"frames": slow}, {"effects": "full"}, {"snap": "again"}], **env)
    assert snaps["again"]["effects"] == "full"  # der Mensch kann zuruecksetzen


@pytestmark_node
def test_effects_and_state_send_no_commands(tmp_path):
    snaps = run(tmp_path, [ev("state", {"state": "listening"}), {"effects": "off"}, {"effects": "full"}, {"snap": "s"}], JARVIS_HARNESS_REDUCED="0")
    assert snaps["s"]["sent"] == []
