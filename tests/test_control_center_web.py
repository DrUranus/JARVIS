"""Statische Pruefungen der Weboberflaeche (cc-shell): keine externen Ressourcen, kein unsicheres DOM, Orb-Start, UI-Modus rein lokal, Notaus immer sichtbar."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

import jarvis.control_center as cc

ROOT = Path(cc.__file__).parent
WEB = ROOT / "web"
FILES = ("index.html", "app.js", "styles.css")


def text(name):
    return (WEB / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", FILES)
def test_no_external_resources(name):
    src = text(name)
    assert not re.search(r"(https?:)?//[A-Za-z0-9.-]+\.[a-z]{2,}", src.replace("</", "")), name
    assert not re.search(r"@import|url\(\s*['\"]?(https?:|//)", src)
    assert "cdn" not in src.lower() and "googleapis" not in src.lower()


def test_html_references_only_local_files_and_no_inline_code():
    html = text("index.html")
    assert re.findall(r'(?:src|href)="([^"]+)"', html) == ["styles.css?t=__TOKEN__", "app.js?t=__TOKEN__"]
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "<style" not in html
    assert not re.search(r"\son[a-z]+=", html) and "style=" not in html


def test_js_avoids_dangerous_dom_apis():
    js = text("app.js")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "localStorage", "sessionStorage", "XMLHttpRequest", "WebSocket(", "postMessage"):
        assert bad not in js, bad


def test_js_talks_only_to_own_endpoints():
    js = text("app.js")
    assert "http://" not in js and "https://" not in js
    assert re.findall(r"new EventSource\((.*)\);", js) == ["url(\"events\", lastSeq)"]
    # genau drei eigene Ziele: Befehle (POST), die Zustandstabelle des Kerns (GET, cc-ai-core) und die lesenden Ansichten (GET, cc-results-audit)
    assert re.findall(r"fetch\(([^,]*),", js) == ["url(\"view/agents\"", "url(\"view/mission\"", "url(\"view/audit\"", "url(\"command\")", "url(\"view/\" + which", "url(\"core_states.json\")", "url(\"/overlay/open\")"]  # view/agents: Zeitleiste (WP07b, GET); view/mission: Mission Control (V2.1 M6, GET, nur lesend); view/audit: Freigabe-Verlauf (WP07c, GET); overlay/open: nur Mini-Overlay, Token+Origin, oeffnet das Hauptfenster


def test_starts_in_orb_mode_and_has_toggle_and_emergency_button_in_both_modes():
    html = text("index.html")
    assert re.search(r'<body[^>]*data-mode="orb"', html)
    assert 'id="mode-toggle"' in html
    assert 'id="emergency"' in html
    # der Notaus-Knopf liegt ausserhalb der Ansicht, die im Orb-Modus oder im Dashboard-Modus ausgeblendet wird
    css = text("styles.css")
    assert not re.search(r"\[data-mode=[^\]]*\][^{]*#emergency[^{]*\{[^}]*display\s*:\s*none", css)
    assert "prefers-reduced-motion" in css or "prefers-reduced-motion" in text("app.js")


def test_mode_switch_is_purely_local():
    js = text("app.js")
    m = re.search(r"function setMode\(.*?\n\}", js, re.S)
    assert m, "setMode fehlt"
    body = m.group(0)
    for forbidden in ("send(", "fetch(", "EventSource", "emergency", "confirm", "permission"):
        assert forbidden not in body, forbidden
    assert 'setMode("orb")' in js  # Start im Orb-Modus


def test_emergency_button_sends_only_the_contract_command():
    js = text("app.js")
    assert '"emergency_stop"' in js
    assert "reset_emergency" not in js  # das Aufheben bleibt eine Rueckfrage der Engine, nicht der UI
    assert "grant" not in js  # kein Rechte-Befehl; Antworten auf Rueckfragen sind nur `confirm` (siehe test_control_center_confirmation.py)


def test_importing_package_starts_nothing_and_is_not_wired():
    out = subprocess.run([sys.executable, "-c", "import threading, jarvis.control_center as c, jarvis.control_center.server; print(threading.active_count())"],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out == "1"
    src = Path(cc.__file__).parents[1]
    for p in src.rglob("*.py"):
        if "control_center" in p.parts or p.name == "config.py":  # cc-backend-binding: nur die Einstellung control_center.enabled lebt in config.py
            continue
        content = p.read_text(encoding="utf-8")
        if p.as_posix().endswith("/interface/doctor.py"):
            # Doctor darf das Control Center nur lesend diagnostizieren; kein Import, kein Start.
            assert not re.search(r"^(?:from|import)\s+jarvis\.control_center\b", content, re.M), p
            assert not re.search(r"\b(?:start|serve_forever)\s*\(", content), p
            continue
        assert "control_center" not in content, p  # sonst ist nichts verdrahtet (bootstrap.py startet das Control Center nie)


def test_server_module_uses_only_stdlib_and_contract():
    tree = (ROOT / "server.py").read_text(encoding="utf-8")
    imports = set(re.findall(r"^(?:from|import) ([A-Za-z_\.]+)", tree, re.M))
    assert all(i.split(".")[0] in sys.stdlib_module_names or i.split(".")[0] in ("jarvis", "__future__") for i in imports), imports
    assert not [i for i in imports if i.startswith("jarvis") and not i.startswith(("jarvis.ui_contract", "jarvis.control_center.views"))]


def test_pyproject_keeps_no_dependencies():
    import tomllib
    data = tomllib.loads((Path(cc.__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")) if (Path(cc.__file__).parents[2] / "pyproject.toml").exists() else None
    if data is None:
        data = tomllib.loads((Path(cc.__file__).parents[3] / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == []
    assert "cc" not in data["project"]["optional-dependencies"]
