"""Conformance suite for every `UiBackend`: the real backend (strand A) and the fake pass the same checks; a transport/UI (strand B) can use it to test its client.
Raises AssertionError with a clear text. Only the contract is used; no secrets are written anywhere."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from jarvis.ui_contract.backend import UiBackend
from jarvis.ui_contract.schema import COMMAND_TYPES, MAX_TEXT, VERSION, ContractError, looks_secret, validate_event

SECRET = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"


@dataclass(frozen=True)
class ConformanceHooks:
    """Optional helpers of a backend under test. `trigger_confirmation(backend)` makes it open a confirmation (the real backend does so through a tool call);
    `advance(backend, seconds)` lets time pass for the timeout check."""
    trigger_confirmation: Callable[[UiBackend], Any] | None = None
    advance: Callable[[UiBackend, float], Any] | None = None


def _cmd(type_: str, data: dict[str, Any] | None = None, cid: str = "k1") -> dict[str, Any]:
    return {"v": VERSION, "id": cid, "type": type_, "data": data or {}}


def _valid(events: list[dict[str, Any]], what: str) -> list[dict[str, Any]]:
    out = []
    for e in events:
        try:
            out.append(validate_event(e))
        except ContractError as exc:
            raise AssertionError(f"{what}: event does not follow the contract ({exc})") from None
    return out


def _ascending(events: list[dict[str, Any]], what: str) -> None:
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(set(seqs)), f"{what}: seq must be strictly ascending, got {seqs}"


def _ack(backend: UiBackend, command: dict[str, Any], *, ok: bool, code: str | None = None) -> dict[str, Any]:
    ack = _valid([backend.send(command)], f"ack for {command.get('type')!r}")[0]
    assert ack["type"] == "ack", "send() must return an ack event"
    assert ack["data"]["ok"] is ok, f"{command.get('type')!r}: expected ok={ok}, got {ack['data']}"
    if code is not None:
        assert ack["data"]["code"] == code, f"{command.get('type')!r}: expected code {code!r}, got {ack['data']['code']!r}"
    return ack


def run_conformance(make_backend: Callable[[], UiBackend], hooks: ConformanceHooks | None = None) -> None:
    hooks = hooks or ConformanceHooks()
    # 1. snapshot: hello first, all valid, ascending, the pictures a UI needs
    b = make_backend()
    snap = _valid(b.snapshot(), "snapshot")
    assert snap and snap[0]["type"] == "hello", "the snapshot must start with the hello event"
    assert snap[0]["data"]["contract"] == VERSION, "hello must name the contract version"
    _ascending(snap, "snapshot")
    assert {"hello", "state", "activity", "emergency"} <= {e["type"] for e in snap}, "snapshot lacks state, activity or emergency"
    assert b.hello()["type"] == "hello"
    # 2. replay
    log = _valid(b.events_since(0), "events_since(0)")
    _ascending(log, "events_since(0)")
    assert b.events_since(log[-1]["seq"]) == [], "events_since(last seq) must be empty"
    assert len(b.events_since(0, 1)) <= 1, "limit must be honoured"
    # 3. commands: every valid one is answered with a matching ack
    for t in COMMAND_TYPES:
        if t in ("emergency_stop", "reset_emergency", "confirm", "cancel"):
            continue
        data = {"text": "Hallo"} if t == "submit_text" else {}
        ack = _valid([b.send(_cmd(t, data, "c-" + t))], t)[0]
        assert ack["type"] == "ack" and ack["data"]["id"] == "c-" + t, f"{t}: the ack must carry the command id"
    # 4. malformed input is refused with ok=false, never accepted and never an exception
    for bad in ({"v": VERSION, "id": "x1", "type": "grant_permission", "data": {}}, {"v": "2.0", "id": "x2", "type": "request_snapshot", "data": {}},
                _cmd("submit_text", {"text": "a" * (MAX_TEXT + 1)}, "x3"), _cmd("submit_text", {"text": ""}, "x4"), {"type": "request_snapshot"}, "kein objekt"):
        ack = _valid([b.send(bad)], "ack for a malformed command")[0]       # type: ignore[arg-type]
        assert ack["data"]["ok"] is False, f"a malformed command must be refused: {str(bad)[:60]}"
    _ack(b, _cmd("confirm", {"request_id": "gibt-es-nicht", "choice": "allow_once"}, "x5"), ok=False, code="unknown_request")
    _ack(b, _cmd("cancel", {"kind": "goal", "id": "gibt-es-nicht"}, "x6"), ok=False)
    # 5. no secret ever leaves the backend
    c = make_backend()
    c.send(_cmd("submit_text", {"text": f"mein Schluessel ist {SECRET}"}, "s1"))
    for e in _valid(c.events_since(0), "secret check") + c.snapshot():
        assert not looks_secret(str(e["data"])), f"a secret-looking value appeared in a {e['type']} event"
    # 6. optional: confirmation flow (needs the backend to be able to open one)
    if hooks.trigger_confirmation is not None:
        d = make_backend()
        hooks.trigger_confirmation(d)
        pending = [e for e in _valid(d.snapshot(), "snapshot with confirmation") if e["type"] == "confirmation_request"]
        assert pending, "an open confirmation must be part of the snapshot"
        req = pending[0]["data"]
        assert req["choices"], "a request must offer at least one choice"
        _ack(d, _cmd("confirm", {"request_id": req["request_id"], "choice": "allow_always"}, "q0"), ok=False, code="invalid_command")
        offered = {"allow_once", "allow_session", "deny"} - set(req["choices"])
        if offered:
            _ack(d, _cmd("confirm", {"request_id": req["request_id"], "choice": sorted(offered)[0]}, "q1"), ok=False, code="choice_not_offered")
        _ack(d, _cmd("confirm", {"request_id": req["request_id"], "choice": "deny"}, "q2"), ok=True)
        closed = [e for e in _valid(d.events_since(0), "events") if e["type"] == "confirmation_closed"]
        assert closed and closed[-1]["data"] == {"request_id": req["request_id"], "outcome": "denied"}, "denying must close the request as denied"
        _ack(d, _cmd("confirm", {"request_id": req["request_id"], "choice": "deny"}, "q3"), ok=False, code="unknown_request")
        # detach means deny
        e2 = make_backend()
        hooks.trigger_confirmation(e2)
        open_id = [x for x in e2.snapshot() if x["type"] == "confirmation_request"][0]["data"]["request_id"]
        e2.detach()
        last = [x for x in e2.events_since(0) if x["type"] == "confirmation_closed"][-1]["data"]
        assert last == {"request_id": open_id, "outcome": "cancelled"}, "a vanished client must close open confirmations as cancelled (denied)"
        if hooks.advance is not None:
            f = make_backend()
            hooks.trigger_confirmation(f)
            rid = [x for x in f.snapshot() if x["type"] == "confirmation_request"][0]["data"]
            hooks.advance(f, rid["timeout_s"] + 1)
            last = [x for x in f.events_since(0) if x["type"] == "confirmation_closed"][-1]["data"]
            assert last == {"request_id": rid["request_id"], "outcome": "timeout"}, "an unanswered confirmation must close as timeout (denied)"
    # 7. emergency stop
    g = make_backend()
    _ack(g, _cmd("emergency_stop", None, "e1"), ok=True)
    after = _valid(g.snapshot(), "snapshot after the emergency stop")
    assert [e for e in after if e["type"] == "emergency"][-1]["data"]["engaged"] is True, "the emergency stop must show as engaged"
    assert [e for e in after if e["type"] == "state"][-1]["data"]["state"] == "emergency", "the state must be emergency"
    for t, data in (("submit_text", {"text": "weiter"}), ("start_voice", {}), ("cancel", {"kind": "goal", "id": "g1"})):
        _ack(g, _cmd(t, data, "e-" + t), ok=False, code="emergency")
    _ack(g, _cmd("request_snapshot", None, "e2"), ok=True)
    _ack(g, _cmd("reset_emergency", None, "e3"), ok=True)
    still = _valid(g.snapshot(), "snapshot after reset_emergency")
    assert [e for e in still if e["type"] == "emergency"][-1]["data"]["engaged"] is True, "reset_emergency is only a request: the stop stays until the human decides"
