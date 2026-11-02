"""Protokoll des UIA-Aktions-Providers (Backlog-Schritt uia-actions) ohne pywinauto: Worker-Antworten mit einem Test-Akteur, der echte Provider mit einem Test-Worker-Prozess.

Linux und Windows gleich. Dass pywinauto am echten Fenster wirklich bedient, belegt nur tests/test_computer_uia_actions_real.py im Windows-CI-Lauf."""
from __future__ import annotations

import io
import json
import sys
import textwrap

import pytest

from jarvis.computer import ComputerError, ErrorCode
from jarvis.computer.providers import uia_act_worker as w
from jarvis.computer.providers.pywinauto_uia_actions import PywinautoUiaActionProvider
from jarvis.computer.uia_actions import UiAction, UiTarget

TARGET = UiTarget("0.1", "Newsletter", "CheckBox", "news")


class Actor:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def state(self, *a):
        self.calls.append(("state", a))
        if self.error:
            raise self.error
        return {"enabled": True, "visible": True, "is_password": False, "patterns": ["focus", "toggle"], "value": None, "read_only": None,
                "toggle_state": "off", "selected": None, "has_focus": False}

    def act(self, *a):
        self.calls.append(("act", a))
        if self.error:
            raise self.error


def ask(actor, **req):
    out = io.StringIO()
    w.serve(actor, io.StringIO(json.dumps(req) + "\n"), out)
    return json.loads(out.getvalue())


BASE = {"id": 7, "handle": 5, "path": "0.1", "name": "Newsletter", "control_type": "CheckBox", "automation_id": "news"}


def test_the_worker_answers_state_and_act_and_echoes_the_id():
    a = Actor()
    s = ask(a, op="state", **BASE)
    assert s["ok"] is True and s["id"] == 7 and s["state"]["toggle_state"] == "off"
    r = ask(a, op="act", action="toggle", value=None, **BASE)
    assert r == {"ok": True, "id": 7} and a.calls[-1] == ("act", (5, "0.1", "Newsletter", "CheckBox", "news", "toggle", None))


@pytest.mark.parametrize("req", [
    {"op": "click", **BASE}, {"op": "state", **{**BASE, "handle": -1}}, {"op": "state", **{**BASE, "handle": True}}, {"op": "state", **{**BASE, "name": 5}},
    {"op": "act", "action": "drag", "value": None, **BASE}, {"op": "act", "action": "set_value", "value": None, **BASE}, {"op": "act", "action": "toggle", "value": "x", **BASE},
    {"op": "act", "action": "set_value", "value": "x" * 5001, **BASE}])
def test_the_worker_rejects_bad_requests_without_touching_the_actor(req):
    a = Actor()
    out = ask(a, **req)
    assert out["ok"] is False and out["code"] == "invalid_input" and a.calls == []


@pytest.mark.parametrize("exc,code", [(LookupError("x"), "window_not_found"), (w.Changed(), "target_changed"), (w.Blocked(), "blocked_target"), (w.Unsupported(), "unsupported")])
def test_the_worker_maps_errors_to_codes_and_never_leaks_exception_text(exc, code):
    out = ask(Actor(exc), op="act", action="toggle", value=None, **BASE)
    assert out["ok"] is False and out["code"] == code
    boom = ask(Actor(RuntimeError("Geheimnis im Text")), op="state", **BASE)
    assert boom["ok"] is False and "Geheimnis" not in json.dumps(boom) and boom["id"] == 7


def test_the_worker_serve_loop_survives_garbage_lines():
    out = io.StringIO()
    w.serve(Actor(), io.StringIO("kein json\n[1]\n"), out)
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert [l["ok"] for l in lines] == [False, False] and all(l["id"] is None for l in lines)


STUB = textwrap.dedent('''
    import sys
    from jarvis.computer.providers import uia_act_worker as w
    class A:
        def state(self, handle, path, name, ctype, aid):
            if name == "Kennwort":
                raise w.Blocked()
            return {"enabled": True, "visible": True, "is_password": False, "patterns": ["focus", "toggle", "set_value"], "value": "abc", "read_only": False,
                    "toggle_state": "on", "selected": None, "has_focus": True}
        def act(self, *a):
            pass
    w.serve(A(), sys.stdin, sys.stdout)
''')


@pytest.fixture
def provider(tmp_path):
    script = tmp_path / "stub_worker.py"
    script.write_text(STUB, encoding="utf-8")
    p = PywinautoUiaActionProvider(max_calls=4, call_timeout=30.0, worker_command=[sys.executable, "-u", str(script)])
    yield p
    p.shutdown()


def test_the_provider_reads_a_state_and_performs_through_the_worker_process(provider):
    s = provider.read_state(5, TARGET)
    assert s.toggle_state == "on" and UiAction.TOGGLE in s.patterns and s.value == "abc" and s.has_focus is True and "abc" not in repr(s)
    assert provider.perform(5, TARGET, UiAction.TOGGLE) is None
    assert provider.perform(5, TARGET, UiAction.SET_VALUE, "neu") is None and provider.calls_used == 3 and provider.workers_started == 1


def test_the_provider_refuses_inconsistent_values_and_bad_arguments(provider):
    for kw in ({"action": UiAction.SET_VALUE, "value": None}, {"action": UiAction.TOGGLE, "value": "x"}):
        with pytest.raises(ComputerError) as exc:
            provider.perform(5, TARGET, **kw)
        assert exc.value.code is ErrorCode.INVALID_INPUT
    with pytest.raises(ComputerError):
        provider.read_state(-1, TARGET)
    with pytest.raises(ComputerError):
        provider.perform(True, TARGET, UiAction.FOCUS)
    assert provider.calls_used == 0 and provider.workers_started == 0


def test_a_protected_control_is_reported_as_blocked_target(provider):
    with pytest.raises(ComputerError) as exc:
        provider.read_state(5, UiTarget("0.2", "Kennwort", "Edit", "pw"))
    assert exc.value.code is ErrorCode.BLOCKED_TARGET


def test_halt_refuses_every_call_stops_the_worker_and_keeps_the_budget(provider):
    provider.read_state(5, TARGET)
    assert provider.worker_running
    provider.halt("test")
    assert not provider.worker_running
    with pytest.raises(ComputerError) as exc:
        provider.perform(5, TARGET, UiAction.TOGGLE)
    assert exc.value.code is ErrorCode.FAILSAFE and provider.calls_used == 1
    provider.resume()
    provider.read_state(5, TARGET)
    assert provider.calls_used == 2


def test_the_session_budget_is_never_reset(provider):
    for _ in range(4):
        provider.read_state(5, TARGET)
    provider.halt("x")
    provider.resume()
    with pytest.raises(ComputerError) as exc:
        provider.read_state(5, TARGET)
    assert exc.value.code is ErrorCode.RATE_LIMITED


def test_the_public_surface_is_small():
    public = {n for n in dir(PywinautoUiaActionProvider) if not n.startswith("_") and callable(getattr(PywinautoUiaActionProvider, n))}
    assert public == {"read_state", "perform", "halt", "resume", "shutdown"}


def test_a_dead_worker_is_a_structured_error(tmp_path):
    p = PywinautoUiaActionProvider(max_calls=3, call_timeout=10.0, worker_command=[sys.executable, "-c", "import sys; sys.exit(3)"])
    try:
        with pytest.raises(ComputerError) as exc:
            p.read_state(5, TARGET)
        assert exc.value.code is ErrorCode.BACKEND_ERROR
    finally:
        p.shutdown()


def test_a_long_non_ascii_text_still_fits_into_one_request_line():
    a = Actor()
    text = "\u00e4\u20ac" * 2500                                  # 5000 Zeichen, als JSON etwa 30 kB
    out = ask(a, op="act", action="set_value", value=text, **BASE)
    assert out["ok"] is True and a.calls[-1][1][-1] == text
