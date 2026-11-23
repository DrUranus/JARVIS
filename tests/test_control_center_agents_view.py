"""WP07a: nur lesende Ansichten `/view/agents` (Agenten und Aufgaben des Orchestrators) und `/view/trace` (Werkzeugaufrufe aus dem Audit, ohne Inhalte).

Gleiche Regeln wie die uebrigen Ansichten: nur GET, Token/Host/Origin, unbekannte Parameter und falsche Grenzen -> 400, begrenzt, geschwaerzt, deterministisch, leere Quelle ->
leer mit Grund, kein neues Ereignis auf dem UI-Kanal, kein Schreibweg. Nur Loopback, keine echten Agenten."""
import http.client
import json
import re
from pathlib import Path

import pytest

import jarvis.control_center as cc
from jarvis.control_center import launcher as launcher_mod
from jarvis.control_center import views as views_mod
from jarvis.control_center.server import VIEW_PATHS, ControlCenterServer
from jarvis.control_center.views import ReadViews, ViewError
from jarvis.permissions.audit import AuditEvent, AuditEventType, AuditLogger, MemoryAuditSink
from jarvis.redaction import SecretDetector
from jarvis.ui_contract import FakeUiBackend

SECRET = "sk-" + "A1b2C3d4E5f6G7h8I9j0"


def task(i, agent="research", status="SUCCEEDED", **kw):
    d = {"task_id": f"at-{i:04d}", "agent_id": agent, "status": status, "priority": 5, "objective": f"Ziel {i}", "dependencies": [], "requested": True,
         "cancel_requested": False, "timed_out": False, "still_running": False, "summary": f"fertig {i}", "error_code": None,
         "started_at": f"2026-11-12T10:00:{i % 60:02d}+00:00", "finished_at": f"2026-11-12T10:01:{i % 60:02d}+00:00"}
    d.update(kw)
    return d


def agent(i, status="AVAILABLE", **kw):
    d = {"id": i, "status": status, "capabilities": ["research.web"], "reason": ""}
    d.update(kw)
    return d


def source(tasks=(), agents=()):
    return lambda limit: {"agents": list(agents), "tasks": list(tasks)[-limit:]}


def audit_with(events):
    sink = MemoryAuditSink(2000)
    for e in events:
        sink.record(e)
    return AuditLogger([sink]).tail


# ---- agents ------------------------------------------------------------------------------------------------------------------------------------
def test_agents_lists_agents_and_tasks_newest_first_with_metadata_only():
    v = ReadViews(agents_source=source([task(1), task(2, "business", "FAILED", error_code="invalid_input"), task(3)], [agent("research"), agent("business", "DISABLED", reason="aus")]))
    out = v.agents({})
    assert out["available"] is True and out["reason"] == "" and out["limit"] == 50
    assert [t["task_id"] for t in out["items"]] == ["at-0003", "at-0002", "at-0001"]
    assert [a["id"] for a in out["agents"]] == ["business", "research"]                                  # nach Namen sortiert (deterministisch)
    t2 = next(t for t in out["items"] if t["task_id"] == "at-0002")
    assert t2["agent_id"] == "business" and t2["status"] == "FAILED" and t2["error_code"] == "invalid_input" and t2["summary"] == "fertig 2"
    assert set(t2) <= {"task_id", "agent_id", "status", "priority", "objective", "summary", "error_code", "started_at", "finished_at", "dependencies", "timed_out", "cancel_requested"}
    assert out["agents"][0] == {"id": "business", "status": "DISABLED", "capabilities": ["research.web"], "reason": "aus"}


def test_agents_filters_by_status_and_agent_and_validates_them():
    v = ReadViews(agents_source=source([task(1), task(2, "business", "FAILED"), task(3, "business")], [agent("research")]))
    assert [t["task_id"] for t in v.agents({"agent": "business"})["items"]] == ["at-0003", "at-0002"]
    assert [t["task_id"] for t in v.agents({"status": "FAILED"})["items"]] == ["at-0002"]
    assert v.agents({"agent": "gibtsnicht"})["items"] == []
    for bad in ({"status": "a b"}, {"agent": "x;y"}, {"unknown": "1"}, {"limit": "0"}, {"limit": "201"}, {"limit": "x"}, {"status": ""}):
        with pytest.raises(ViewError):
            v.agents(bad)


def test_agents_limit_is_bounded_and_a_thousand_tasks_never_exceed_it():
    v = ReadViews(agents_source=source([task(i) for i in range(1000)]))
    assert len(v.agents({})["items"]) == 50 and len(v.agents({"limit": "200"})["items"]) == 200 and len(v.agents({"limit": "3"})["items"]) == 3


def test_agents_redacts_secrets_truncates_long_texts_and_drops_unknown_fields():
    v = ReadViews(agents_source=source([task(1, objective=f"nutze {SECRET} jetzt " + "x" * 5000, summary=SECRET, extra_secret=SECRET, result={"geheim": SECRET},
                                                  dependencies=[f"d{i}" for i in range(50)])], [agent("research", reason=f"key {SECRET}")]),
                  detector=SecretDetector())
    out = v.agents({})
    blob = json.dumps(out)
    assert SECRET not in blob and "extra_secret" not in blob and "result" not in out["items"][0]
    assert len(out["items"][0]["objective"]) <= 300 and len(out["items"][0]["dependencies"]) <= 20 and len(out["agents"][0]["reason"]) <= 200


def test_agents_without_a_source_or_with_a_failing_source_is_empty_with_a_reason_and_no_internals():
    assert ReadViews().agents({}) == {"available": False, "limit": 50, "filters": {"agent": None, "status": None}, "agents": [], "items": [],
                                      "reason": "Die Agentenschicht ist nicht aktiv (agents.enabled = false)."}

    def boom(limit):
        raise RuntimeError(f"intern {SECRET}")
    out = ReadViews(agents_source=boom, detector=SecretDetector()).agents({})
    assert out["available"] is False and out["items"] == [] and SECRET not in json.dumps(out) and "intern" not in json.dumps(out) and out["reason"]


def test_agents_tolerates_malformed_source_data():
    for junk in (None, "x", 5, {"tasks": "x", "agents": 5}, {"tasks": [None, 5, "x", {"task_id": 3}], "agents": [None, {"id": None}]}):
        out = ReadViews(agents_source=lambda limit, j=junk: j).agents({})
        assert isinstance(out["items"], list) and isinstance(out["agents"], list)                      # nie eine Ausnahme


# ---- trace ----------------------------------------------------------------------------------------------------------------------------------------
def mk(type_, **kw):
    return AuditEvent(type_, **kw)


def trace_events():
    return [mk(AuditEventType.EXECUTION_RESULT, tool="files", action="read", status="ok", level="GREEN", resource="C:/geheim/pfad.txt", detail=f"inhalt {SECRET}", extra={"k": SECRET}),
            mk(AuditEventType.PERMISSION_DENIED, tool="browser", action="goto", status="denied", level="RED", resource="https://x.test/", detail="regel"),
            mk(AuditEventType.POLICY_LOADED, detail="keine werkzeugaktion"),
            mk(AuditEventType.EXECUTION_RESULT, tool="files", action="write", status="error", level="YELLOW")]


def test_trace_lists_tool_calls_newest_first_without_any_content():
    out = ReadViews(audit_tail=audit_with(trace_events()), detector=SecretDetector()).trace({})
    assert out["available"] is True and [(i["tool"], i["action"]) for i in out["items"]] == [("files", "write"), ("browser", "goto"), ("files", "read")]
    blob = json.dumps(out)
    assert SECRET not in blob and "geheim" not in blob and "detail" not in blob and "extra" not in blob and "resource" not in blob
    assert set(out["items"][0]) <= {"timestamp", "type", "tool", "action", "level", "status"}


def test_trace_filters_validate_and_limit():
    v = ReadViews(audit_tail=audit_with(trace_events() * 100))
    assert {i["tool"] for i in v.trace({"tool": "browser"})["items"]} == {"browser"} and {i["status"] for i in v.trace({"status": "ok"})["items"]} == {"ok"}
    assert len(v.trace({})["items"]) == 50 and len(v.trace({"limit": "5"})["items"]) == 5
    for bad in ({"tool": "a b"}, {"unknown": "1"}, {"limit": "0"}, {"limit": "999"}):
        with pytest.raises(ViewError):
            v.trace(bad)


def test_trace_without_audit_or_with_a_failing_audit_is_empty_with_a_reason():
    assert ReadViews().trace({})["available"] is False and ReadViews().trace({})["items"] == []

    def boom(n):
        raise OSError("platte " + SECRET)
    out = ReadViews(audit_tail=boom, detector=SecretDetector()).trace({})
    assert out["available"] is False and SECRET not in json.dumps(out) and "platte" not in json.dumps(out)


# ---- Server ------------------------------------------------------------------------------------------------------------------------------------
def get(srv, path, *, token=True, host=None, method="GET", origin=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    sep = "&" if "?" in path else "?"
    headers = {"Host": host or f"127.0.0.1:{srv.port}"}
    if origin:
        headers["Origin"] = origin
    conn.request(method, path + (f"{sep}t={srv.token}" if token else ""), headers=headers)
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, r.getheader("Content-Type"), body


@pytest.fixture
def srv():
    backend = FakeUiBackend()
    s = ControlCenterServer(backend, poll_interval=0.02, views=ReadViews(agents_source=source([task(i) for i in range(5)], [agent("research")]),
                                                                       audit_tail=audit_with(trace_events()), detector=SecretDetector()))
    s.backend = backend
    s.start()
    yield s
    s.stop()


def test_server_serves_both_views_as_json_behind_token_and_host(srv):
    for path in ("/view/agents", "/view/trace"):
        status, ctype, body = get(srv, path)
        assert status == 200 and ctype.startswith("application/json") and json.loads(body)["available"] is True
        assert get(srv, path, token=False)[0] == 401
        assert get(srv, path, host="evil.example:80")[0] == 403
    assert json.loads(get(srv, "/view/agents?agent=research&limit=2")[2])["items"][0]["agent_id"] == "research"


def test_server_views_reject_bad_parameters_without_internals(srv):
    for path in ("/view/agents?limit=abc", "/view/agents?unknown=1", "/view/agents?status=a%20b", "/view/trace?tool=a%20b", "/view/trace?limit=0"):
        status, _, body = get(srv, path)
        assert status == 400 and b"Traceback" not in body


def test_server_views_are_read_only(srv):
    for path in ("/view/agents", "/view/trace"):
        for method in ("PUT", "DELETE", "PATCH"):
            assert get(srv, path, method=method)[0] == 405
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        conn.request("POST", f"{path}?t={srv.token}", body="{}", headers={"Host": f"127.0.0.1:{srv.port}", "Origin": f"http://127.0.0.1:{srv.port}", "Content-Type": "application/json"})
        assert conn.getresponse().status == 404
        conn.close()


def test_reading_the_views_creates_no_event_on_the_ui_channel(srv):
    before = list(srv.backend.events_since(0))
    for path in ("/view/agents", "/view/trace", "/view/agents?limit=3"):
        get(srv, path)
    assert list(srv.backend.events_since(0)) == before


def test_view_paths_are_exactly_the_five_read_only_views():
    assert VIEW_PATHS == {"/view/history": "history", "/view/audit": "audit", "/view/doctor": "doctor", "/view/agents": "agents", "/view/trace": "trace"}


def test_server_view_failure_is_500_generic():
    class Boom(ReadViews):
        def agents(self, params):
            raise RuntimeError(f"secret {SECRET}")
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02, views=Boom())
    s.start()
    try:
        status, _, body = get(s, "/view/agents")
        assert status == 500 and SECRET.encode() not in body
    finally:
        s.stop()


# ---- Struktur und Verdrahtung (nur lesend) --------------------------------------------------------------------------------------------------------
def test_views_module_still_imports_no_agents_permissions_or_tools_and_has_no_write_names():
    src = Path(views_mod.__file__).read_text(encoding="utf-8")
    imports = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M))
    assert not [m for m in imports if m.startswith(("jarvis.permissions", "jarvis.tools", "jarvis.bootstrap", "jarvis.goals", "jarvis.agents"))], imports
    assert not re.search(r"\b(?:def|class)\s+\w*(?:write|delete|record|set|cancel|confirm|submit|start|run)\w*", src, re.I)


class FakeOrchestrator:
    """Nur list/describe/registry: jede andere Benutzung (submit, start, cancel, run) wird zum Fehler."""

    def __init__(self):
        self.calls = []
        self.registry = type("R", (), {"list": lambda s: [FakeAgent("research"), FakeAgent("business")]})()

    def list(self, status=None, limit=None):
        self.calls.append("list")
        return [type("Res", (), {"task_id": f"at-{i:04d}"})() for i in range(1, 4)][-(limit or 3):]

    def describe(self, task_id):
        self.calls.append("describe")
        return task(int(task_id[3:]))

    def __getattr__(self, name):
        raise AssertionError(f"the views must not touch orchestrator.{name}")


class FakeAgent:
    def __init__(self, i):
        self.id, self.capabilities = i, frozenset({"research.web"})
        self.status = type("S", (), {"value": "AVAILABLE", "name": "AVAILABLE"})()
        self.status_reason = ""


def test_launcher_builds_a_read_only_agents_source_from_the_orchestrator():
    orch = FakeOrchestrator()
    core = type("Core", (), {"subsystems": {"agents": type("A", (), {"orchestrator": orch})()}, "permissions": None})()
    views = launcher_mod.build_views(core, None)
    out = views.agents({})
    assert out["available"] is True and [t["task_id"] for t in out["items"]] == ["at-0003", "at-0002", "at-0001"] and {a["id"] for a in out["agents"]} == {"research", "business"}
    assert set(orch.calls) == {"list", "describe"}


def test_launcher_without_an_orchestrator_gives_an_empty_agents_view():
    core = type("Core", (), {"subsystems": {}, "permissions": None})()
    assert launcher_mod.build_views(core, None).agents({})["available"] is False


def test_launcher_source_uses_no_write_methods_of_the_orchestrator():
    src = Path(launcher_mod.__file__).read_text(encoding="utf-8")
    for bad in (".submit(", ".start(", ".cancel(", ".run(", ".shutdown(", ".halt("):
        assert bad not in src.split("def build_views", 1)[1].split("def main", 1)[0], bad
