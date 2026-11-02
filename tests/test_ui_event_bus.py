"""Ereignisprotokoll (EventLog) und UI-Adapter (ControllerUiBackend) des UI-Vertrags. Kein Tk, kein Netzwerk, kein Mikrofon; Linux und Windows gleich."""
from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.interface import ui_events
from jarvis.interface.gui_model import ActivityEvent, ActivityItem, ActivitySnapshot, GuiController
from jarvis.interface.ui_events import ControllerUiBackend
from jarvis.permissions.confirmation import ConfirmationChoice, ConfirmationRequest
from jarvis.permissions.emergency import EmergencyStop
from jarvis.permissions.levels import PermissionLevel
from jarvis.redaction import SecretDetector
from jarvis.ui_contract import COMMAND_TYPES, ConformanceHooks, ContractError, FakeClock, run_conformance
from jarvis.ui_contract.bus import EventLog

SECRET = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"
ROOT = Path(__file__).resolve().parents[1]


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


def cmd(type_, data=None, cid="c1"):
    return {"v": "1.0", "id": cid, "type": type_, "data": data or {}}


# ---- EventLog ------------------------------------------------------------------------------------------------------------------------------------
def test_eventlog_numbers_events_and_replays():
    log = EventLog(FakeClock(), SecretDetector([]))
    seqs = [log.emit("chat", {"sender": "user", "text": f"t{i}"})["seq"] for i in range(5)]
    assert seqs == [1, 2, 3, 4, 5] and log.last_seq == 5
    assert [e["seq"] for e in log.events_since(2)] == [3, 4, 5]
    assert [e["seq"] for e in log.events_since(0, 2)] == [1, 2]
    assert log.events_since(5) == []
    assert len(log.events_since(0, 0)) == 1 and len(log.events_since(0, 99999)) == 5      # limit 1..1000


def test_eventlog_is_a_ring_buffer_but_keeps_the_latest_snapshot_events():
    log = EventLog(FakeClock(), SecretDetector([]), capacity=3)
    log.emit("state", {"state": "ready", "detail": ""})
    for i in range(5):
        log.emit("chat", {"sender": "user", "text": str(i)})
    got = log.events_since(0)
    assert [e["seq"] for e in got] == [4, 5, 6]                       # older ones are gone, numbers keep counting
    assert log.latest("state")["seq"] == 1 and log.latest("hello") is None


def test_eventlog_returns_copies_so_callers_cannot_change_the_log():
    log = EventLog(FakeClock(), SecretDetector([]))
    e = log.emit("chat", {"sender": "user", "text": "a"})
    e["type"] = "error"
    log.events_since(0)[0]["data"]["text"] = "x"
    assert log.events_since(0)[0]["type"] == "chat" and log.events_since(0)[0]["data"]["text"] == "a"


def test_eventlog_redacts_every_text_before_the_event_exists():
    log = EventLog(FakeClock(), detector=SecretDetector(["geheim-wert-123"]))
    log.emit("confirmation_request", {"request_id": "r1", "tool": "t", "action": "a", "resource": f"datei {SECRET}", "level": "red", "reason": "geheim-wert-123",
                                      "context": [{"key": "k", "value": f"password: hunter2xx {SECRET}"}], "choices": ["deny"], "timeout_s": 5})
    text = repr(log.events_since(0)) + repr(log.latest("hello"))
    assert SECRET not in text and "geheim-wert-123" not in text and "hunter2xx" not in text and "[REDACTED]" in text


def test_eventlog_redaction_failure_creates_no_event_and_burns_no_number():
    class Broken(SecretDetector):
        def redact(self, text):
            raise RuntimeError("boom")
    log = EventLog(FakeClock(), detector=Broken())
    with pytest.raises(RuntimeError):
        log.emit("chat", {"sender": "user", "text": "a"})
    assert log.last_seq == 0 and log.events_since(0) == []


def test_eventlog_rejects_events_that_break_the_contract_without_a_trace():
    log = EventLog(FakeClock(), SecretDetector([]))
    with pytest.raises(ContractError):
        log.emit("chat", {"sender": "nobody", "text": "a"})
    with pytest.raises(ContractError):
        log.emit("grant_permission", {})
    assert log.last_seq == 0


def test_eventlog_clean_redacts_before_cutting():
    log = EventLog(FakeClock(), SecretDetector([]))
    out = log.clean("x " * 3 + SECRET, 12)
    assert SECRET[:6] not in out and len(out) <= 12


def test_eventlog_is_thread_safe_with_gapless_numbers():
    log = EventLog(FakeClock(), SecretDetector([]), capacity=5000)
    def work():
        for _ in range(200):
            log.emit("chat", {"sender": "user", "text": "x"})
    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    seqs = [e["seq"] for e in log.events_since(0, 1000)]
    assert log.last_seq == 1600 and seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert [e["seq"] for e in log.events_since(0, 1000)] == list(range(1, 1001))


def test_eventlog_ack_is_valid_and_redacted():
    log = EventLog(FakeClock(), SecretDetector([]))
    ack = log.ack("c1", False, "x", f"fehler {SECRET}")
    assert ack["type"] == "ack" and ack["seq"] == 1 and SECRET not in repr(ack)
    assert log.last_seq == 0                                           # an ack is not part of the log


# ---- Fake-Core und Adapter ---------------------------------------------------------------------------------------------------------------------
class FakePermissions:
    """Wie die Engine: der Notaus wird nur nach einer Entscheidung des Menschen (ConfirmationProvider) aufgehoben."""
    def __init__(self):
        self.emergency = EmergencyStop()
        self.provider = None

    def reset_emergency_stop(self, source="user"):
        def authorize():
            req = ConfirmationRequest(request_id="emergency-reset", tool="jarvis", action="emergency_reset", level=PermissionLevel.YELLOW, resource="emergency stop",
                                      reason="aufheben?", context={}, session_allowed=False)
            return self.provider is not None and self.provider.confirm(req) is ConfirmationChoice.ALLOW_ONCE
        return self.emergency.reset(authorize, source)


class FakeCore:
    def __init__(self, with_emergency=True):
        self.subsystems = {}
        self.tasks = None
        self.permissions = FakePermissions() if with_emergency else SimpleNamespace()
        self.handled = []

    def handle(self, text):
        self.handled.append(text)
        return SimpleNamespace(text=f"echo {text}")


def make(clock=None, **kw):
    core = FakeCore(**kw)
    ctl = GuiController(core, settings=None, command_runner=lambda *a: "")
    backend = ControllerUiBackend(ctl, choice_enum=ConfirmationChoice, clock=clock or FakeClock(), confirmation_timeout_s=30)
    core.permissions.provider = backend.confirmation_provider
    return backend, ctl, core


def open_confirmation(backend, **over):
    kw = dict(request_id="x", tool="keyboard", action="type", level=PermissionLevel.YELLOW, resource="keyboard://notepad", reason="Text tippen",
              context={"fenster": "Notepad"}, session_allowed=True)
    kw.update(over)
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("choice", backend.confirmation_provider.confirm(ConfirmationRequest(**kw))), daemon=True)
    t.start()
    assert wait_for(lambda: any(e["type"] == "confirmation_request" for e in backend.snapshot()))
    return box, t


def hooks():
    def trigger(b):
        open_confirmation(b)
    def advance(b, seconds):
        b._log._clock.advance(seconds)
        b.expire()
    return ConformanceHooks(trigger_confirmation=trigger, advance=advance)


def test_adapter_passes_the_conformance_suite_against_a_fake_core():
    run_conformance(lambda: make()[0], hooks())


def test_adapter_passes_the_conformance_suite_without_a_central_emergency_stop():
    # without the engine's emergency stop there is no button: the emergency_stop command must say so and nothing else may break
    b, _, _ = make(with_emergency=False)
    ack = b.send(cmd("emergency_stop"))
    assert ack["data"]["ok"] is False and ack["data"]["code"] == "unavailable"
    assert "emergency" not in b.hello()["data"]["capabilities"]


def test_text_flows_through_the_controller_and_is_redacted():
    b, ctl, core = make()
    ack = b.send(cmd("submit_text", {"text": f"mein Schluessel ist {SECRET}"}))
    assert ack["data"]["ok"] is True
    assert wait_for(lambda: any(e["data"].get("sender") == "jarvis" for e in b.events_since(0) if e["type"] == "chat"))
    chats = [e["data"] for e in b.events_since(0) if e["type"] == "chat"]
    assert [c["sender"] for c in chats][:2] == ["user", "jarvis"]
    assert SECRET not in repr(b.events_since(0)) and core.handled                      # the core got the text, the UI never gets the secret back


def test_submit_results_map_to_acks():
    b, ctl, _ = make()
    assert b.send(cmd("submit_text", {"text": "   "}))["data"]["code"] == "empty"
    gate = threading.Event()
    ctl.core.handle = lambda text: (gate.wait(5), SimpleNamespace(text="x"))[1]
    assert b.send(cmd("submit_text", {"text": "a"}))["data"]["ok"] is True
    assert b.send(cmd("submit_text", {"text": "b"}))["data"]["code"] == "busy"
    gate.set()
    assert wait_for(lambda: not ctl.busy)


def test_state_events_follow_the_controller_without_duplicates():
    b, ctl, _ = make()
    gate = threading.Event()
    ctl.core.handle = lambda text: (gate.wait(5), SimpleNamespace(text="x"))[1]
    b.send(cmd("submit_text", {"text": "a"}))
    assert [e["data"]["state"] for e in b.events_since(0) if e["type"] == "state"][-1] == "processing"
    gate.set()
    assert wait_for(lambda: [e["data"]["state"] for e in b.events_since(0) if e["type"] == "state"][-1] == "ready")
    states = [e["data"]["state"] for e in b.events_since(0) if e["type"] == "state"]
    assert all(a != c for a, c in zip(states, states[1:]))


def test_activity_is_translated_and_cancel_goes_to_request_cancel_only_for_known_items():
    b, ctl, _ = make()
    calls = []
    ctl.request_cancel = lambda kind, ident: calls.append((kind, ident)) or True
    ctl._emit(ActivityEvent(ActivitySnapshot((ActivityItem("goal", "g 1/ä", "RUNNING", f"Ziel {SECRET}"), ActivityItem("agent_task", "t1", "RUNNING", "x", "dieser Agent unterstützt keinen Abbruch")),
                                             ("Ziele: kaputt",), ("Reparaturläufe",))))
    act = [e for e in b.snapshot() if e["type"] == "activity"][0]["data"]
    assert [i["id"] for i in act["items"]] == ["g_1__", "t1"] and [i["cancellable"] for i in act["items"]] == [True, False]
    assert SECRET not in repr(act) and act["problems"] == ["Ziele: kaputt"] and act["inactive"] == ["Reparaturläufe"]
    assert b.send(cmd("cancel", {"kind": "goal", "id": "nope"}))["data"]["code"] == "unknown_task"
    assert b.send(cmd("cancel", {"kind": "agent_task", "id": "t1"}))["data"]["code"] == "not_cancellable"
    assert calls == []
    assert b.send(cmd("cancel", {"kind": "goal", "id": "g_1__"}))["data"]["ok"] is True
    assert calls == [("goal", "g 1/ä")]                                              # the REAL id goes to the controller


def test_request_snapshot_asks_the_controller_for_a_fresh_activity_list():
    b, ctl, _ = make()
    seen = []
    ctl.request_activity = lambda: seen.append(1) or True
    assert b.send(cmd("request_snapshot"))["data"]["ok"] is True and seen == [1]


def test_voice_commands_use_the_controller_and_report_the_reason_when_unavailable():
    b, ctl, _ = make()
    ack = b.send(cmd("start_voice"))["data"]
    assert ack["ok"] is False and ack["code"] == "voice_unavailable" and ack["message"]
    assert b.send(cmd("stop_voice"))["data"]["code"] == "not_active"
    ctl._voice_running = True                                                          # as if the voice mode ran
    stopped = []
    ctl.stop_voice = lambda: stopped.append(1)
    assert b.send(cmd("stop_voice"))["data"]["ok"] is True and stopped == [1]
    assert [e["data"] for e in b.events_since(0) if e["type"] == "voice_level"] == [{"level": 0, "active": True}]


# ---- Notaus, Zeitueberschreitung, Trennung: abgelehnt -------------------------------------------------------------------------------------------------
def closed_events(b):
    return [e["data"] for e in b.events_since(0) if e["type"] == "confirmation_closed"]


def test_confirm_allow_and_deny_reach_the_provider():
    b, _, _ = make()
    box, t = open_confirmation(b)
    req = [e for e in b.snapshot() if e["type"] == "confirmation_request"][0]["data"]
    assert req["choices"] == ["allow_once", "allow_session", "deny"] and req["context"] == [{"key": "fenster", "value": "Notepad"}]
    assert b.send(cmd("confirm", {"request_id": req["request_id"], "choice": "allow_once"}))["data"]["ok"] is True
    t.join(5)
    assert box["choice"] is ConfirmationChoice.ALLOW_ONCE and closed_events(b)[-1]["outcome"] == "allow_once"
    box2, t2 = open_confirmation(b, session_allowed=False)
    rid = [e for e in b.snapshot() if e["type"] == "confirmation_request"][0]["data"]
    assert rid["choices"] == ["allow_once", "deny"]
    assert b.send(cmd("confirm", {"request_id": rid["request_id"], "choice": "allow_session"}))["data"]["code"] == "choice_not_offered"
    b.send(cmd("confirm", {"request_id": rid["request_id"], "choice": "deny"}))
    t2.join(5)
    assert box2["choice"] is ConfirmationChoice.DENY


def test_a_confirmation_without_an_answer_times_out_as_denied():
    clock = FakeClock()
    b, _, _ = make(clock)
    box, t = open_confirmation(b)
    clock.advance(31)
    b.expire()
    t.join(5)
    assert box["choice"] is ConfirmationChoice.DENY and closed_events(b)[-1]["outcome"] == "timeout"
    assert not [e for e in b.snapshot() if e["type"] == "confirmation_request"]


def test_a_confirmation_times_out_in_real_time_too():
    core = FakeCore()
    b = ControllerUiBackend(GuiController(core, settings=None), choice_enum=ConfirmationChoice, confirmation_timeout_s=1)
    start = time.monotonic()
    choice = b.confirmation_provider.confirm(ConfirmationRequest("x", "t", "a", PermissionLevel.RED))
    assert choice is ConfirmationChoice.DENY and time.monotonic() - start < 4


def test_detach_closes_open_confirmations_as_cancelled_and_denies_later_ones():
    b, _, _ = make()
    box, t = open_confirmation(b)
    b.detach()
    t.join(5)
    assert box["choice"] is ConfirmationChoice.DENY and closed_events(b)[-1]["outcome"] == "cancelled"
    # nobody is attached: a new question is denied at once and never shown
    assert b.confirmation_provider.confirm(ConfirmationRequest("y", "t", "a", PermissionLevel.RED)) is ConfirmationChoice.DENY
    assert not [e for e in b.events_since(0) if e["type"] == "confirmation_request"][1:]


def test_emergency_stop_denies_open_confirmations_and_blocks_commands():
    b, ctl, core = make()
    box, t = open_confirmation(b)
    assert b.send(cmd("emergency_stop"))["data"]["ok"] is True
    t.join(5)
    assert box["choice"] is ConfirmationChoice.DENY and core.permissions.emergency.engaged
    assert wait_for(lambda: closed_events(b) and closed_events(b)[-1]["outcome"] == "cancelled")
    snap = b.snapshot()
    assert [e for e in snap if e["type"] == "emergency"][-1]["data"]["engaged"] is True
    assert [e for e in snap if e["type"] == "state"][-1]["data"]["state"] == "emergency"
    for t_, d in (("submit_text", {"text": "x"}), ("start_voice", {}), ("cancel", {"kind": "goal", "id": "g"}), ("confirm", {"request_id": "r9", "choice": "deny"})):
        assert b.send(cmd(t_, d))["data"]["code"] == "emergency"
    assert core.handled == []
    assert b.send(cmd("emergency_stop"))["data"]["code"] == "already_engaged"


def test_reset_emergency_is_only_a_request_and_the_human_decides():
    b, ctl, core = make()
    b.send(cmd("emergency_stop"))
    assert wait_for(lambda: core.permissions.emergency.engaged)
    assert b.send(cmd("reset_emergency"))["data"]["code"] == "confirmation_requested"
    assert core.permissions.emergency.engaged                                          # the message itself lifted nothing
    assert wait_for(lambda: any(e["type"] == "confirmation_request" for e in b.snapshot()))
    req = [e for e in b.snapshot() if e["type"] == "confirmation_request"][0]["data"]
    assert req["action"] == "emergency_reset" and req["choices"] == ["allow_once", "deny"]
    b.send(cmd("confirm", {"request_id": req["request_id"], "choice": "deny"}))        # answering is allowed in the emergency, but only for this question
    time.sleep(0.2)
    assert core.permissions.emergency.engaged and [e for e in b.snapshot() if e["type"] == "emergency"][-1]["data"]["engaged"] is True
    # ... a second try, this time the human agrees
    assert wait_for(lambda: b.send(cmd("reset_emergency"))["data"]["ok"])
    assert wait_for(lambda: any(e["type"] == "confirmation_request" for e in b.snapshot()))
    req = [e for e in b.snapshot() if e["type"] == "confirmation_request"][0]["data"]
    b.send(cmd("confirm", {"request_id": req["request_id"], "choice": "allow_once"}))
    assert wait_for(lambda: not core.permissions.emergency.engaged)
    assert wait_for(lambda: [e for e in b.snapshot() if e["type"] == "emergency"][-1]["data"]["engaged"] is False)


def test_reset_emergency_without_engaged_stop_is_refused():
    b, _, _ = make()
    assert b.send(cmd("reset_emergency"))["data"]["code"] == "not_engaged"


def test_an_unrelated_confirmation_cannot_be_answered_during_the_emergency():
    b, _, core = make()
    box, t = open_confirmation(b)
    rid = [e for e in b.snapshot() if e["type"] == "confirmation_request"][0]["data"]["request_id"]
    core.permissions.emergency.engage("test", "test")
    assert b.send(cmd("confirm", {"request_id": rid, "choice": "allow_once"}))["data"]["code"] == "emergency"
    b.detach()
    t.join(5)
    assert box["choice"] is ConfirmationChoice.DENY


# ---- Struktur: nur vorhandene GuiController-Methoden -----------------------------------------------------------------------------------------------
CONTROLLER_API = {"submit", "start_voice", "stop_voice", "request_cancel", "emergency_stop", "reset_emergency", "request_activity", "drain", "set_confirmation_denier",
                  "confirmation_waiting", "emergency_engaged", "emergency_available", "voice_active", "settings", "tracker"}
COMMAND_TARGETS = {"submit_text": {"submit"}, "start_voice": {"start_voice"}, "stop_voice": {"voice_active", "stop_voice"}, "cancel": {"request_cancel"},
                   "emergency_stop": {"emergency_engaged", "emergency_available", "emergency_stop"}, "reset_emergency": {"emergency_engaged", "reset_emergency"},
                   "request_snapshot": {"request_activity"}, "confirm": set()}


def _controller_attrs(node):
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "_ctl" and isinstance(n.value.value, ast.Name)
            and n.value.value.id == "self"}


def test_the_adapter_touches_only_existing_controller_methods_and_nothing_of_the_core():
    tree = ast.parse(Path(ui_events.__file__).read_text(encoding="utf-8"))
    used = _controller_attrs(tree)
    assert used and used <= CONTROLLER_API, f"unerlaubter Zugriff auf den Controller: {sorted(used - CONTROLLER_API)}"
    for name in used:
        assert hasattr(GuiController, name) or name in {"emergency_engaged", "voice_active", "emergency_available"} or name in {"settings", "tracker"}, name
    assert all(hasattr(GuiController, n) for n in used - {"settings", "tracker"})
    src = ast.dump(tree)
    for forbidden in ("'core'", "'permissions'", "'tools'", "'execute'", "'emergency'", "'engage'", "'reset'", "'run_stoppers'", "'cancel_activity'", "'say'"):
        assert f"attr={forbidden}" not in src, f"der Adapter greift auf {forbidden} zu"


def test_every_command_maps_to_its_controller_methods_only():
    assert set(COMMAND_TARGETS) == set(COMMAND_TYPES)
    handlers = {n.name[4:]: n for n in ast.walk(ast.parse(Path(ui_events.__file__).read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef) and n.name.startswith("_do_")}
    assert set(handlers) == set(COMMAND_TYPES)
    for name, fn in handlers.items():
        assert _controller_attrs(fn) == COMMAND_TARGETS[name], f"{name}: {sorted(_controller_attrs(fn))}"


def test_commands_call_nothing_but_the_expected_controller_methods_at_runtime():
    core = FakeCore()
    spy = SimpleNamespace(calls=[])
    ctl = GuiController(core, settings=None, command_runner=lambda *a: "")
    b = ControllerUiBackend(ctl, choice_enum=ConfirmationChoice, clock=FakeClock())
    for name in ("submit", "start_voice", "stop_voice", "request_cancel", "emergency_stop", "reset_emergency", "request_activity"):
        real = getattr(ctl, name)
        setattr(ctl, name, lambda *a, _n=name, _r=real, **k: (spy.calls.append(_n), _r(*a, **k))[1])
    core_calls = []
    core.handle = lambda text: (core_calls.append(text), SimpleNamespace(text="ok"))[1]
    for t in COMMAND_TYPES:
        b.send(cmd(t, {"text": "hi"} if t == "submit_text" else {"kind": "goal", "id": "g"} if t == "cancel" else {"request_id": "r", "choice": "deny"} if t == "confirm" else {}))
    assert set(spy.calls) <= {"submit", "start_voice", "request_activity", "emergency_stop", "reset_emergency"}
    assert "request_cancel" not in spy.calls and "stop_voice" not in spy.calls            # unknown activity / no voice: the adapter refuses before the controller
    assert core.permissions.emergency.engaged is True                                      # a reset REQUEST never lifts anything itself
    assert core_calls == ["hi"]


def test_the_adapter_is_not_wired_anywhere():
    for f in (ROOT / "src" / "jarvis").rglob("*.py"):
        if f.name in ("ui_events.py", "bus.py") or "ui_contract" in f.parts:
            continue
        assert "ui_events" not in f.read_text(encoding="utf-8"), f"{f.relative_to(ROOT)} verdrahtet den Adapter (nicht Teil dieses Schritts)"
    assert "ui_events" not in (ROOT / "src" / "jarvis" / "bootstrap.py").read_text(encoding="utf-8")


def test_the_adapter_does_not_import_the_permission_package():
    tree = ast.parse(Path(ui_events.__file__).read_text(encoding="utf-8"))
    mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] + [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in mods if m.startswith("jarvis.permissions") or m.startswith("jarvis.tools") or m.startswith("jarvis.core")], mods
