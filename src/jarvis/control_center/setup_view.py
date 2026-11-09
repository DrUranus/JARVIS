"""Einrichtungs- und Diagnosebericht fuer das Control Center (nur lesend, nur Daten).

Baut den Bericht aus der Doctor-Pruefung (`jarvis.interface.doctor.diagnose`: Python, optionale Pakete, Konfiguration, Sicherheitsmodus) und aus dem, was der laufende Kern schon
weiss (Agentenstatus, Einstellungen). Er schaltet nichts ein, schreibt nichts, startet nichts und fragt kein Netz. Schluessel erscheinen nur als gesetzt/nicht gesetzt (nie der Wert),
Pfade gar nicht. Fehlt etwas, steht dort auf Deutsch, was fehlt und was der Mensch tun kann; Berechtigungen werden nie vorgeschlagen zu lockern."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import sys
from typing import Any, Callable, Mapping

from jarvis.interface.doctor import diagnose

OK, HINT, OFF = "ok", "hint", "off"
SEARCH_KEY = "BRAVE_SEARCH_API_KEY"


def _version() -> str:
    try:
        return importlib.metadata.version("jarvis-ai")
    except importlib.metadata.PackageNotFoundError:
        return "nicht installiert (Quellordner)"


def _component(name: str, state: str, text: str) -> dict[str, str]:
    return {"name": name, "state": state, "text": text}


def build_report(core: Any, settings: Any, env: Mapping[str, str] | None = None, find_spec: Callable[[str], Any] = importlib.util.find_spec) -> dict[str, Any]:
    env = os.environ if env is None else env
    d = diagnose(settings=settings, env=env, find_spec=find_spec)
    have = lambda mod: find_spec(mod) is not None                                          # noqa: E731
    v = settings.voice
    comps: list[dict[str, str]] = []
    prov = settings.llm.provider
    comps.append(_component("Sprachmodell", HINT if prov == "mock" else OK,
                            "Testmodus (mock): antwortet nur einfach. Für echte Antworten einen Anbieter einstellen und den Schlüssel als Umgebungsvariable setzen." if prov == "mock"
                            else f"Anbieter: {prov}"))
    if str(v.stt_provider).lower() == "console":
        comps.append(_component("Sprache", OFF, "Nur Konsole/Tastatur (stt_provider = console): kein Mikrofon. Für Sprache einen STT-Anbieter einstellen."))
    elif not have("sounddevice"):
        comps.append(_component("Sprache", HINT, f"Anbieter {v.stt_provider}/{v.tts_provider} eingestellt, aber sounddevice fehlt: pip install -e \".[voice]\"."))
    else:
        comps.append(_component("Sprache", OK, f"Anbieter {v.stt_provider}/{v.tts_provider}; Mikrofon-Paket vorhanden (die Hardware wird hier nicht geprüft). Mikrofon startet nur auf Knopfdruck."))
    b = settings.browser
    if not b.enabled:
        comps.append(_component("Browser", OFF, "Aus (browser.enabled = false). Nötig für Seiten lesen und Webrecherche."))
    elif b.provider == "playwright" and not have("playwright"):
        comps.append(_component("Browser", HINT, 'Eingeschaltet, aber Playwright fehlt: pip install -e ".[browser]" und python -m playwright install chromium.'))
    else:
        comps.append(_component("Browser", OK, f"Eingeschaltet (Anbieter {b.provider}); jede Navigation fragt nach."))
    r = settings.research
    key = bool(env.get(SEARCH_KEY))
    if not r.enabled:
        comps.append(_component("Webrecherche", OFF, "Aus ([research] enabled = false)."))
    elif not r.search_enabled:
        comps.append(_component("Webrecherche", HINT, "Research-Agent an, Websuche aus (search_enabled = false): nur vorgegebene Webadressen werden gelesen."))
    elif not key:
        comps.append(_component("Webrecherche", HINT, f"Websuche eingeschaltet, aber {SEARCH_KEY} ist nicht gesetzt: ohne Schlüssel keine Suche."))
    else:
        comps.append(_component("Webrecherche", OK, f"Websuche eingeschaltet, {SEARCH_KEY} ist gesetzt (der Wert wird nie angezeigt)."))
    f, o = settings.files.enabled, settings.office.enabled
    comps.append(_component("Dateien und Office", OK if (f or o) else OFF,
                            f"Dateien: {'an' if f else 'aus'}, Office: {'an' if o else 'aus'}. Änderungen fragen immer nach, Löschen gibt es nicht." if (f or o)
                            else "Beides aus (files.enabled / office.enabled). Dateiaufträge im Chat sind nicht möglich."))
    comps.append(_component("Mini-Overlay", OK if have("webview") else OFF,
                            "pywebview vorhanden (Start nur ausdrücklich mit --overlay)." if have("webview") else 'pywebview fehlt (nur für das Overlay): pip install -e ".[ui]".'))
    agents: list[dict[str, str]] = []
    sub = core.subsystems.get("agents") if core is not None else None
    registry = getattr(sub, "registry", None)
    for a in (registry.list() if registry is not None else []):
        st = getattr(getattr(a, "status", None), "value", str(getattr(a, "status", "")))
        reason = getattr(getattr(a, "state", None), "reason", "") or ""
        agents.append({"id": str(a.id), "status": str(st), "reason": str(reason)[:200]})
    if not agents:
        comps.append(_component("Agenten", OFF, "Die Agentenschicht ist aus (agents.enabled = false)."))
    else:
        up = sum(1 for a in agents if a["status"] == "AVAILABLE")
        comps.append(_component("Agenten", OK if up else HINT, f"{up} von {len(agents)} Agenten bereit; ausgeschaltete Agenten nennen ihren Grund."))
    return {"python": d["python"], "platform": sys.platform, "jarvis": _version(), "errors": d["errors"], "hints": d["hints"],
            "items": [{"level": lvl, "text": text} for lvl, text in d["lines"]], "components": comps, "agents": agents, "keys": d["keys"],
            "security": {"mode": settings.security.mode, "confirmation": settings.security.confirmation},
            "note": "Nur lesend: diese Ansicht schaltet nichts ein und ändert keine Berechtigung."}
