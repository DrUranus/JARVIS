"""Mikrofon-Auswahl (ersetzt den frueher fest kodierten Geraeteindex 2).

`voice.audio_device`: leer/None/"default" = Windows-Standardgeraet (sounddevice waehlt es; es wird geprueft, dass eines existiert) | Zahl = Geraeteindex |
sonst ein Namensteil ("Razer", "Auna"; Gross-/Kleinschreibung egal). Wird bei JEDER Aufnahme neu aufgeloest, damit ein neu angestecktes Mikrofon funktioniert.
Kein Treiber-/Systemzugriff ausser dem lesenden `query_devices`; nichts wird veraendert. Fehler sind verstaendliche VoiceUnavailableError-Meldungen mit der Liste
der verfuegbaren Eingabegeraete."""
from __future__ import annotations

from typing import Any

from jarvis.errors import VoiceUnavailableError

DEFAULT_WORDS = ("", "default", "standard", "auto")


def input_devices(sd: Any) -> list[tuple[int, str]]:
    """(Index, Name) aller Geraete mit mindestens einem Eingangskanal."""
    out: list[tuple[int, str]] = []
    for i, d in enumerate(sd.query_devices()):
        try:
            if int(d.get("max_input_channels", 0)) > 0:
                out.append((i, str(d.get("name", ""))))
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def _available(devs: list[tuple[int, str]]) -> str:
    return ", ".join(f"{i}: {n}" for i, n in devs[:8]) or "keines"


def resolve_input_device(sd: Any, setting: "str | int | None") -> "int | None":
    """Geraeteindex fuer sounddevice oder None (= Windows-Standardgeraet)."""
    devs = input_devices(sd)
    if not devs:
        raise VoiceUnavailableError("Kein Mikrofon gefunden: es ist kein Eingabegeraet angeschlossen oder freigegeben "
                                    "(Windows-Einstellungen > Datenschutz > Mikrofon pruefen).")
    text = "" if setting is None else str(setting).strip()
    if text.lower() in DEFAULT_WORDS:
        try:
            default = sd.default.device[0]
        except (AttributeError, IndexError, TypeError):
            default = None
        if default is None or int(default) < 0 or int(default) not in {i for i, _ in devs}:
            raise VoiceUnavailableError("Kein Standard-Mikrofon gesetzt. Waehle in Windows ein Standardgeraet oder setze voice.audio_device "
                                        f"(Index oder Namensteil). Verfuegbar: {_available(devs)}")
        return None
    if text.lstrip("-").isdigit():
        index = int(text)
        if index not in {i for i, _ in devs}:
            raise VoiceUnavailableError(f"Mikrofon mit Index {index} nicht verfuegbar (voice.audio_device). Verfuegbar: {_available(devs)}")
        return index
    wanted = text.casefold()
    matches = [(i, n) for i, n in devs if wanted in n.casefold()]
    if not matches:
        raise VoiceUnavailableError(f"Mikrofon {text!r} nicht gefunden (angesteckt? voice.audio_device pruefen). Verfuegbar: {_available(devs)}")
    return matches[0][0]
