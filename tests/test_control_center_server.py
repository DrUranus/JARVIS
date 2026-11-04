"""Control-Center-Server (Schritt cc-shell): nur Loopback, Token, Host/Origin, Vertrag, Limits. Nur Loopback-Sockets, kein externes Netzwerk."""
import http.client
import json
import socket
import threading

import pytest

from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend, validate_event
from jarvis.ui_contract.schema import MAX_COMMAND_BYTES


@pytest.fixture
def srv():
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    s.start()
    yield s
    s.stop()


def request(srv, method, path, *, body=None, headers=None, token=True, host=None, origin=None, ctype="application/json"):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{srv.port}"}
    if origin:
        h["Origin"] = origin
    if body is not None:
        h["Content-Type"] = ctype
    h.update(headers or {})
    if token is True:
        path += ("&" if "?" in path else "?") + "t=" + srv.token
    elif token:
        path += ("&" if "?" in path else "?") + "t=" + token
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, dict(resp.getheaders()), data


def cmd(cid="c1", type_="submit_text", data=None):
    return json.dumps({"v": "1.0", "id": cid, "type": type_, "data": data if data is not None else {"text": "hallo"}})


def good_origin(srv):
    return f"http://127.0.0.1:{srv.port}"


# ---- Start nur auf ausdruecklichen Befehl, nur Loopback -----------------------------------------------------------------------------------
def test_nothing_listens_before_start_and_import_has_no_side_effects():
    before = threading.active_count()
    s = ControlCenterServer(FakeUiBackend())
    assert s.port is None and threading.active_count() == before
    with pytest.raises(RuntimeError):
        s.url


def test_binds_only_to_loopback(srv):
    assert srv.host == "127.0.0.1" and srv._httpd.server_address[0] == "127.0.0.1"
    assert srv.url.startswith("http://127.0.0.1:") and srv.token in srv.url


@pytest.mark.parametrize("host", ["0.0.0.0", "", "::", "192.168.1.5", "localhost", "example.com"])
def test_non_loopback_bind_refused(host):
    with pytest.raises(ValueError):
        ControlCenterServer(FakeUiBackend(), host=host)


def test_weak_token_refused():
    with pytest.raises(ValueError):
        ControlCenterServer(FakeUiBackend(), token="abc")


def test_tokens_are_random():
    assert ControlCenterServer(FakeUiBackend()).token != ControlCenterServer(FakeUiBackend()).token


def test_double_start_refused(srv):
    with pytest.raises(RuntimeError):
        srv.start()


def test_stop_closes_port():
    s = ControlCenterServer(FakeUiBackend())
    s.start()
    port = s.port
    s.stop()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


# ---- Token ------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/index.html", "/app.js", "/styles.css", "/events", "/command", "/nope", "/../server.py"])
@pytest.mark.parametrize("token", [False, "", "wrong", "x" * 43])
def test_no_valid_token_gets_nothing(srv, path, token):
    status, _, body = request(srv, "GET", path, token=token)
    assert status == 401 and b"JARVIS" not in body and b"function" not in body


def test_post_without_token_never_reaches_backend(srv):
    status, _, _ = request(srv, "POST", "/command", body=cmd(), token=False, origin=good_origin(srv))
    assert status == 401
    assert not [e for e in srv.backend.events_since(0) if e["type"] == "chat"]


def test_token_in_header_is_accepted(srv):
    status, _, _ = request(srv, "GET", "/app.js", token=False, headers={"X-JARVIS-Token": srv.token})
    assert status == 200


# ---- Host / Origin -----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["evil.example", "evil.example:80", "127.0.0.1", "127.0.0.1:1", "0.0.0.0", "[::1]"])
def test_foreign_host_rejected(srv, host):
    status, _, _ = request(srv, "GET", "/", host=host)
    assert status == 403


def test_localhost_host_allowed(srv):
    status, _, _ = request(srv, "GET", "/", host=f"localhost:{srv.port}")
    assert status == 200


@pytest.mark.parametrize("origin", ["http://evil.example", "https://127.0.0.1:%d", "http://127.0.0.1:1", "null", "http://127.0.0.1.evil.example", ""])
def test_foreign_origin_rejected_on_post_and_get(srv, origin):
    origin = origin % srv.port if "%d" in origin else origin
    for method, path, body in (("POST", "/command", cmd()), ("GET", "/events?since=0", None), ("GET", "/", None)):
        status, _, _ = request(srv, method, path, body=body, headers={"Origin": origin})
        assert status == 403, (method, path, origin)
    assert not [e for e in srv.backend.events_since(0) if e["type"] == "chat"]


def test_post_requires_origin(srv):
    status, _, _ = request(srv, "POST", "/command", body=cmd())
    assert status == 403


def test_post_requires_json_content_type(srv):
    status, _, _ = request(srv, "POST", "/command", body=cmd(), origin=good_origin(srv), ctype="text/plain")
    assert status == 415


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_other_methods_rejected(srv, method):
    status, headers, _ = request(srv, method, "/command", body="{}", origin=good_origin(srv))
    assert status == 405 and "Access-Control-Allow-Origin" not in headers


def test_no_cors_headers(srv):
    _, headers, _ = request(srv, "GET", "/app.js")
    assert not any(k.lower().startswith("access-control") for k in headers)


# ---- Befehle ueber den Vertrag -----------------------------------------------------------------------------------------------------------
def test_valid_command_goes_through_contract(srv):
    status, _, body = request(srv, "POST", "/command", body=cmd(), origin=good_origin(srv))
    ack = json.loads(body)
    assert status == 200 and ack["type"] == "ack" and ack["data"]["ok"] is True and ack["data"]["id"] == "c1"
    validate_event(ack)
    assert any(e["type"] == "chat" and e["data"]["text"] == "hallo" for e in srv.backend.events_since(0))


@pytest.mark.parametrize("raw", ["not json", "[]", "{}", '{"v":"1.0","id":"c","type":"run_tool","data":{}}', '{"v":"2.0","id":"c","type":"submit_text","data":{"text":"x"}}',
                                 '{"v":"1.0","id":"c","type":"submit_text","data":{"text":"x"},"extra":1}', '{"v":"1.0","id":"c","type":"submit_text","data":{"text":NaN}}',
                                 '{"v":"1.0","id":"c","type":"grant_permission","data":{"tool":"shell"}}'])
def test_invalid_commands_rejected_with_ack_false(srv, raw):
    status, _, body = request(srv, "POST", "/command", body=raw, origin=good_origin(srv))
    ack = json.loads(body)
    assert status == 400 and ack["data"]["ok"] is False and ack["data"]["code"] == "invalid_command"
    assert not [e for e in srv.backend.events_since(0) if e["type"] == "chat"]


def test_oversized_command_rejected_before_parsing(srv):
    big = cmd(data={"text": "a" * (MAX_COMMAND_BYTES + 10)})
    status, _, _ = request(srv, "POST", "/command", body=big, origin=good_origin(srv))
    assert status == 413
    assert not [e for e in srv.backend.events_since(0) if e["type"] == "chat"]


def test_lying_content_length_cannot_exceed_limit(srv):
    s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    s.sendall((f"POST /command?t={srv.token} HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\nOrigin: {good_origin(srv)}\r\nContent-Type: application/json\r\n"
               f"Content-Length: 999999999\r\n\r\n").encode())
    assert s.recv(100).split()[1] == b"413"
    s.close()


def test_missing_or_bad_content_length(srv):
    for cl in ("-5", "abc"):
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        s.sendall((f"POST /command?t={srv.token} HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\nOrigin: {good_origin(srv)}\r\nContent-Type: application/json\r\n"
                   f"Content-Length: {cl}\r\n\r\n").encode())
        assert s.recv(100).split()[1] in (b"400", b"411")
        s.close()


def test_emergency_stop_works_and_blocks_other_commands(srv):
    s1, _, b1 = request(srv, "POST", "/command", body=cmd("e1", "emergency_stop", {}), origin=good_origin(srv))
    assert json.loads(b1)["data"]["ok"] is True
    _, _, b2 = request(srv, "POST", "/command", body=cmd("c2"), origin=good_origin(srv))
    assert json.loads(b2)["data"]["code"] == "emergency"


def test_ui_has_no_command_for_rights(srv):
    from jarvis.ui_contract import COMMAND_TYPES
    assert not [c for c in COMMAND_TYPES if any(w in c for w in ("grant", "permission", "tool", "rule", "mode"))]


# ---- Ereignisstrom (SSE) ----------------------------------------------------------------------------------------------------------------
def read_sse(srv, *, path="/events", headers=None, want=4, timeout=5):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=timeout)
    h = {"Host": f"127.0.0.1:{srv.port}"}
    h.update(headers or {})
    conn.request("GET", path + ("&" if "?" in path else "?") + "t=" + srv.token, headers=h)
    resp = conn.getresponse()
    events = []
    if resp.status != 200:
        conn.close()
        return resp.status, resp.getheader("Content-Type"), events
    buf = b""
    while len(events) < want:
        chunk = resp.fp.readline()
        if not chunk:
            break
        buf += chunk
        if buf.endswith(b"\n\n"):
            for line in buf.decode().splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
            buf = b""
    conn.close()
    return resp.status, resp.getheader("Content-Type"), events


def test_sse_starts_with_snapshot_hello_first(srv):
    status, ctype, events = read_sse(srv, want=4)
    assert status == 200 and ctype.startswith("text/event-stream")
    assert events[0]["type"] == "hello"
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    for e in events:
        validate_event(e)


def test_sse_delivers_new_events_and_reconnect_replays(srv):
    _, _, first = read_sse(srv, want=4)
    last = first[-1]["seq"]
    request(srv, "POST", "/command", body=cmd(), origin=good_origin(srv))
    _, _, more = read_sse(srv, path=f"/events?since={last}", want=2)
    assert more and all(e["seq"] > last for e in more) and any(e["type"] == "chat" for e in more)
    _, _, via_header = read_sse(srv, headers={"Last-Event-ID": str(last)}, want=2)
    assert via_header and all(e["seq"] > last for e in via_header)


def test_sse_bad_since_rejected(srv):
    for since in ("abc", "-1", "99999999999999999999"):
        status, _, _ = read_sse(srv, path=f"/events?since={since}")
        assert status == 400


def test_client_limit(srv):
    srv.max_clients = 1
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", f"/events?t={srv.token}", headers={"Host": f"127.0.0.1:{srv.port}"})
    r = conn.getresponse()
    r.fp.readline()
    status, _, _ = read_sse(srv)
    assert status == 503
    conn.close()


def test_detach_when_last_client_leaves():
    backend = FakeUiBackend()
    s = ControlCenterServer(backend, poll_interval=0.02)
    s.start()
    try:
        backend.send(json.loads(cmd("c1", "submit_text", {"text": "!confirm"})))
        read_sse(s, want=1)
        deadline = threading.Event()
        for _ in range(100):
            if any(e["type"] == "confirmation_closed" and e["data"]["outcome"] == "cancelled" for e in backend.events_since(0, 1000)):
                break
            deadline.wait(0.05)
        assert any(e["type"] == "confirmation_closed" and e["data"]["outcome"] == "cancelled" for e in backend.events_since(0, 1000))
    finally:
        s.stop()


# ---- Antwort-Header / CSP ----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/app.js", "/styles.css"])
def test_security_headers_and_csp(srv, path):
    status, headers, _ = request(srv, "GET", path)
    assert status == 200
    csp = headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "connect-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "http:" not in csp and "https:" not in csp and "*" not in csp
    assert headers["X-Content-Type-Options"] == "nosniff" and headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in csp


def test_index_carries_token_for_assets_only_when_authorised(srv):
    _, _, body = request(srv, "GET", "/")
    assert srv.token.encode() in body and b"__TOKEN__" not in body


def test_error_responses_leak_no_internal_details(srv):
    status, _, body = request(srv, "GET", "/nope")
    assert status == 404 and b"Traceback" not in body and b"/home" not in body
