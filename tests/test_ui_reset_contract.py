"""Reset contract through the existing loopback transport; no device or external provider."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.control_center.server import ControlCenterServer
from jarvis.interface.cli import _emergency
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.confirmation import ConfirmationRequest
from jarvis.permissions.levels import PermissionLevel
from jarvis.ui_contract.fake import FakeClock, FakeUiBackend
from test_control_center_binding import cmd, post, real_env, wait_for


def controller_core(folder):
    env = {**real_env(folder), "JARVIS_ASSISTANT_CONFIRMATION_TIMEOUT_SECONDS": "10"}
    return build_core(load_settings(env=env))


@pytest.fixture(params=["fake", "controller"])
def endpoint(request, tmp_path):
    if request.param == "fake":
        backend = FakeUiBackend()
    else:
        core = controller_core(tmp_path)
        backend = core.subsystems["assistant"].ui
    server = ControlCenterServer(backend)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def send(server, command, **data):
    status, ack = post(server, cmd(command, data))
    assert status == 200
    return ack["data"]


def answer(server, rid, choice):
    return send(server, "confirm", request_id=rid, choice=choice)


def open_id(backend):
    questions = [e["data"] for e in backend.snapshot() if e["type"] == "confirmation_request"]
    if not questions:
        return None
    assert len(questions) == 1 and questions[0]["choices"] == ["allow_once", "deny"]
    return questions[0]["request_id"]


def engaged(backend):
    return next(e["data"]["engaged"] for e in backend.snapshot() if e["type"] == "emergency")


def reset(server):
    def submitted():
        reply = send(server, "reset_emergency")
        if reply["code"] == "busy":
            return False  # Previous reset worker is finishing after its answer.
        assert reply["ok"] and reply["code"] == "confirmation_requested"
        return True

    assert wait_for(submitted)
    assert wait_for(lambda: open_id(server.backend))
    return open_id(server.backend)


def test_only_one_offered_answer_to_the_current_reset(endpoint):
    server = endpoint
    assert send(server, "reset_emergency")["code"] == "not_engaged"
    assert send(server, "emergency_stop")["ok"]
    rid = reset(server)
    assert engaged(server.backend)
    assert send(server, "reset_emergency")["code"] == "busy"
    assert answer(server, "unrelated", "allow_once")["code"] == "emergency"
    assert answer(server, rid, "allow_session")["code"] == "choice_not_offered"
    status, _ = post(server, cmd("reset_emergency", {"choice": "allow_once"}))
    assert status == 400
    for kind, args in (("start_voice", {}), ("stop_voice", {}), ("submit_text", {"text": "weiter"}),
                       ("cancel", {"kind": "goal", "id": "g1"})):
        assert send(server, kind, **args)["code"] == "emergency"
    assert answer(server, rid, "deny")["ok"]
    assert engaged(server.backend)
    assert answer(server, rid, "allow_once")["ok"] is False

    second = reset(server)
    assert second != rid
    assert answer(server, rid, "allow_once")["ok"] is False
    barrier = threading.Barrier(2)
    def concurrent_answer(choice):
        barrier.wait(timeout=5)
        return choice, answer(server, second, choice)["ok"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(concurrent_answer, ("deny", "allow_once")))
    assert sum(results.values()) == 1
    assert wait_for(lambda: engaged(server.backend) == results["deny"])
    closed = [e["data"]["outcome"] for e in server.backend.events_since(0)
              if e["type"] == "confirmation_closed" and e["data"]["request_id"] == second]
    assert closed == ["denied" if results["deny"] else "allow_once"]


def test_deadline_and_detach_consume_the_reset(endpoint):
    server = endpoint
    backend = server.backend
    send(server, "emergency_stop")
    if isinstance(backend, FakeUiBackend):
        clock = backend._clock
    else:
        clock = FakeClock()
        backend._log._clock = clock
    rid = reset(server)
    timeout = next(e["data"]["timeout_s"] for e in backend.snapshot() if e["type"] == "confirmation_request")
    clock.advance(timeout)  # Exactly at the deadline, without a separate cleanup call.
    assert answer(server, rid, "allow_once")["ok"] is False
    assert engaged(backend)
    second = reset(server)
    backend.detach()
    assert answer(server, second, "allow_once")["ok"] is False
    assert engaged(backend)
    assert [e["data"]["outcome"] for e in backend.events_since(0)
            if e["type"] == "confirmation_closed"] == ["timeout", "cancelled"]


def test_server_shutdown_cancels_an_outstanding_reset(endpoint):
    send(endpoint, "emergency_stop")
    rid = reset(endpoint)
    endpoint.stop()
    events = endpoint.backend.events_since(0)
    assert any(e["type"] == "confirmation_closed" and e["data"] == {"request_id": rid, "outcome": "cancelled"}
               for e in events)
    assert engaged(endpoint.backend)


def test_foreign_session_id_is_inert(endpoint, tmp_path):
    server = endpoint
    if isinstance(server.backend, FakeUiBackend):
        peer = FakeUiBackend()
    else:
        folder = tmp_path / "peer"
        folder.mkdir()
        peer = controller_core(folder).subsystems["assistant"].ui
    other = ControlCenterServer(peer)
    other.start()
    try:
        for instance in (server, other):
            send(instance, "emergency_stop")
        rid, foreign = reset(server), reset(other)
        assert rid != foreign
        assert answer(server, foreign, "allow_once")["code"] == "emergency"
        assert open_id(server.backend) == rid and engaged(server.backend)
    finally:
        other.stop()


def test_ack_cannot_clear_the_engine_latch_or_release_the_tool(tmp_path, monkeypatch):
    core = controller_core(tmp_path)
    backend = core.subsystems["assistant"].ui
    provider = backend.confirmation_provider
    original = provider.confirm
    accepted, release = threading.Event(), threading.Event()
    def pause_before_engine_receives_choice(request):
        choice = original(request)
        if choice is ConfirmationChoice.ALLOW_ONCE:
            accepted.set()
            if not release.wait(10):
                return ConfirmationChoice.DENY
        return choice
    monkeypatch.setattr(provider, "confirm", pause_before_engine_receives_choice)
    server = ControlCenterServer(backend)
    server.start()
    try:
        send(server, "emergency_stop")
        rid = reset(server)
        assert answer(server, rid, "allow_once")["ok"]
        assert accepted.wait(5) and core.permissions.emergency.engaged and engaged(backend)
        assert answer(server, rid, "allow_once")["ok"] is False
        result = core.tools.execute("echo", text="lokaler Test")
        assert not result.success and "emergency stop" in result.error
        release.set()
        assert wait_for(lambda: not core.permissions.emergency.engaged and not engaged(backend))
    finally:
        release.set()
        server.stop()


def test_provider_metadata_alone_cannot_open_a_reset_and_cli_is_preserved(tmp_path):
    core = controller_core(tmp_path)
    backend = core.subsystems["assistant"].ui
    backend.send(cmd("emergency_stop"))
    # A normal provider callback has no reset authority, even while a genuine CLI question is open elsewhere.
    request = ConfirmationRequest("emergency-reset", "jarvis", "emergency_reset", PermissionLevel.YELLOW,
                                  resource="emergency stop", session_allowed=False)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(_emergency, core, "reset")
        assert wait_for(lambda: open_id(backend))
        rid = open_id(backend)
        assert backend.send(cmd("reset_emergency"))["data"]["code"] == "busy"
        assert "bereits" in _emergency(core, "reset")
        assert backend.confirmation_provider.confirm(request) is ConfirmationChoice.DENY
        assert open_id(backend) == rid and core.permissions.emergency.engaged
        assert backend.send(cmd("confirm", {"request_id": rid, "choice": "allow_once"}))["data"]["ok"]
        assert result.result(timeout=5) and not core.permissions.emergency.engaged


def test_shutdown_refuses_a_queued_snapshot_after_restart(endpoint, monkeypatch):
    from jarvis.control_center import server as transport

    waiting, resume = threading.Event(), threading.Event()
    parse = transport.parse_command

    def delay(body):
        command = parse(body)
        waiting.set()
        assert resume.wait(5)
        return command

    monkeypatch.setattr(transport, "parse_command", delay)
    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(post, endpoint, cmd("request_snapshot"))
        try:
            assert waiting.wait(5)
            endpoint.stop()
            endpoint.start()
        finally:
            resume.set()
        assert response.result(timeout=5)[0] == 503
    assert send(endpoint, "request_snapshot")["ok"]
