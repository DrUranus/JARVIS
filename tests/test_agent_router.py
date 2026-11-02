"""Agenten-Router (agent-router): Fake-LLM statt Netzwerk. Der Router waehlt nur aus dem Register (verfuegbar) und innerhalb dessen, was der
Task erlaubt; jede Entscheidung geht als routing-Daten und ins Audit; er fuehrt nichts aus."""
from __future__ import annotations

import json
import threading

import pytest

from agents_util import FakeAgent
from jarvis.agents import AgentPlanner, AgentRegistry
from jarvis.agents.router import AgentRouter, LLMAgentPlanner, RoutingDecision, audit_listener, event_listener
from jarvis.agents.state import AgentStatus
from jarvis.config import AgentRouterSettings, ConfigError, load_settings
from jarvis.permissions.audit import AuditEvent, AuditEventType, AuditLogger, MemoryAuditSink
from jarvis.redaction import SecretDetector
from jarvis.ui_contract.bus import EventLog

WEB = "Öffne die Webseite https://example.com und lies die Seite"
CODE = "Führe die Tests im Projekt aus"


def registry():
    reg = AgentRegistry()
    reg.register(FakeAgent("browser", {"browser.read", "browser.interact"}))
    reg.register(FakeAgent("coding", {"coding.read", "coding.write", "coding.test"}))
    reg.register(FakeAgent("research", {"research.web"}))
    return reg


def llm_says(**reply):
    calls = []

    def propose(objective, candidates):
        calls.append((objective, candidates))
        return reply
    propose.calls = calls
    return propose


def to_audit(logger):
    """What the wiring will do: dict -> AuditEvent -> AuditLogger (redaction + sinks)."""
    return audit_listener(lambda m: logger.record(AuditEvent(AuditEventType.LLM_ROUTE, **m)))


def router(reg=None, llm=None, **kw):
    return AgentRouter(reg or registry(), AgentPlanner(reg or registry()) if reg is None else AgentPlanner(reg), llm=llm, **kw)


# ---- Regeln (Rueckfall) ------------------------------------------------------------------------------------------------------------
def test_rules_route_without_llm():
    reg = registry()
    r = AgentRouter(reg, AgentPlanner(reg))
    d = r.route(WEB, task_id="t1")
    assert (d.agent_id, d.source, d.task_id) == ("browser", "rules", "t1")
    assert "browser.read" in d.capabilities and d.reason


def test_no_match_gives_empty_decision():
    reg = registry()
    d = AgentRouter(reg, AgentPlanner(reg)).route("hallo wie geht es dir")
    assert d.agent_id is None and d.capabilities == frozenset() and d.source == "rules"


# ---- LLM-Pfad ----------------------------------------------------------------------------------------------------------------------
def test_llm_choice_is_used_when_valid():
    reg = registry()
    llm = llm_says(agent="research", capabilities=["research.web"], reason="needs sources")
    d = AgentRouter(reg, AgentPlanner(reg), llm=llm).route(WEB)
    assert (d.agent_id, d.source, d.capabilities, d.reason) == ("research", "llm", frozenset({"research.web"}), "needs sources")
    cands = llm.calls[0][1]
    assert set(cands) == {"browser", "coding", "research"}


@pytest.mark.parametrize("reply", [
    {"agent": "nope", "capabilities": ["research.web"]},                      # unbekannter Agent
    {"agent": "research", "capabilities": ["coding.write"]},                  # Faehigkeit, die der Agent nicht hat
    {"agent": "research", "capabilities": ["research.web", "x.y"]},           # erfundene Faehigkeit
    {"agent": "research", "capabilities": "research.web"},                    # falscher Typ
    {"agent": "research", "capabilities": ["research.web"], "tool": "shell"}, # zusaetzlicher Schluessel
    {"agent": "research", "capabilities": ["research.web"], "confirmed": True},
    {"agent": 7, "capabilities": []},
    {"capabilities": ["research.web"]},
    {"agent": "research", "capabilities": ["research.web"], "reason": 5},
    "kein objekt", None, [], 42,
])
def test_invalid_llm_reply_falls_back_to_rules(reply):
    reg = registry()
    d = AgentRouter(reg, AgentPlanner(reg), llm=lambda o, c: reply).route(WEB)
    assert d.source == "rules" and d.agent_id == "browser"


def test_llm_exception_falls_back():
    reg = registry()

    def boom(o, c):
        raise RuntimeError("provider down")
    d = AgentRouter(reg, AgentPlanner(reg), llm=boom).route(WEB)
    assert d.source == "rules" and d.agent_id == "browser"


def test_llm_timeout_falls_back_and_is_bounded():
    reg = registry()
    release = threading.Event()

    def slow(o, c):
        release.wait(10)
        return {"agent": "research", "capabilities": ["research.web"]}
    try:
        d = AgentRouter(reg, AgentPlanner(reg), llm=slow, timeout=0.05).route(WEB)
    finally:
        release.set()
    assert d.source == "rules" and d.agent_id == "browser"


def test_llm_json_string_reply_is_parsed_and_oversized_rejected():
    reg = registry()
    ok = json.dumps({"agent": "coding", "capabilities": ["coding.read"], "reason": "r"})
    assert AgentRouter(reg, AgentPlanner(reg), llm=lambda o, c: ok).route(WEB).source == "llm"
    huge = json.dumps({"agent": "coding", "capabilities": ["coding.read"], "reason": "x" * 50_000})
    assert AgentRouter(reg, AgentPlanner(reg), llm=lambda o, c: huge).route(WEB).source == "rules"


def test_reason_is_cut_and_cleaned():
    reg = registry()
    llm = llm_says(agent="coding", capabilities=["coding.read"], reason="a\x00b" + "z" * 1000)
    d = AgentRouter(reg, AgentPlanner(reg), llm=llm, max_reason_chars=50).route(WEB)
    assert len(d.reason) <= 50 and "\x00" not in d.reason


def test_objective_sent_to_llm_is_limited_and_redacted():
    reg = registry()
    llm = llm_says(agent="coding", capabilities=["coding.read"])
    AgentRouter(reg, AgentPlanner(reg), llm=llm, max_objective_chars=100, redactor=SecretDetector()).route("sk-" + "A" * 40 + " " + "x" * 500)
    sent = llm.calls[0][0]
    assert len(sent) <= 100 and "sk-AAAA" not in sent


# ---- Missbrauch: nur verfuegbar und erlaubt ----------------------------------------------------------------------------------------
def _disable(agent):
    agent.state.transition(AgentStatus.DISABLED)


def test_disabled_agent_is_not_candidate_nor_chosen():
    reg = registry()
    _disable(reg.get("research"))
    llm = llm_says(agent="research", capabilities=["research.web"])
    d = AgentRouter(reg, AgentPlanner(reg), llm=llm).route(WEB)
    assert "research" not in llm.calls[0][1]
    assert d.source == "rules" and d.agent_id == "browser"


def test_disabled_rules_agent_gives_no_decision():
    reg = registry()
    _disable(reg.get("browser"))
    d = AgentRouter(reg, AgentPlanner(reg)).route(WEB)
    assert d.agent_id is None


def test_allowed_agents_limit_llm_and_rules():
    reg = registry()
    llm = llm_says(agent="browser", capabilities=["browser.read"])
    d = AgentRouter(reg, AgentPlanner(reg), llm=llm).route(WEB, allowed_agents=frozenset({"coding"}))
    assert set(llm.calls[0][1]) == {"coding"}
    assert d.agent_id is None and d.source == "rules"          # Regeln wuerden browser waehlen -> nicht erlaubt -> kein Agent


def test_allowed_capabilities_limit_choice():
    reg = registry()
    llm = llm_says(agent="browser", capabilities=["browser.read", "browser.interact"])
    d = AgentRouter(reg, AgentPlanner(reg), llm=llm).route(WEB, allowed_capabilities=frozenset({"browser.read"}))
    assert llm.calls[0][1]["browser"] == ["browser.read"]
    assert d.source == "rules" and d.capabilities == frozenset({"browser.read"})   # LLM wollte interact -> ungueltig -> Regeln, gefiltert


def test_required_capabilities_must_be_offered_and_allowed():
    reg = registry()
    r = AgentRouter(reg, AgentPlanner(reg))
    assert r.route(WEB, required=frozenset({"coding.write"}), allowed_agents=frozenset({"browser"})).agent_id is None
    assert r.route(WEB, required=frozenset({"browser.interact"}), allowed_capabilities=frozenset({"browser.read"})).agent_id is None
    d = AgentRouter(reg, AgentPlanner(reg), llm=llm_says(agent="research", capabilities=["research.web"])).route(WEB, required=frozenset({"browser.read"}))
    assert d.agent_id == "browser" and d.source == "rules"     # LLM-Wahl ohne die geforderte Faehigkeit ist ungueltig


def test_llm_must_include_required_capabilities():
    reg = registry()
    llm = llm_says(agent="browser", capabilities=["browser.read"])
    d = AgentRouter(reg, AgentPlanner(reg), llm=llm).route(WEB, required=frozenset({"browser.interact"}))
    assert d.source == "rules"


def test_empty_or_bad_objective_and_params():
    reg = registry()
    r = AgentRouter(reg, AgentPlanner(reg))
    assert r.route("   ").agent_id is None
    assert r.route(None).agent_id is None                      # type: ignore[arg-type]
    assert r.route(WEB, task_id="bad id!").task_id != "bad id!"


# ---- Ereignis und Audit ------------------------------------------------------------------------------------------------------------
def test_every_decision_reaches_event_and_audit_listeners():
    reg = registry()
    log = EventLog(None, SecretDetector())
    sink = MemoryAuditSink()
    r = AgentRouter(reg, AgentPlanner(reg), llm=llm_says(agent="coding", capabilities=["coding.read"], reason="tests"))
    r.add_listener(event_listener(log.emit))
    r.add_listener(to_audit(AuditLogger([sink])))
    r.route(CODE, task_id="t9")
    r.route("hallo wie geht es dir", task_id="t10")          # auch "kein Agent" wird gemeldet
    ev = [e for e in log.events_since(0) if e["type"] == "routing"]
    assert [e["data"]["task_id"] for e in ev] == ["t9", "t10"]
    assert ev[0]["data"]["agent"] == "coding" and ev[0]["data"]["source"] == "llm" and ev[0]["data"]["reason"] == "tests"
    tail = sink.tail(10)
    assert len(tail) == 2 and all(e["tool"] == "agent_router" and e["action"] == "route" for e in tail)
    assert tail[0]["resource"] == "t9" and tail[0]["extra"]["agent"] == "coding"


def test_failing_listener_never_breaks_routing():
    reg = registry()
    r = AgentRouter(reg, AgentPlanner(reg))
    seen = []
    r.add_listener(lambda d: (_ for _ in ()).throw(RuntimeError("x")))
    r.add_listener(lambda d: seen.append(d))
    assert r.route(WEB).agent_id == "browser" and len(seen) == 1


def test_audit_listener_redacts_reason_and_survives_failing_sink():
    class Bad(MemoryAuditSink):
        def record(self, event):
            raise OSError("disk")
    d = RoutingDecision("t1", "coding", frozenset({"coding.read"}), "llm", "sk-" + "B" * 40)
    to_audit(AuditLogger([Bad()]))(d)                      # wirft nicht
    sink = MemoryAuditSink()
    to_audit(AuditLogger([sink]))(d)
    assert "sk-BBBB" not in json.dumps(sink.tail(1))


def test_decision_validates_itself():
    for bad in (dict(source="magic"), dict(agent_id="Bad Id"), dict(capabilities=frozenset({"nodot"}))):
        kw = dict(task_id="t", agent_id="coding", capabilities=frozenset({"coding.read"}), source="rules", reason="r")
        kw.update(bad)
        with pytest.raises(ValueError):
            RoutingDecision(**kw)


# ---- LLM-Planer ueber Provider -----------------------------------------------------------------------------------------------------
class Prov:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []

    def complete_text(self, system, user, **kw):
        self.calls.append((system, user, kw))
        if self.exc:
            raise self.exc
        return self.reply


def test_llm_planner_uses_provider_and_marks_data_untrusted():
    p = Prov(json.dumps({"agent": "coding", "capabilities": ["coding.read"], "reason": "ok"}))
    reg = registry()
    d = AgentRouter(reg, AgentPlanner(reg), llm=LLMAgentPlanner(p)).route(CODE)
    assert d.source == "llm" and d.agent_id == "coding"
    system, user, kw = p.calls[0]
    assert "untrusted" in system and kw.get("temperature") == 0.0
    assert json.loads(user)["candidates"]["coding"] == ["coding.read", "coding.test", "coding.write"]


def test_llm_planner_provider_error_and_garbage_fall_back():
    reg = registry()
    for prov in (Prov(exc=RuntimeError("net")), Prov("not json"), Prov("")):
        assert AgentRouter(reg, AgentPlanner(reg), llm=LLMAgentPlanner(prov)).route(WEB).source == "rules"


# ---- Einstellung ------------------------------------------------------------------------------------------------------------------
def test_setting_default_off_and_validated(tmp_path):
    s = load_settings(env={}).agents.router
    assert s == AgentRouterSettings() and s.enabled is False
    f = tmp_path / "c.toml"
    f.write_text("[agents.router]\nenabled = true\ntimeout_seconds = 3\n", encoding="utf-8")
    b = load_settings(f, env={}).agents.router
    assert b.enabled is True and b.timeout_seconds == 3.0
    for bad in ("timeout_seconds = 0", "timeout_seconds = 61", "max_objective_chars = 0", "max_objective_chars = 99999", "max_reason_chars = 0",
                "max_reason_chars = 5000", "bogus = 1", "skip_permissions = true"):
        f.write_text(f"[agents.router]\n{bad}\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_settings(f, env={})


def test_router_is_wired_in_bootstrap_only_behind_the_assistant_and_router_flags():
    # assistant-e2e wired the router; it stays off unless assistant.enabled AND agents.router.enabled (see tests/test_assistant_e2e.py)
    import pathlib
    text = pathlib.Path("src/jarvis/bootstrap.py").read_text(encoding="utf-8")
    assert "settings.assistant.enabled and settings.agents.router.enabled" in text and "llm=None" in text
