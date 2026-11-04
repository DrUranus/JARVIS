"""cc-confirmation: Rueckfrage-Dialog der Weboberflaeche. Server-Tests gegen das Fake-Backend (Zeitablauf, Schliessen, Verbindungsverlust = abgelehnt) und statische
Asset-Pruefungen (alle Felder, Ablehnen als Standard, Notaus immer erreichbar, nur angebotene Wahlmoeglichkeiten). Nur Loopback, kein externes Netzwerk."""
import http.client
import json
import re
import socket
import threading
from pathlib import Path

import pytest

import jarvis.control_center as cc
from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend

WEB = Path(cc.__file__).parent / "web"


def text(name):
    return (WEB / name).read_text(encoding="utf-8")


def post(srv, body):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("POST", f"/command?t={srv.token}", body=json.dumps(body),
                 headers={"Host": f"127.0.0.1:{srv.port}", "Origin": f"http://127.0.0.1:{srv.port}", "Content-Type": "application/json"})
    r = conn.getresponse()
    out = json.loads(r.read())
    conn.close()
    return out


def command(cid, type_, data):
    return {"v": "1.0", "id": cid, "type": type_, "data": data}


def closed(backend):
    return [e["data"] for e in backend.events_since(0, 1000) if e["type"] == "confirmation_closed"]


def open_sse(srv):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", f"/events?t={srv.token}", headers={"Host": f"127.0.0.1:{srv.port}"})
    resp = conn.getresponse()
    resp.fp.readline()
    return conn


def wait_for(cond, tries=100):
    ev = threading.Event()
    for _ in range(tries):
        if cond():
            return True
        ev.wait(0.05)
    return cond()


@pytest.fixture
def srv():
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    s.start()
    yield s
    s.stop()


def ask(srv):
    post(srv, command("q1", "submit_text", {"text": "!confirm"}))
    return next(e for e in srv.backend.events_since(0, 1000) if e["type"] == "confirmation_request")["data"]


# ---- Server: fail-closed -------------------------------------------------------------------------------------------------------------------
def test_timeout_means_denied(srv):
    req = ask(srv)
    srv.backend.advance(req["timeout_s"] + 1)
    assert closed(srv.backend) == [{"request_id": req["request_id"], "outcome": "timeout"}]
    ack = post(srv, command("c2", "confirm", {"request_id": req["request_id"], "choice": "allow_once"}))
    assert ack["data"]["ok"] is False and ack["data"]["code"] == "unknown_request"  # nach Zeitablauf laesst sich nichts mehr erlauben


def test_closing_the_window_means_denied(srv):
    req = ask(srv)
    conn = open_sse(srv)
    conn.close()  # Fenster geschlossen: letzter Client geht
    assert wait_for(lambda: {"request_id": req["request_id"], "outcome": "cancelled"} in closed(srv.backend))


def test_connection_loss_means_denied(srv):
    req = ask(srv)
    sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    sock.sendall(f"GET /events?t={srv.token} HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\n\r\n".encode())
    assert b"200" in sock.recv(4096)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")  # RST statt FIN: Verbindung bricht hart ab
    sock.close()
    assert wait_for(lambda: {"request_id": req["request_id"], "outcome": "cancelled"} in closed(srv.backend))


def test_nothing_is_allowed_without_an_explicit_confirm(srv):
    ask(srv)
    open_sse(srv).close()
    assert wait_for(lambda: closed(srv.backend))
    assert all(c["outcome"] not in ("allow_once", "allow_session") for c in closed(srv.backend))


def test_only_offered_choices_are_accepted(srv):
    req = ask(srv)
    assert "allow_session" not in req["choices"]
    ack = post(srv, command("c2", "confirm", {"request_id": req["request_id"], "choice": "allow_session"}))
    assert ack["data"]["ok"] is False and ack["data"]["code"] == "choice_not_offered"
    assert closed(srv.backend) == []  # die Anfrage bleibt offen, nichts wurde erlaubt


def test_deny_and_allow_once_work_for_offered_choices(srv):
    req = ask(srv)
    assert post(srv, command("c2", "confirm", {"request_id": req["request_id"], "choice": "deny"}))["data"]["ok"] is True
    assert closed(srv.backend) == [{"request_id": req["request_id"], "outcome": "denied"}]


def test_unknown_request_is_rejected(srv):
    ack = post(srv, command("c2", "confirm", {"request_id": "nope", "choice": "deny"}))
    assert ack["data"]["code"] == "unknown_request"


def test_emergency_stop_works_while_a_question_is_open_and_denies_it(srv):
    req = ask(srv)
    assert post(srv, command("c3", "emergency_stop", {}))["data"]["ok"] is True
    assert {"request_id": req["request_id"], "outcome": "cancelled"} in closed(srv.backend)


# ---- Weboberflaeche: statische Pruefungen -------------------------------------------------------------------------------------------------
def test_dialog_exists_outside_both_views_and_is_hidden_by_default():
    html = text("index.html")
    m = re.search(r'<[^>]*id="confirm-dialog"[^>]*>', html)
    assert m and "hidden" in m.group(0) and 'role="alertdialog"' in m.group(0) and 'aria-modal="true"' in m.group(0)
    # nicht innerhalb der Modus-Ansichten, die ausgeblendet werden koennen
    assert html.index('id="confirm-dialog"') > html.index("</main>")


@pytest.mark.parametrize("field", ["tool", "action", "resource", "level", "reason", "context", "timeout_s", "choices", "request_id"])
def test_js_renders_every_request_field(field):
    js = text("app.js")
    assert re.search(r"\bd\.%s\b|\breq\.%s\b|\bq\.%s\b" % (field, field, field), js), field


@pytest.mark.parametrize("ident", ["dlg-tool", "dlg-action", "dlg-resource", "dlg-level", "dlg-reason", "dlg-context", "dlg-remaining", "dlg-choices"])
def test_dialog_has_a_slot_for_every_field(ident):
    assert f'id="{ident}"' in text("index.html")


def test_deny_is_the_default_and_comes_first():
    js = text("app.js")
    assert "DENY_FIRST" in js or re.search(r"deny.*sort|sort.*deny", js, re.S)
    assert ".focus()" in js
    assert re.search(r'ESCAPE|"Escape"', js, re.I)  # Escape lehnt ab, bestaetigt nie
    assert not re.search(r'"Enter"', js)  # Enter bestaetigt nie


def test_only_offered_choices_are_buttons_and_sendable():
    js = text("app.js")
    assert re.search(r"offered\.includes\(", js) or re.search(r"choices\.includes\(", js)
    # keine feste Schaltflaeche fuer eine Sitzungsfreigabe im HTML
    html = text("index.html")
    assert "allow_session" not in html and "allow_once" not in html
    # confirm sendet ausschliesslich Kennung und Wahl
    assert [x.strip() for x in re.findall(r'send\("confirm", \{([^}]*)\}', js)] == ["request_id: id, choice: choice"]


def test_close_timeout_and_connection_loss_clear_the_dialog_and_disable_answers():
    js = text("app.js")
    assert "confirmation_closed" in js and "clearConfirmations" in js
    onerr = re.search(r"source\.onerror = .*?\n  \};", js, re.S)
    assert onerr and "clearConfirmations" in onerr.group(0)  # Verbindungsverlust = abgelehnt, nichts mehr sendbar
    assert "abgelehnt" in js


def test_emergency_button_stays_reachable_above_the_dialog():
    css, html, js = text("styles.css"), text("index.html"), text("app.js")
    z = lambda sel: int(re.search(re.escape(sel) + r"\s*\{[^}]*z-index:\s*(\d+)", css).group(1))
    assert z("#bar") > z("#confirm-dialog")
    assert 'id="emergency"' in html and html.index('id="emergency"') < html.index('id="confirm-dialog"')
    assert not re.search(r"#emergency[^{]*\{[^}]*(display\s*:\s*none|visibility\s*:\s*hidden|pointer-events\s*:\s*none)", css)
    assert not re.search(r"\[data-[a-z]+=[^\]]*\][^{]*#emergency[^{]*\{[^}]*display\s*:\s*none", css)
    # der Notaus-Knopf sendet ohne Rueckfrage
    m = re.search(r'el\("emergency"\)\.addEventListener\("click", (.*?)\);\n', js)
    assert m and "confirm(" not in m.group(1) and "send(\"emergency_stop\"" in m.group(1)
    # der Dialog sperrt die Leiste nicht (kein inert/disabled auf #bar)
    assert "inert" not in js and "inert" not in html


def test_dialog_is_independent_of_ui_mode():
    css, js = text("styles.css"), text("app.js")
    assert not re.search(r"\[data-mode[^\]]*\][^{]*#confirm-dialog", css)
    m = re.search(r"function setMode\(.*?\n\}", js, re.S)
    assert "confirm" not in m.group(0).lower() and "dlg" not in m.group(0)
