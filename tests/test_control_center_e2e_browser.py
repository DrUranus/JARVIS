"""Browser-E2E des Control Centers (NEXUS Premium V2) in echtem Chromium gegen den echten Loopback-Server.

Was das ist: DOM, Canvas-Pixel, Klicks, Tastatur, SSE und POST laufen wirklich in einem Browser (headless Chromium). Backends: das deterministische `FakeUiBackend` (X0-Vertrag)
und die ECHTE Engine (build_core mit Mock-LLM, Notaus/PermissionEngine) fuer den Notaus. Was das NICHT ist: keine native pywebview-Fensterpruefung (Fokus, Always-on-Top,
Overlay als eigenes Fenster) und kein interaktiver Windows-Desktop; diese Abnahme bleibt Issue #186 (docs/WINDOWS_GUI_AUTOMATION.md). Kein Netzwerk ausser Loopback.

Voraussetzung: `pip install playwright` und ein Chromium (`python -m playwright install chromium` oder JARVIS_CHROMIUM_PATH). Ohne Playwright wird uebersprungen; ein
uebersprungener Test gilt nie als bestanden (die CI-Jobs pruefen im JUnit-Bericht, dass nichts uebersprungen wurde). Beweise (Screenshots) landen in JARVIS_GUI_EVIDENCE
(Standard reports/gui)."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="playwright fehlt: Browser-E2E nicht moeglich (ein uebersprungener Test gilt nicht als bestanden)")

from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("JARVIS_GUI_EVIDENCE", ROOT / "reports" / "gui")) / "e2e"
HUE_JS = """(id) => {
  const c = document.getElementById(id), g = c.getContext('2d'), d = g.getImageData(0, 0, c.width, c.height).data;
  const bins = {green: 0, teal: 0, blue: 0, violet: 0, gold: 0, red: 0}, total = {n: 0};
  for (let i = 0; i < d.length; i += 4) {
    const a = d[i + 3]; if (a < 40) continue;
    const r = d[i] / 255, gr = d[i + 1] / 255, b = d[i + 2] / 255, mx = Math.max(r, gr, b), mn = Math.min(r, gr, b), v = mx, s = mx ? (mx - mn) / mx : 0;
    if (s < 0.5 || v < 0.45) continue;
    let h = 0; const df = mx - mn;
    if (mx === r) h = ((gr - b) / df) % 6; else if (mx === gr) h = (b - r) / df + 2; else h = (r - gr) / df + 4;
    h = (h * 60 + 360) % 360; const w = a / 255; total.n += w;
    if (h >= 85 && h < 160) bins.green += w; else if (h >= 160 && h < 195) bins.teal += w; else if (h >= 195 && h < 245) bins.blue += w;
    else if (h >= 245 && h < 300) bins.violet += w; else if (h >= 30 && h < 60) bins.gold += w; else if (h >= 340 || h < 15) bins.red += w;
  }
  return Object.assign(bins, {opaque: total.n});
}"""


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as pw:
        exe = os.environ.get("JARVIS_CHROMIUM_PATH")
        b = pw.chromium.launch(headless=True, executable_path=exe) if exe else pw.chromium.launch(headless=True)
        yield b
        b.close()


def until(page, expr, timeout=10.0):
    """Wartet, bis der JS-Ausdruck wahr ist. Nutzt page.evaluate (CDP): die strenge CSP der Seite bleibt unveraendert wirksam (wait_for_function wertet Strings per eval aus)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if page.evaluate(expr):
            return
        time.sleep(0.05)
    raise AssertionError(f"Bedingung nicht erreicht: {expr}")


class Gui:
    """Server (Fake-Backend) plus eine Browserseite; sammelt JS-Fehler und alle Netzwerkziele."""

    def __init__(self, browser, backend=None, *, viewport=(1440, 900), on_open_main=None, query="", **ctx):
        self.backend = backend or FakeUiBackend()
        self.srv = ControlCenterServer(self.backend, poll_interval=0.02, on_open_main=on_open_main)
        self.srv.start()
        self.context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, **ctx)
        self.page = self.context.new_page()
        self.errors: list[str] = []
        self.hosts: set[str] = set()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.bad: list[str] = []
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
        self.page.on("response", lambda r: self.bad.append(f"{r.status} {r.url}") if r.status >= 400 and not r.url.endswith("/favicon.ico") else None)     # der Browser fragt selbststaendig /favicon.ico (ohne Token: 401, gewollt)
        self.page.on("request", lambda r: self.hosts.add(re.sub(r"^\w+://([^/:]+).*$", r"\1", r.url)) if r.url.startswith(("http", "ws")) else None)
        self.page.goto(self.srv.url + query, wait_until="domcontentloaded")
        until(self.page, "document.body.dataset.conn === 'open'", 10.0)

    def state(self, expected, timeout=10000):
        until(self.page, f"document.body.dataset.state === '{expected}'", timeout / 1000)

    def shot(self, name):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(EVIDENCE / f"{name}.png"))

    def hues(self, canvas="orb"):
        return self.page.evaluate(HUE_JS, canvas)

    def close(self):
        self.context.close()
        self.srv.stop()


@pytest.fixture
def gui(browser):
    g = Gui(browser)
    yield g
    assert not g.errors, f"JavaScript-/Konsolenfehler: {g.errors}"
    assert not g.bad, f"fehlgeschlagene Anfragen: {g.bad}"
    assert g.hosts <= {"127.0.0.1"}, f"externe Netzwerkziele: {g.hosts}"          # keine externen Ressourcen
    g.close()


def greenish(h):
    return h["green"] + h["teal"]


# ---- Orb, Zustandsfarben, 3D-Darstellung ---------------------------------------------------------------------------------------------------
def test_starts_in_orb_mode_with_a_drawn_core_and_the_reported_state(gui):
    p = gui.page
    assert p.locator("body").get_attribute("data-mode") == "orb"
    gui.state("ready")
    assert p.locator("#orb").is_visible() and p.locator("#emergency").is_visible()
    assert "bereit" in p.locator("#orb-state").inner_text().lower()
    h = gui.hues()
    assert h["opaque"] > 5000, h                                                      # die Kugel ist wirklich gezeichnet (nicht leer)
    assert greenish(h) > 20000 and greenish(h) > h["blue"] and h["gold"] + h["red"] < 500       # bereit = gruen
    assert h["blue"] > 5000                                                           # die violett-blaue Kugel bleibt sichtbar
    gui.shot("orb_ready")


def test_state_colors_follow_the_backend_for_listening_confirmation_and_emergency(gui):
    p = gui.page
    gui.state("ready")
    ready = gui.hues()
    p.click("#voice-start")
    gui.state("listening")
    p.wait_for_timeout(300)
    listening = gui.hues()
    assert listening["blue"] > 2 * greenish(listening) and greenish(listening) < 500 and listening["blue"] > ready["blue"]      # hoert zu = blau
    gui.shot("orb_listening")
    p.click("#voice-stop")
    gui.state("ready")
    p.fill("#input", "!confirm")
    p.press("#input", "Enter")
    gui.state("awaiting_confirmation")
    p.wait_for_timeout(300)
    h = gui.hues()
    assert h["gold"] > h["blue"] + h["violet"] and h["gold"] > 20000                  # Rueckfrage = gold
    gui.shot("orb_awaiting_confirmation")
    p.click("#emergency")                                                             # der Notaus ist auch mit offenem Dialog erreichbar
    gui.state("emergency")
    p.wait_for_timeout(300)
    h = gui.hues()
    assert h["red"] > 10000 and h["red"] > h["gold"] and greenish(h) < 500            # Notaus = rot
    gui.shot("orb_emergency")


def test_core_is_animated_in_full_mode_and_static_in_the_2d_fallback(gui):
    p = gui.page
    gui.state("ready")
    first = p.evaluate("document.getElementById('orb').toDataURL()")
    p.wait_for_timeout(700)
    assert p.evaluate("document.getElementById('orb').toDataURL()") != first          # voll: bewegt sich
    p.select_option("#effects", "off")
    until(p, "document.body.dataset.effects === 'off'")
    flat = p.evaluate("document.getElementById('orb').toDataURL()")
    p.wait_for_timeout(500)
    assert p.evaluate("document.getElementById('orb').toDataURL()") == flat           # 2D-Fallback: statisch
    assert p.evaluate(HUE_JS, "orb")["opaque"] > 3000                                 # und trotzdem sichtbar
    gui.shot("orb_fallback_2d")
    p.select_option("#effects", "reduced")
    until(p, "document.body.dataset.effects === 'reduced'")
    gui.shot("orb_reduced")


def test_system_reduced_motion_forces_the_static_fallback(browser):
    g = Gui(browser, reduced_motion="reduce")
    try:
        g.state("ready")
        assert g.page.locator("body").get_attribute("data-effects") == "off"
        a = g.page.evaluate("document.getElementById('orb').toDataURL()")
        g.page.wait_for_timeout(500)
        assert g.page.evaluate("document.getElementById('orb').toDataURL()") == a
        assert not g.errors
    finally:
        g.close()


# ---- Orb <-> Dashboard, Live-Daten, Chat ---------------------------------------------------------------------------------------------------
def test_manual_switch_between_orb_and_dashboard_and_live_status(gui):
    p = gui.page
    gui.state("ready")
    p.click("#mode-toggle")
    assert p.locator("body").get_attribute("data-mode") == "dashboard"
    for pane in ("#agents-panel", "#status-panel", "#tasks-panel", "#orb-mini"):
        assert p.locator(pane).is_visible(), pane
    assert p.locator("#st-conn").inner_text() == "verbunden" and p.locator("#st-emergency").inner_text() == "nicht aktiv"
    assert p.locator("#st-confirm").inner_text() == "keine"
    p.fill("#input", "!task")
    p.press("#input", "Enter")
    until(p, "document.getElementById('st-tasks').textContent.startsWith('1 aktiv')")     # echte Aktivitaet des Backends
    assert "Testaufgabe" in p.locator("#task-list").inner_text()
    assert "Aufgabe" in p.locator("#chat").inner_text()
    gui.shot("dashboard_task")
    p.click("#mode-toggle")
    assert p.locator("body").get_attribute("data-mode") == "orb" and p.locator("#orb").is_visible()


def test_chat_roundtrip_shows_user_and_backend_messages(gui):
    p = gui.page
    gui.state("ready")
    p.click("#mode-toggle")
    p.fill("#input", "Hallo JARVIS")
    p.click("#input-form button[type=submit]")
    until(p, "document.getElementById('chat').textContent.includes('Echo: Hallo JARVIS')")
    text = p.locator("#chat").inner_text()
    assert "user: Hallo JARVIS" in text and p.locator("#input").input_value() == ""


def test_task_can_be_cancelled_and_the_real_answer_is_shown(gui):
    p = gui.page
    gui.state("ready")
    p.click("#mode-toggle")
    p.fill("#input", "!task")
    p.press("#input", "Enter")
    p.get_by_role("button", name="Abbrechen").click()
    until(p, "document.getElementById('task-detail').textContent.includes('abgebrochen')")
    until(p, "document.getElementById('st-tasks').textContent.startsWith('0 aktiv')")


# ---- Freigabedialog (fail-closed) ----------------------------------------------------------------------------------------------------------
def open_confirmation(gui):
    gui.page.fill("#input", "!confirm")
    gui.page.press("#input", "Enter")
    gui.page.wait_for_selector("#confirm-dialog:not([hidden])")


def test_confirmation_dialog_defaults_to_deny_and_escape_denies(gui):
    p = gui.page
    gui.state("ready")
    open_confirmation(gui)
    gui.shot("confirmation_dialog")
    assert "keyboard" in p.locator("#dlg-tool").inner_text() and p.locator("body").get_attribute("data-pending") == "yes"
    buttons = p.locator("#dlg-choices button")
    assert buttons.first.get_attribute("data-choice") == "deny"                       # Ablehnen steht zuerst
    assert p.evaluate("document.activeElement && document.activeElement.dataset.choice") == "deny"     # und hat den Fokus
    p.keyboard.press("Enter")                                                         # Enter bestaetigt nie: es loest nur den fokussierten Knopf (deny) aus
    p.wait_for_selector("#confirm-dialog", state="hidden")
    until(p, "document.getElementById('chat').textContent.includes('Abgelehnt')")
    assert "Bestätigt" not in p.locator("#chat").inner_text()
    open_confirmation(gui)
    p.keyboard.press("Escape")
    p.wait_for_selector("#confirm-dialog", state="hidden")
    until(p, "(document.getElementById('chat').textContent.match(/Abgelehnt/g) || []).length === 2")


def test_confirmation_allow_once_is_sent_only_on_an_explicit_click(gui):
    p = gui.page
    gui.state("ready")
    open_confirmation(gui)
    p.get_by_role("button", name="Einmal erlauben").click()
    p.wait_for_selector("#confirm-dialog", state="hidden")
    until(p, "document.getElementById('chat').textContent.includes('Bestätigt')")


def test_confirmation_without_answer_times_out_as_denied(gui):
    p = gui.page
    gui.state("ready")
    open_confirmation(gui)
    gui.backend.advance(gui.backend.TIMEOUT_S + 1)                                    # Zeitablauf im Backend: gilt als abgelehnt
    p.wait_for_selector("#confirm-dialog", state="hidden")
    until(p, "document.getElementById('chat').textContent.includes('Zeitüberschreitung')")
    assert "Bestätigt" not in p.locator("#chat").inner_text()


def test_connection_loss_closes_the_dialog_and_shows_disconnected(browser):
    g = Gui(browser)
    try:
        g.state("ready")
        open_confirmation(g)
        g.srv.stop()                                                                  # Verbindungsverlust: die Anfrage gilt als abgelehnt, nichts wird gesendet
        until(g.page, "document.body.dataset.conn === 'closed'", 15.0)
        g.page.wait_for_selector("#confirm-dialog", state="hidden")
        assert "GETRENNT" in g.page.locator("#conn").inner_text() and g.page.locator("body").get_attribute("data-state") == "none"
        g.shot("connection_lost")
    finally:
        g.context.close()


# ---- Notaus --------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["orb", "dashboard"])
def test_emergency_button_works_in_every_mode_and_blocks_further_input(gui, mode):
    p = gui.page
    gui.state("ready")
    if mode == "dashboard":
        p.click("#mode-toggle")
    p.click("#emergency")
    gui.state("emergency")
    assert p.locator("#emergency-banner").is_visible() and "NOTAUS" in p.locator("#state-label").inner_text()
    assert p.locator("#voice-start").is_disabled()
    p.fill("#input", "weiter")
    p.press("#input", "Enter")
    until(p, "document.getElementById('chat').textContent.includes('Abgelehnt (emergency)')")      # der Backend-Vertrag verweigert
    gui.shot(f"emergency_{mode}")


def test_emergency_button_engages_the_real_engine_from_the_browser(browser, tmp_path):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    from jarvis.control_center.launcher import build_server
    from test_control_center_binding import real_env
    core = build_core(load_settings(env=real_env(tmp_path)))
    srv = build_server(load_settings(env=real_env(tmp_path)), core)
    srv.start()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(srv.url, wait_until="domcontentloaded")
        until(page, "document.body.dataset.conn === 'open'", 10.0)
        assert core.permissions.emergency.engaged is False
        page.click("#emergency")
        until(page, "document.body.dataset.state === 'emergency'", 10.0)
        assert core.permissions.emergency.engaged is True                             # die echte Engine, nicht nur die Anzeige
        out = core.tools.execute("echo", text="hallo")
        assert out.success is False and "emergency stop" in out.error
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(EVIDENCE / "emergency_real_engine.png"))
        assert not errors
    finally:
        ctx.close()
        srv.stop()


# ---- Mini-Overlay (als Webseite; das native Fenster prueft nur ein echter Desktop) --------------------------------------------------------------
def test_overlay_view_shows_core_and_emergency_and_opens_the_main_window(browser):
    opened: list[int] = []
    g = Gui(browser, viewport=(140, 160), on_open_main=lambda: opened.append(1), query="&view=overlay")
    try:
        p = g.page
        assert p.locator("body").get_attribute("data-mode") == "overlay"
        assert p.locator("#emergency").is_visible() and p.locator("#orb").is_visible()
        assert p.evaluate(HUE_JS, "orb")["opaque"] > 800                              # der Kern ist im Overlay gezeichnet
        assert p.evaluate("document.documentElement.scrollWidth <= 140 + 2")
        g.shot("overlay")
        p.click("#orb")
        deadline = time.monotonic() + 5
        while not opened and time.monotonic() < deadline:
            time.sleep(0.05)
        assert opened                                                                 # Token + Origin, oeffnet nur das Hauptfenster
        p.click("#emergency")
        g.state("emergency")
        assert not g.errors
    finally:
        g.close()


def test_page_works_without_token_only_as_unauthorized(browser):
    g = Gui(browser)
    try:
        resp = g.page.request.get(f"http://127.0.0.1:{g.srv.port}/events")
        assert resp.status in (401, 403)
    finally:
        g.close()
