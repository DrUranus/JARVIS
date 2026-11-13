"""V2.1 Mission 6: reines, nur lesendes Ansichtsmodell fuer NEXUS Mission Control (isolierter Prototyp, nicht verdrahtet)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from jarvis.control_center import mission_view as mv

ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-ant-api03-" + "A" * 40


def snap(**over):
    base = {
        "graph": {"nodes": [{"id": "a", "label": "Recherche", "status": "SUCCEEDED", "deps": []}, {"id": "b", "label": "Modell", "status": "RUNNING", "deps": ["a"]},
                            {"id": "c", "label": "Plan", "status": "PENDING", "deps": ["a", "b"]}, {"id": "d", "label": "Bericht", "status": "FAILED", "deps": ["c"]}]},
        "agents": [{"name": "research", "state": "running", "task": "t1"}, {"name": "business", "state": "idle"}],
        "costs": {"llm_calls": 4, "tokens": 1200, "cost": None, "limit_calls": 30},
        "errors": [{"code": "tool_failed", "where": "d", "text": "Zeitlimit"}],
        "sources": [{"title": "Statistik", "url": "https://example.org/a", "retrieved_at": "2026-11-01", "quality": "high"}],
        "memory": {"project": "p1", "records": 12, "stale": 2, "conflicts": [{"key": "preis", "values": 2}]},
        "business": [{"name": "Idee A", "score": 71.5, "rank": 1, "why": "geringes Startkapital"}],
        "quality": {"accepted": False, "failed": ["sources"], "unknown": ["calculations"]},
        "approvals": [{"id": "ap1", "what": "Datei schreiben", "level": "confirm", "state": "pending"}],
    }
    base.update(over)
    return base


def test_all_nine_panels_are_present_and_json_safe():
    view = mv.build(snap())
    assert set(view) == set(mv.PANELS) and len(mv.PANELS) == 9
    assert all(view[p]["available"] is True for p in mv.PANELS)
    json.dumps(view)


def test_graph_has_waves_edges_counts_and_progress():
    g = mv.build(snap())["graph"]
    assert [n["wave"] for n in g["nodes"]] == [0, 1, 2, 3] and {"from": "a", "to": "c"} in g["edges"] and len(g["edges"]) == 4
    assert g["counts"] == {"SUCCEEDED": 1, "RUNNING": 1, "PENDING": 1, "FAILED": 1} and g["progress_percent"] == 25
    assert g["blocked_by_failure"] == [] and g["problems"] == []


def test_graph_reports_cycles_unknown_dependencies_and_unknown_status_instead_of_guessing():
    g = mv.build(snap(graph={"nodes": [{"id": "a", "deps": ["b"], "status": "PENDING"}, {"id": "b", "deps": ["a"], "status": "weird"}, {"id": "c", "deps": ["zz"], "status": "FAILED"},
                                       {"id": "d", "deps": ["c"], "status": "PENDING"}, {"id": "a", "status": "PENDING"}]}))["graph"]
    assert {"cycle", "unknown_dependency", "duplicate_id"} <= set(g["problems"])
    by = {n["id"]: n for n in g["nodes"]}
    assert by["b"]["status"] == "UNKNOWN" and by["a"]["wave"] is None and g["blocked_by_failure"] == ["d"]


def test_missing_panels_say_so_and_nothing_is_invented():
    view = mv.build({})
    assert all(view[p] == {"available": False, "reason": "not_provided"} for p in mv.PANELS)
    view = mv.build({"graph": "kaputt", "agents": 7, "costs": []})
    assert all(view[p] == {"available": False, "reason": "invalid"} for p in ("graph", "agents", "costs"))
    assert mv.build("nichts")["graph"]["available"] is False


def test_unknown_costs_stay_unknown_and_are_never_zero_or_estimated():
    c = mv.build(snap())["costs"]
    assert c["cost"] == "UNKNOWN" and c["llm_calls"] == 4 and c["limit_calls"] == 30
    c = mv.build(snap(costs={"cost": "viel", "tokens": -5, "llm_calls": True}))["costs"]
    assert c["cost"] == "UNKNOWN" and c["tokens"] == "UNKNOWN" and c["llm_calls"] == "UNKNOWN"
    assert mv.build(snap(costs={"cost": 0.42}))["costs"]["cost"] == 0.42


def test_secrets_are_redacted_and_texts_and_lists_are_bounded():
    view = mv.build(snap(errors=[{"code": "x", "text": f"token {SECRET} " + "y" * 5000}] * 500,
                         graph={"nodes": [{"id": f"n{i}", "label": SECRET, "status": "PENDING"} for i in range(400)]}))
    text = json.dumps(view)
    assert SECRET not in text and len(view["errors"]["items"]) == mv.MAX_ITEMS and view["errors"]["truncated"] is True
    assert len(view["graph"]["nodes"]) == mv.MAX_NODES and view["graph"]["truncated"] is True
    assert all(len(e["text"]) <= mv.MAX_TEXT for e in view["errors"]["items"])


def test_only_http_source_links_are_shown_as_links():
    s = mv.build(snap(sources=[{"title": "a", "url": "javascript:alert(1)"}, {"title": "b", "url": "file:///c:/x"}, {"title": "c", "url": "https://example.org/x"}]))["sources"]["items"]
    assert [i["url"] for i in s] == [None, None, "https://example.org/x"]


def test_approvals_are_display_only_and_carry_no_way_to_answer():
    a = mv.build(snap(approvals=[{"id": "ap1", "what": "x", "state": "pending", "approve_url": "/api/approve", "token": "t", "answer": "yes", "callback": "f"}]))["approvals"]
    assert a["display_only"] is True and a["pending"] == 1 and set(a["items"][0]) == {"id", "what", "level", "state"}
    assert mv.build(snap(approvals=[{"id": "x", "state": "approved_by_agent"}]))["approvals"]["items"][0]["state"] == "UNKNOWN"


def test_quality_is_only_accepted_on_an_explicit_true_without_open_points():
    q = mv.build(snap())["progress"]["quality"]
    assert q["accepted"] is False and q["failed"] == ["sources"] and q["unknown"] == ["calculations"]
    assert mv.build(snap(quality={"accepted": "yes"}))["progress"]["quality"]["accepted"] is False
    assert mv.build(snap(quality={"accepted": True, "failed": ["files"]}))["progress"]["quality"]["accepted"] is False
    assert mv.build(snap(quality={"accepted": True, "failed": [], "unknown": []}))["progress"]["quality"]["accepted"] is True


def test_input_is_not_modified_and_the_module_is_read_only():
    data = snap()
    before = json.dumps(data, sort_keys=True)
    mv.build(data)
    assert json.dumps(data, sort_keys=True) == before
    tree = ast.parse((ROOT / "src" / "jarvis" / "control_center" / "mission_view.py").read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "re", "typing", "jarvis.redaction"}, mods


def test_nothing_is_wired_into_the_server_or_the_web_page_yet():
    for rel in ("src/jarvis/control_center/server.py", "src/jarvis/control_center/web/app.js", "src/jarvis/control_center/web/index.html", "src/jarvis/bootstrap.py"):
        assert "mission_view" not in (ROOT / rel).read_text(encoding="utf-8"), rel
