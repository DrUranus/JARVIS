"""UI-Vertrag v1 (Backlog-Schritt ui-contract-v1): versionierte Ereignisse und Befehle zwischen Backend (Strang A) und Control Center (Strang B).

Nur Standardbibliothek, keine Oberflaeche, keine Abhaengigkeit, keine Verdrahtung, keine Berechtigung. Beide Straenge testen ihre Seite mit derselben Konformitaetspruefung
(`jarvis.ui_contract.conformance.run_conformance`). Linux und Windows gleich."""
from __future__ import annotations

import ast
import copy
import json
import re
import sys
from pathlib import Path

import pytest

from jarvis.ui_contract import (COMMAND_TYPES, EVENT_TYPES, MAX_TEXT, VERSION, ConformanceHooks, ContractError, FakeClock, FakeUiBackend, UiBackend, command_schema,
                                event_schema, run_conformance, validate_command, validate_event)

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "jarvis" / "ui_contract"
TS = "2026-11-02T10:00:00Z"
SECRET = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"


def ev(type_, data, seq=1, **kw):
    return {"v": VERSION, "seq": seq, "ts": TS, "type": type_, "data": data, **kw}


def cmd(type_, data=None, id_="c1"):
    return {"v": VERSION, "id": id_, "type": type_, "data": data or {}}


GOOD_EVENTS = {
    "hello": {"contract": VERSION, "backend": "fake", "capabilities": ["chat", "voice"], "emergency": False},
    "state": {"state": "ready", "detail": ""},
    "chat": {"sender": "jarvis", "text": "Hallo"},
    "activity": {"items": [{"kind": "goal", "id": "g1", "title": "Ziel", "status": "RUNNING", "note": "", "cancellable": True}], "problems": [], "inactive": ["agents"]},
    "task_update": {"kind": "agent_task", "id": "t1", "status": "RUNNING", "detail": "Schritt 2"},
    "routing": {"task_id": "t1", "agent": "browser", "source": "rules", "reason": "URL im Auftrag"},
    "result": {"task_id": "t1", "summary": "fertig", "artifacts": [{"name": "bericht.md", "kind": "file", "ref": "ws/bericht.md"}]},
    "confirmation_request": {"request_id": "r1", "tool": "keyboard", "action": "type", "resource": "keyboard://text@notepad.exe", "level": "yellow", "reason": "Text tippen",
                             "context": [{"key": "fenster", "value": "Notepad"}], "choices": ["allow_once", "deny"], "timeout_s": 60},
    "confirmation_closed": {"request_id": "r1", "outcome": "denied"},
    "emergency": {"engaged": True, "reason": "Notaus", "report": ["computer: stopped"]},
    "voice_level": {"level": 0.25, "active": True},
    "error": {"code": "backend_error", "message": "kaputt"},
    "ack": {"id": "c1", "ok": True, "code": "ok", "message": ""},
}
GOOD_COMMANDS = {
    "submit_text": {"text": "Hallo JARVIS"}, "start_voice": {}, "stop_voice": {}, "cancel": {"kind": "goal", "id": "g1"},
    "confirm": {"request_id": "r1", "choice": "allow_once"}, "emergency_stop": {}, "reset_emergency": {}, "request_snapshot": {},
}


# ---- Aufbau des Vertrags ------------------------------------------------------------------------------------------------------------------
def test_version_and_the_closed_sets_of_types():
    assert VERSION == "1.0" and set(EVENT_TYPES) == set(GOOD_EVENTS) and set(COMMAND_TYPES) == set(GOOD_COMMANDS)


def test_every_documented_example_validates_and_is_returned_normalised():
    for t, data in GOOD_EVENTS.items():
        e = validate_event(ev(t, data))
        assert e["type"] == t and json.loads(json.dumps(e)) == e
    for t, data in GOOD_COMMANDS.items():
        assert validate_command(cmd(t, data))["type"] == t


# ---- Ereignisse: streng ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mutate", [
    lambda e: e.pop("seq"), lambda e: e.update(seq=0), lambda e: e.update(seq=True), lambda e: e.update(seq="1"), lambda e: e.update(v="2.0"), lambda e: e.update(v=1),
    lambda e: e.update(ts="gestern"), lambda e: e.update(ts="2026-11-02 10:00:00"), lambda e: e.update(type="unbekannt"), lambda e: e.update(extra=1), lambda e: e.update(data=[]),
    lambda e: e["data"].update(unerwartet=1), lambda e: e["data"].pop("state"), lambda e: e["data"].update(state="schlaeft"), lambda e: e["data"].update(detail=5),
    lambda e: e["data"].update(detail="x" * 201),
])
def test_malformed_events_are_rejected(mutate):
    e = ev("state", {"state": "ready", "detail": ""})
    mutate(e)
    with pytest.raises(ContractError):
        validate_event(e)


@pytest.mark.parametrize("type_,mutate", [
    ("chat", lambda d: d.update(sender="root")), ("chat", lambda d: d.update(text="x" * (MAX_TEXT + 1))), ("chat", lambda d: d.update(text=5)),
    ("activity", lambda d: d["items"][0].update(kind="mail")), ("activity", lambda d: d["items"][0].update(cancellable="ja")),
    ("activity", lambda d: d.update(items=d["items"] * 300)), ("activity", lambda d: d["items"][0].update(id="a b")), ("activity", lambda d: d["items"][0].update(id="")),
    ("confirmation_request", lambda d: d.update(level="blau")), ("confirmation_request", lambda d: d.update(choices=["allow_always"])), ("confirmation_request", lambda d: d.update(choices=[])),
    ("confirmation_request", lambda d: d.update(timeout_s=0)), ("confirmation_request", lambda d: d.update(timeout_s=10_000)),
    ("confirmation_request", lambda d: d.update(context=[{"key": "a", "value": "b"}] * 11)),
    ("confirmation_closed", lambda d: d.update(outcome="allowed")), ("voice_level", lambda d: d.update(level=1.5)), ("voice_level", lambda d: d.update(level=-0.1)),
    ("voice_level", lambda d: d.update(level=True)), ("voice_level", lambda d: d.update(active=1)), ("emergency", lambda d: d.update(engaged="ja")),
    ("result", lambda d: d["artifacts"][0].update(kind="exe")), ("result", lambda d: d.update(artifacts=d["artifacts"] * 60)), ("routing", lambda d: d.update(source="orakel")),
    ("ack", lambda d: d.update(ok="ja")), ("hello", lambda d: d.update(capabilities=["x"] * 40)),
])
def test_each_event_type_checks_its_fields(type_, mutate):
    data = copy.deepcopy(GOOD_EVENTS[type_])
    mutate(data)
    with pytest.raises(ContractError):
        validate_event(ev(type_, data))


def test_control_characters_in_texts_are_replaced_not_passed_on():
    text = validate_event(ev("chat", {"sender": "user", "text": "a\x00b\x1b[31mc\nd"}))["data"]["text"]
    assert "\x00" not in text and "\x1b" not in text and "\n" not in text and text.startswith("a b ")


def test_the_same_major_version_is_accepted_and_another_one_is_not():
    assert validate_event({**ev("state", GOOD_EVENTS["state"]), "v": "1.7"})["v"] == "1.7"
    for v in ("2.0", "0.9", "1", "1.x", ""):
        with pytest.raises(ContractError):
            validate_event({**ev("state", GOOD_EVENTS["state"]), "v": v})


# ---- Befehle: streng, ohne Rechte-Aenderung ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    cmd("submit_text", {"text": ""}), cmd("submit_text", {"text": "x" * (MAX_TEXT + 1)}), cmd("submit_text", {}), cmd("submit_text", {"text": "a", "extra": 1}),
    cmd("cancel", {"kind": "mail", "id": "g1"}), cmd("cancel", {"kind": "goal"}), cmd("confirm", {"request_id": "r1", "choice": "allow_always"}),
    cmd("confirm", {"request_id": "", "choice": "deny"}), cmd("emergency_stop", {"x": 1}), cmd("start_voice", {"x": 1}),
    cmd("grant_permission", {"tool": "keyboard"}), cmd("set_policy", {}), cmd("run_tool", {"tool": "keyboard"}), cmd("lift_emergency", {}), cmd("exec", {"cmd": "calc"}),
    {**cmd("request_snapshot"), "id": ""}, {**cmd("request_snapshot"), "id": "x" * 65}, {**cmd("request_snapshot"), "id": 5}, {**cmd("request_snapshot"), "v": "2.0"},
    {**cmd("request_snapshot"), "extra": 1}, {"v": VERSION, "id": "c1", "type": "request_snapshot"},
])
def test_malformed_or_unknown_commands_are_rejected(bad):
    with pytest.raises(ContractError):
        validate_command(bad)


def test_no_command_can_grant_permissions_change_policy_run_tools_or_lift_the_emergency_stop():
    assert not [c for c in COMMAND_TYPES if re.search(r"grant|policy|rule|tool|exec|run|lift|override|bypass|allow_always|sudo", c)]
    assert COMMAND_TYPES.count("reset_emergency") == 1        # nur eine ANFRAGE: die Engine fragt den Menschen selbst (siehe docs/UI_CONTRACT.md)


def test_oversized_json_is_refused_before_parsing_further():
    from jarvis.ui_contract.schema import MAX_COMMAND_BYTES, parse_command
    with pytest.raises(ContractError):
        parse_command("{" + '"x":"' + "a" * MAX_COMMAND_BYTES + '"}')
    with pytest.raises(ContractError):
        parse_command("kein json")
    assert parse_command(json.dumps(cmd("request_snapshot")))["type"] == "request_snapshot"


# ---- JSON-Schema fuer Strang B ----------------------------------------------------------------------------------------------------------------
def test_the_exported_json_schemas_match_the_code():
    es, cs = event_schema(), command_schema()
    for schema, types in ((es, EVENT_TYPES), (cs, COMMAND_TYPES)):
        assert json.loads(json.dumps(schema)) == schema and schema["$schema"].startswith("https://json-schema.org/")
        assert {b["properties"]["type"]["const"] for b in schema["oneOf"]} == set(types)
        assert all(b["additionalProperties"] is False and b["properties"]["data"]["additionalProperties"] is False for b in schema["oneOf"])
    chat = next(b for b in es["oneOf"] if b["properties"]["type"]["const"] == "chat")
    assert chat["properties"]["data"]["properties"]["text"]["maxLength"] == MAX_TEXT
    assert set(chat["required"]) == {"v", "seq", "ts", "type", "data"}
    sub = next(b for b in cs["oneOf"] if b["properties"]["type"]["const"] == "confirm")
    assert set(sub["properties"]["data"]["properties"]["choice"]["enum"]) == {"allow_once", "allow_session", "deny"}


def test_the_schema_files_for_the_frontend_are_up_to_date():
    from jarvis.ui_contract.schema import write_schema_files
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        write_schema_files(Path(tmp))
        for name in ("ui-events.schema.json", "ui-commands.schema.json"):
            assert (Path(tmp) / name).read_text(encoding="utf-8") == (PKG / "schema" / name).read_text(encoding="utf-8"), f"{name} veraltet: python -m jarvis.ui_contract.schema"


# ---- Fake-Backend und Konformitaet --------------------------------------------------------------------------------------------------------
def make_fake():
    return FakeUiBackend(FakeClock())


HOOKS = ConformanceHooks(trigger_confirmation=lambda b: b.send(cmd("submit_text", {"text": "!confirm"}, "hook1")), advance=lambda b, s: b.advance(s))


def test_the_fake_backend_passes_the_conformance_suite():
    run_conformance(make_fake, HOOKS)
    run_conformance(make_fake)                    # auch ohne Hilfsfunktionen (ein echtes Backend hat sie nicht immer)


def test_the_fake_backend_is_deterministic():
    def script(b):
        b.send(cmd("submit_text", {"text": "Hallo"}))
        b.send(cmd("submit_text", {"text": "!task"}, "c2"))
        b.send(cmd("emergency_stop", id_="c3"))
        return json.dumps(b.events_since(0), sort_keys=True)
    assert script(make_fake()) == script(make_fake())


def test_the_conformance_suite_catches_broken_backends():
    class NoHello(FakeUiBackend):
        def snapshot(self):
            return super().snapshot()[1:]

    class BadSeq(FakeUiBackend):
        def events_since(self, seq, limit=200):
            return list(reversed(super().events_since(seq, limit)))

    class Leaky(FakeUiBackend):
        def _chat(self, sender, text):
            self._emit("chat", {"sender": sender, "text": text + " " + SECRET})          # umgeht die Schwaerzung

    class NoEmergencyEffect(FakeUiBackend):
        def _emergency(self, reason):
            return None

    class Lax(FakeUiBackend):
        def send(self, command):
            return {"v": VERSION, "seq": 0, "ts": TS, "type": "ack", "data": {"id": "x", "ok": True, "code": "ok", "message": ""}}

    class LetsEverythingThrough(FakeUiBackend):
        def _refuse_in_emergency(self, command):
            return None

    for broken in (NoHello, BadSeq, Leaky, NoEmergencyEffect, Lax, LetsEverythingThrough):
        with pytest.raises(AssertionError):
            run_conformance(lambda cls=broken: cls(FakeClock()), HOOKS)


def test_a_confirmation_that_nobody_answers_closes_as_timeout_and_a_detached_client_means_deny():
    b = make_fake()
    b.send(cmd("submit_text", {"text": "!confirm"}))
    req = [e for e in b.events_since(0) if e["type"] == "confirmation_request"][-1]["data"]
    b.advance(req["timeout_s"] + 1)
    closed = [e for e in b.events_since(0) if e["type"] == "confirmation_closed"][-1]["data"]
    assert closed == {"request_id": req["request_id"], "outcome": "timeout"}
    b.send(cmd("submit_text", {"text": "!confirm"}, "c2"))
    pending = [e for e in b.events_since(0) if e["type"] == "confirmation_request"][-1]["data"]
    b.detach()
    assert [e for e in b.events_since(0) if e["type"] == "confirmation_closed"][-1]["data"] == {"request_id": pending["request_id"], "outcome": "cancelled"}
    ack = b.send(cmd("confirm", {"request_id": pending["request_id"], "choice": "allow_once"}, "c3"))
    assert ack["data"]["ok"] is False and ack["data"]["code"] == "unknown_request"       # nach dem Schliessen gibt es nichts mehr zu erlauben


def test_the_backend_interface_is_small_and_abstract():
    assert {n for n in dir(UiBackend) if not n.startswith("_")} == {"hello", "snapshot", "events_since", "send", "detach"}
    with pytest.raises(TypeError):
        UiBackend()      # type: ignore[abstract]


# ---- Aufbau: Standardbibliothek, keine Verdrahtung ---------------------------------------------------------------------------------------------
def test_the_package_uses_only_the_standard_library_and_touches_no_other_part_of_jarvis():
    allowed_roots = set(sys.stdlib_module_names) | {"jarvis"}
    for f in PKG.glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) else []
            for m in mods:
                root = m.split(".")[0]
                assert root in allowed_roots, f"{f.name}: {m}"
                if root == "jarvis":
                    assert m.startswith("jarvis.ui_contract") or m == "jarvis", f"{f.name}: importiert {m} (der Vertrag haengt von keinem anderen Teil ab)"


def test_nothing_imports_the_contract_yet_and_no_setting_dependency_or_wiring_was_added():
    src = ROOT / "src" / "jarvis"
    for f in src.rglob("*.py"):
        if "ui_contract" in f.parts:
            continue
        assert "jarvis.ui_contract" not in f.read_text(encoding="utf-8"), f"{f.relative_to(ROOT)} nutzt den Vertrag schon (Verdrahtung gehoert in spaetere Schritte)"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject and "ui_contract" not in pyproject
    assert "ui_contract" not in (ROOT / "config" / "jarvis.toml").read_text(encoding="utf-8")
