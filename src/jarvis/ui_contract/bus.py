"""Ereignisprotokoll des UI-Vertrags (Backlog-Schritt event-bus): Ringpuffer mit Folgenummern, Wiederholung per `events_since`, thread-sicher.

Jeder Text wird mit `jarvis.redaction` geschwaerzt, BEVOR ein Ereignis entsteht (kein Ereignis, keine Folgenummer, kein Pufferplatz fuer ungeschwaerzte Daten). Schlaegt die
Schwaerzung oder die Vertragspruefung fehl, entsteht kein Ereignis (fail closed). Das Protokoll fuehrt nichts aus und kennt keine Berechtigung."""
from __future__ import annotations

import copy
import datetime as dt
import threading
from collections import deque
from typing import Any, Protocol

from jarvis.redaction import SecretDetector
from jarvis.ui_contract.schema import VERSION, validate_event

LATEST_TYPES = ("hello", "state", "activity", "emergency")      # was ein Schnappschuss braucht, auch wenn der Ringpuffer sie schon verdraengt hat
DEFAULT_CAPACITY = 1000


class Clock(Protocol):
    def now(self) -> dt.datetime: ...


class _SystemClock:
    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


class EventLog:
    def __init__(self, clock: Clock | None = None, capacity: int = DEFAULT_CAPACITY, detector: SecretDetector | None = None) -> None:
        if not 1 <= capacity <= 100_000:
            raise ValueError("capacity must be 1..100000")
        self._clock: Clock = clock or _SystemClock()
        self._detector = detector or SecretDetector.from_environment()
        self._lock = threading.RLock()
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._latest: dict[str, dict[str, Any]] = {}
        self._seq = 0

    # ---- Schwaerzung ----------------------------------------------------------------------------------------------------------------
    def clean(self, text: Any, limit: int) -> str:
        """Schwaerzen, dann kuerzen (so wird kein Geheimnis in der Mitte durchgeschnitten und halb ausgegeben)."""
        return self._detector.redact(text)[:max(0, limit)]

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._detector.redact(value)
        if isinstance(value, dict):
            return {k: self._redact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact(v) for v in value]
        return value

    # ---- Schreiben --------------------------------------------------------------------------------------------------------------------
    def emit(self, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        """Schwaerzt `data`, prueft gegen den Vertrag und haengt das Ereignis an. Wirft ContractError (oder den Fehler der Schwaerzung); dann bleibt alles unveraendert."""
        safe = self._redact(data)
        with self._lock:
            ts = self._clock.now().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            event = validate_event({"v": VERSION, "seq": self._seq + 1, "ts": ts, "type": type_, "data": safe})
            self._seq += 1
            self._events.append(event)
            if type_ in LATEST_TYPES:
                self._latest[type_] = event
        return copy.deepcopy(event)

    # ---- Lesen ------------------------------------------------------------------------------------------------------------------------
    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def events_since(self, seq: int, limit: int = 200) -> list[dict[str, Any]]:
        """Ereignisse mit Folgenummer > seq in Reihenfolge, hoechstens `limit` (1..1000). Was der Ringpuffer schon verdraengt hat, fehlt (der Client holt dann einen Schnappschuss)."""
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            return [copy.deepcopy(e) for e in self._events if e["seq"] > seq][:limit]

    def latest(self, type_: str) -> dict[str, Any] | None:
        with self._lock:
            e = self._latest.get(type_)
            return copy.deepcopy(e) if e is not None else None

    def now_utc(self) -> dt.datetime:
        return self._clock.now().astimezone(dt.timezone.utc)

    def ack(self, cid: str, ok: bool, code: str = "ok", message: str = "") -> dict[str, Any]:
        """Antwort auf einen Befehl (kein Protokolleintrag; sie traegt die zuletzt vergebene Folgenummer, mindestens 1)."""
        data = self._redact({"id": cid, "ok": ok, "code": code, "message": message[:300]})
        with self._lock:
            ts = self.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
            return validate_event({"v": VERSION, "seq": max(self._seq, 1), "ts": ts, "type": "ack", "data": data})
