"""NEXUS-Ende-zu-Ende: eine Recherchefrage ohne URL im Chat -> Ziel -> Websuche (Mock) -> Seiten lesen (Fake-Browser, jede Seite ueber die PermissionEngine) -> Antwort mit
Quellen im Chat. Plus verstaendliche Erklaerungen, wenn etwas fehlt. Echter Kern (build_core, Mock-LLM), echter Assistent/UI-Adapter; kein Netzwerk."""
from __future__ import annotations

import time

import pytest

from analysis_util import SHOP_A, SHOP_B, SHOP_C, make_web
from browser_util import ONCE
from jarvis.bootstrap import build_core
from jarvis.browser import factory as browser_factory
from jarvis.browser.providers.fake import FakeBrowserProvider
from jarvis.config import load_settings
from jarvis.interface.cli import run_command
from jarvis.permissions.confirmation import ScriptedConfirmation
from jarvis.research.search import FakeSearchProvider, SearchHit, SearchService
from test_computer_integration import env_for
from test_research_web_search import HITS, Sub

ENV = dict(JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_RESEARCH_ENABLED="true",
           JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake")


@pytest.fixture(autouse=True)
def fake_web(monkeypatch):
    monkeypatch.setitem(browser_factory._BUILDERS, "fake", lambda s: FakeBrowserProvider(make_web()))


def make(tmp_path, search=True, **extra):
    env = env_for(tmp_path, **ENV, **({"JARVIS_RESEARCH_SEARCH_ENABLED": "true"} if search else {}), **extra)
    settings = load_settings(env=env)
    core = build_core(settings)
    return core, settings


def chat_after(ui, text, wait=20.0):
    r = ui.send({"v": "1.0", "id": "n1", "type": "submit_text", "data": {"text": text}})
    assert r["data"]["ok"], r
    end = time.monotonic() + wait
    while time.monotonic() < end:
        evs = ui.events_since(0, 500)
        replies = [e["data"]["text"] for e in evs if e["type"] == "chat" and e["data"]["sender"] == "jarvis"]
        if replies and not any(e["type"] == "state" and e["data"]["state"] == "processing" for e in evs[-1:]):
            return replies, evs
        time.sleep(0.1)
    return [e["data"]["text"] for e in ui.events_since(0, 500) if e["type"] == "chat"], ui.events_since(0, 500)


def test_a_research_question_in_the_chat_is_searched_read_and_answered_with_sources(tmp_path):
    core, _ = make(tmp_path)
    core.subsystems["research_search"] = Sub(FakeSearchProvider(HITS))
    core.permissions.set_confirmation_provider(ScriptedConfirmation([ONCE] * 100), source="test")      # der Mensch erlaubt jede Seite; die Engine fragt trotzdem
    ui = core.subsystems["assistant"].ui
    replies, evs = chat_after(ui, "Recherchiere die Preise für Innenreinigung in der Region und fasse sie zusammen")
    text = "\n".join(replies)
    assert "SUCCEEDED" in text and "Quellen:" in text and SHOP_A in text and SHOP_B in text and "ungeprüfte Daten" in text, text
    assert not any("10.0.0.5" in r for r in replies)
    audit = core.permissions.audit.tail(200)
    assert any("browser" in str(e) for e in audit)                                                     # Seitenaufrufe stehen im Audit der Engine


def test_without_a_confirmation_no_page_is_read_and_the_chat_explains_why(tmp_path):
    core, _ = make(tmp_path)
    core.subsystems["research_search"] = Sub(FakeSearchProvider(HITS))
    core.permissions.set_confirmation_provider(ScriptedConfirmation([]), source="test")                # keine Antwort = abgelehnt
    replies, _ = chat_after(core.subsystems["assistant"].ui, "Recherchiere die Preise für Innenreinigung")
    text = "\n".join(replies)
    assert "Quellen:" not in text and "So geht es weiter:" in text and "Freigabe" in text and "Was fehlt" in text


def test_without_search_the_blocked_message_says_what_is_missing_why_and_what_to_do(tmp_path):
    core, st = make(tmp_path, search=False)
    out = run_command(core, "/goal Recherchiere die Vorteile von Python", st, lambda _t: None, lambda _p: "")
    for part in ("Was fehlt", "Warum es nicht weitergeht", "Das kannst du tun", "Alternative", "BRAVE_SEARCH_API_KEY", "Webadresse"):
        assert part in out, (part, out)


def test_with_search_enabled_but_no_key_the_message_names_the_key_and_nothing_is_sent(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    core, st = make(tmp_path)                                                                           # search_enabled ohne Schluessel: Subsystem meldet "disabled"
    assert not core.subsystems["research_search"].available
    out = run_command(core, "/goal Recherchiere die Vorteile von Python", st, lambda _t: None, lambda _p: "")
    assert "BRAVE_SEARCH_API_KEY" in out and "So geht es weiter" in out and "Quellen:" not in out


def test_plain_chat_routing_only_for_research_requests_and_not_for_slash_or_other_text(tmp_path):
    from jarvis.interface.cli import research_route
    core, _ = make(tmp_path)
    assert research_route(core, "Recherchiere Preise") == "/goal Recherchiere Preise"
    assert research_route(core, "Finde heraus, wie das Wetter wird") is not None
    assert research_route(core, "Hallo") is None and research_route(core, "/goal Recherchiere x") is None and research_route(core, "Ich möchte recherchieren") is None
    (tmp_path / "x").mkdir()
    off, _ = make(tmp_path / "x")
    off.subsystems["goals"].engine = None
    assert research_route(off, "Recherchiere Preise") is None


def test_emergency_stop_halts_the_search(tmp_path):
    core, st = make(tmp_path)
    core.subsystems["research_search"] = Sub(FakeSearchProvider(HITS))
    core.permissions.emergency.trigger("test")
    out = run_command(core, "/goal Recherchiere Preise für Innenreinigung", st, lambda _t: None, lambda _p: "")
    assert "Quellen:" not in out and "SUCCEEDED" not in out
