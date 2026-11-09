"""Nur lesende Ansichten des Control Centers (cc-results-audit): Ergebnisse und Verlauf aus dem Journal, Audit-Ereignisse mit Filter.

Dieses Modul liest ausschliesslich: das Journal ueber `list` (die Datenbank wird nie angelegt oder veraendert), das Audit-Protokoll ueber eine `tail`-Funktion.
Es importiert weder Berechtigungen noch Werkzeuge, fuehrt nichts aus und hat keinen Schreibweg. Jeder Text wird vor der Ausgabe erneut geschwaerzt
(`SecretDetector`) und gekuerzt; Anzahl und Suchfenster sind begrenzt. Was nicht vorliegt, wird leer mit Grund gemeldet - nichts wird erfunden."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Mapping

from jarvis.redaction import SecretDetector

log = logging.getLogger("jarvis.control_center")

DEFAULT_LIMIT, MAX_LIMIT, AUDIT_WINDOW = 50, 200, 1000
MAX_TEXT_LEN, MAX_ITEMS_PER_LIST = 1000, 20
KINDS = ("goal", "agent_task")
_TOKEN = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
_STATUS = re.compile(r"[A-Za-z_]{1,32}")
_NUMBER = re.compile(r"[0-9]{1,6}")
_AUDIT_FIELDS = ("id", "timestamp", "type", "request_id", "tool", "action", "resource", "level", "status", "rule", "scope", "detail")


class ViewError(ValueError):
    """The request does not follow the view contract (unknown parameter, bad filter, limit out of range). The message is safe to show."""


class ReadViews:
    def __init__(self, journal: Any = None, audit_tail: Callable[[int], list[dict[str, Any]]] | None = None, detector: SecretDetector | None = None, *,
                 default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT, audit_window: int = AUDIT_WINDOW,
                 doctor: Callable[[], dict[str, Any]] | None = None) -> None:
        if not 1 <= default_limit <= max_limit:
            raise ValueError("default_limit must be within 1..max_limit")
        self._journal, self._audit_tail, self._doctor = journal, audit_tail, doctor
        self._detector = detector or SecretDetector.from_environment()
        self._default, self._max, self._window = default_limit, max_limit, max(1, audit_window)

    # ---- Hilfen -----------------------------------------------------------------------------------------------------------------------------
    def _limit(self, params: Mapping[str, str]) -> int:
        raw = params.get("limit")
        if raw is None:
            return self._default
        if not _NUMBER.fullmatch(raw) or not 1 <= int(raw) <= self._max:
            raise ViewError(f"limit must be a number within 1..{self._max}")
        return int(raw)

    @staticmethod
    def _check_keys(params: Mapping[str, str], allowed: tuple[str, ...]) -> None:
        unknown = sorted(set(params) - set(allowed) - {"limit"})
        if unknown:
            raise ViewError("unknown parameter: " + ", ".join(k[:32] for k in unknown))

    @staticmethod
    def _filter(params: Mapping[str, str], name: str, pattern: re.Pattern[str]) -> str | None:
        raw = params.get(name)
        if raw is None:
            return None
        if not pattern.fullmatch(raw):
            raise ViewError(f"invalid filter {name}")
        return raw

    def _text(self, value: Any, limit: int = MAX_TEXT_LEN) -> str:
        return " ".join(self._detector.redact("" if value is None else value).split())[:limit]

    def _texts(self, values: Any) -> list[str]:
        return [self._text(v) for v in list(values or ())[:MAX_ITEMS_PER_LIST]]

    # ---- Verlauf und Ergebnisse (Journal) ---------------------------------------------------------------------------------------------------
    def history(self, params: Mapping[str, str]) -> dict[str, Any]:
        self._check_keys(params, ("kind", "status"))
        limit = self._limit(params)
        kind = self._filter(params, "kind", _TOKEN)
        if kind is not None and kind not in KINDS:
            raise ViewError("invalid filter kind")
        status = self._filter(params, "status", _STATUS)
        status = status.upper() if status else None
        out: dict[str, Any] = {"available": False, "limit": limit, "filters": {"kind": kind, "status": status}, "items": [], "reason": ""}
        if self._journal is None:
            out["reason"] = "Kein Journal aktiv (journal.enabled = false)."
            return out
        try:
            cap = int(getattr(self._journal, "max_entries", MAX_LIMIT))
            entries = self._journal.list(limit=cap, kind=kind)
        except Exception:                                                              # noqa: BLE001 - never show internals of a broken store
            log.warning("journal view failed", exc_info=True)
            out["reason"] = "Das Journal ist nicht lesbar."
            return out
        out["available"] = True
        out["items"] = [self._entry(e) for e in entries if status is None or e.status == status][:limit]
        return out

    def _entry(self, e: Any) -> dict[str, Any]:
        iso = lambda d: d.isoformat() if d is not None else None                       # noqa: E731
        return {"kind": self._text(e.kind, 32), "id": self._text(e.ref_id, 64), "status": self._text(e.status, 32), "text": self._text(e.text),
                "result": self._text(e.result), "evidence": self._texts(e.evidence), "error": self._text(e.error) if e.error else None,
                "created_at": iso(e.created_at), "started_at": iso(e.started_at), "finished_at": iso(e.finished_at), "recorded_at": iso(e.recorded_at),
                "steps": [{"no": int(s.step_no), "id": self._text(s.step_id, 64), "status": self._text(s.status, 32), "text": self._text(s.text),
                           "side_effect": bool(s.side_effect), "result": self._text(s.result), "evidence": self._texts(s.evidence),
                           "error": self._text(s.error) if s.error else None} for s in list(e.steps)[:100]]}

    # ---- Audit-Ereignisse (geschwaerzt) -----------------------------------------------------------------------------------------------------
    def audit(self, params: Mapping[str, str]) -> dict[str, Any]:
        names = ("type", "tool", "status", "level")
        self._check_keys(params, names)
        limit = self._limit(params)
        flt = {n: self._filter(params, n, _TOKEN) for n in names}
        out: dict[str, Any] = {"available": False, "limit": limit, "filters": flt, "items": [], "reason": ""}
        if self._audit_tail is None:
            out["reason"] = "Kein Audit-Protokoll aktiv (security.audit_enabled = false)."
            return out
        try:
            raw = list(self._audit_tail(self._window))
        except Exception:                                                              # noqa: BLE001
            log.warning("audit view failed", exc_info=True)
            out["reason"] = "Das Audit-Protokoll ist nicht lesbar."
            return out
        out["available"] = True
        items = []
        for ev in reversed(raw):                                                       # newest first
            item = self._audit_item(ev)
            if all(v is None or item.get(n) == v for n, v in flt.items()):
                items.append(item)
                if len(items) >= limit:
                    break
        out["items"] = items
        return out

    def _audit_item(self, ev: Any) -> dict[str, Any]:
        if not isinstance(ev, dict):
            return {"type": "unreadable_line"}
        item = {k: self._text(ev[k], 300 if k != "detail" else MAX_TEXT_LEN) for k in _AUDIT_FIELDS if k in ev and ev[k] not in (None, "")}
        extra = ev.get("extra")
        if isinstance(extra, dict) and extra:
            item["extra"] = {self._text(k, 64): self._text(v, 300) for k, v in list(self._detector.redact_mapping(extra).items())[:MAX_ITEMS_PER_LIST]}
        return item or {"type": "unreadable_line"}


    # ---- Einrichtung und Diagnose (nur lesend, nur Daten) -----------------------------------------------------------------------------------
    def doctor(self, params: Mapping[str, str]) -> dict[str, Any]:
        """Der Einrichtungsbericht (siehe setup_view): Python, Pakete, Konfiguration, Komponenten, Agenten, Schluessel nur als gesetzt/nicht gesetzt. Keine Parameter."""
        if params:
            raise ViewError("unknown parameter: " + ", ".join(sorted(k[:32] for k in params)))
        out: dict[str, Any] = {"available": False, "limit": 0, "items": [], "reason": ""}
        if self._doctor is None:
            out["reason"] = "Kein Diagnosebericht verfügbar."
            return out
        try:
            rep = self._doctor()
        except Exception:                                                              # noqa: BLE001 - never show internals
            log.warning("doctor view failed", exc_info=True)
            out["reason"] = "Die Diagnose konnte nicht erstellt werden."
            return out
        t = self._text
        out.update(available=True, python=t(rep.get("python"), 32), platform=t(rep.get("platform"), 32), jarvis=t(rep.get("jarvis"), 64),
                   errors=int(rep.get("errors", 0)), hints=int(rep.get("hints", 0)), note=t(rep.get("note"), 300),
                   items=[{"level": t(i.get("level"), 16), "text": t(i.get("text"), 600)} for i in list(rep.get("items") or [])[:60]],
                   components=[{"name": t(c.get("name"), 60), "state": t(c.get("state"), 8), "text": t(c.get("text"), 400)} for c in list(rep.get("components") or [])[:20]],
                   agents=[{"id": t(a.get("id"), 32), "status": t(a.get("status"), 16), "reason": t(a.get("reason"), 200)} for a in list(rep.get("agents") or [])[:20]],
                   keys={t(k, 64): bool(v) for k, v in list((rep.get("keys") or {}).items())[:12]},
                   security={t(k, 32): t(v, 32) for k, v in list((rep.get("security") or {}).items())[:6]})
        return out
