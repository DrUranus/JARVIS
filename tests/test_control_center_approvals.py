"""WP07c: Freigabe-Panel (NEXUS, Premium-V2-Design): alle offenen Rueckfragen (aelteste zuerst, Frist, angebotene Auswahl) und der Verlauf aus /view/audit.
`confirm` bleibt der einzige Schreibweg; nichts wird automatisch erlaubt. Node-DOM (web/app.js unveraendert), Asset-Struktur (CSP) und Chromium-E2E (wenn Playwright vorhanden)."""
from __future__ import annotations

import json
import re

import pytest

from test_control_center_dashboard import NODE, WEB, ev, run_scenario, text

pytestmark_node = pytest.mark.skipif(NODE is None, reason="Node.js nicht installiert (nur fuer den DOM-Test)")


def req(i, choices=("allow_once", "deny"), tool="keyboard", action="type", level="yellow", reason="Text tippen", resource="keyboard://text@notepad.exe", timeout_s=60):
    return ev("confirmation_request", {"request_id": f"r{i}", "tool": tool, "action": action, "resource": resource, "level": level, "reason": reason,
                                       "context": [{"key": "fenster", "value": "Notepad"}], "choices": list(choices), "timeout_s": timeout_s})


def closed(i, outcome="denied"):
    return ev("confirmation_closed", {"request_id": f"r{i}", "outcome": outcome})


def audit_event(kind, i, **kw):
    e = {"id": f"a{i}", "timestamp": f"2026-11-12T10:0{i % 10}:0{i % 10}+00:00", "type": kind, "request_id": f"r{i}", "tool": "keyboard", "action": "type", "level": "yellow", "status": "pending"}
    e.update(kw)
    return e


def audit_view(items, available=True, reason=""):
    return {"available": available, "limit": 50, "filters": {}, "items": items, "reason": reason}


def snap(tmp_path, steps):
    return run_scenario(tmp_path, [*steps, {"snap": "s"}])["s"]


def entries(s):
    return s["items"]["approvals-list"]


def history(s):
    return s["items"]["approvals-history"]


# ---- Struktur (CSP, Design, nur vorhandene Endpunkte) -------------------------------------------------------------------------------------------------
def test_assets_have_the_approvals_panel_and_stay_inside_the_csp_rules():
    html, js, css = text("index.html"), text("app.js"), text("styles.css")
    for i in ("approvals-panel", "approvals-list", "approvals-note", "approvals-history", "approvals-history-note", "approvals-refresh"):
        assert f'id="{i}"' in html, i
    assert "renderApprovals" in js and "loadApprovalHistory" in js
    seg = js.split("function renderApprovals")[1].split("\n// ----")[0]
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", ".src =", "href", 'setAttribute("style"', "style.cssText", "THREE"):
        assert bad not in seg, bad
    assert " style=" not in html and "onclick" not in html and not re.search(r"https?://", css) and sorted(p.name for p in WEB.iterdir() if p.suffix == ".js") == ["app.js"]


def test_the_panel_adds_no_write_path_and_the_history_is_a_plain_get_of_the_audit_view():
    js = text("app.js")
    approvals = js.split("function renderApprovals")[1].split("\n// ----")[0]
    assert "send(" not in approvals and "answer(" not in approvals and 'createElement("button")' not in approvals and "addEventListener" not in approvals.split("async function loadApprovalHistory")[0]
    assert len(re.findall(r'send\("confirm"', js)) == 1                         # still exactly one place sends `confirm`: the dialog's answer()
    hist = js.split("async function loadApprovalHistory")[1].split("\nasync function ")[0].split("\nfunction ")[0]
    assert 'url("view/audit"' in hist and 'method: "GET"' in hist and "send(" not in hist and "POST" not in hist
    for field in ("detail", "resource", "extra"):
        assert f".{field}" not in hist and f'"{field}"' not in hist, field        # nur Zeit, Art, Werkzeug, Aktion, Stufe, Status, Regel


def test_state_colours_use_existing_tokens_and_motion_is_gated():
    css = text("styles.css")
    assert "#approvals-panel" in css
    for s in ("open", "confirmation_accepted", "confirmation_rejected", "confirmation_requested"):
        assert f'data-kind="{s}"' in css or s == "open", s
    for rule in (r for r in re.findall(r"[^{}]*\{[^}]*animation[^}]*\}", css.split("#approvals-panel", 1)[1]) if "animation: none" not in r):
        assert 'body[data-effects="full"]' in rule, rule


# ---- offene Anfragen (Node-DOM) ---------------------------------------------------------------------------------------------------------------------------
@pytestmark_node
def test_no_open_request_says_so(tmp_path):
    s = snap(tmp_path, [])
    assert entries(s) == [] and "keine offenen" in s["text"]["approvals-note"]


@pytestmark_node
@pytest.mark.parametrize("n", [1, 3])
def test_all_open_requests_are_listed_oldest_first_with_their_deadline(tmp_path, n):
    s = snap(tmp_path, [req(i, tool=f"tool{i}", reason=f"Grund {i}") for i in range(1, n + 1)])
    es = entries(s)
    assert len(es) == n and [("tool%d" % (i + 1)) in e["text"] for i, e in enumerate(es)] == [True] * n
    assert all("60 s" in e["text"] or "Frist" in e["text"] for e in es) and f"{n} offen" in s["text"]["approvals-note"]
    assert "tool1" in s["text"]["dlg-tool"]                         # the dialog still shows the first request


@pytestmark_node
def test_each_entry_names_only_the_choices_of_its_own_request_and_has_no_buttons(tmp_path):
    s = snap(tmp_path, [req(1, choices=("deny",)), req(2, choices=("allow_session", "allow_once", "deny"))])
    es = entries(s)
    assert "angeboten: Ablehnen" in es[0]["text"] and "Einmal erlauben" not in es[0]["text"]
    assert "angeboten: Ablehnen, Einmal erlauben, Fuer die Sitzung erlauben" in es[1]["text"]
    assert s["buttons"]["approvals-list"] == [] and s["sent"] == []       # the list only displays; answering stays in the modal dialog


@pytestmark_node
def test_answering_still_works_only_through_the_dialog_and_sends_one_confirm(tmp_path):
    s = snap(tmp_path, [req(1), req(2), {"click": {"id": "dlg-choices", "text": "Ablehnen"}}])
    confirms = [c for c in s["sent"] if c["type"] == "confirm"]
    assert len(confirms) == 1 and confirms[0]["data"] == {"request_id": "r1", "choice": "deny"}


@pytestmark_node
def test_closed_requests_leave_the_list_and_a_lost_connection_clears_it(tmp_path):
    s = snap(tmp_path, [req(1, tool="erstes"), req(2, tool="zweites"), closed(1)])
    assert len(entries(s)) == 1 and "zweites" in entries(s)[0]["text"] and "erstes" not in entries(s)[0]["text"]
    s = snap(tmp_path, [req(1), req(2), {"disconnect": True}])
    assert entries(s) == [] and "keine offenen" in s["text"]["approvals-note"]


@pytestmark_node
def test_hostile_request_text_is_only_ever_text(tmp_path):
    evil = '<img src=x onerror=alert(1)>"; </script>'
    s = snap(tmp_path, [req(1, tool=evil, action=evil, reason=evil, resource=evil)])
    assert evil in entries(s)[0]["text"]


@pytestmark_node
def test_the_emergency_button_stays_reachable_and_effective_with_requests_open(tmp_path):
    s = snap(tmp_path, [req(1), req(2), {"clickId": "emergency"}])
    assert [c["type"] for c in s["sent"]] == ["emergency_stop"] and s["props"]["emergency"]["disabled"] is False


@pytestmark_node
def test_nothing_is_ever_answered_without_a_click(tmp_path):
    s = snap(tmp_path, [req(1), req(2), req(3), {"wait": True}, {"frames": [0, 1000, 120000]}])
    assert s["sent"] == []


@pytestmark_node
def test_escape_still_denies_the_first_request_only(tmp_path):
    s = snap(tmp_path, [req(1), req(2), {"key": "Escape"}])
    confirms = [c for c in s["sent"] if c["type"] == "confirm"]
    assert len(confirms) == 1 and confirms[0]["data"] == {"request_id": "r1", "choice": "deny"}


# ---- Verlauf (Audit, geschwaerzt) -----------------------------------------------------------------------------------------------------------------------
@pytestmark_node
def test_history_requests_the_three_confirmation_types_with_get_only(tmp_path):
    s = snap(tmp_path, [{"views": {"audit": audit_view([])}}, {"clickId": "approvals-refresh"}])
    urls = s["fetchedUrls"]
    assert len(urls) == 3 and all(u.startswith("view/audit?") and "t=TESTTOKEN" in u for u in urls) and s["sent"] == []
    assert {re.search(r"type=([a-z_]+)", u).group(1) for u in urls} == {"confirmation_requested", "confirmation_accepted", "confirmation_rejected"}


@pytestmark_node
def test_history_shows_only_the_redacted_summary_fields(tmp_path):
    secret = "sk-HISTORY-SECRET-DETAIL-123456"
    items = [audit_event("confirmation_accepted", 3, detail=secret, resource=secret, extra={"k": secret}, rule="r-allow")]
    s = snap(tmp_path, [{"views": {"audit": audit_view(items)}}, {"clickId": "approvals-refresh"}])
    h = history(s)
    assert h and secret not in json.dumps(s["text"]) and "keyboard" in h[0]["text"] and "type" in h[0]["text"] and "yellow" in h[0]["text"]
    assert h[0]["dataset"]["kind"] == "confirmation_accepted"


@pytestmark_node
def test_history_is_merged_newest_first_and_capped(tmp_path):
    items = [audit_event("confirmation_requested", i % 10, id=f"a{i}", timestamp=f"2026-11-12T10:{i // 60:02d}:{i % 60:02d}+00:00") for i in range(150)]
    s = snap(tmp_path, [{"views": {"audit": audit_view(items)}}, {"clickId": "approvals-refresh"}])
    assert len(history(s)) == 100 and "weitere" in s["text"]["approvals-history-note"]
    times = [re.search(r"\d\d:\d\d:\d\d", e["text"]).group(0) for e in history(s)]
    assert times == sorted(times, reverse=True)


@pytestmark_node
def test_history_without_audit_shows_the_reason_not_an_error(tmp_path):
    s = snap(tmp_path, [{"views": {"audit": audit_view([], available=False, reason="Kein Audit-Protokoll aktiv (security.audit_enabled = false).")}}, {"clickId": "approvals-refresh"}])
    assert "Kein Audit-Protokoll" in s["text"]["approvals-history-note"] and history(s) == []


@pytestmark_node
def test_history_reloads_when_a_request_closes_but_at_most_once_per_second(tmp_path):
    steps = [{"views": {"audit": audit_view([audit_event("confirmation_rejected", 1)])}}]
    for i in range(1, 11):
        steps += [req(i), closed(i)]
    s = snap(tmp_path, [*steps, {"wait": True}])
    assert s["fetched"].count("audit") == 3                           # one refresh (three types) for all ten closings within the same second


@pytestmark_node
def test_existing_dashboard_and_dialog_are_untouched(tmp_path):
    s = snap(tmp_path, [req(1)])
    assert s["props"]["confirm-dialog"]["hidden"] is False and s["buttons"]["dlg-choices"][0] == "Ablehnen"
    assert "keyboard" in s["text"]["confirmation"]


# ---- Chromium-E2E ----------------------------------------------------------------------------------------------------------------------------------------
def test_e2e_open_request_is_listed_answered_and_the_emergency_button_works(tmp_path):
    pytest.importorskip("playwright.sync_api", reason="playwright fehlt: Browser-E2E nicht moeglich (ein uebersprungener Test gilt nicht als bestanden)")
    import os
    import time
    from playwright import sync_api as pw_api
    from jarvis.control_center.server import ControlCenterServer
    from jarvis.control_center.views import ReadViews
    from jarvis.ui_contract import FakeUiBackend

    backend = FakeUiBackend()
    audit = [audit_event("confirmation_requested", 1)]
    srv = ControlCenterServer(backend, poll_interval=0.02, views=ReadViews(audit_tail=lambda n: list(audit)[-n:]))
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
            if page.evaluate("document.body.dataset.mode") == "orb":
                page.click("#mode-toggle")
            page.fill("#input", "!confirm")
            page.press("#input", "Enter")
            page.wait_for_selector("#approvals-list li")
            assert page.evaluate("document.querySelectorAll('#approvals-list li').length") == 1
            assert page.evaluate("document.querySelectorAll('#approvals-list li button').length") == 0
            page.click("#dlg-choices button[data-choice=deny]")
            page.wait_for_selector("#approvals-list li", state="detached")
            page.click("#approvals-refresh")
            end = time.monotonic() + 10
            while time.monotonic() < end and page.evaluate("document.querySelectorAll('#approvals-history li').length") < 1:
                time.sleep(0.05)
            assert page.evaluate("document.querySelectorAll('#approvals-history li').length") >= 1
            assert page.evaluate("document.querySelector('#approvals-note').textContent").startswith("keine offenen")
            page.fill("#input", "!confirm")
            page.press("#input", "Enter")
            page.wait_for_selector("#approvals-list li")
            page.click("#emergency")                                       # NOT-AUS bei offenem Panel
            end = time.monotonic() + 10
            while time.monotonic() < end and not backend._emergency_on:
                time.sleep(0.05)
            assert backend._emergency_on is True and not errors, errors
            browser.close()
    finally:
        srv.stop()
