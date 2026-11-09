"""cc-dashboard (Strang B, B3): Aufgaben-/Agenten-Dashboard der Weboberflaeche.
- Server: activity, task_update, routing, result erreichen den Client live (SSE gegen FakeUiBackend); cancel liefert die echte Antwort des Backends.
- DOM: web/app.js laeuft unveraendert in Node mit einem DOM-Ersatz (tests/support/cc_dom_harness.js) und bekommt Vertragsereignisse; Anzeige und Abbrechen werden geprueft.
- Assets: Texte nie als HTML, Premium-V2-Layout, automatischer Wechsel nur bei belegbarer Komplexitaet.
Nur Loopback, kein externes Netzwerk."""
import http.client
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

import jarvis.control_center as cc
from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend

WEB = Path(cc.__file__).parent / "web"
HARNESS = Path(__file__).parent / "support" / "cc_dom_harness.js"
NODE = shutil.which("node")


def text(name):
    return (WEB / name).read_text(encoding="utf-8")


# ---- Server: Ereignisse live, cancel mit echter Antwort ---------------------------------------------------------------------------------------
def post(srv, body):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("POST", f"/command?t={srv.token}", body=json.dumps(body),
                 headers={"Host": f"127.0.0.1:{srv.port}", "Origin": f"http://127.0.0.1:{srv.port}", "Content-Type": "application/json"})
    out = json.loads(conn.getresponse().read())
    conn.close()
    return out


def command(cid, type_, data):
    return {"v": "1.0", "id": cid, "type": type_, "data": data}


@pytest.fixture
def srv():
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    s.start()
    yield s
    s.stop()


def read_events(srv, until, limit=60):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", f"/events?t={srv.token}", headers={"Host": f"127.0.0.1:{srv.port}"})
    resp = conn.getresponse()
    seen = []
    done = threading.Event()

    def pump():
        try:
            for raw in resp.fp:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    seen.append(json.loads(line[5:]))
                    if until(seen):
                        done.set()
                        return
        except OSError:
            pass
    t = threading.Thread(target=pump, daemon=True)
    t.start()
    return conn, seen, done


def test_dashboard_events_reach_the_client_live(srv):
    conn, seen, done = read_events(srv, lambda s: any(e["type"] == "result" for e in s))
    try:
        post(srv, command("a1", "submit_text", {"text": "!task"}))
        task = next(i for i in srv.backend.events_since(0, 100) if i["type"] == "activity" and i["data"]["items"])["data"]["items"][0]
        srv.backend._emit("routing", {"task_id": task["id"], "agent": "research", "source": "rules", "reason": "Schluesselwort"})
        srv.backend._emit("task_update", {"kind": "agent_task", "id": task["id"], "status": "SUCCEEDED", "detail": "fertig"})
        srv.backend._emit("result", {"task_id": task["id"], "summary": "Zusammenfassung", "artifacts": [{"name": "bericht.txt", "kind": "file", "ref": "bericht.txt"}]})
        assert done.wait(5)
    finally:
        conn.close()
    types = [e["type"] for e in seen]
    for t in ("activity", "routing", "task_update", "result"):
        assert t in types, t
    assert types.index("routing") < types.index("task_update") < types.index("result")
    assert [e["seq"] for e in seen] == sorted(e["seq"] for e in seen)


def test_cancel_returns_the_real_backend_answer(srv):
    post(srv, command("a1", "submit_text", {"text": "!task"}))
    task = next(i for i in srv.backend.events_since(0, 100) if i["type"] == "activity" and i["data"]["items"])["data"]["items"][0]
    refused = post(srv, command("c0", "cancel", {"kind": "agent_task", "id": "gibtsnicht"}))
    assert refused["data"]["ok"] is False and refused["data"]["code"] == "unknown_task"
    ok = post(srv, command("c1", "cancel", {"kind": "agent_task", "id": task["id"]}))
    assert ok["data"]["ok"] is True and ok["data"]["id"] == "c1"
    assert any(e["type"] == "task_update" and e["data"]["status"] == "CANCELLED" for e in srv.backend.events_since(0, 100))


# ---- Assets: nie HTML, Befehle, Layout ---------------------------------------------------------------------------------------------------------
def test_dashboard_texts_are_never_inserted_as_html():
    js = text("app.js")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "createContextualFragment", "DOMParser", "srcdoc", "href", ".src =", "setAttribute(\"on"):
        assert bad not in js, bad
    assert "createElement(\"a\")" not in js and "createElement(\"iframe\")" not in js and "createElement(\"img\")" not in js
    # Aufgaben, Agenten, Ergebnisse werden ausschliesslich ueber textContent gesetzt
    assert js.count("textContent") >= 20


def test_cancel_command_is_wired_with_contract_fields_only():
    js = text("app.js")
    assert re.search(r'send\("cancel",\s*\{\s*kind:\s*\w+(\.\w+)?,\s*id:\s*\w+(\.\w+)?\s*\}', js)
    assert "reset_emergency" not in js and "grant" not in js


def test_premium_v2_layout_agents_left_orb_center_tasks_right():
    html = text("index.html")
    order = [html.index(i) for i in ('id="agents-panel"', 'id="orb-mini"', 'id="tasks-panel"')]
    assert order == sorted(order)
    for i in ("task-list", "task-detail", "results-list", "agent-list"):
        assert f'id="{i}"' in html
    css = text("styles.css")
    assert re.search(r"#dashboard-view\s*\{[^}]*grid-template-columns", css)
    assert 'id="emergency"' in html and 'id="mode-toggle"' in html


def test_auto_switch_is_evidence_based_and_never_without_data():
    js = text("app.js")
    m = re.search(r"function maybeAutoSwitch\(.*?\n\}", js, re.S)
    assert m, "maybeAutoSwitch fehlt"
    body = m.group(0)
    assert "MIN_PLANNED_STEPS" in body and "MIN_AGENTS" in body and "manualMode" in body
    assert re.search(r"MIN_PLANNED_STEPS\s*=\s*3", js) and re.search(r"MIN_AGENTS\s*=\s*2", js)
    for forbidden in ("send(", "fetch(", "emergency", "permission", "confirm"):
        assert forbidden not in body, forbidden
    assert "complexity" not in js.lower() and "x0" not in js.lower()  # keine erfundenen X0-Daten


def test_docs_name_the_x0_data_gap():
    doc = (Path(cc.__file__).parents[3] / "docs" / "UI_CONTRACT.md").read_text(encoding="utf-8")
    assert "cc-dashboard" in doc and "Datenluecke" in doc and "X0" in doc


# ---- DOM-Verhalten (Node) ------------------------------------------------------------------------------------------------------------------------
pytestmark_node = pytest.mark.skipif(NODE is None, reason="Node.js nicht installiert (nur fuer den DOM-Test)")


def run_scenario(tmp_path, steps):
    f = tmp_path / "scenario.json"
    f.write_text(json.dumps(steps), encoding="utf-8")
    out = subprocess.run([NODE, str(HARNESS), str(WEB), str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


_seq = [0]


def ev(type_, data):
    _seq[0] += 1
    return {"ev": {"v": "1.0", "seq": _seq[0], "ts": "2026-11-02T10:00:00Z", "type": type_, "data": data}}


def item(i, kind="agent_task", status="RUNNING", cancellable=True, title="Aufgabe"):
    return {"kind": kind, "id": i, "title": title, "status": status, "note": "", "cancellable": cancellable}


def activity(*items):
    return ev("activity", {"items": list(items), "problems": [], "inactive": []})


@pytestmark_node
def test_dom_follows_activity_task_update_routing_and_result(tmp_path):
    hostile = "<img src=x onerror=alert(1)>"
    snaps = run_scenario(tmp_path, [
        activity(item("t1", title=hostile)),
        {"snap": "a"},
        ev("routing", {"task_id": "t1", "agent": "research", "source": "rules", "reason": "Schluesselwort"}),
        {"snap": "b"},
        ev("task_update", {"kind": "agent_task", "id": "t1", "status": "SUCCEEDED", "detail": "fertig"}),
        ev("result", {"task_id": "t1", "summary": "Das Ergebnis", "artifacts": [{"name": "bericht.txt", "kind": "file", "ref": "javascript:alert(1)"}]}),
        {"snap": "c"},
    ])
    a, b, c = snaps["a"], snaps["b"], snaps["c"]
    assert hostile in a["text"]["task-list"]  # als Text, unveraendert
    assert "research" not in a["text"]["agent-list"]
    assert "research" in b["text"]["agent-list"] and "Schluesselwort" in b["text"]["task-detail"] and "rules" in b["text"]["task-detail"]
    assert "SUCCEEDED" in c["text"]["task-list"] and "fertig" in c["text"]["task-detail"]
    assert "Das Ergebnis" in c["text"]["results-list"] and "bericht.txt" in c["text"]["results-list"] and "javascript:alert(1)" in c["text"]["results-list"]


@pytestmark_node
@pytest.mark.parametrize("ack,expected", [
    ({"ok": True, "code": "cancel_requested", "message": ""}, "Abbruch angefordert"),
    ({"ok": True, "code": "ok", "message": ""}, "abgebrochen"),
    ({"ok": False, "code": "not_cancellable", "message": "this work cannot be cancelled"}, "abgelehnt"),
])
def test_dom_cancel_shows_the_real_answer(tmp_path, ack, expected):
    snaps = run_scenario(tmp_path, [
        activity(item("t1")),
        {"ack": ack},
        {"click": {"id": "task-list", "text": "Abbrechen"}},
        {"snap": "s"},
    ])
    s = snaps["s"]
    assert [c for c in s["sent"] if c["type"] == "cancel"] == [{"v": "1.0", "id": s["sent"][0]["id"], "type": "cancel", "data": {"kind": "agent_task", "id": "t1"}}]
    shown = s["text"]["task-detail"] + s["text"]["task-list"]
    assert expected in shown
    if not ack["ok"]:
        assert ack["code"] in shown and ack["message"] in shown


@pytestmark_node
def test_dom_non_cancellable_task_has_no_cancel_button(tmp_path):
    snaps = run_scenario(tmp_path, [activity(item("t1", cancellable=False)), {"snap": "s"}])
    assert "Abbrechen" not in snaps["s"]["buttons"]["task-list"]


@pytestmark_node
def test_dom_auto_switch_needs_three_planned_steps_or_two_agents(tmp_path):
    plan = lambda n: [item(f"p{i}", kind="plan", title=f"Schritt {i}") for i in range(n)]  # noqa: E731
    snaps = run_scenario(tmp_path, [
        activity(*plan(2)), {"snap": "two_steps"},
        activity(item("t1")), ev("routing", {"task_id": "t1", "agent": "research", "source": "llm", "reason": "r"}), {"snap": "one_agent"},
        activity(*plan(3)), {"snap": "three_steps"},
    ])
    assert snaps["two_steps"]["mode"] == "orb" and snaps["one_agent"]["mode"] == "orb"
    assert snaps["three_steps"]["mode"] == "dashboard"
    snaps = run_scenario(tmp_path, [
        activity(item("t1"), item("t2")),
        ev("routing", {"task_id": "t1", "agent": "research", "source": "llm", "reason": "r"}), {"snap": "one"},
        ev("routing", {"task_id": "t2", "agent": "coding", "source": "rules", "reason": "r"}), {"snap": "two"},
    ])
    assert snaps["one"]["mode"] == "orb" and snaps["two"]["mode"] == "dashboard"


@pytestmark_node
def test_dom_manual_choice_wins_over_auto_switch(tmp_path):
    plan = [item(f"p{i}", kind="plan") for i in range(4)]
    snaps = run_scenario(tmp_path, [{"toggle": True}, {"toggle": True}, {"snap": "manual_orb"}, activity(*plan), {"snap": "after"}])
    assert snaps["manual_orb"]["mode"] == "orb" and snaps["after"]["mode"] == "orb"  # wer selbst gewaehlt hat, wird nicht umgeschaltet


@pytestmark_node
def test_dom_no_auto_switch_without_evidence(tmp_path):
    snaps = run_scenario(tmp_path, [activity(item("t1"), item("t2"), item("t3")), ev("chat", {"sender": "jarvis", "text": "komplex komplex komplex"}), {"snap": "s"}])
    assert snaps["s"]["mode"] == "orb"


# ---- Aufgaben-/Ergebnisansicht (Aufgabe 5) ---------------------------------------------------------------------------------------------------
@pytestmark_node
def test_dom_shows_status_history_german_label_result_and_a_clear_error(tmp_path):
    snaps = run_scenario(tmp_path, [
        activity(item("t1", title="Datei lesen", status="PENDING"), item("t2", title="Ordner anlegen")),
        ev("task_update", {"kind": "agent_task", "id": "t1", "status": "RUNNING", "detail": ""}),
        ev("task_update", {"kind": "agent_task", "id": "t1", "status": "RUNNING", "detail": ""}),
        ev("task_update", {"kind": "agent_task", "id": "t1", "status": "SUCCEEDED", "detail": ""}),
        ev("result", {"task_id": "t1", "summary": "Inhalt gelesen", "artifacts": []}),
        {"snap": "ok"},
        ev("task_update", {"kind": "agent_task", "id": "t2", "status": "FAILED", "detail": "Pfad liegt ausserhalb des Arbeitsbereichs"}),
        {"click": {"id": "task-list", "text": "Ordner anlegen [FAILED]"}},
        {"snap": "bad"},
        ev("task_update", {"kind": "agent_task", "id": "t3", "status": "BLOCKED", "detail": ""}),
        {"click": {"id": "task-list", "text": "t3 [BLOCKED]"}},
        {"snap": "nogrund"},
    ])
    ok, bad = snaps["ok"]["text"]["task-detail"], snaps["bad"]["text"]["task-detail"]
    assert "PENDING -> RUNNING -> SUCCEEDED" in ok and ok.count("RUNNING") == 1            # doppelte Meldungen erzeugen keine doppelte Stufe
    assert "SUCCEEDED (erfolgreich)" in ok and "Ergebnis: Inhalt gelesen" in ok
    assert "Fehler: Pfad liegt ausserhalb des Arbeitsbereichs" in bad and "FAILED (fehlgeschlagen)" in bad
    assert "Fehler: das Backend nannte keinen Grund" in snaps["nogrund"]["text"]["task-detail"]


@pytestmark_node
def test_dom_result_links_back_to_its_task_as_a_button_not_a_hyperlink(tmp_path):
    snaps = run_scenario(tmp_path, [
        activity(item("t1", title="Erste"), item("t2", title="Zweite")),
        ev("result", {"task_id": "t2", "summary": "Zwei fertig", "artifacts": []}),
        {"click": {"id": "results-list", "text": "Zur Aufgabe"}},
        {"snap": "x"},
    ])
    assert "Titel: Zweite" in snaps["x"]["text"]["task-detail"]
    assert 'href=' not in text("app.js").split("function renderResults")[1].split("function renderDashboard")[0]
