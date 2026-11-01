"""Deterministic fake backend for the contract: no model, no tool, no microphone, no clock of its own (a `FakeClock` is injected). Strand B develops and tests the
Control Center against it, strand A runs the same conformance suite against the real backend. Texts starting with `!` script behaviour: `!task` adds an activity item,
`!confirm` opens a confirmation (it needs an answer, times out after `timeout_s` and closes as denied-by-timeout)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from jarvis.ui_contract.backend import UiBackend
from jarvis.ui_contract.schema import VERSION, ContractError, redact_text, validate_command, validate_event


class FakeClock:
    def __init__(self, start: dt.datetime | None = None) -> None:
        self._t = start or dt.datetime(2026, 11, 2, 10, 0, 0, tzinfo=dt.timezone.utc)

    def now(self) -> dt.datetime:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += dt.timedelta(seconds=seconds)


class FakeUiBackend(UiBackend):
    TIMEOUT_S = 30

    def __init__(self, clock: FakeClock | None = None, name: str = "fake") -> None:
        self._clock = clock or FakeClock()
        self._name = name
        self._log: list[dict[str, Any]] = []
        self._seq = 0
        self._latest: dict[str, dict[str, Any]] = {}
        self._activity: list[dict[str, Any]] = []
        self._pending: dict[str, dict[str, Any]] = {}
        self._voice = False
        self._emergency_on = False
        self._next_id = 0
        self._emit("hello", {"contract": VERSION, "backend": name, "capabilities": ["chat", "voice", "activity", "confirmation", "emergency"], "emergency": False})
        self._emit("state", {"state": "ready", "detail": ""})
        self._publish_activity()
        self._emit("emergency", {"engaged": False, "reason": "", "report": []})

    # ---- Ereignisse ---------------------------------------------------------------------------------------------------------------------
    def _emit(self, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        ts = self._clock.now().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event = validate_event({"v": VERSION, "seq": self._seq, "ts": ts, "type": type_, "data": data})
        self._log.append(event)
        if type_ in ("hello", "state", "activity", "emergency"):
            self._latest[type_] = event
        return event

    def _chat(self, sender: str, text: str) -> None:
        self._emit("chat", {"sender": sender, "text": redact_text(text)[:4000]})

    def _state(self, state: str, detail: str = "") -> None:
        self._emit("state", {"state": state, "detail": detail})

    def _publish_activity(self) -> None:
        self._emit("activity", {"items": [dict(i) for i in self._activity], "problems": [], "inactive": []})

    def _id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}{self._next_id}"

    def _ack(self, cid: str, ok: bool, code: str = "ok", message: str = "") -> dict[str, Any]:
        ts = self._clock.now().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return validate_event({"v": VERSION, "seq": max(self._seq, 1), "ts": ts, "type": "ack", "data": {"id": cid, "ok": ok, "code": code, "message": message}})

    # ---- Schnittstelle ------------------------------------------------------------------------------------------------------------------
    def hello(self) -> dict[str, Any]:
        return dict(self._latest["hello"])

    def snapshot(self) -> list[dict[str, Any]]:
        events = [self._latest[k] for k in ("hello", "state", "activity", "emergency")]
        events += [r["event"] for r in self._pending.values()]
        return sorted((dict(e) for e in events), key=lambda e: e["seq"])

    def events_since(self, seq: int, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        return [dict(e) for e in self._log if e["seq"] > seq][:limit]

    def detach(self) -> None:
        for rid in list(self._pending):
            self._close(rid, "cancelled")
        if self._voice:
            self._voice = False
            self._emit("voice_level", {"level": 0, "active": False})
        if not self._emergency_on:
            self._state("ready")

    def advance(self, seconds: float) -> None:
        """Test helper: time passes; confirmations that nobody answered close as timeout (fail closed)."""
        self._clock.advance(seconds)
        now = self._clock.now()
        for rid, rec in list(self._pending.items()):
            if rec["deadline"] <= now:
                self._close(rid, "timeout")

    def _refuse_in_emergency(self, command: dict[str, Any]) -> dict[str, Any] | None:
        if self._emergency_on and command["type"] not in ("emergency_stop", "reset_emergency", "request_snapshot"):
            return self._ack(command["id"], False, "emergency", "the emergency stop is engaged")
        return None

    def send(self, command: dict[str, Any]) -> dict[str, Any]:
        try:
            cmd = validate_command(command)
        except ContractError:
            raw_id = command.get("id") if isinstance(command, dict) else None
            return self._ack(raw_id if isinstance(raw_id, str) and 0 < len(raw_id) <= 64 and raw_id.replace("-", "x").replace("_", "x").replace(".", "x").replace(":", "x").isalnum() else "invalid",
                             False, "invalid_command", "the command does not follow the contract")
        refused = self._refuse_in_emergency(cmd)
        if refused is not None:
            return refused
        return getattr(self, "_do_" + cmd["type"])(cmd["id"], cmd["data"])

    # ---- Befehle ------------------------------------------------------------------------------------------------------------------------
    def _do_submit_text(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        if self._pending:
            return self._ack(cid, False, "busy", "a confirmation is open")
        text = data["text"]
        self._chat("user", text)
        if text.startswith("!task"):
            tid = self._id("t")
            self._activity.append({"kind": "agent_task", "id": tid, "title": "Testaufgabe", "status": "RUNNING", "note": "", "cancellable": True})
            self._publish_activity()
            self._chat("jarvis", f"Aufgabe {tid} gestartet")
        elif text.startswith("!confirm"):
            self._request(tool="keyboard", action="type", resource="keyboard://text@notepad.exe", level="yellow", reason="Text tippen (Test)",
                          context=[{"key": "fenster", "value": "Notepad"}], choices=["allow_once", "deny"], reply=True)
        else:
            self._state("processing")
            self._chat("jarvis", "Echo: " + text[:100])
            self._state("ready")
        return self._ack(cid, True)

    def _request(self, *, tool: str, action: str, resource: str, level: str, reason: str, context: list[dict[str, str]], choices: list[str], reply: bool,
                 kind: str = "text") -> str:
        rid = self._id("r")
        event = self._emit("confirmation_request", {"request_id": rid, "tool": tool, "action": action, "resource": resource, "level": level, "reason": reason,
                                                    "context": context, "choices": choices, "timeout_s": self.TIMEOUT_S})
        self._pending[rid] = {"event": event, "choices": choices, "deadline": self._clock.now() + dt.timedelta(seconds=self.TIMEOUT_S), "reply": reply, "kind": kind}
        self._state("awaiting_confirmation")
        return rid

    def _close(self, rid: str, outcome: str) -> None:
        rec = self._pending.pop(rid)
        self._emit("confirmation_closed", {"request_id": rid, "outcome": outcome})
        allowed = outcome in ("allow_once", "allow_session")
        if rec["kind"] == "emergency_reset":
            if allowed:
                self._emergency_on = False
                self._emit("emergency", {"engaged": False, "reason": "", "report": []})
        elif rec["reply"]:
            self._chat("jarvis", "Bestätigt" if allowed else ("Zeitüberschreitung: nicht erlaubt" if outcome == "timeout" else "Abgelehnt"))
        if not self._pending:
            self._state("emergency" if self._emergency_on else "ready")

    def _do_confirm(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        rec = self._pending.get(data["request_id"])
        if rec is None:
            return self._ack(cid, False, "unknown_request", "no such open confirmation")
        if data["choice"] not in rec["choices"]:
            return self._ack(cid, False, "choice_not_offered", "this choice was not offered")
        self._close(data["request_id"], "denied" if data["choice"] == "deny" else data["choice"])
        return self._ack(cid, True)

    def _do_cancel(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        item = next((i for i in self._activity if i["id"] == data["id"] and i["kind"] == data["kind"]), None)
        if item is None:
            return self._ack(cid, False, "unknown_task", "no such activity")
        if not item["cancellable"]:
            return self._ack(cid, False, "not_cancellable", "this work cannot be cancelled")
        self._activity.remove(item)
        self._emit("task_update", {"kind": item["kind"], "id": item["id"], "status": "CANCELLED", "detail": ""})
        self._publish_activity()
        return self._ack(cid, True)

    def _do_start_voice(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        if self._voice:
            return self._ack(cid, False, "voice_active", "voice mode is already running")
        self._voice = True
        self._state("listening")
        self._emit("voice_level", {"level": 0, "active": True})
        return self._ack(cid, True)

    def _do_stop_voice(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._voice:
            return self._ack(cid, False, "not_active", "voice mode is not running")
        self._voice = False
        self._emit("voice_level", {"level": 0, "active": False})
        self._state("ready")
        return self._ack(cid, True)

    def _emergency(self, reason: str) -> None:
        self._emergency_on = True
        for rid in list(self._pending):
            self._close(rid, "cancelled")
        self._voice = False
        self._emit("emergency", {"engaged": True, "reason": reason, "report": ["fake: stopped"]})
        self._state("emergency", reason)

    def _do_emergency_stop(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        if self._emergency_on:
            return self._ack(cid, True, "already_engaged")
        self._emergency("Notaus per UI")
        return self._ack(cid, True)

    def _do_reset_emergency(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._emergency_on:
            return self._ack(cid, False, "not_engaged", "the emergency stop is not engaged")
        if any(r["kind"] == "emergency_reset" for r in self._pending.values()):
            return self._ack(cid, False, "busy", "the question is already open")
        self._request(tool="jarvis", action="emergency_reset", resource="emergency stop", level="yellow", reason="Notaus aufheben?", context=[],
                      choices=["allow_once", "deny"], reply=False, kind="emergency_reset")
        return self._ack(cid, True, "confirmation_requested")        # nothing is lifted by the message itself: the human decides

    def _do_request_snapshot(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._ack(cid, True)
