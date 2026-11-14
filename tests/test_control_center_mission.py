"""V2.1 M6 NEXUS Mission Control: eine NUR LESENDE Ansicht (`/view/mission`) im bestehenden Premium-V2-Control-Center.
Abhaengigkeitsgraph, Agentenstatus, Budget, Fortschritt, Qualitaetspruefung, Business-Ergebnisse, Projektgedaechtnis. Keine neue Bibliothek, kein neuer Freigabe- oder Ausfuehrungsweg:
die Ansicht liest ueber Quellfunktionen und ruft nie submit/start/cancel/run auf."""
from __future__ import annotations

import http.client
import json
import re
from pathlib import Path

import pytest

import jarvis.control_center.mission as mission_mod
from jarvis.control_center import launcher as launcher_mod
from jarvis.control_center.mission import MissionView
from jarvis.control_center.server import VIEW_PATHS, ControlCenterServer
from jarvis.control_center.views import ReadViews, ViewError
from jarvis.ui_contract import FakeUiBackend
from test_control_center_dashboard import NODE, run_scenario, text

KEY = "sk-" + "a1" * 12


def task(i, status="SUCCEEDED", agent="research", deps=(), **kw):
    t = {"task_id": f"t{i}", "agent_id": agent, "status": status, "objective": f"Aufgabe {i}", "summary": "", "dependencies": list(deps), "timed_out": False, "cancel_requested": False}
    t.update(kw)
    return t


def src(*tasks, agents=None):
    return lambda limit: {"agents": agents if agents is not None else [{"id": "research", "status": "AVAILABLE", "capabilities": ["research.web"], "reason": ""},
                                                                         {"id": "business", "status": "DISABLED", "capabilities": ["business.analyze"], "reason": "off"}],
                          "tasks": list(tasks)[-limit:]}


def view(*tasks, **kw):
    return MissionView(agents_source=src(*tasks), **kw)


# ---- Graph ---------------------------------------------------------------------------------------------------------------------------------------------
def test_graph_orders_tasks_in_waves_by_their_dependencies():
    out = view(task(1), task(2, deps=["t1"]), task(3, deps=["t1"]), task(4, deps=["t2", "t3"])).snapshot(50)
    g = out["graph"]
    assert out["available"] is True and g["available"] is True
    assert g["waves"] == [["t1"], ["t2", "t3"], ["t4"]] and {n["id"]: n["wave"] for n in g["nodes"]} == {"t1": 0, "t2": 1, "t3": 1, "t4": 2}
    assert sorted(map(tuple, g["edges"])) == [("t1", "t2"), ("t1", "t3"), ("t2", "t4"), ("t3", "t4")]


def test_a_dependency_outside_the_window_is_reported_not_invented():
    g = view(task(2, deps=["t1"]), task(3, deps=["t2"])).snapshot(50)["graph"]
    assert g["waves"] == [["t2"], ["t3"]] and g["external_deps"] == ["t1"]


def test_a_cycle_never_hangs_and_is_reported():
    g = view(task(1, deps=["t2"]), task(2, deps=["t1"]), task(3)).snapshot(50)["graph"]
    assert sorted(g["cycle"]) == ["t1", "t2"] and g["waves"] == [["t3"]] and {n["id"]: n["wave"] for n in g["nodes"]}["t1"] is None


def test_the_graph_is_bounded_and_keeps_the_newest_tasks():
    tasks = [task(i) for i in range(1, 400)]
    out = view(*tasks).snapshot(25)
    assert len(out["graph"]["nodes"]) == 25 and out["graph"]["nodes"][-1]["id"] == "t399" and out["graph"]["truncated"] is True and out["limit"] == 25


# ---- Agentenstatus und Fortschritt ----------------------------------------------------------------------------------------------------------------------
def test_agent_status_counts_open_tasks_per_agent():
    out = view(task(1, "RUNNING"), task(2, "PENDING"), task(3, "SUCCEEDED"), task(4, "RUNNING", agent="business")).snapshot(50)["agents"]
    by = {a["id"]: a for a in out["items"]}
    assert by["research"]["running"] == 1 and by["research"]["pending"] == 1 and by["research"]["status"] == "AVAILABLE" and by["business"]["reason"] == "off" and by["business"]["running"] == 1


def test_progress_counts_by_status_and_a_percentage_of_finished_tasks():
    p = view(task(1), task(2, "FAILED"), task(3, "RUNNING"), task(4, "PENDING")).snapshot(50)["progress"]
    assert p["total"] == 4 and p["by_status"] == {"SUCCEEDED": 1, "FAILED": 1, "RUNNING": 1, "PENDING": 1} and p["finished"] == 2 and p["percent"] == 50
    assert view().snapshot(50)["progress"] == {"available": True, "total": 0, "by_status": {}, "finished": 0, "percent": 0}


# ---- Optionale Quellen: nichts wird erfunden ---------------------------------------------------------------------------------------------------------------
def test_budget_business_quality_and_memory_say_why_they_are_empty():
    out = view(task(1)).snapshot(50)
    for key in ("budget", "business", "quality", "memory"):
        assert out[key]["available"] is False and out[key]["reason"], key


def test_budget_shows_numbers_only():
    usage = lambda: {"calls": 3, "max_calls": 50, "elapsed": 12.5, "max_seconds": 600.0, "exhausted": None, "started": True, "unknown": "x"}
    b = view(task(1), budget_source=usage).snapshot(50)["budget"]
    assert b["available"] is True and b["session"] == {"calls": 3, "max_calls": 50, "elapsed": 12.5, "max_seconds": 600.0, "exhausted": None, "started": True}
    assert view(task(1), budget_source=lambda: {"calls": 50, "max_calls": 50, "elapsed": 1.0, "max_seconds": 5.0, "exhausted": "Aufrufe aufgebraucht", "started": True}).snapshot(50)["budget"]["session"]["exhausted"] == "Aufrufe aufgebraucht"


def test_business_results_are_summaries_with_confidence_and_unknowns_never_the_full_output():
    rows = [{"task_id": "t9", "agent_id": "strategist", "kind": "rank", "summary": "ranking of 3 idea(s); first: A " + KEY, "confidence": "medium", "unknowns": 2, "sources": 4, "output": {"secret": "x"}}]
    b = view(task(1), business_source=lambda limit: rows).snapshot(50)["business"]
    assert b["available"] is True and b["items"][0]["agent_id"] == "strategist" and b["items"][0]["unknowns"] == 2 and "output" not in b["items"][0]
    assert KEY not in json.dumps(b) and "[REDACTED]" in json.dumps(b)


def test_quality_shows_verdicts_and_a_self_reported_success_does_not_count_as_accepted():
    rows = [{"task_id": "t1", "accepted": False, "failed": ["sources"], "unknown": ["files"], "self_reported": "SUCCEEDED"}, {"task_id": "t2", "accepted": True, "failed": [], "unknown": [], "self_reported": "SUCCEEDED"}]
    q = view(task(1), quality_source=lambda limit: rows).snapshot(50)["quality"]
    assert q["available"] is True and q["accepted"] == 1 and q["rejected"] == 1 and q["items"][0]["failed"] == ["sources"] and q["items"][0]["self_reported"] == "SUCCEEDED"


def test_project_memory_shows_counts_per_project_never_the_records():
    rows = [{"project": "alpha", "counts": {"confirmed": 3, "issue": 1}, "conflicts": 1, "stale": 2, "suggestions": 1, "records": ["geheim"]}]
    m = view(task(1), memory_source=lambda: rows).snapshot(50)["memory"]
    assert m["available"] is True and m["projects"] == [{"project": "alpha", "counts": {"confirmed": 3, "issue": 1}, "conflicts": 1, "stale": 2, "suggestions": 1}]


def test_a_failing_source_gives_only_a_generic_reason_and_does_not_break_the_other_sections():
    def boom(*a):
        raise RuntimeError(f"secret {KEY}")
    out = view(task(1), budget_source=boom, business_source=boom, quality_source=boom, memory_source=boom).snapshot(50)
    assert KEY not in json.dumps(out) and "RuntimeError" not in json.dumps(out)
    for key in ("budget", "business", "quality", "memory"):
        assert out[key]["available"] is False and "nicht lesbar" in out[key]["reason"]
    assert out["graph"]["available"] is True and out["progress"]["total"] == 1


def test_without_an_agents_source_everything_is_empty_with_a_reason():
    out = MissionView(agents_source=None).snapshot(50)
    assert out["available"] is False and "Agentenschicht" in out["reason"] and out["graph"]["nodes"] == []
    boom = MissionView(agents_source=lambda n: (_ for _ in ()).throw(RuntimeError(KEY))).snapshot(50)
    assert boom["available"] is False and KEY not in json.dumps(boom)


def test_texts_are_redacted_and_clipped_and_malformed_data_is_tolerated():
    t = task(1, objective="Suche " + KEY + " " + "x" * 500, summary=None)
    out = view(t, "kaputt", {"task_id": 5}, task(2, deps="nicht-liste")).snapshot(50)
    blob = json.dumps(out)
    assert KEY not in blob and all(len(n["objective"]) <= 120 for n in out["graph"]["nodes"])


# ---- ReadViews / Server ---------------------------------------------------------------------------------------------------------------------------------
def test_readviews_mission_validates_parameters_and_reports_a_missing_view():
    assert ReadViews().mission({})["available"] is False
    rv = ReadViews(mission=view(task(1)))
    assert rv.mission({"limit": "5"})["limit"] == 5
    for bad in ({"limit": "0"}, {"limit": "x"}, {"unknown": "1"}, {"agent": "a"}):
        with pytest.raises(ViewError):
            rv.mission(bad)


def get(srv, path, method="GET", token=True, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    sep = "&" if "?" in path else "?"
    conn.request(method, path + (f"{sep}t={srv.token}" if token else ""), headers={"Host": host or f"127.0.0.1:{srv.port}"})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, r.getheader("Content-Type") or "", body


@pytest.fixture
def srv():
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02, views=ReadViews(mission=view(task(1), task(2, deps=["t1"]))))
    s.start()
    yield s
    s.stop()


def test_the_server_serves_the_mission_view_as_read_only_json_behind_token_and_host(srv):
    status, ctype, body = get(srv, "/view/mission")
    assert status == 200 and ctype.startswith("application/json") and json.loads(body)["graph"]["waves"] == [["t1"], ["t2"]]
    assert get(srv, "/view/mission", token=False)[0] == 401 and get(srv, "/view/mission", host="evil.example:80")[0] == 403
    assert get(srv, "/view/mission?limit=abc")[0] == 400 and get(srv, "/view/mission?x=1")[0] == 400
    for method in ("PUT", "DELETE", "PATCH"):
        assert get(srv, "/view/mission", method=method)[0] == 405
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("POST", f"/view/mission?t={srv.token}", body="{}", headers={"Host": f"127.0.0.1:{srv.port}", "Origin": f"http://127.0.0.1:{srv.port}", "Content-Type": "application/json"})
    assert conn.getresponse().status == 404
    conn.close()


def test_reading_the_mission_view_creates_no_event_on_the_ui_channel(srv):
    before = list(srv.backend.events_since(0))
    get(srv, "/view/mission")
    assert list(srv.backend.events_since(0)) == before


def test_exactly_one_view_path_was_added():
    assert VIEW_PATHS == {"/view/history": "history", "/view/audit": "audit", "/view/doctor": "doctor", "/view/agents": "agents", "/view/trace": "trace", "/view/mission": "mission"}


# ---- Verdrahtung: nur lesend -----------------------------------------------------------------------------------------------------------------------------------
class Orch:
    """Nur list/describe/registry: jede andere Benutzung (submit, start, cancel, run, set_enabled ...) wird zum Fehler."""
    def __init__(self, results=()):
        self.calls, self._results = [], list(results)
        self.registry = type("R", (), {"list": lambda s: []})()

    def list(self, status=None, limit=None):
        self.calls.append("list")
        return self._results[-(limit or len(self._results)):]

    def describe(self, task_id):
        self.calls.append("describe")
        return task(int(task_id[1:]))

    def __getattr__(self, name):
        raise AssertionError(f"mission must not touch orchestrator.{name}")


def result(i, agent, output, status="SUCCEEDED", summary="s"):
    return type("Res", (), {"task_id": f"t{i}", "agent_id": agent, "status": type("S", (), {"value": status})(), "summary": summary, "output": output})()


def core_with(orch, budget=None):
    return type("Core", (), {"subsystems": {"agents": type("A", (), {"orchestrator": orch})()}, "permissions": type("P", (), {"audit": None, "budget": budget})()})()


def test_launcher_wires_the_mission_view_read_only_from_the_orchestrator_and_the_session_budget():
    usage = type("U", (), {"calls": 2, "max_calls": 10, "elapsed": 1.0, "max_seconds": 60.0, "started": True, "exhausted": None})()
    budget = type("B", (), {"usage": lambda s: usage})()
    biz = result(2, "business", {"kind": "business_result", "task": "market_analysis", "confidence": {"level": "high"}, "unknowns": ["a", "b"], "sources": [{}, {}, {}]}, summary="Markt")
    strat = result(3, "strategist", {"kind": "strategist_result", "task": "rank", "result": {}, "sources": []}, summary="Rang")
    other = result(1, "research", {"kind": "research_result"})
    orch = Orch([other, biz, strat])
    out = launcher_mod.build_views(core_with(orch, budget), None).mission({})
    assert out["available"] is True and out["budget"]["session"]["calls"] == 2
    rows = {r["task_id"]: r for r in out["business"]["items"]}
    assert set(rows) == {"t2", "t3"} and rows["t2"]["confidence"] == "high" and rows["t2"]["unknowns"] == 2 and rows["t2"]["sources"] == 3 and rows["t3"]["kind"] == "rank"
    assert out["quality"]["available"] is False and out["memory"]["available"] is False
    assert set(orch.calls) <= {"list", "describe"}


def test_launcher_without_an_orchestrator_has_an_empty_mission_view():
    core = type("Core", (), {"subsystems": {}, "permissions": None})()
    assert launcher_mod.build_views(core, None).mission({})["available"] is False


# ---- Struktur: keine Schreibnamen, keine verbotenen Importe ---------------------------------------------------------------------------------------------------
def test_the_mission_module_imports_no_agents_permissions_tools_or_writers_and_has_no_write_names():
    s = Path(mission_mod.__file__).read_text(encoding="utf-8")
    imports = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", s, re.M))
    assert not [m for m in imports if m.startswith(("jarvis.permissions", "jarvis.tools", "jarvis.bootstrap", "jarvis.goals", "jarvis.agents", "jarvis.business", "jarvis.memory", "jarvis.quality"))], imports
    assert not [m for m in imports if m.split(".")[0] in ("os", "subprocess", "socket", "http", "urllib", "shutil", "pathlib", "sqlite3", "threading")], imports
    assert not re.search(r"\b(?:def|class)\s+\w*(?:write|delete|record|set|cancel|confirm|submit|start|run|approve|grant|engage|reset)\w*", s, re.I)


# ---- Oberflaeche: Struktur ---------------------------------------------------------------------------------------------------------------------------------------
def test_the_assets_have_the_mission_panel_and_use_no_new_library_or_dangerous_api():
    html, js, css = text("index.html"), text("app.js"), text("styles.css")
    for i in ("mission-panel", "mission-note", "mission-refresh", "mission-graph", "mission-agents", "mission-budget", "mission-progress", "mission-errors", "mission-quality", "mission-business", "mission-memory"):
        assert f'id="{i}"' in html, i
    body = js.split("function renderMission")[1].split("\nasync function ")[0]
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", ".src =", "href", 'setAttribute("style"', "style.cssText", "three", "THREE", "eval(", "POST"):
        assert bad not in body, bad
    load = js.split("async function loadMission")[1].split("\nfunction ")[0].split("\nasync function ")[0]
    assert 'url("view/mission"' in load and 'method: "GET"' in load and "send(" not in load and "confirm" not in load.lower() and "emergency" not in load.lower()
    assert " style=" not in html and "onclick" not in html and not re.search(r"@import|url\(http|https?://", css)
    assert sorted(p.name for p in (Path(mission_mod.__file__).parent / "web").iterdir() if p.suffix == ".js") == ["app.js"]


# ---- Oberflaeche: DOM (Node) ----------------------------------------------------------------------------------------------------------------------------------------
def mission_data(**over):
    d = {"available": True, "reason": "", "limit": 100,
         "graph": {"available": True, "truncated": False, "waves": [["t1"], ["t2", "t3"]], "edges": [["t1", "t2"], ["t1", "t3"]], "external_deps": [], "cycle": [], "blocked_by_failure": ["t9"],
                   "nodes": [{"id": "t1", "agent": "research", "status": "SUCCEEDED", "wave": 0, "deps": [], "objective": "Preise"},
                             {"id": "t2", "agent": "business", "status": "RUNNING", "wave": 1, "deps": ["t1"], "objective": "Analyse"},
                             {"id": "t3", "agent": "business", "status": "FAILED", "wave": 1, "deps": ["t1"], "objective": "Plan"}]},
         "agents": {"available": True, "items": [{"id": "research", "status": "AVAILABLE", "reason": "", "capabilities": ["research.web"], "pending": 0, "running": 0}]},
         "budget": {"available": True, "reason": "", "session": {"calls": 3, "max_calls": 50, "elapsed": 12.0, "max_seconds": 600.0, "exhausted": None, "started": True}},
         "progress": {"available": True, "total": 3, "by_status": {"SUCCEEDED": 1, "RUNNING": 1, "FAILED": 1}, "finished": 2, "percent": 67},
         "quality": {"available": True, "reason": "", "accepted": 0, "rejected": 1, "items": [{"task_id": "t3", "accepted": False, "failed": ["sources"], "unknown": [], "self_reported": "SUCCEEDED"}]},
         "business": {"available": True, "reason": "", "items": [{"task_id": "t2", "agent_id": "strategist", "kind": "rank", "summary": "Rangfolge", "confidence": "medium", "unknowns": 1, "sources": 2}]},
         "memory": {"available": False, "reason": "Projektgedaechtnis noch nicht angebunden."},
         "errors": {"available": True, "reason": "", "items": [{"task_id": "t3", "agent": "business", "code": "agent_crashed", "status": "FAILED"}]}}
    d.update(over)
    return d


def snap(tmp_path, data):
    return run_scenario(tmp_path, [{"views": {"mission": data}}, {"clickId": "mission-refresh"}, {"snap": "s"}])["s"]


def test_dom_renders_all_sections_from_the_view_with_text_only(tmp_path):
    if NODE is None:
        pytest.fail("Node.js fehlt: der DOM-Test der Mission-Control-Ansicht kann nicht laufen")
    s = snap(tmp_path, mission_data())
    assert s["fetched"] == ["mission"] and "3 Aufgaben" in s["text"]["mission-note"]
    graph = s["items"]["mission-graph"]
    waves = [x for x in graph if x["className"] == "mission-wave"]
    assert len(waves) == 2 and len(graph) == 3 and graph[2]["className"] == "tl-err" and "t1" in graph[0]["text"] and "t2" in graph[1]["text"] and "t3" in graph[1]["text"]
    assert any("research" in x["text"] for x in s["items"]["mission-agents"])
    assert "3/50" in s["text"]["mission-budget"] and s["props"]["mission-progress"]["value"] == 67
    assert "sources" in s["text"]["mission-quality"] and "strategist" in s["text"]["mission-business"] and "noch nicht angebunden" in s["text"]["mission-memory"]
    assert "agent_crashed" in s["text"]["mission-errors"] and "t9" in s["text"]["mission-graph"]


def test_dom_shows_the_reason_when_the_layer_is_off_and_never_throws_on_odd_data(tmp_path):
    if NODE is None:
        pytest.fail("Node.js fehlt")
    s = snap(tmp_path, {"available": False, "reason": "Die Agentenschicht ist nicht aktiv (agents.enabled = false)."})
    assert "nicht aktiv" in s["text"]["mission-note"] and s["items"]["mission-graph"] == []
    s = snap(tmp_path, {"available": True, "graph": "kaputt", "agents": None, "progress": [], "budget": 5})
    assert s["fetched"] == ["mission"]


# ---- uebernommen aus dem Prototyp claude/v21-nexus (mission_view.py): Fehler und Blockade durch Fehlschlag ---------------------------------------------------------
def test_tasks_behind_a_failed_or_cancelled_task_are_listed_as_blocked_by_that_failure():
    g = view(task(1, "FAILED", error_code="timeout"), task(2, "PENDING", deps=["t1"]), task(3, "PENDING", deps=["t2"]), task(4, "SUCCEEDED"), task(5, "PENDING", deps=["t4"])).snapshot(50)["graph"]
    assert g["blocked_by_failure"] == ["t2", "t3"]


def test_errors_show_codes_per_task_without_texts():
    out = view(task(1, "FAILED", error_code="timeout", summary="Geheimnis " + KEY), task(2, "BLOCKED", error_code="emergency_stop"), task(3)).snapshot(50)["errors"]
    assert out["available"] is True and [(e["task_id"], e["code"]) for e in out["items"]] == [("t2", "emergency_stop"), ("t1", "timeout")]
    assert KEY not in json.dumps(out) and "Geheimnis" not in json.dumps(out)
    assert view(task(1)).snapshot(50)["errors"]["items"] == []
