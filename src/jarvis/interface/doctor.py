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


def run_doctor(config_path: str | None = None, settings: Settings | None = None, env: Mapping[str, str] | None = None,
               find_spec: Callable[[str], Any] = importlib.util.find_spec) -> tuple[str, int]:
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

    errors = sum(1 for lvl, _ in lines if lvl == ERROR)
    hints = sum(1 for lvl, _ in lines if lvl == HINT)
    body = ["JARVIS Doctor (nur lesend)"] + [f"  [{lvl}] {text}" for lvl, text in lines]
    body.append(f"Ergebnis: {errors} Fehler, {hints} Hinweis(e). " +
                ("Bitte die Fehler beheben." if errors else "JARVIS ist startbereit."))
    return "\n".join(body), 1 if errors else 0
