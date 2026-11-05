"""`jarvis doctor` / `/doctor`: Umgebungs- und Konfigurationspruefung. Nur lesend: kein Core, keine Subsysteme, keine Importe der
optionalen Pakete (nur `find_spec`), keine Dateien, kein Netz. Schluessel erscheinen ausschliesslich als "gesetzt"/"nicht gesetzt"."""
from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any, Callable, Mapping

from jarvis.config import Settings, load_settings
from jarvis.errors import JarvisError

OK, HINT, ERROR = "OK", "HINWEIS", "FEHLER"
KEY_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JARVIS_LLM_API_KEY", "JARVIS_VOICE_API_KEY")
SUBSYSTEMS = ("memory", "history", "computer", "browser", "coding", "agents", "goals", "budget", "self_repair",
              "self_improvement", "research", "business", "finance")


def _module(find_spec: Callable[[str], Any], name: str) -> bool:
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def probe_webview2() -> str | None:
    """Version der Evergreen-WebView2-Laufzeit (nur Windows). Liest ausschliesslich Registry-Werte (kein Schreiben, kein Start); None = nicht gefunden."""
    import winreg  # nur unter Windows vorhanden
    sub = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"
    for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                       (winreg.HKEY_CURRENT_USER, 0)):
        try:
            with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | view) as key:
                version = str(winreg.QueryValueEx(key, "pv")[0])
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return version
    return None


def run_doctor(config_path: str | None = None, settings: Settings | None = None, env: Mapping[str, str] | None = None,
               find_spec: Callable[[str], Any] = importlib.util.find_spec, webview2_probe: Callable[[], str | None] | None = None,
               platform: str | None = None) -> tuple[str, int]:
    """Return (Bericht, Exit-Code). Exit-Code 0 = keine Fehler (Hinweise moeglich), 1 = mindestens ein Fehler."""
    env = os.environ if env is None else env
    lines: list[tuple[str, str]] = []

    def add(level: str, text: str) -> None:
        lines.append((level, text))

    v = sys.version_info
    if v >= (3, 11):
        add(OK, f"Python {v.major}.{v.minor}.{v.micro} (benötigt: 3.11 oder neuer)")
    else:
        add(ERROR, f"Python {v.major}.{v.minor}.{v.micro} ist zu alt. Bitte Python 3.11 oder neuer installieren.")

    optional = (
        ("tkinter", "tkinter (GUI)", "Ohne tkinter startet die grafische Oberfläche nicht. Unter Windows: Python von python.org verwenden."),
        ("sounddevice", "sounddevice (Mikrofon, voice)", 'Nur für Sprachmodus mit Mikrofon nötig: pip install -e ".[voice]"'),
        ("numpy", "numpy (Wiedergabe, voice)", 'Nur für Sprachmodus nötig: pip install -e ".[voice]"'),
        ("playwright", "playwright (Browser-Agent)", 'Nur für den Browser-Agenten nötig: pip install -e ".[browser]" und python -m playwright install chromium'),
    )
    for module, label, advice in optional:
        if _module(find_spec, module):
            add(OK, f"{label}: verfügbar")
        else:
            add(HINT, f"{label}: nicht verfügbar. {advice}")

    if settings is None:
        try:
            settings = load_settings(config_path, env=env)
            add(OK, f"Konfiguration gültig ({config_path or 'eingebaute Defaults, keine Datei gefunden'})")
        except JarvisError as exc:
            add(ERROR, f"Konfiguration ungültig: {exc}")
    else:
        add(OK, "Konfiguration gültig (bereits geladen)")

    for var in KEY_VARS:
        add(OK, f"{var}: {'gesetzt' if env.get(var) else 'nicht gesetzt'}")
    if settings is not None:
        provider = settings.llm.provider
        needed = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
        if needed and not (env.get(needed) or env.get("JARVIS_LLM_API_KEY")):
            add(HINT, f"LLM-Anbieter ist '{provider}', aber {needed} (oder JARVIS_LLM_API_KEY) ist nicht gesetzt. "
                      "Mit provider = \"mock\" läuft JARVIS offline.")
        else:
            add(OK, f"LLM-Anbieter: {provider}")

    if settings is not None:
        active = [name for name in SUBSYSTEMS if getattr(settings, name).enabled]
        if settings.goals.replanning:
            active.append("goals.replanning")
        add(OK, "Aktive Subsysteme: " + (", ".join(active) if active else "keine (alle optionalen Subsysteme sind ausgeschaltet)")
            + ". Der Doctor schaltet nichts ein.")
        s, f = settings.security, settings.finance
        add(OK, f"Sicherheitsmodus: {s.mode} (Bestätigung: {s.confirmation}); audit_strict = {str(s.audit_strict).lower()}; "
                f"Paper-Trading-only = {str(f.paper_trading_only).lower()}")
        if s.mode != "standard" and s.mode != "lockdown":
            add(ERROR, f"Unbekannter Sicherheitsmodus '{s.mode}'.")
        if not s.audit_strict:
            add(HINT, "security.audit_strict ist aus: bei nicht schreibbarem Audit-Log werden Aktionen nicht mehr abgelehnt.")
        if not s.audit_enabled:
            add(HINT, "security.audit_enabled ist aus: Sicherheitsereignisse werden nicht protokolliert.")
        if not f.paper_trading_only:
            add(ERROR, "finance.paper_trading_only muss true bleiben.")
        if active and s.mode == "standard" and s.confirmation == "deny":
            add(HINT, "Aktive Subsysteme, aber confirmation = deny: Aktionen mit Rückfrage werden abgelehnt.")

    _control_center(add, settings, sys.platform if platform is None else platform, webview2_probe or probe_webview2)

    errors = sum(1 for lvl, _ in lines if lvl == ERROR)
    hints = sum(1 for lvl, _ in lines if lvl == HINT)
    body = ["JARVIS Doctor (nur lesend)"] + [f"  [{lvl}] {text}" for lvl, text in lines]
    body.append(f"Ergebnis: {errors} Fehler, {hints} Hinweis(e). " +
                ("Bitte die Fehler beheben." if errors else "JARVIS ist startbereit."))
    return "\n".join(body), 1 if errors else 0


def _control_center(add: Callable[[str, str], None], settings: Settings | None, platform: str, probe: Callable[[], str | None]) -> None:
    """Control-Center-Voraussetzungen (cc-windows-start). Nur Hinweise, nie Fehler; kein Import von `jarvis.control_center`, kein Server, kein Schreiben."""
    if settings is not None:
        cc = settings.control_center.enabled
        add(OK, f"Control Center: control_center.enabled = {str(cc).lower()}. Start nur ausdrücklich mit `jarvis-cc` (lokal, 127.0.0.1); "
                "nötig sind control_center.enabled, assistant.enabled und agents.enabled. Der Doctor schaltet nichts ein.")
        if cc and not (settings.assistant.enabled and settings.agents.enabled):
            add(HINT, "control_center.enabled ist an, aber assistant.enabled und/oder agents.enabled fehlen: `jarvis-cc` bricht dann mit Fehlercode 2 ab.")
    if not platform.startswith("win"):
        add(HINT, "WebView2-Laufzeit: nur unter Windows prüfbar (hier nicht geprüft).")
    else:
        try:
            version = probe()
        except Exception as exc:  # Registry nicht lesbar o. ae.: melden, nie abbrechen
            add(HINT, f"WebView2-Laufzeit: nicht prüfbar ({type(exc).__name__}).")
        else:
            if version:
                add(OK, f"WebView2-Laufzeit: gefunden (Version {version})")
            else:
                add(HINT, "WebView2-Laufzeit: nicht gefunden. Nur für ein späteres natives Fenster nötig (Evergreen-Runtime von Microsoft); "
                          "das Control Center läuft heute im Systembrowser (Edge) und braucht sie nicht.")
    add(OK, "Darstellung: Canvas-2D im Browser. Ein 3D-Kern (WebGL/Three.js) ist nicht enthalten; bei fehlender 3D-Unterstützung gilt der 2D-Rückfall "
            "(Effekte lassen sich auf „reduziert/aus“ stellen).")
    add(OK, "Mini-Overlay und natives Fenster: nicht enthalten (nicht freigegeben). Der Notaus-Knopf liegt in der Control-Center-Seite im Browser.")
