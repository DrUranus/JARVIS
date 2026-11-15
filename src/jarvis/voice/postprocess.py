"""Behutsame Nachbearbeitung erkannter Sprache (Speech Recognition Upgrade V1).

Grundsaetze:
- Es wird nichts erfunden: nur eine kleine Liste bekannter Fehlhoerungen der eigenen Eigennamen (JARVIS, NEXUS) wird als GANZES Wort ersetzt; sonst bleibt der Text
  unveraendert (ausser Leerraum). Das Originaltranskript bleibt beim Aufrufer erhalten (Diagnose), Audio wird hier nie gespeichert.
- Riskante Sprachbefehle (loeschen, bezahlen, herunterfahren ...) werden NICHT stillschweigend ausgefuehrt: der Sprachmodus fragt zuerst nach ("Bestaetige ...").
  Das ersetzt keine Freigabe: jede Aktion fragt weiterhin ueber PermissionEngine/Freigabedialog; dies ist nur eine zusaetzliche Rueckfrage, weil Spracherkennung
  Woerter vertauschen kann ("lese" <-> "loesche")."""
from __future__ import annotations

import re

# Bekannte Fehlhoerungen (ganze Woerter, ohne Beachtung der Gross-/Kleinschreibung) -> Eigenname. Bewusst klein und nur fuer Eigennamen.
_NAME_FIXES: tuple[tuple[str, str], ...] = (
    (r"d?sch?arvis|tscharvis|charvis|jarwis|jarvies|jarvas|dscharwis|jervis|jarviss|javis|jarvis", "JARVIS"),   # "javis": gemessene Ausgabe von Whisper medium/large-v3-turbo
    (r"nexxus|nekzus|nexes|nex\s+us|nexuss|nexus", "NEXUS"),                                                    # Schreibweise vereinheitlichen (Whisper liefert "Nexus")
)
_COMPILED = tuple((re.compile(rf"\b(?:{pat})\b", re.IGNORECASE), name) for pat, name in _NAME_FIXES)

# Verben mit Wirkung, die bei Verhoeren fatal waeren. Stamm genuegt (\w*), deutsch und englisch.
_RISKY = re.compile(
    r"\b(?:l[oö]e?sch\w*|entfern\w*|formatier\w*|[uü]e?berweis\w*|bezahl\w*|kauf\w*|bestell\w*|herunterfahr\w*|neustart\w*|"
    r"delete\w*|remove\w*|erase\w*|format|wipe\w*|pay\b|purchase\w*|buy\b|shut\s*down|reboot\w*)|\bfahr\w*\b[^.!?]{0,40}\bherunter\b", re.IGNORECASE)
_CONFIRM = re.compile(r"^\W*(?:best[aä]e?tige|confirm)\b[\s,.:;!?\-]*", re.IGNORECASE)


def normalize_transcript(text: str) -> str:
    """Leerraum vereinheitlichen und bekannte Fehlhoerungen der Eigennamen korrigieren. Sonst unveraendert."""
    out = " ".join(str(text or "").split())
    for pattern, name in _COMPILED:
        out = pattern.sub(name, out)
    return out


def is_risky(text: str) -> bool:
    return bool(_RISKY.search(text or ""))


def split_confirmation(text: str) -> tuple[bool, str]:
    """(bestaetigt, Befehl ohne das Wort 'Bestaetige'). Ohne Bestaetigungswort ist der Befehl unveraendert."""
    m = _CONFIRM.match(text or "")
    return (True, text[m.end():].strip()) if m else (False, (text or "").strip())
