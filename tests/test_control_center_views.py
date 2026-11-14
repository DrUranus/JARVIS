"""cc-results-audit (Strang B, B7): nur lesende Ansichten fuer Verlauf/Ergebnisse (Journal) und Audit-Ereignisse (geschwaerzt, mit Filter und Begrenzung).
- ReadViews: Filter, Begrenzung, Schwaerzung, kein erfundener Inhalt.
- Server: nur GET /view/history und /view/audit, hinter Host/Token, kein Schreibweg.
- Struktur: keine Schreib-/Rechte-/Werkzeug-Importe, JS sendet fuer die Ansichten nur GET.
- DOM (Node): Anzeige aus echten Antworten, keine Befehle.
Nur Loopback, temporaere Dateien, kein externes Netzwerk."""
import http.client
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

import jarvis.control_center as cc
from jarvis.control_center import views as views_mod
from jarvis.control_center.server import ControlCenterServer
from jarvis.control_center.views import ReadViews, ViewError
from jarvis.journal.store import JournalStore
from jarvis.permissions.audit import AuditEvent, AuditEventType, AuditLogger, MemoryAuditSink
from jarvis.redaction import SecretDetector
from jarvis.ui_contract import FakeUiBackend

WEB = Path(cc.__file__).parent / "web"
HARNESS = Path(__file__).parent / "support" / "cc_dom_harness.js"
NODE = shutil.which("node")
SECRET = "sk-" + "A1b2C3d4E5f6G7h8I9j0"


def text(name):
    return (WEB / name).read_text(encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    s = JournalStore(tmp_path / "journal.db", max_entries=100, detector=SecretDetector())
    s.record("goal", "g1", "COMPLETED", "Ziel eins", result="fertig", evidence=["beleg a"])
    s.record("goal", "g2", "FAILED", "Ziel zwei", error="kaputt")
    s.record("agent_task", "t1", "COMPLETED", "Aufgabe eins", result="ok", steps=[{"step_id": "s1", "status": "COMPLETED", "text": "Schritt", "side_effect": False}])
    s.record("agent_task", "t2", "CANCELLED", "Aufgabe zwei")
    return s


def audit_with(events):
    sink = MemoryAuditSink(2000)
    for e in events:
        sink.record(e)
    return AuditLogger([sink]).tail


def mk(type_, **kw):
    return AuditEvent(type_, **kw)


# ---- Verlauf / Ergebnisse (Journal) -----------------------------------------------------------------------------------------------------------
def test_history_lists_real_entries_newest_first_with_steps(store):
    out = ReadViews(journal=store).history({})
    assert out["available"] is True
    assert [i["id"] for i in out["items"]] == ["t2", "t1", "g2", "g1"]
    t1 = next(i for i in out["items"] if i["id"] == "t1")
    assert t1["steps"][0]["text"] == "Schritt" and t1["steps"][0]["side_effect"] is False
    g1 = next(i for i in out["items"] if i["id"] == "g1")
    assert g1["result"] == "fertig" and g1["evidence"] == ["beleg a"]


def test_history_filters_by_kind_and_status_and_limit(store):
    v = ReadViews(journal=store)
    assert {i["kind"] for i in v.history({"kind": "goal"})["items"]} == {"goal"}
    assert [i["id"] for i in v.history({"status": "failed"})["items"]] == ["g2"]
    assert [i["id"] for i in v.history({"kind": "agent_task", "status": "COMPLETED"})["items"]] == ["t1"]
    assert len(v.history({"limit": "2"})["items"]) == 2
    assert v.history({"limit": "2"})["limit"] == 2


def test_history_limit_is_bounded_and_validated(store):
    v = ReadViews(journal=store, default_limit=3, max_limit=3)
    assert len(v.history({})["items"]) == 3
    for bad in ("0", "-1", "abc", "4", "1e3", " 2", "9" * 30):
        with pytest.raises(ViewError):
            v.history({"limit": bad})


@pytest.mark.parametrize("params", [{"kind": "other"}, {"status": "x; DROP"}, {"status": "a" * 40}, {"bogus": "1"}, {"kind": ""}])
def test_history_rejects_bad_filters(store, params):
    with pytest.raises(ViewError):
        ReadViews(journal=store).history(params)


def test_history_redacts_even_if_the_store_holds_a_secret(store, tmp_path):
    con = sqlite3.connect(tmp_path / "journal.db")
    con.execute("UPDATE journal_entries SET result = ?, text = ?, error = ?, evidence = ? WHERE ref_id = 'g1'",
                (f"key {SECRET}", "password = hunter2hunter2", f"token: {SECRET}", json.dumps([f"x {SECRET}"])))
    con.execute("UPDATE journal_steps SET text = ? WHERE ref_id = 't1'", (f"api_key={SECRET}",))
    con.commit()
    con.close()
    dump = json.dumps(ReadViews(journal=store, detector=SecretDetector()).history({}))
    assert SECRET not in dump and "hunter2hunter2" not in dump and "[REDACTED]" in dump


def test_history_without_journal_is_empty_and_says_so():
    out = ReadViews().history({})
    assert out["available"] is False and out["items"] == [] and out["reason"]


def test_history_on_missing_database_is_empty_but_available(tmp_path):
    out = ReadViews(journal=JournalStore(tmp_path / "none.db")).history({})
    assert out["items"] == [] and out["available"] is True
    assert not (tmp_path / "none.db").exists()   # lesen legt nichts an


def test_history_does_not_change_the_journal(store, tmp_path):
    before = store.count()
    raw = (tmp_path / "journal.db").read_bytes()
    ReadViews(journal=store).history({"kind": "goal"})
    assert store.count() == before and (tmp_path / "journal.db").read_bytes() == raw


# ---- Audit ------------------------------------------------------------------------------------------------------------------------------------
def test_audit_lists_newest_first_and_filters():
    tail = audit_with([mk(AuditEventType.PERMISSION_GRANTED, tool="files", status="ok", level="G"),
                       mk(AuditEventType.PERMISSION_DENIED, tool="shell", status="denied", level="R"),
                       mk(AuditEventType.EXECUTION_RESULT, tool="files", status="ok", level="G")])
    v = ReadViews(audit_tail=tail)
    out = v.audit({})
    assert out["available"] is True and [e["type"] for e in out["items"]] == ["execution_result", "permission_denied", "permission_granted"]
    assert [e["type"] for e in v.audit({"type": "permission_denied"})["items"]] == ["permission_denied"]
    assert {e["tool"] for e in v.audit({"tool": "files"})["items"]} == {"files"}
    assert len(v.audit({"status": "ok"})["items"]) == 2 and len(v.audit({"level": "R"})["items"]) == 1
    assert len(v.audit({"limit": "1"})["items"]) == 1


def test_audit_limit_bounded_and_filters_validated():
    v = ReadViews(audit_tail=audit_with([mk(AuditEventType.POLICY_LOADED)] * 5), default_limit=2, max_limit=4)
    assert len(v.audit({})["items"]) == 2
    with pytest.raises(ViewError):
        v.audit({"limit": "5"})
    for bad in ({"type": "a b"}, {"tool": "x" * 65}, {"foo": "1"}):
        with pytest.raises(ViewError):
            v.audit(bad)


def test_audit_scan_window_is_bounded():
    asked = []

    def tail(n):
        asked.append(n)
        return []
    ReadViews(audit_tail=tail, audit_window=300).audit({"limit": "10"})
    assert asked == [300]


def test_audit_redacts_everything_again_and_drops_unknown_fields():
    raw = [{"type": "execution_result", "id": "a", "detail": f"Bearer token = {SECRET}", "extra": {"password": "hunter2hunter2", "note": f"k {SECRET}"},
            "tool": "files", "internal_secret_field": SECRET}, {"type": "unreadable_line"}]
    out = ReadViews(audit_tail=lambda n: raw, detector=SecretDetector()).audit({})
    dump = json.dumps(out)
    assert SECRET not in dump and "hunter2hunter2" not in dump
    assert "internal_secret_field" not in dump
    assert any(i["type"] == "unreadable_line" for i in out["items"])


def test_audit_without_source_is_empty_and_says_so():
    out = ReadViews().audit({})
    assert out["available"] is False and out["items"] == [] and out["reason"]


def test_audit_source_failure_is_reported_without_details():
    def boom(n):
        raise OSError(f"cannot open /secret/{SECRET}")
    out = ReadViews(audit_tail=boom).audit({})
    assert out["items"] == [] and out["available"] is False and SECRET not in json.dumps(out)


# ---- Server ------------------------------------------------------------------------------------------------------------------------------------
def get(srv, path, *, token=True, host=None, method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    sep = "&" if "?" in path else "?"
    conn.request(method, path + (f"{sep}t={srv.token}" if token else ""), headers={"Host": host or f"127.0.0.1:{srv.port}"})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, r.getheader("Content-Type"), body


@pytest.fixture
def srv(store):
    tail = audit_with([mk(AuditEventType.PERMISSION_GRANTED, tool="files", status="ok", detail=f"x {SECRET}")])
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02, views=ReadViews(journal=store, audit_tail=tail, detector=SecretDetector()))
    s.start()
    yield s
    s.stop()


def test_server_serves_history_and_audit_as_json(srv):
    status, ctype, body = get(srv, "/view/history?kind=goal&limit=5")
    assert status == 200 and ctype.startswith("application/json")
    assert {i["kind"] for i in json.loads(body)["items"]} == {"goal"}
    status, _, body = get(srv, "/view/audit?tool=files")
    assert status == 200 and SECRET.encode() not in body and json.loads(body)["items"][0]["tool"] == "files"


def test_server_view_needs_token_and_host(srv):
    assert get(srv, "/view/history", token=False)[0] == 401
    assert get(srv, "/view/audit", host="evil.example:80")[0] == 403


def test_server_view_bad_filter_is_400_without_internals(srv):
    status, _, body = get(srv, "/view/history?limit=abc")
    assert status == 400 and b"Traceback" not in body
    assert get(srv, "/view/audit?type=a%20b")[0] == 400
    assert get(srv, "/view/history?unknown=1")[0] == 400


def test_server_view_is_read_only(srv):
    for method in ("PUT", "DELETE", "PATCH"):
        assert get(srv, "/view/history", method=method)[0] == 405
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("POST", f"/view/history?t={srv.token}", body="{}", headers={"Host": f"127.0.0.1:{srv.port}", "Origin": f"http://127.0.0.1:{srv.port}",
                                                                           "Content-Type": "application/json"})
    assert conn.getresponse().status == 404
    conn.close()


def test_server_without_views_has_no_view_routes():
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    s.start()
    try:
        assert get(s, "/view/history")[0] == 404 and get(s, "/view/audit")[0] == 404
    finally:
        s.stop()


def test_server_view_failure_is_500_generic(store):
    class Boom(ReadViews):
        def history(self, params):
            raise RuntimeError(f"secret {SECRET}")
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02, views=Boom(journal=store))
    s.start()
    try:
        status, _, body = get(s, "/view/history")
        assert status == 500 and SECRET.encode() not in body
    finally:
        s.stop()


# ---- Struktur: nur lesend ---------------------------------------------------------------------------------------------------------------------
def test_views_module_is_structurally_read_only():
    src = Path(views_mod.__file__).read_text(encoding="utf-8")
    imports = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M))
    assert not [m for m in imports if m.startswith(("jarvis.permissions", "jarvis.tools", "jarvis.bootstrap", "jarvis.goals", "jarvis.agents"))], imports
    for bad in (".record(", ".write", "open(", "sqlite3", "INSERT", "UPDATE", "DELETE", "unlink", "subprocess", "os.system", "execute(", "send("):
        assert bad not in src, bad
    assert not re.search(r"\b(?:def|class)\s+\w*(?:write|delete|record|set|cancel|confirm)\w*", src, re.I)


def test_launcher_and_server_expose_no_write_view(srv):
    s = Path(cc.__file__).parent / "server.py"
    src = s.read_text(encoding="utf-8")
    post = src[src.index("def do_POST"):src.index("def _method_not_allowed")]
    assert "view" not in post


def test_js_views_use_get_only_and_no_commands():
    js = text("app.js")
    targets = re.findall(r"fetch\(([^,]*),", js)
    assert targets == ["url(\"view/agents\"", "url(\"view/audit\"", "url(\"command\")", "url(\"view/\" + which", "url(\"core_states.json\")", "url(\"/overlay/open\")"]  # view/agents: Zeitleiste (WP07b, GET); view/audit: Freigabe-Verlauf (WP07c, GET); overlay/open: nur Mini-Overlay, Token+Origin, oeffnet das Hauptfenster
    m = re.search(r"async function loadView\(.*?\n\}", js, re.S)
    assert m, "loadView fehlt"
    body = m.group(0)
    assert "GET" in body and "POST" not in body and "send(" not in body and "body:" not in body
    for bad in ("setInterval", "setTimeout"):
        assert bad not in body
    html = text("index.html")
    for i in ("history-list", "audit-list", "history-note", "audit-note", "history-refresh", "audit-refresh", "history-kind", "history-status", "audit-type", "audit-tool"):
        assert f'id="{i}"' in html


# ---- DOM (Node) --------------------------------------------------------------------------------------------------------------------------------
pytestmark_node = pytest.mark.skipif(NODE is None, reason="node nicht installiert")


def run_dom(tmp_path, steps):
    f = tmp_path / "scenario.json"
    f.write_text(json.dumps(steps), encoding="utf-8")
    out = subprocess.run([NODE, str(HARNESS), str(WEB), str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


HISTORY = {"available": True, "limit": 50, "items": [
    {"kind": "goal", "id": "g1", "status": "COMPLETED", "text": "Ziel eins", "result": "fertig", "evidence": ["beleg a"], "error": None,
     "recorded_at": "2026-11-05T10:00:00+00:00", "steps": [{"no": 1, "id": "s1", "status": "COMPLETED", "text": "Schritt eins", "side_effect": True,
                                                             "result": "", "evidence": [], "error": None}]}]}
AUDIT = {"available": True, "limit": 50, "items": [{"type": "permission_denied", "id": "a1", "timestamp": "2026-11-05T10:00:01+00:00", "tool": "shell",
                                                    "action": "run", "status": "denied", "level": "R", "detail": "nicht erlaubt"}]}


@pytestmark_node
def test_dom_shows_real_history_and_audit_details_and_sends_no_command(tmp_path):
    snaps = run_dom(tmp_path, [{"views": {"history": HISTORY, "audit": AUDIT}}, {"clickId": "history-refresh"}, {"clickId": "audit-refresh"}, {"snap": "a"}])
    t = snaps["a"]["text"]
    assert "Ziel eins" in t["history-list"] and "fertig" in t["history-list"] and "beleg a" in t["history-list"] and "Schritt eins" in t["history-list"]
    assert "permission_denied" in t["audit-list"] and "nicht erlaubt" in t["audit-list"] and "shell" in t["audit-list"]
    assert snaps["a"]["sent"] == []                                    # keine Befehle durch die Ansichten
    assert snaps["a"]["fetched"] == ["history", "audit"]


@pytestmark_node
def test_dom_nothing_is_shown_before_the_user_asks_and_empty_is_not_faked(tmp_path):
    snaps = run_dom(tmp_path, [{"views": {"history": {"available": False, "items": [], "reason": "kein Journal"}, "audit": AUDIT}},
                               {"snap": "start"}, {"clickId": "history-refresh"}, {"snap": "after"}])
    assert snaps["start"]["fetched"] == [] and snaps["start"]["text"]["history-list"] == ""
    assert "kein Journal" in snaps["after"]["text"]["history-note"]
    assert snaps["after"]["text"]["history-list"] == ""


@pytestmark_node
def test_dom_filters_are_sent_as_query_parameters_only_when_set(tmp_path):
    snaps = run_dom(tmp_path, [{"views": {"history": HISTORY, "audit": AUDIT}}, {"set": {"id": "history-kind", "value": "goal"}}, {"set": {"id": "history-status", "value": "failed"}},
                               {"clickId": "history-refresh"}, {"snap": "a"}])
    assert snaps["a"]["fetchedUrls"][0].startswith("view/history?") and "kind=goal" in snaps["a"]["fetchedUrls"][0] and "status=FAILED" in snaps["a"]["fetchedUrls"][0]
    assert "limit=" in snaps["a"]["fetchedUrls"][0]


# ---- Verdrahtung (Launcher) -----------------------------------------------------------------------------------------------------------------
def test_build_server_wires_journal_and_audit_read_only(tmp_path):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from jarvis.control_center.launcher import build_server
    from test_computer_integration import env_for
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_CONTROL_CENTER_ENABLED="true",
                  JARVIS_JOURNAL_ENABLED="true", JARVIS_JOURNAL_PATH=str(tmp_path / "j.db"))      # eigener Pfad: nie das gemeinsame data/journal.db anderer Tests lesen
    settings = load_settings(env=env)
    core = build_core(settings)
    srv = build_server(settings, core)
    assert srv.views is not None and srv.views._audit_tail is not None
    store = core.subsystems["assistant"].journal.store
    store.record("goal", "gx", "COMPLETED", "echtes Ziel", result="ok")
    out = srv.views.history({})
    assert out["available"] is True and [i["id"] for i in out["items"]] == ["gx"]
    assert srv.views.audit({})["available"] is True
