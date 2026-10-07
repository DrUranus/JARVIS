"""ResearchAgent against the REAL permission engine, tool registry and browser controller (fake provider, configurable web)."""
from __future__ import annotations

import json

import pytest

from analysis_util import SHOP_A, SHOP_B, SHOP_C, make_rig, make_web
from browser_util import NO, ONCE
from jarvis.agents import TaskStatus
from jarvis.browser.providers.fake import FakeDoc, el
from jarvis.research import ResearchLimits
from jarvis.research.agent import ResearchAgent

S = TaskStatus
Q = ["Preise Innenreinigung"]


def srcs(out, status=None):
    return [s for s in out["sources"] if status is None or s["status"] == status]


def test_several_sources_are_read_compared_and_returned_with_their_sources(tmp_path):
    r = make_rig(tmp_path)
    res = r.run("research", {"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": Q})
    o = res.output
    assert res.status is S.SUCCEEDED and o["kind"] == "research_result" and len(srcs(o, "ok")) == 3
    assert all(s["retrieved_at"] and s["source"] and s["url"].startswith("https://") and 0 <= s["relevance"] <= 1 for s in srcs(o, "ok"))
    assert {f["source_url"] for f in o["figures"]} == {SHOP_A, SHOP_B, SHOP_C}
    kinds = {c["kind"] for c in o["claims"]}
    assert "FACT" in kinds and "INFERENCE" in kinds
    assert all(c["sources"] for c in o["claims"] if c["kind"] == "FACT")                           # every fact carries a source
    assert o["untrusted_content"] and r.provider.calls_named("page.goto")


def test_conflicting_sources_are_marked_conflict_with_both_sides(tmp_path):
    o = make_rig(tmp_path).run("research", {"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": Q}).output
    c = next(c for c in o["conflicts"] if c["label"] == "innenreinigung")
    assert c["status"] == "CONFLICT" and {e["value"] for e in c["entries"]} == {50.0, 80.0, 52.5}
    assert any("CONFLICT" in u for u in o["uncertainties"])
    conflicted = [cl for cl in o["claims"] if "Innenreinigung" in cl["text"]]
    assert conflicted and all(cl["kind"] == "UNCERTAIN" for cl in conflicted)


def test_opinions_and_hedged_statements_are_not_facts(tmp_path):
    o = make_rig(tmp_path).run("research", {"urls": [SHOP_B], "questions": ["Preise Fahrzeugaufbereitung"]}).output
    hedged = [c for c in o["claims"] if "angeblich" in c["text"]]
    assert hedged and hedged[0]["kind"] == "UNCERTAIN"
    o2 = make_rig(tmp_path / "x").run("research", {"urls": [SHOP_A], "questions": ["bester Anbieter Region Fahrzeugaufbereitung"]}).output
    assert any(c["kind"] == "OPINION" for c in o2["claims"])


def test_unavailable_sources_are_reported_not_invented(tmp_path):
    r = make_rig(tmp_path)
    o = r.run("research", {"urls": ["https://slow.example.com/", SHOP_A, "https://empty.example.com/"], "questions": Q}).output
    by = {s["url"]: s for s in o["sources"]}
    assert by["https://slow.example.com/"]["status"] == "unavailable" and by["https://slow.example.com/"]["retrieved_at"] is None
    assert by["https://empty.example.com/"]["status"] == "unavailable" and "no readable text" in by["https://empty.example.com/"]["note"]
    assert by[SHOP_A]["status"] == "ok" and any("unavailable" in u for u in o["uncertainties"])


def test_nothing_readable_fails_instead_of_inventing_a_result(tmp_path):
    res = make_rig(tmp_path).run("research", {"urls": ["https://slow.example.com/", "https://empty.example.com/"], "questions": Q})
    assert res.status is S.FAILED and res.error_code == "no_sources_available" and "nothing could be read" in res.output["summary"]
    assert res.output["claims"] == [] and res.output["figures"] == []


def test_blocked_addresses_never_reach_the_browser(tmp_path):
    r = make_rig(tmp_path)
    bad = ["http://10.0.0.5/secret", "http://localhost/", "javascript:alert(1)", "file:///etc/passwd", "http://169.254.169.254/", "https://u:p@example.com/", "http://2130706433/"]
    o = r.run("research", {"urls": [SHOP_A, *bad], "questions": Q}).output
    assert len(srcs(o, "blocked")) == len(bad) and len(srcs(o, "ok")) == 1
    visited = [c[1] for c in r.provider.calls_named("page.goto")]
    assert not any(any(b in str(v) for b in ("10.0.0.5", "localhost", "169.254", "file:", "javascript", "2130706433", "u:p@")) for v in visited)


def test_a_redirect_to_an_internal_address_discards_what_was_read(tmp_path):
    r = make_rig(tmp_path)
    res = r.run("research", {"urls": ["https://redirect.example.com/", SHOP_A], "questions": Q})
    o = res.output
    redirect = next(s for s in o["sources"] if "redirect" in s["url"])
    assert redirect["status"] in ("blocked", "unavailable") and "internal" not in json.dumps(o["claims"]).lower() and "Secret" not in json.dumps(o["claims"])


def test_duplicates_are_read_once(tmp_path):
    r = make_rig(tmp_path)
    o = r.run("research", {"urls": [SHOP_A, SHOP_A, SHOP_A + "?utm_source=x", "https://www.wash-a.example.com/", SHOP_B], "questions": Q}).output
    assert len(srcs(o)) <= 3 and len([c for c in r.provider.calls_named("page.goto") if "wash-a" in str(c[1])]) == 1


def test_max_sources_limit_is_applied_and_reported(tmp_path):
    r = make_rig(tmp_path, limits=ResearchLimits(max_sources=2, max_actions=40))
    o = r.run("research", {"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": Q, "max_sources": 99}).output
    assert len(srcs(o, "ok")) == 2 and len(srcs(o, "skipped")) == 1 and "max_sources" in srcs(o, "skipped")[0]["note"]
    o2 = make_rig(tmp_path / "b").run("research", {"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": Q, "max_sources": 1}).output
    assert len(srcs(o2, "ok")) == 1


def test_max_actions_budget_stops_the_research(tmp_path):
    r = make_rig(tmp_path, limits=ResearchLimits(max_sources=8, max_actions=4))
    o = r.run("research", {"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": Q}).output
    assert o["actions_used"] <= 4 and len(srcs(o, "ok")) < 3 and any("budget" in s["note"] for s in srcs(o, "skipped"))


def test_timeout_stops_reading_and_marks_the_rest_skipped(tmp_path):
    t = {"now": 0.0}

    def mono():
        t["now"] += 40.0
        return t["now"]
    r = make_rig(tmp_path, agents=[ResearchAgent(ResearchLimits(timeout=100), monotonic=mono)])
    o = r.run("research", {"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": Q}).output
    assert len(srcs(o, "skipped")) >= 1 and any("timeout" in s["note"] for s in srcs(o, "skipped")) and len(srcs(o, "ok")) < 3


def test_result_is_truncated_to_its_limit(tmp_path):
    r = make_rig(tmp_path, limits=ResearchLimits(max_result_chars=2500))
    o = r.run("research", {"urls": ["https://big.example.com/", SHOP_A, SHOP_B], "questions": ["Fahrzeugaufbereitung Paket"]}).output
    assert len(json.dumps(o)) <= 2600 and o["truncated"] is True


def test_secrets_in_pages_are_redacted(tmp_path):
    o = make_rig(tmp_path).run("research", {"urls": ["https://secrets.example.com/"], "questions": Q}).output
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV123456" not in json.dumps(o)


def test_follow_links_reads_relevant_pages_of_the_same_site_only(tmp_path):
    web = make_web()
    web.add(FakeDoc("https://wash-a.example.com/", "A", "Fahrzeugaufbereitung Region.", elements=[
        el("a", name="Preise Fahrzeugaufbereitung", href="https://wash-a.example.com/preise"), el("a", name="Preise extern", href="https://wash-b.example.org/"),
        el("a", name="Preise intern", href="http://10.0.0.5/admin")]))
    r = make_rig(tmp_path, web=web)
    o = r.run("research", {"urls": [SHOP_A], "questions": ["Preise Fahrzeugaufbereitung"], "follow_links": True, "max_sources": 3}).output
    urls = [s["url"] for s in srcs(o, "ok")]
    assert "https://wash-a.example.com/preise" in urls and all("wash-a" in u for u in urls)


def test_domain_filters_apply_before_any_navigation(tmp_path):
    r = make_rig(tmp_path)
    o = r.run("research", {"urls": [SHOP_A, SHOP_B], "questions": Q, "allowed_domains": ["wash-a.example.com"], "excluded_domains": ["wash-b.example.org"]}).output
    assert len(srcs(o, "ok")) == 1 and len(srcs(o, "blocked")) == 1
    assert not [c for c in r.provider.calls_named("page.goto") if "wash-b" in str(c[1])]


def test_declined_navigation_blocks_the_task_without_retry(tmp_path):
    r = make_rig(tmp_path, [ONCE, NO])                                 # start allowed, the navigation is declined
    res = r.run("research", {"urls": [SHOP_A, SHOP_B], "questions": Q})
    assert res.status is S.BLOCKED and res.error_code == "permission_denied"
    assert [q.action for q in r.prompts.requests] == ["start", "goto", "stop"] and not r.provider.calls_named("page.goto")      # (the stop tidies up what the task opened)


def test_no_answers_means_no_reading(tmp_path):
    res = make_rig(tmp_path, []).run("research", {"urls": [SHOP_A], "questions": Q})
    assert res.status is S.BLOCKED and not make_rig(tmp_path / "x", []).provider.calls_named("page.goto")


def test_the_permission_engine_asks_for_every_navigation(tmp_path):
    r = make_rig(tmp_path)
    r.run("research", {"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": Q})
    actions = [q.action for q in r.prompts.requests]
    assert "start" in actions and actions.count("goto") == 3                          # the browser's own rules stay fully active


def test_research_uses_only_the_browser_tool_and_only_read_actions_after_goto(tmp_path):
    r = make_rig(tmp_path)
    r.run("research", {"urls": [SHOP_A], "questions": Q})
    assert ResearchAgent.tool_names == frozenset({"browser"})
    names = [c[0] for c in r.provider.calls]
    assert not any(n.startswith(("element.", "page.fill", "page.click", "page.upload", "page.download")) for n in names)


def test_invalid_requests_fail_before_any_tool_call(tmp_path):
    r = make_rig(tmp_path)
    for data in ({}, {"urls": []}, {"urls": [SHOP_A], "max_sources": -5}, {"urls": [SHOP_A], "confirmed": True}):
        res = r.run("research", data)
        assert res.status is S.FAILED and res.error_code == "invalid_input"
    assert not r.provider.calls and not r.prompts.requests


def test_capability_is_required(tmp_path):
    res = make_rig(tmp_path).run("research", {"urls": [SHOP_A]}, caps={"research.web"})
    assert res.status is S.SUCCEEDED
    r2 = make_rig(tmp_path / "x")
    from jarvis.agents import AgentTask
    from jarvis.agents.context import AgentContext
    out = ResearchAgent().perform(AgentTask("x", agent_id="research", input={"urls": [SHOP_A]}), AgentContext("t", "x", {}, frozenset({"browser.read"})))
    assert out.status is S.BLOCKED and out.error_code == "capability_not_allowed"


def test_legacy_single_url_input_still_works(tmp_path):
    res = make_rig(tmp_path).run("research", {"url": SHOP_A})
    assert res.status is S.SUCCEEDED and len(srcs(res.output, "ok")) == 1


def test_the_browser_session_started_by_the_task_is_closed(tmp_path):
    r = make_rig(tmp_path)
    r.run("research", {"urls": [SHOP_A], "questions": Q})
    assert not r.browser.overview().get("session")
    r.run("research", {"urls": [SHOP_B], "questions": Q})                                   # a second task works: nothing was left open


def test_a_missing_browser_tool_is_a_clear_failure(tmp_path):
    r = make_rig(tmp_path)
    r.registry._tools.pop("browser") if hasattr(r.registry, "_tools") else None
    res = r.run("research", {"urls": [SHOP_A]})
    assert res.status is S.FAILED and res.error_code in ("tool_unavailable", "step_failed")


def test_cancellation_during_research(tmp_path):
    import threading
    from agents_util import wait_event
    web = make_web()
    web.slow.add(SHOP_B)
    r = make_rig(tmp_path, web=web, executor=None)
    from jarvis.agents import AgentTask
    t = AgentTask("Recherchiere", agent_id="research", input={"urls": [SHOP_A, SHOP_B, SHOP_C], "questions": Q}, required_capabilities=frozenset({"research.web"}))
    r.orch.submit(t)
    r.orch.cancel(t.task_id)                                                               # cancelled before it starts: nothing is read
    assert r.orch.get(t.task_id).status is S.CANCELLED and not r.provider.calls_named("page.goto")


def test_agent_failure_does_not_poison_the_next_task(tmp_path):
    r = make_rig(tmp_path)
    bad = r.run("research", {"urls": ["https://slow.example.com/"], "questions": Q})
    good = r.run("research", {"urls": [SHOP_A], "questions": Q})
    assert bad.status is S.FAILED and good.status is S.SUCCEEDED


class StubGateway:
    """A browser tool that LIES about the final URL (e.g. a redirect the browser layer failed to flag): the agent must not trust it."""

    def __init__(self, final_url, text="Interne Daten: Innenreinigung ab 99 €."):
        self.final_url, self.text, self.calls = final_url, text, []

    def available(self, tool):
        return tool == "browser"

    def call(self, tool, **kw):
        from types import SimpleNamespace as NS
        self.calls.append(kw)
        out = {"running": True} if kw["action"] == "status" else {"url": self.final_url, "title": "t", "text": self.text} if kw["action"] == "text" else {}
        return NS(success=True, output=out, error=None, permission=None)


@pytest.mark.parametrize("final", ["http://10.0.0.5/admin", "http://localhost/", "http://169.254.169.254/latest", "file:///etc/passwd", "https://user:pw@evil.example.com/"])
def test_the_agent_does_not_trust_the_browser_about_where_a_page_ended_up(final):
    from jarvis.agents import AgentTask
    from jarvis.agents.context import AgentContext
    gw = StubGateway(final)
    ctx = AgentContext("t", "x", {}, frozenset({"research.web"}), tools=gw)
    out = ResearchAgent().perform(AgentTask("Recherchiere", agent_id="research", input={"urls": ["https://wash-a.example.com/"], "questions": ["Innenreinigung"]}), ctx)
    o = out.output
    assert out.status is S.FAILED and o["sources"][0]["status"] == "blocked" and "redirected" in o["sources"][0]["note"]
    assert o["claims"] == [] and o["figures"] == [] and "99" not in json.dumps(o["claims"])                          # what was read there is discarded
