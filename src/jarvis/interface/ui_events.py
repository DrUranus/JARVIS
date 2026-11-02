"""UI-Adapter (Backlog-Schritt event-bus, Strang A / A1): macht den `GuiController` zu einem `UiBackend` des UI-Vertrags.

Der Adapter UEBERSETZT nur. Die Ereignisse des Controllers (Zustand, Chat, Aktivitaet, Notaus, Sprachmodus) werden zu Vertragsereignissen; die acht Befehle werden AUSSCHLIESSLICH
auf vorhandene Methoden des Controllers abgebildet (`submit`, `start_voice`, `stop_voice`, `request_cancel`, `emergency_stop`, `reset_emergency`, `request_activity`). Eine Methode
des Core, ein Werkzeug, die PermissionEngine oder die Konfiguration beruehrt er nie; jede Tool-Aktion bleibt hinter `ToolRegistry.execute -> PermissionEngine`. Ein Strukturtest
(`tests/test_ui_event_bus.py`) erzwingt das. `reset_emergency` stellt nur die Anfrage: die Engine fragt den Menschen ueber den hier angebotenen `confirmation_provider`.

Bestaetigungen schlagen fehl, nicht auf: ohne Antwort nach `timeout_s`, bei `detach()`, beim Notaus und bei jedem Fehler gilt DENY. Jeder Text wird vor dem Erzeugen eines Ereignisses
geschwaerzt (`EventLog`). Verdrahtung (bootstrap.py) gehoert nicht zu diesem Schritt: nichts ruft diesen Adapter auf."""
from __future__ import annotations

import copy
import datetime as dt
import logging
import threading
from typing import Any

from jarvis.redaction import SecretDetector
from jarvis.interface.gui_model import (ActivityEvent, ActivitySnapshot, ChatEvent, EmergencyEvent, GuiController, StateEvent, SubmitResult)
from jarvis.ui_contract.backend import UiBackend
from jarvis.ui_contract.bus import Clock, EventLog
from jarvis.ui_contract.schema import ID, MAX_ITEMS, MAX_TEXT, VERSION, ContractError, validate_command

log = logging.getLogger("jarvis.interface.ui_events")

DEFAULT_CONFIRMATION_TIMEOUT_S = 120.0
POLL_S = 0.05
_SENDERS = {"Du": "user", "JARVIS": "jarvis", "System": "system"}
_SUBMIT_ACKS = {SubmitResult.STARTED: (True, "ok"), SubmitResult.HANDLED: (True, "handled"), SubmitResult.EMPTY: (False, "empty"), SubmitResult.BUSY: (False, "busy"),
                SubmitResult.VOICE_ACTIVE: (False, "voice_active"), SubmitResult.CLOSED: (False, "closed"), SubmitResult.EMERGENCY: (False, "emergency")}
_ALLOWED_IN_EMERGENCY = ("emergency_stop", "reset_emergency", "request_snapshot")
_NO_CANCEL_NOTE = "unterstützt keinen Abbruch"


class UiConfirmationProvider:
    """Die Bestaetigungen der PermissionEngine laufen hier ueber den Vertrag (Schnittstelle wie `permissions.confirmation.ConfirmationProvider`: `confirm(request) -> Wahl`).
    Jeder Fehler und jede fehlende Antwort bedeutet DENY. Der Adapter importiert das Paket `jarvis.permissions` bewusst nicht (die Liste der erlaubten Nutzer ist durch einen
    Sicherheitstest festgelegt); die Aufzaehlung der Wahlmoeglichkeiten (`ConfirmationChoice`) reicht die spaetere Verdrahtung in `bootstrap.py` herein."""

    def __init__(self, adapter: "ControllerUiBackend", timeout_s: float = DEFAULT_CONFIRMATION_TIMEOUT_S) -> None:
        self._adapter = adapter
        self.timeout_s = timeout_s

    def confirm(self, request: Any) -> Any:
        try:
            rec = self._adapter._open_confirmation(request, self.timeout_s)
            if rec is None:
                return self._adapter._deny
            self._adapter._ctl.confirmation_waiting(True)
            try:
                while not rec["done"].wait(POLL_S):
                    self._adapter.expire()
            finally:
                self._adapter._ctl.confirmation_waiting(False)
            return rec["choice"]
        except Exception:
            log.exception("UI confirmation failed; denying")
            return self._adapter._deny


class ControllerUiBackend(UiBackend):
    def __init__(self, controller: GuiController, *, choice_enum: Any, clock: Clock | None = None, name: str = "jarvis", log_capacity: int = 1000,
                 confirmation_timeout_s: float = DEFAULT_CONFIRMATION_TIMEOUT_S, event_log: EventLog | None = None) -> None:
        self._ctl = controller
        self._deny = choice_enum.DENY                                  # die Aufzaehlung der Engine (ConfirmationChoice): nur ihre Mitglieder zaehlen als Antwort
        self._allow = {"allow_once": choice_enum.ALLOW_ONCE, "allow_session": choice_enum.ALLOW_SESSION}
        self._log = event_log or EventLog(clock, SecretDetector.from_environment(), log_capacity)
        self._lock = threading.RLock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._activity: dict[str, tuple[str, str, bool]] = {}        # Vertrags-ID -> (Art, echte ID, abbrechbar)
        self._next_id = 0
        self._attached = True
        self._voice_seen = False
        self._emergency_reason = ""
        self.confirmation_provider = UiConfirmationProvider(self, confirmation_timeout_s)
        controller.set_confirmation_denier(self.deny_pending)         # Notaus: offene Fragen gelten als abgelehnt
        caps = ["chat", "activity", "confirmation"] + (["voice"] if controller.settings is not None else []) + (["emergency"] if controller.emergency_available else [])
        engaged = controller.emergency_engaged
        self._log.emit("hello", {"contract": VERSION, "backend": name, "capabilities": caps, "emergency": engaged})
        self._log.emit("state", {"state": controller.tracker.state.value, "detail": ""})
        self._log.emit("activity", {"items": [], "problems": [], "inactive": []})
        self._log.emit("emergency", {"engaged": engaged, "reason": "", "report": []})

    # ---- Controller-Ereignisse -> Vertragsereignisse -----------------------------------------------------------------------------------
    def pump(self) -> None:
        """Holt alles, was der Controller seit dem letzten Mal gemeldet hat (er wird hier statt vom Tk-Fenster abgeholt). Ein Transport darf das regelmaessig aufrufen."""
        with self._lock:
            for ev in self._ctl.drain():
                try:
                    self._translate(ev)
                except ContractError:
                    log.warning("event %s does not fit the contract; dropped", type(ev).__name__)
            self._voice_level()
        self.expire()

    def _translate(self, ev: Any) -> None:
        if isinstance(ev, ChatEvent):
            self._log.emit("chat", {"sender": _SENDERS.get(ev.entry.sender, "system"), "text": self._log.clean(ev.entry.text, MAX_TEXT)})
        elif isinstance(ev, StateEvent):
            data = {"state": ev.state.value, "detail": self._log.clean(ev.detail, 200)}
            last = self._log.latest("state")
            if last is None or last["data"] != data:
                self._log.emit("state", data)
        elif isinstance(ev, ActivityEvent):
            self._publish_activity(ev.snapshot)
        elif isinstance(ev, EmergencyEvent):
            if ev.engaged and not self._emergency_reason:
                self._emergency_reason = "Notaus aktiv"
            report = [self._log.clean(line, 200) for line in ev.text.splitlines() if line.strip()][:20] if ev.engaged else []
            self._log.emit("emergency", {"engaged": ev.engaged, "reason": self._emergency_reason if ev.engaged else "", "report": report})
            if not ev.engaged:
                self._emergency_reason = ""
        # InputEvent, StatusEvent, CallEvent (Dialoge des Tk-Fensters) und CloseEvent haben im Vertrag keine Entsprechung.

    def _voice_level(self) -> None:
        active = self._ctl.voice_active
        if active != self._voice_seen:
            self._voice_seen = active
            self._log.emit("voice_level", {"level": 0, "active": active})

    def _publish_activity(self, snap: ActivitySnapshot) -> None:
        items, mapping = [], {}
        for it in snap.items[:MAX_ITEMS]:
            cid = "".join(c if (c.isascii() and (c.isalnum() or c in "_.:-")) else "_" for c in str(it.ident))[:64] or "_"
            if f"{it.kind}:{cid}" in mapping:
                continue
            cancellable = _NO_CANCEL_NOTE not in it.note
            mapping[f"{it.kind}:{cid}"] = (it.kind, it.ident, cancellable)
            items.append({"kind": it.kind, "id": cid, "title": self._log.clean(it.text, 200), "status": self._log.clean(it.status, 32), "note": self._log.clean(it.note, 200),
                          "cancellable": cancellable})
        self._activity = {k: v for k, v in mapping.items()}
        self._log.emit("activity", {"items": items, "problems": [self._log.clean(p, 200) for p in snap.problems[:20]],
                                    "inactive": [self._log.clean(p, 64) for p in snap.inactive[:20]]})

    # ---- UiBackend ------------------------------------------------------------------------------------------------------------------------
    def hello(self) -> dict[str, Any]:
        return self._log.latest("hello") or {}

    def snapshot(self) -> list[dict[str, Any]]:
        self._attached = True
        self.pump()
        with self._lock:
            events = [e for e in (self._log.latest(k) for k in ("hello", "state", "activity", "emergency")) if e is not None]
            events += [r["event"] for r in self._pending.values()]
        return sorted((copy.deepcopy(e) for e in events), key=lambda e: e["seq"])

    def events_since(self, seq: int, limit: int = 200) -> list[dict[str, Any]]:
        self.pump()
        return self._log.events_since(seq, limit)

    def detach(self) -> None:
        with self._lock:
            self._attached = False
            for rid in list(self._pending):
                self._close(rid, "cancelled")
        if self._ctl.voice_active:
            self._ctl.stop_voice()
        self.pump()

    def send(self, command: dict[str, Any]) -> dict[str, Any]:
        try:
            cmd = validate_command(command)
        except ContractError:
            raw = command.get("id") if isinstance(command, dict) else None
            try:
                cid = ID.check(raw, "id")
            except ContractError:
                cid = "invalid"
            return self._log.ack(cid, False, "invalid_command", "the command does not follow the contract")
        self._attached = True
        self.pump()
        cid = cmd["id"]
        if self._ctl.emergency_engaged and cmd["type"] not in _ALLOWED_IN_EMERGENCY and not self._is_reset_answer(cmd):
            return self._log.ack(cid, False, "emergency", "the emergency stop is engaged")
        try:
            ack = getattr(self, "_do_" + cmd["type"])(cid, cmd["data"])
        except Exception as exc:
            log.exception("UI command %s failed", cmd["type"])
            ack = self._log.ack(cid, False, "internal_error", type(exc).__name__)
        self.pump()
        return ack

    # ---- Befehle: nur vorhandene GuiController-Methoden -------------------------------------------------------------------------------------
    def _do_submit_text(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        ok, code = _SUBMIT_ACKS[self._ctl.submit(data["text"])]
        return self._log.ack(cid, ok, code)

    def _do_start_voice(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        reason = self._ctl.start_voice()
        return self._log.ack(cid, True) if not reason else self._log.ack(cid, False, "voice_unavailable", self._log.clean(reason, 300))

    def _do_stop_voice(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._ctl.voice_active:
            return self._log.ack(cid, False, "not_active", "voice mode is not running")
        self._ctl.stop_voice()
        return self._log.ack(cid, True)

    def _do_cancel(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        known = self._activity.get(f"{data['kind']}:{data['id']}")
        if known is None:
            return self._log.ack(cid, False, "unknown_task", "no such activity")
        kind, ident, cancellable = known
        if not cancellable:
            return self._log.ack(cid, False, "not_cancellable", "this work cannot be cancelled")
        if not self._ctl.request_cancel(kind, ident):
            return self._log.ack(cid, False, "busy", "a cancel request for this work is already running")
        return self._log.ack(cid, True, "cancel_requested")

    def _do_emergency_stop(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        if self._ctl.emergency_engaged:
            return self._log.ack(cid, True, "already_engaged")
        if not self._ctl.emergency_available:
            return self._log.ack(cid, False, "unavailable", "no central emergency stop is available")
        self._emergency_reason = "Notaus per UI"
        self._ctl.emergency_stop(self._emergency_reason)
        return self._log.ack(cid, True)

    def _do_reset_emergency(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._ctl.emergency_engaged:
            return self._log.ack(cid, False, "not_engaged", "the emergency stop is not engaged")
        if not self._ctl.reset_emergency():
            return self._log.ack(cid, False, "busy", "the question is already open")
        return self._log.ack(cid, True, "confirmation_requested")        # nichts wird durch die Nachricht aufgehoben: der Mensch entscheidet

    def _do_request_snapshot(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        self._ctl.request_activity()
        return self._log.ack(cid, True)

    def _do_confirm(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rec = self._pending.get(data["request_id"])
            if rec is None:
                return self._log.ack(cid, False, "unknown_request", "no such open confirmation")
            if data["choice"] not in rec["choices"]:
                return self._log.ack(cid, False, "choice_not_offered", "this choice was not offered")
            self._close(data["request_id"], "denied" if data["choice"] == "deny" else data["choice"])
        return self._log.ack(cid, True)

    # ---- Rueckfragen -------------------------------------------------------------------------------------------------------------------------
    def _is_reset_answer(self, cmd: dict[str, Any]) -> bool:
        """Beim Notaus ist `confirm` gesperrt, ausser fuer die Frage der Engine, ob er aufgehoben werden soll: sonst waere die Aufhebung ueber die Oberflaeche nie
        beantwortbar. Die Entscheidung trifft auch dann der Mensch; `deny` und jeder Fehler lassen den Notaus bestehen."""
        if cmd["type"] != "confirm":
            return False
        with self._lock:
            rec = self._pending.get(cmd["data"]["request_id"])
            return bool(rec and rec["reset"])

    def _open_confirmation(self, request: Any, timeout_s: float) -> dict[str, Any] | None:
        with self._lock:
            if not self._attached:
                return None                                              # niemand da, den man fragen koennte: abgelehnt
            self._next_id += 1
            rid = f"r{self._next_id}"
            choices = ["allow_once"] + (["allow_session"] if request.session_allowed else []) + ["deny"]
            timeout = min(600.0, max(1.0, float(timeout_s)))
            clean = self._log.clean
            event = self._log.emit("confirmation_request", {
                "request_id": rid, "tool": clean(request.tool, 64), "action": clean(request.action, 64), "resource": clean(request.resource or "", 300),
                "level": request.level.value, "reason": clean(request.reason, 300),
                "context": [{"key": clean(k, 64), "value": clean(v, 300)} for k, v in list(request.context.items())[:10]], "choices": choices, "timeout_s": timeout})
            rec = {"event": event, "choices": choices, "deadline": self._log.now_utc() + dt.timedelta(seconds=timeout), "done": threading.Event(),
                   "choice": self._deny, "reset": request.tool == "jarvis" and request.action == "emergency_reset"}
            self._pending[rid] = rec
            return rec

    def _close(self, rid: str, outcome: str) -> None:
        with self._lock:
            rec = self._pending.pop(rid, None)
            if rec is None:
                return
            try:
                if outcome in self._allow and outcome in rec["choices"]:
                    rec["choice"] = self._allow[outcome]
                self._log.emit("confirmation_closed", {"request_id": rid, "outcome": outcome})
            finally:
                rec["done"].set()

    def expire(self) -> None:
        """Unbeantwortete Fragen schliessen nach `timeout_s` als `timeout` (= abgelehnt)."""
        with self._lock:
            now = self._log.now_utc()
            for rid, rec in list(self._pending.items()):
                if rec["deadline"] <= now:
                    self._close(rid, "timeout")

    def deny_pending(self) -> int:
        """Notaus: jede offene Frage gilt als abgelehnt (`cancelled`). Ausgenommen ist nur die Frage der Engine, ob der Notaus aufgehoben werden soll: die Anhalte-Laeufe
        des Controllers kommen asynchron, ein spaeter Lauf duerfte sonst die Frage schlucken, die der Mensch gerade beantworten soll (ohne Antwort bleibt der Notaus ohnehin)."""
        with self._lock:
            ids = [rid for rid, rec in self._pending.items() if not rec["reset"]]
            for rid in ids:
                self._close(rid, "cancelled")
        return len(ids)
