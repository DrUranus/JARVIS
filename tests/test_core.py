from jarvis.core import Context, JarvisCore, ResponseKind
from jarvis.core.core import looks_like_goal
from jarvis.errors import LLMError
from jarvis.llm.mock import MockProvider
from jarvis.llm.base import Message


def test_chat_builds_context(provider):
    core = JarvisCore(provider)
    r = core.handle("Wie geht's?")
    assert r.kind is ResponseKind.CHAT and r.text == "ok"
    core.handle("Und weiter?")
    sent = provider.calls[-1].messages
    assert sent[0].role.value == "system"
    assert [m.content for m in sent[1:]] == ["Wie geht's?", "ok", "Und weiter?"]


def test_greeting_default_mock():
    assert JarvisCore(MockProvider()).handle("Hallo JARVIS").text == "Hallo. Ich bin bereit."


def test_goal_routes_to_planner(core):
    r = core.handle("Erstelle ein Python-Programm, das eine CSV-Datei analysiert.")
    assert r.kind is ResponseKind.PLAN and r.task is not None
    assert "Code schreiben" in r.text
    assert core.tasks.get(r.task.id) is r.task


def test_routing_heuristic():
    assert looks_like_goal("JARVIS, erstelle mir eine Website")
    assert looks_like_goal("Build a web shop")
    assert not looks_like_goal("Hallo")
    assert not looks_like_goal("Was ist offen?")


def test_empty_input(core):
    assert core.handle("   ").text == ""


def test_llm_failure_becomes_error_response_and_context_stays_clean():
    def boom(r):
        raise LLMError("offline")
    core = JarvisCore(MockProvider(responder=boom))
    r = core.handle("Hallo")
    assert r.kind is ResponseKind.ERROR and not r.ok and "offline" in r.text
    assert len(core.context) == 0


def test_unexpected_exception_is_contained():
    def boom(r):
        raise ValueError("bug")
    r = JarvisCore(MockProvider(responder=boom)).handle("Hallo")
    assert r.kind is ResponseKind.ERROR and "ValueError" in r.text


def test_context_window_bounded():
    c = Context(max_messages=3)
    for i in range(6):
        c.add_user(str(i))
    assert [m.content for m in c.build()[1:]] == ["3", "4", "5"]
    c.clear()
    assert len(c) == 0 and isinstance(c.build()[0], Message)
