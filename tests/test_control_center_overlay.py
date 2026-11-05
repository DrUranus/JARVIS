"""Optionales Mini-Overlay (cc-mini-overlay, Option A): rechteckig ca. 140x140, verschiebbar, optional Always-on-Top, Klick oeffnet das Hauptfenster,
nie klickdurchlaessig, Start nur ausdruecklich, Notaus immer erreichbar. pywebview wird in den Tests nie importiert (Fake-Modul), kein Netz.
Linux-Ergebnisse sind kein Windows-Nachweis (echtes Fenster: Windows-CI/Handpruefung)."""
import ast
import json
import re
from pathlib import Path

import pytest

from jarvis.control_center import launcher, overlay
from jarvis.control_center.overlay import OVERLAY_SIZE, OverlayUnavailable, overlay_options, overlay_url, start_overlay, webview_available
from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend
from test_control_center_server import cmd, good_origin, request

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "jarvis" / "control_center" / "web"
URL = "http://127.0.0.1:5555/?t=" + "x" * 32


class FakeWebview:
    def __init__(self):
        self.windows, self.started = [], []

    def create_window(self, title, url=None, **kw):
        self.windows.append((title, url, kw))
        return object()

    def start(self, *a, **kw):
        self.started.append((a, kw))


# ---- Fensterform ---------------------------------------------------------------------------------------------------------------------------
def test_options_small_rectangular_draggable_not_click_through():
    o = overlay_options()
    assert (o["width"], o["height"]) == OVERLAY_SIZE == (140, 140)
    assert o["frameless"] is True and o["easy_drag"] is True and o["resizable"] is False
    assert o["on_top"] is False                       # Always-on-Top nur auf ausdruecklichen Wunsch
    assert o["transparent"] is False                  # unter Windows nicht unterstuetzt; Rechteck, nie klickdurchlaessig
    assert "js_api" not in o and overlay_options(on_top=True)["on_top"] is True


def test_overlay_url_loopback_only_and_keeps_token():
    u = overlay_url(URL)
    assert u.startswith("http://127.0.0.1:5555/?") and "view=overlay" in u and "t=" + "x" * 32 in u
    for bad in ("http://example.com/?t=" + "x" * 32, "https://127.0.0.1:5555/?t=abc", "file:///c:/x", "http://localhost:5555/?t=abc"):
        with pytest.raises(OverlayUnavailable):
            overlay_url(bad)


def test_start_overlay_passes_options_without_bridge_or_debug():
    wv = FakeWebview()
    start_overlay(URL, webview_module=wv)
    (title, url, kw), = wv.windows
    assert "view=overlay" in url and kw["width"] == kw["height"] == 140 and kw["on_top"] is False and "js_api" not in kw
    (_, skw), = wv.started
    assert skw.get("debug", False) is False
    wv2 = FakeWebview()
    start_overlay(URL, on_top=True, webview_module=wv2)
    assert wv2.windows[0][2]["on_top"] is True


def test_missing_webview_is_german_error_not_import_crash():
    assert webview_available(lambda name: None) is False and webview_available(lambda name: object()) is True
    with pytest.raises(OverlayUnavailable) as e:
        start_overlay(URL, webview_module=None, find_spec=lambda name: None)
    assert "pywebview" in str(e.value) and '.[ui]' in str(e.value)


def test_overlay_module_never_imports_webview_at_top_level():
    tree = ast.parse((ROOT / "src" / "jarvis" / "control_center" / "overlay.py").read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name.split(".")[0] for n in top for a in n.names} | {n.module.split(".")[0] for n in top if isinstance(n, ast.ImportFrom) and n.module}
    assert "webview" not in names


# ---- Start nur ausdruecklich ----------------------------------------------------------------------------------------------------------------
def test_launcher_has_overlay_flags_default_off_and_bootstrap_does_not_know_it():
    src = (ROOT / "src" / "jarvis" / "control_center" / "launcher.py").read_text(encoding="utf-8")
    assert '"--overlay"' in src and '"--overlay-on-top"' in src
    assert "overlay" not in (ROOT / "src" / "jarvis" / "bootstrap.py").read_text(encoding="utf-8")


def test_launcher_overlay_without_webview_aborts_before_anything_listens(monkeypatch, capsys):
    started = []
    monkeypatch.setattr(launcher, "load_settings", lambda *a, **k: object())
    monkeypatch.setattr(launcher, "build_core", lambda s: object())

    class S:
        def start(self): started.append(1)
        def stop(self): pass
        url = URL

    monkeypatch.setattr(launcher, "build_server", lambda s, c: S())
    monkeypatch.setattr(launcher, "webview_available", lambda *a, **k: False)
    assert launcher.main(["--overlay"]) == 2
    assert started == [] and "pywebview" in capsys.readouterr().err


# ---- Klick oeffnet das Hauptfenster ---------------------------------------------------------------------------------------------------------
def test_open_main_route_needs_callback_token_and_origin():
    calls = []
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    s.start()
    try:
        assert request(s, "POST", "/overlay/open", body="{}", origin=good_origin(s))[0] == 404    # ohne Rueckruf gibt es die Route nicht
    finally:
        s.stop()
    s = ControlCenterServer(FakeUiBackend(), poll_interval=0.02, on_open_main=lambda: calls.append(1))
    s.start()
    try:
        assert request(s, "POST", "/overlay/open", body="{}", origin=good_origin(s), token=False)[0] == 401
        assert request(s, "POST", "/overlay/open", body="{}", origin="http://evil.example")[0] in (401, 403)
        assert calls == []
        assert request(s, "POST", "/overlay/open", body="{}", origin=good_origin(s))[0] == 200
        assert calls == [1]
    finally:
        s.stop()


def test_launcher_opens_main_only_in_system_browser_with_main_url(monkeypatch):
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda u: opened.append(u))
    launcher.open_main_window(URL)
    assert opened == [URL] and "view=overlay" not in opened[0]


# ---- Notaus bei Overlay und geschlossenem Hauptfenster ---------------------------------------------------------------------------------------
def test_emergency_stop_reachable_through_overlay_client_alone():
    """Das Overlay ist ein eigener Client mit demselben Befehlsweg; es braucht kein anderes Fenster."""
    b = FakeUiBackend()
    s = ControlCenterServer(b, poll_interval=0.02)
    s.start()
    try:
        st, _, body = request(s, "POST", "/command", body=cmd("e1", "emergency_stop", {}), origin=good_origin(s))
        assert st == 200 and json.loads(body)["data"]["id"] == "e1"
    finally:
        s.stop()


def test_overlay_page_structure():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    assert 'id="emergency"' in html and 'id="overlay-open"' in html
    assert '"overlay"' in js and "/overlay/open" in js and "view" in js
    block = " ".join(re.findall(r'body\[data-mode="overlay"\][^{]*\{[^}]*\}', css))
    assert block and "#emergency" in css
    assert "pointer-events: none" not in css and "app-region" not in css      # nie klickdurchlaessig
    assert re.search(r'body\[data-mode="overlay"\]\s+#emergency\s*\{[^}]*display:\s*block', css)   # Notaus im Overlay immer sichtbar
    assert "pywebview" not in js and "window.pywebview" not in js            # keine JS-Python-Bruecke
