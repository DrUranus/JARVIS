"""WP07b: Aufgaben-Zeitleiste (NEXUS, Premium-V2-Design). Reine, lesende Anzeige aus `/view/agents`; K4: DOM-Liste statt Canvas.
Node-DOM (web/app.js unveraendert) und Asset-Struktur (CSP: kein Inline-Code, kein innerHTML, kein Three.js). Die Chromium-E2E-Faelle und die Leistungsmessung (E10) stehen in tests/test_control_center_e2e_browser.py: dort laufen sie im Workflow \"Control Center GUI E2E\" mit Playwright (Linux und Windows), nicht als Einzel-Skip im normalen Lauf."""
from __future__ import annotations

import json
import re

import pytest

from test_control_center_dashboard import NODE, WEB, activity, ev, item, run_scenario, text

pytestmark_node = pytest.mark.skipif(NODE is None, reason="Node.js nicht installiert (nur fuer den DOM-Test)")

STATES = ["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"]


def task(i, status="RUNNING", agent="research", objective="Preise suchen", **kw):
    t = {"task_id": f"at-{i:04d}", "agent_id": agent, "status": status, "objective": objective, "summary": "", "dependencies": [], "timed_out": False, "cancel_requested": False}
    t.update(kw)
    return t


def agents_view(*tasks, available=True, reason="", agents=None):
    return {"available": available, "limit": 50, "filters": {"agent": None, "status": None}, "agents": agents or [], "items": list(tasks), "reason": reason}


def snap(tmp_path, steps):
    return run_scenario(tmp_path, [*steps, {"snap": "s"}])["s"]


def rows(s):
    return s["props"]["timeline-list"]


# ---- Struktur (CSP, Design, keine neue Bibliothek) -------------------------------------------------------------------------------------------------
def test_assets_have_the_timeline_panel_and_stay_inside_the_csp_rules():
    html, js, css = text("index.html"), text("app.js"), text("styles.css")
    for i in ("timeline-panel", "timeline-list", "timeline-note", "timeline-refresh"):
        assert f'id="{i}"' in html, i
    assert "renderTimeline" in js and "loadTimeline" in js
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", ".src =", "href", 'setAttribute("style"', "setAttribute('style'", "style.cssText", "three", "THREE"):
        assert bad not in js.split("function renderTimeline")[1].split("\nfunction ")[0], bad
    assert "<script" not in html.replace('<script src="app.js?t=__TOKEN__"></script>', "") and " style=" not in html and "onclick" not in html
    assert not re.search(r"@import|url\(http|https?://", css)
    assert not list(WEB.glob("*.min.js")) and sorted(p.name for p in WEB.iterdir() if p.suffix == ".js") == ["app.js"]


def test_the_timeline_only_reads_the_agents_view_with_get():
    js = text("app.js")
    body = js.split("async function loadTimeline")[1].split("\nasync function ")[0].split("\nfunction ")[0]
    assert 'url("view/agents"' in body and 'method: "GET"' in body
    assert "send(" not in body and "POST" not in body and "confirm" not in body.lower() and "emergency" not in body.lower()


def test_status_colours_use_the_existing_design_tokens_and_motion_is_gated():
    css = text("styles.css")
    for s in ("pending", "running", "succeeded", "failed", "blocked", "cancelled"):
        assert re.search(rf"#timeline-list li\[data-status=\"{s}\"\]", css), s
    anim = re.findall(r"[^{}]*\{[^}]*animation[^}]*\}", css.split("#timeline-panel", 1)[1]) if "#timeline-panel" in css else []
    for rule in (r for r in anim if "animation: none" not in r):                      # jede Animation der Zeitleiste nur bei Effektstufe full
        assert 'body[data-effects="full"]' in rule, rule
    assert "prefers-reduced-motion" in css or "data-effects" in css


# ---- DOM (Node) -------------------------------------------------------------------------------------------------------------------------------------
def entries(s):
    return s["items"]["timeline-list"]


@pytestmark_node
def test_empty_state_explains_itself(tmp_path):
    s = snap(tmp_path, [{"views": {"agents": agents_view()}}, {"clickId": "timeline-refresh"}])
    assert entries(s) == [] and "keine Aufgaben" in s["text"]["timeline-note"]
    assert s["fetched"] == ["agents"]


@pytestmark_node
def test_unavailable_agent_layer_shows_the_reason_not_an_error(tmp_path):
    s = snap(tmp_path, [{"views": {"agents": agents_view(available=False, reason="Die Agentenschicht ist nicht aktiv (agents.enabled = false).")}}, {"clickId": "timeline-refresh"}])
    assert "nicht aktiv" in s["text"]["timeline-note"] and entries(s) == []


@pytestmark_node
@pytest.mark.parametrize("status", STATES)
def test_each_state_gets_its_own_status_marker_and_text(tmp_path, status):
    s = snap(tmp_path, [{"views": {"agents": agents_view(task(1, status, objective="Eine Aufgabe"))}}, {"clickId": "timeline-refresh"}])
    (e,) = entries(s)
    assert e["dataset"]["status"] == status.lower() and "Eine Aufgabe" in e["text"] and "research" in e["text"]


@pytestmark_node
def test_unknown_status_is_shown_neutral_never_as_success(tmp_path):
    s = snap(tmp_path, [{"views": {"agents": agents_view(task(1, "WEIRD"))}}, {"clickId": "timeline-refresh"}])
    assert entries(s)[0]["dataset"]["status"] == "unknown"


@pytestmark_node
def test_oldest_first_with_times_and_dependencies(tmp_path):
    newest_first = agents_view(task(3, "RUNNING", started_at="2026-11-12T10:03:00+00:00"),
                               task(2, "SUCCEEDED", started_at="2026-11-12T10:02:00+00:00", finished_at="2026-11-12T10:02:30+00:00", dependencies=["at-0001"]),
                               task(1, "SUCCEEDED", started_at="2026-11-12T10:01:00+00:00", finished_at="2026-11-12T10:01:30+00:00"))
    s = snap(tmp_path, [{"views": {"agents": newest_first}}, {"clickId": "timeline-refresh"}])
    texts = [e["text"] for e in entries(s)]
    assert ["at-0001" in texts[0], "at-0002" in texts[1], "at-0003" in texts[2]] == [True, True, True]
    assert "10:02:00" in texts[1] and "10:02:30" in texts[1] and "at-0001" in texts[1].split("abhaengig")[-1]


@pytestmark_node
@pytest.mark.parametrize("n,shown", [(1, 1), (50, 50), (100, 100), (500, 100)])
def test_visible_entries_are_capped_with_a_rest_note(tmp_path, n, shown):
    many = agents_view(*[task(i, "SUCCEEDED") for i in range(n, 0, -1)])
    s = snap(tmp_path, [{"views": {"agents": many}}, {"clickId": "timeline-refresh"}])
    assert len(entries(s)) == shown
    if n > shown:
        assert f"+{n - shown} weitere" in s["text"]["timeline-note"]


@pytestmark_node
def test_hostile_text_is_only_ever_text(tmp_path):
    evil = '<img src=x onerror=alert(1)>"; </script>'
    s = snap(tmp_path, [{"views": {"agents": agents_view(task(1, "FAILED", objective=evil, agent=evil, summary=evil, error_code=evil))}}, {"clickId": "timeline-refresh"}])
    (e,) = entries(s)
    assert evil in e["text"]
    assert e["dataset"]["status"] == "failed"


@pytestmark_node
def test_a_failed_request_keeps_the_page_alive(tmp_path):
    s = snap(tmp_path, [{"views": {"agents": None}}, {"clickId": "timeline-refresh"}])
    assert s["text"]["timeline-note"] == "nicht abrufbar" and entries(s) == []


@pytestmark_node
def test_a_task_event_reloads_the_timeline_but_at_most_once_per_second(tmp_path):
    steps = [{"views": {"agents": agents_view(task(1))}}]
    for i in range(30):
        steps.append(ev("task_update", {"kind": "agent_task", "id": f"at-{i:04d}", "status": "RUNNING", "detail": ""}))
    s = snap(tmp_path, [*steps, {"wait": True}])
    assert s["fetched"].count("agents") == 1                       # the other 29 events fall into the same second
    assert len(entries(s)) == 1


@pytestmark_node
def test_events_that_are_not_task_events_do_not_fetch(tmp_path):
    s = snap(tmp_path, [{"views": {"agents": agents_view(task(1))}}, ev("chat", {"sender": "jarvis", "text": "hallo"}), ev("state", {"state": "ready", "detail": ""})])
    assert s["fetched"] == []


@pytestmark_node
def test_refresh_sends_get_only_and_no_command(tmp_path):
    s = snap(tmp_path, [{"views": {"agents": agents_view(task(1))}}, {"clickId": "timeline-refresh"}])
    assert s["sent"] == [] and s["fetchedUrls"][0].startswith("view/agents?") and "t=TESTTOKEN" in s["fetchedUrls"][0] and "limit=" in s["fetchedUrls"][0]


@pytestmark_node
def test_effect_mode_off_draws_the_same_entries_without_animation_classes(tmp_path):
    base = [{"views": {"agents": agents_view(task(1, "RUNNING"))}}, {"clickId": "timeline-refresh"}]
    off = snap(tmp_path, [{"effects": "off"}, *base])
    full = snap(tmp_path, [{"effects": "full"}, *base])
    assert entries(off)[0]["text"] == entries(full)[0]["text"] and "anim" not in entries(off)[0]["className"] and off["effects"] == "off"


@pytestmark_node
def test_existing_dashboard_panels_and_the_emergency_button_are_untouched(tmp_path):
    s = snap(tmp_path, [{"views": {"agents": agents_view(task(1))}}, {"clickId": "timeline-refresh"}, activity(item("t1"))])
    assert "t1" in s["text"]["task-list"] or "Aufgabe" in s["text"]["task-list"]
    s2 = snap(tmp_path, [{"clickId": "emergency"}])
    assert [c["type"] for c in s2["sent"]] == ["emergency_stop"]
