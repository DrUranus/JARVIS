"""Windows-Smoke des Control Centers (Schritt cc-windows-smoke): echter Server mit echtem Backend (`build_core`, Mock-LLM), nur Loopback-Sockets,
ohne Browser und ohne Fenster. Darf nicht per Skip entfallen: keine Skip-Markierung in dieser Datei (Strukturtest unten).
Ablauf: starten -> Token und Origin erzwingen -> Ereignisstrom lesen -> Befehl und Antwort pruefen -> sauber beenden."""
import http.client
import json
import socket
from pathlib import Path

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.control_center.launcher import build_server
from jarvis.ui_contract import validate_event
from test_computer_integration import env_for


def _env(tmp_path):
    return env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true",
                   JARVIS_CONTROL_CENTER_ENABLED="true", JARVIS_ASSISTANT_CONFIRMATION_TIMEOUT_SECONDS="1")


def _http(srv, method, path, *, token=True, origin=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    headers = {"Host": f"127.0.0.1:{srv.port}"}
    if origin:
        headers["Origin"] = origin
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        path += ("&" if "?" in path else "?") + "t=" + srv.token
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _read_events(srv, want, since=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    try:
        conn.request("GET", f"/events?t={srv.token}" + (f"&since={since}" if since is not None else ""), headers={"Host": f"127.0.0.1:{srv.port}"})
        resp = conn.getresponse()
        assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/event-stream")
        events, buf = [], b""
        while len(events) < want:
            line = resp.fp.readline()
            if not line:
                break
            buf += line
            if buf.endswith(b"\n\n"):
                events += [json.loads(x[6:]) for x in buf.decode().splitlines() if x.startswith("data: ")]
                buf = b""
        return events
    finally:
        conn.close()


def test_server_smoke_start_token_origin_stream_command_stop(tmp_path):
    core = build_core(load_settings(env=_env(tmp_path)))
    srv = build_server(load_settings(env=_env(tmp_path)), core)
    assert srv.port is None                                                   # vor dem Start lauscht nichts
    srv.start()
    port = srv.port
    origin = f"http://127.0.0.1:{port}"
    try:
        assert srv.host == "127.0.0.1" and srv.url.startswith(f"http://127.0.0.1:{port}/")
        # Token wird erzwungen
        for bad in (False, "falsch"):
            status, body = _http(srv, "GET", "/", token=False) if bad is False else _http(srv, "GET", "/?t=falsch", token=False)
            assert status == 401 and b"JARVIS" not in body
        assert _http(srv, "GET", "/")[0] == 200
        # Origin wird erzwungen (POST ohne und mit fremdem Origin)
        cmd = json.dumps({"v": "1.0", "id": "s1", "type": "submit_text", "data": {"text": "hallo"}})
        assert _http(srv, "POST", "/command", body=cmd)[0] == 403
        assert _http(srv, "POST", "/command", body=cmd, origin="http://evil.example")[0] == 403
        assert _http(srv, "POST", "/command", body=cmd, origin=origin, token=False)[0] == 401
        # Ereignisstrom: beginnt mit hello, Vertrag gueltig, Folgenummern aufsteigend
        events = _read_events(srv, 1)
        assert events and events[0]["type"] == "hello"
        for e in events:
            validate_event(e)
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(seqs)
        # Befehl und Antwort (Ack nach Vertrag), Ereignis im Strom
        status, body = _http(srv, "POST", "/command", body=cmd, origin=origin)
        ack = json.loads(body)
        assert status == 200 and ack["type"] == "ack" and ack["data"]["ok"] is True and ack["data"]["id"] == "s1"
        validate_event(ack)
        later = _read_events(srv, 4, since=seqs[-1])
        assert any(e["type"] == "chat" for e in later)
        # ungueltiger Befehl wird mit ack ok=false abgewiesen
        status, body = _http(srv, "POST", "/command", body='{"v":"1.0","id":"s2","type":"run_tool","data":{}}', origin=origin)
        assert status == 400 and json.loads(body)["data"]["ok"] is False
    finally:
        srv.stop()
    # sauber beendet: Port geschlossen, zweites Beenden ist harmlos
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
    srv.stop()


def test_smoke_file_has_no_skip_markers():
    text = Path(__file__).read_text(encoding="utf-8")
    needles = ["pytest.mark." + "skip", "pytest." + "skip(", "importor" + "skip", "skip" + "if("]
    assert not [n for n in needles if n in text]
