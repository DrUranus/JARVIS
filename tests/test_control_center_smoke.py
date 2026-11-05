"""Windows-Smoke (cc-windows-smoke, B9): echter Control-Center-Server auf 127.0.0.1, ohne Browser und ohne Fenster.
Pflichttest fuer den Windows-Runner: keine Skips, kein Netzwerk ausser Loopback, kein Tk, kein Node."""
import http.client
import json
import socket
import threading

from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend, validate_event


def _req(srv, method, path, *, body=None, token=True, origin=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
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


def _sse(srv, *, since=None, want=3):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    path = "/events?t=" + srv.token + (f"&since={since}" if since is not None else "")
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{srv.port}"})
    resp = conn.getresponse()
    events, buf = [], b""
    try:
        assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/event-stream")
        while len(events) < want:
            line = resp.fp.readline()
            if not line:
                break
            buf += line
            if buf.endswith(b"\n\n"):
                events += [json.loads(x[6:]) for x in buf.decode().splitlines() if x.startswith("data: ")]
                buf = b""
    finally:
        conn.close()
    return events


def test_windows_smoke_server_lifecycle_token_origin_stream_command():
    threads_before = threading.active_count()
    srv = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    assert srv.port is None                                   # vor dem Start lauscht nichts
    srv.start()
    port = srv.port
    try:
        origin = f"http://127.0.0.1:{port}"
        assert srv.host == "127.0.0.1"
        # Token wird erzwungen
        for tok in (False, "falsch"):
            path = "/events" + ("?t=" + tok if tok else "")
            assert _req(srv, "GET", path, token=False)[0] == 401
        assert _req(srv, "POST", "/command", body="{}", token=False, origin=origin)[0] == 401
        # Origin wird erzwungen
        cmd = json.dumps({"v": "1.0", "id": "s1", "type": "submit_text", "data": {"text": "smoke"}})
        assert _req(srv, "POST", "/command", body=cmd)[0] == 403
        assert _req(srv, "POST", "/command", body=cmd, origin="http://evil.example")[0] == 403
        assert not [e for e in srv.backend.events_since(0) if e["type"] == "chat"]
        # Ereignisstrom: Schnappschuss beginnt mit hello, Vertrag gueltig
        first = _sse(srv, want=3)
        assert first[0]["type"] == "hello"
        for e in first:
            validate_event(e)
        # Befehl + Antwort
        status, body = _req(srv, "POST", "/command", body=cmd, origin=origin)
        ack = json.loads(body)
        assert status == 200 and ack["type"] == "ack" and ack["data"] == {**ack["data"], "ok": True, "id": "s1"}
        validate_event(ack)
        # Der Befehl erscheint im Ereignisstrom (Wiederaufnahme ab letzter Nummer)
        more = _sse(srv, since=first[-1]["seq"], want=2)
        assert any(e["type"] == "chat" and e["data"]["text"] == "smoke" for e in more)
    finally:
        srv.stop()
    # Sauber beendet: Port zu, Thread weg, erneutes stop() harmlos
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        closed = False
    except OSError:
        closed = True
    assert closed
    srv.stop()
    assert srv.port is not None and srv._httpd is None
    assert threading.active_count() <= threads_before
