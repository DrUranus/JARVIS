"""WP07b: Aufgaben-Zeitleiste (NEXUS, Premium-V2-Design). Reine, lesende Anzeige aus `/view/agents`; K4: DOM-Liste statt Canvas.
Node-DOM (web/app.js unveraendert), Asset-Struktur (CSP: kein Inline-Code, kein innerHTML, kein Three.js) und ein Chromium-E2E (wenn Playwright vorhanden)."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
from pathlib import Path

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


# ---- Chromium-E2E (nur mit Playwright) --------------------------------------------------------------------------------------------------------------
def test_e2e_timeline_colours_update_after_an_event_and_render_time_is_logged(tmp_path):
    pytest.importorskip("playwright.sync_api", reason="playwright fehlt: Browser-E2E nicht moeglich (ein uebersprungener Test gilt nicht als bestanden)")
    import os
    from playwright import sync_api as pw_api
    from jarvis.control_center.server import ControlCenterServer
    from jarvis.control_center.views import ReadViews
    from jarvis.ui_contract import FakeUiBackend

    state = {"tasks": [task(i, s, started_at=f"2026-11-12T10:0{i}:00+00:00") for i, s in enumerate(STATES, start=1)]}
    views = ReadViews(agents_source=lambda limit: {"agents": [{"id": "research", "status": "AVAILABLE", "capabilities": ["research.web"], "reason": ""}], "tasks": list(state["tasks"])})
    backend = FakeUiBackend()
    srv = ControlCenterServer(backend, poll_interval=0.02, views=views)
    srv.start()
    try:
        with pw_api.sync_playwright() as pw:
            exe = os.environ.get("JARVIS_CHROMIUM_PATH")
            try:
                browser = pw.chromium.launch(headless=True, executable_path=exe) if exe else pw.chromium.launch(headless=True)
            except pw_api.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Chromium fehlt: nicht ausgefuehrt, ein uebersprungener Test gilt nicht als bestanden")
                raise
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{srv.port}/?t={srv.token}")
            page.click("#mode-toggle") if page.evaluate("document.body.dataset.mode") == "orb" else None
            t0 = time.perf_counter()
            page.click("#timeline-refresh")
            end = time.monotonic() + 10
            while time.monotonic() < end and page.evaluate("document.querySelectorAll('#timeline-list li').length") < len(STATES):
                time.sleep(0.05)
            render_s = time.perf_counter() - t0
            colours = page.evaluate("Array.from(document.querySelectorAll('#timeline-list li')).map(li => [li.dataset.status, getComputedStyle(li, '::before').backgroundColor || getComputedStyle(li).borderLeftColor])")
            assert [c[0] for c in colours] == [s.lower() for s in STATES]
            assert len({c[1] for c in colours}) >= 5                            # the six states are told apart by colour (queued/cancelled may share the neutral tone)
            state["tasks"].insert(0, task(9, "FAILED", started_at="2026-11-12T10:09:00+00:00"))
            backend._emit("task_update", {"kind": "agent_task", "id": "at-0009", "status": "FAILED", "detail": "x"})
            end = time.monotonic() + 10
            while time.monotonic() < end and page.evaluate("document.querySelectorAll('#timeline-list li').length") < len(STATES) + 1:
                time.sleep(0.05)
            assert page.evaluate("document.querySelectorAll('#timeline-list li').length") == len(STATES) + 1
            assert not errors, errors
            ev_dir = Path(os.environ.get("JARVIS_GUI_EVIDENCE", Path(__file__).resolve().parents[1] / "reports" / "gui")) / "e2e"
            ev_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(ev_dir / "wp07b_timeline.png"))
            print(f"WP07b timeline: first render {render_s * 1000:.0f} ms for {len(STATES)} entries (measured, no threshold: owner number open)")
            browser.close()
    finally:
        srv.stop()


# ---- E10: Leistung (Zielwert: 100 Eintraege, erste Darstellung unter 500 ms) ------------------------------------------------------------------------
PERF_BUDGET_MS = 500.0
PERF_ENTRIES = 100
PERF_RUNS = 3


def test_e2e_first_display_of_100_entries_stays_under_the_e10_target_and_is_recorded(tmp_path):
    pytest.importorskip("playwright.sync_api", reason="playwright fehlt: Browser-E2E nicht moeglich (ein uebersprungener Test gilt nicht als bestanden)")
    import os
    import platform
    from playwright import sync_api as pw_api
    from jarvis.control_center.server import ControlCenterServer
    from jarvis.control_center.views import ReadViews
    from jarvis.ui_contract import FakeUiBackend

    tasks = [task(i, STATES[i % len(STATES)], objective=f"Aufgabe {i} " + "x" * 120, started_at=f"2026-11-12T10:{i // 60:02d}:{i % 60:02d}+00:00", dependencies=[f"at-{i - 1:04d}"] if i else []) for i in range(PERF_ENTRIES)]
    views = ReadViews(agents_source=lambda limit: {"agents": [], "tasks": list(tasks)})
    srv = ControlCenterServer(FakeUiBackend(), poll_interval=0.02, views=views)
    srv.start()
    runs: list[dict[str, float]] = []
    try:
        with pw_api.sync_playwright() as pw:
            exe = os.environ.get("JARVIS_CHROMIUM_PATH")
            try:
                browser = pw.chromium.launch(headless=True, executable_path=exe) if exe else pw.chromium.launch(headless=True)
            except pw_api.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Chromium fehlt: nicht ausgefuehrt, ein uebersprungener Test gilt nicht als bestanden")
                raise
            version = browser.version
            for _ in range(PERF_RUNS):
                page = browser.new_page(viewport={"width": 1440, "height": 900})        # every run is a cold page: first display, not a warm update
                page.goto(f"http://127.0.0.1:{srv.port}/?t={srv.token}")
                if page.evaluate("document.body.dataset.mode") == "orb":
                    page.click("#mode-toggle")
                measured = page.evaluate("""async (want) => {
                  const ul = document.getElementById('timeline-list'); const t0 = performance.now();
                  document.getElementById('timeline-refresh').click();
                  await new Promise((res) => { const check = () => (ul.children.length >= want ? res() : requestAnimationFrame(check)); check(); });
                  const first = performance.now() - t0;
                  const data = await (await fetch(url('view/agents', 0, { limit: '100' }), { method: 'GET' })).json();
                  const r0 = performance.now(); renderTimeline(data); const render = performance.now() - r0;
                  return { first_display_ms: first, render_only_ms: render, rows: ul.children.length };
                }""", PERF_ENTRIES)
                assert measured["rows"] == PERF_ENTRIES
                runs.append(measured)
                page.close()
            browser.close()
    finally:
        srv.stop()
    evidence = {"entries": PERF_ENTRIES, "target_ms": PERF_BUDGET_MS, "runs": runs, "chromium": version, "platform": platform.platform(), "python": platform.python_version(), "cpus": os.cpu_count(),
                "note": "cold page, headless Chromium against the real loopback server with a fake agents source; click -> 100 rows in the DOM. Not a native-window or real-hardware measurement."}
    out = Path(os.environ.get("JARVIS_GUI_EVIDENCE", Path(__file__).resolve().parents[1] / "reports" / "gui")) / "e2e"
    out.mkdir(parents=True, exist_ok=True)
    (out / "wp07b_timeline_perf.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print("E10 timeline perf:", json.dumps(evidence))
    assert runs[0]["first_display_ms"] < PERF_BUDGET_MS, evidence                  # the FIRST (coldest) run decides; all runs are recorded
