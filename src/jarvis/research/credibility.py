"""V2-01 Quellenbewertung: eine reine, erklaerbare Heuristik fuer die Verlaesslichkeit einer Webquelle.

Eingabe sind nur Daten (URL, Titel, Text, Fremdbestaetigungen, Zeit); es gibt kein Netzwerk, keine Datei, keinen Prozess, keine Persistenz und keinen globalen
Zustand. Das Modul ist in V1 NICHT verdrahtet (kein Aufrufer); eine spaetere Anbindung an Recherche-Antworten ist ein eigener, freizugebender Schritt.

Wichtig: Das Ergebnis ist eine HEURISTIK. Sie erkennt Hinweise (Verschluesselung, Institutionsendung, auffaellige Hosts, erkennbares Jahr, Werbesprache,
Fremdbestaetigung), nie die Wahrheit einer Aussage. Jedes Signal nennt seinen Grund; Text der Quelle ist Daten und wird nie als Anweisung gelesen.
"""
from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

MAX_URL = 2048
MAX_TEXT = 20_000
BASE_SCORE = 0.5
MAX_SCORE = 0.95                   # nie "sicher": auch beste Hinweise sind nur Hinweise
CORROBORATION_STEP = 0.1
CORROBORATION_CAP = 0.2

INSTITUTION_SUFFIXES = ("gov", "edu", "mil", "int")
INSTITUTION_SECOND_LEVEL = ("gov.uk", "ac.uk", "gv.at", "admin.ch", "europa.eu", "gouv.fr", "gob.es", "gov.au", "edu.au")
SHORTENERS = frozenset({"bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd", "buff.ly", "cutt.ly", "rebrand.ly"})
USER_CONTENT_SUFFIXES = ("blogspot.com", "wordpress.com", "medium.com", "github.io", "wixsite.com", "weebly.com", "tumblr.com", "substack.com")
PROMO_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"jetzt\s+kaufen", r"buy\s+now", r"100\s*%\s*(garantiert|guaranteed)", r"nur\s+heute", r"limited\s+time", r"gewinnen", r"kostenlos\s+testen",
    r"!{3,}", r"unbegrenzt",
))
YEAR = re.compile(r"(?<!\d)(19[89]\d|20\d\d)(?!\d)")


class Level(str, Enum):
    HIGH = "hoch"
    MEDIUM = "mittel"
    LOW = "niedrig"
    UNKNOWN = "unbekannt"


@dataclass(frozen=True)
class Signal:
    name: str
    delta: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "delta": round(self.delta, 3), "reason": self.reason}


@dataclass(frozen=True)
class SourceAssessment:
    url: str
    host: str
    score: float
    level: Level
    signals: tuple[Signal, ...]
    caveats: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "host": self.host, "score": round(self.score, 3), "level": self.level.value,
                "signals": [s.to_dict() for s in self.signals], "caveats": list(self.caveats)}


CAVEATS = ("Heuristik: erkennt Hinweise, beweist keine Richtigkeit. Aussagen bleiben mit mehreren unabhaengigen Quellen zu pruefen.",)


def _unknown(url: Any, reason: str) -> SourceAssessment:
    text = url if isinstance(url, str) else ""
    return SourceAssessment(text[:200], "", 0.0, Level.UNKNOWN, (Signal("unbrauchbare_eingabe", 0.0, reason),), CAVEATS)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _ends(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    return max(0, int(value))


def _newest_year(text: str, now_year: int) -> int | None:
    years = [int(m.group(1)) for m in YEAR.finditer(text)]
    years = [y for y in years if y <= now_year]            # Zukunftsjahre (Versionsnummern u. a.) sind kein Datum
    return max(years) if years else None


def _level(score: float) -> Level:
    return Level.HIGH if score >= 0.7 else Level.MEDIUM if score >= 0.45 else Level.LOW


def assess_source(url: str, *, title: str = "", text: str = "", corroborating_hosts: int = 0, now: datetime | None = None) -> SourceAssessment:
    """Bewertet eine Quelle. Wirft nie; unbrauchbare Eingaben ergeben Level UNBEKANNT mit Score 0.

    `corroborating_hosts`: Anzahl ANDERER Hosts, die dieselbe Aussage stuetzen (vom Aufrufer ermittelt, hier nur gewichtet).
    `now`: Bezugszeit fuer die Aktualitaet (Standard: jetzt, UTC); fuer Tests setzbar.
    """
    if not isinstance(url, str) or not url.strip():
        return _unknown(url, "keine URL")
    raw = url.strip()[:MAX_URL]
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
    except ValueError:
        return _unknown(raw, "URL nicht lesbar")
    if parts.scheme not in ("http", "https"):
        return _unknown(raw, "nur http/https werden bewertet")
    if not host:
        return _unknown(raw, "kein Host")

    signals: list[Signal] = []
    score = BASE_SCORE
    if parts.scheme == "https":
        signals.append(Signal("https", 0.1, "verschluesselte Verbindung"))
        score += 0.1
    else:
        signals.append(Signal("kein_https", -0.15, "unverschluesselte Verbindung"))
        score -= 0.15

    if _is_ip(host):
        signals.append(Signal("ip_adresse", -0.2, "Host ist eine IP-Adresse statt eines Namens"))
        score -= 0.2
    else:
        if host in SHORTENERS:
            signals.append(Signal("kurzlink", -0.2, "Kurzlink verdeckt das eigentliche Ziel"))
            score -= 0.2
        if "xn--" in host:
            signals.append(Signal("punycode", -0.15, "internationalisierter Hostname, Verwechslungsgefahr"))
            score -= 0.15
        if host.count(".") >= 5:
            signals.append(Signal("viele_subdomains", -0.1, "sehr viele Subdomain-Ebenen"))
            score -= 0.1
        if _ends(host, INSTITUTION_SUFFIXES) or _ends(host, INSTITUTION_SECOND_LEVEL):
            signals.append(Signal("institution", 0.2, "Endung typisch fuer Behoerden/Hochschulen/Organisationen (kein Beweis)"))
            score += 0.2
        if _ends(host, USER_CONTENT_SUFFIXES):
            signals.append(Signal("nutzerinhalte", -0.1, "Plattform fuer Nutzerinhalte, Autor unklar"))
            score -= 0.1

    body = text[:MAX_TEXT] if isinstance(text, str) else ""
    head = title[:300] if isinstance(title, str) else ""
    current = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    year = _newest_year(f"{head}\n{body}", current.year)
    if year is None:
        signals.append(Signal("kein_datum", 0.0, "im Text ist kein Jahr erkennbar"))
    else:
        age = current.year - year
        if age <= 1:
            signals.append(Signal("aktuell", 0.1, f"juengstes erkennbares Jahr {year}"))
            score += 0.1
        elif age > 8:
            signals.append(Signal("veraltet", -0.2, f"juengstes erkennbares Jahr {year}"))
            score -= 0.2
        elif age > 3:
            signals.append(Signal("veraltet", -0.1, f"juengstes erkennbares Jahr {year}"))
            score -= 0.1
        else:
            signals.append(Signal("mittleres_alter", 0.0, f"juengstes erkennbares Jahr {year}"))

    promo = sum(1 for p in PROMO_PATTERNS if p.search(body) or p.search(head))
    if promo:
        signals.append(Signal("werbesprache", -min(0.2, 0.1 * promo), f"{promo} Werbemuster im Text"))
        score -= min(0.2, 0.1 * promo)

    n = _count(corroborating_hosts)
    if n:
        bonus = min(CORROBORATION_CAP, CORROBORATION_STEP * n)
        signals.append(Signal("fremdbestaetigung", bonus, f"{n} weitere Host(s) stuetzen die Aussage"))
        score += bonus

    score = round(min(MAX_SCORE, max(0.0, score)), 3)
    return SourceAssessment(raw[:200], host, score, _level(score), tuple(signals), CAVEATS)
