"""NEXUS Premium V2: Systemstatus-Panel und Zustandsanzeige des Orbs. Nur echte Backend-Ereignisse; ohne Meldung steht "unbekannt" bzw. 0, nie ein erfundener Wert.
DOM-Ersatz in Node (tests/support/cc_dom_harness.js), kein Browser, kein Netzwerk; die echten Browser-Pruefungen stehen in test_control_center_e2e_browser.py."""
import re

import pytest

from test_control_center_core import WEB, ev, pytestmark_node, run

STATUS_IDS = ("st-conn", "st-state", "st-emergency", "st-voice", "st-tasks", "st-agents", "st-results", "st-confirm", "st-effects", "st-seq")


def test_status_panel_and_orb_label_exist_without_inline_style_or_external_parts():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for i in (*STATUS_IDS, "status-panel", "orb-state", "brand"):
        assert f'id="{i}"' in html, i
    assert "style=" not in html and 'width="640"' in html
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    for state in ("ready", "listening", "processing", "speaking", "awaiting_confirmation", "error", "emergency"):
        assert f'body[data-state="{state}"]' in css, state                  # eine Farbe je Zustand auch in der Oberflaeche
    assert "@keyframes" not in css or "prefers-reduced-motion" in css        # Bewegung nur mit Rueckfallweg


def test_app_has_no_fake_data_in_production_code():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    m = re.search(r"function renderStatus\(.*?\n\}", js, re.S)
    assert m
    body = m.group(0)
    for forbidden in ("send(", "fetch(", "Math.random", "Date.now"):
        assert forbidden not in body, forbidden
    assert "Math.random" not in js                                         # keine erfundenen Daten (der Staub des Kerns ist deterministisch)


@pytestmark_node
def test_status_shows_unknown_before_any_event_and_follows_events(tmp_path):
    snaps = run(tmp_path, [{"snap": "start"},
                           ev("state", {"state": "listening"}), ev("voice_level", {"level": 0.4, "active": True}), {"snap": "voice"},
                           ev("activity", {"items": [{"kind": "agent_task", "id": "t1", "title": "A", "status": "RUNNING", "note": "", "cancellable": True},
                                                     {"kind": "agent_task", "id": "t2", "title": "B", "status": "RUNNING", "note": "", "cancellable": True}], "problems": [], "inactive": []}),
                           ev("routing", {"task_id": "t1", "agent": "research", "source": "rules", "reason": "x"}), {"snap": "tasks"},
                           ev("emergency", {"engaged": True, "reason": "test", "report": []}), {"snap": "emergency"}])
    t = snaps["start"]["text"]
    assert t["st-voice"] == "unbekannt" and t["st-state"] != "bereit" and t["st-tasks"].startswith("0 aktiv") and t["st-emergency"] == "nicht aktiv"
    v = snaps["voice"]["text"]
    assert v["st-voice"] == "an" and v["st-state"] == "hoert zu" and v["orb-state"] == "hoert zu" and int(v["st-seq"]) >= 2
    k = snaps["tasks"]["text"]
    assert k["st-tasks"] == "2 aktiv, 2 bekannt" and k["st-agents"] == "1 aktiv"
    e = snaps["emergency"]["text"]
    assert e["st-emergency"] == "AKTIV" and e["st-state"] == "NOTAUS" and e["orb-state"] == "NOTAUS"
    assert snaps["emergency"]["props"]["voice-start"]["disabled"] is True


@pytestmark_node
def test_connection_loss_resets_status_to_unknown(tmp_path):
    snaps = run(tmp_path, [ev("state", {"state": "speaking"}), ev("voice_level", {"level": 0.2, "active": True}), {"disconnect": True}, {"snap": "lost"}])
    t = snaps["lost"]["text"]
    assert t["st-conn"] == "GETRENNT" and t["st-voice"] == "unbekannt" and t["orb-state"] == "kein Zustand gemeldet"


@pytestmark_node
def test_full_core_uses_depth_layers_and_the_2d_fallback_is_flat(tmp_path):
    full = run(tmp_path, [ev("state", {"state": "processing"}), {"frames": [100, 200]}, {"effects": "full"}, {"frames": [300, 400]}, {"snap": "f"}], JARVIS_HARNESS_REDUCED="0")
    calls = full["f"]["props"]["orb"]["calls"]
    assert "clip" in calls and "createRadialGradient" in calls and "ellipse" in calls  # Tiefe: Kugel, Nebel, Gitter, Randlicht
    flat = run(tmp_path, [ev("state", {"state": "processing"}), {"effects": "off"}, {"snap": "o"}], JARVIS_HARNESS_REDUCED="0")
    assert flat["o"]["effects"] == "off"
    all_calls = flat["o"]["props"]["orb"]["calls"]
    last = len(all_calls) - 1 - all_calls[::-1].index("clearRect")           # nur das letzte Bild zaehlt (davor wurde noch voll gezeichnet)
    off_calls = all_calls[last:]
    assert "clip" not in off_calls                                          # 2D-Fallback: flache Scheibe, keine Nebel-/Gitterschichten
    assert "arc" in off_calls and "fill" in off_calls
