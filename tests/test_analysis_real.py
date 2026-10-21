"""REAL research -> business -> finance: real threads, the real orchestrator and timers, the real Goal Engine and a REAL browser (Playwright) reading a local,
harmless 'market' of three competitor sites (127.0.0.1, different ports). Skipped cleanly if Playwright or a browser is missing. Optional public check:
JARVIS_TEST_PUBLIC_WEB=1 reads https://example.com/ (needs internet). No real money, no real messages, no real orders - none of that exists in these layers."""
from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from browser_util import NO, ONCE  # noqa: E402
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry, AgentTask, TaskStatus  # noqa: E402
from jarvis.browser import BrowserController  # noqa: E402
from jarvis.browser.policy import baseline_rules  # noqa: E402
from jarvis.browser.providers.playwright_provider import PlaywrightProvider  # noqa: E402
from jarvis.browser.tools import register_browser_tools  # noqa: E402
from jarvis.business.agent import BusinessAgent  # noqa: E402
from jarvis.config import BrowserSettings  # noqa: E402
from jarvis.finance.agent import FinanceAgent  # noqa: E402
from jarvis.goals import GoalEngine, GoalPlanner, GoalStatus, StepStatus  # noqa: E402
from jarvis.permissions import Policy, ScriptedConfirmation  # noqa: E402
from jarvis.research.agent import ResearchAgent  # noqa: E402
from jarvis.tools import ToolRegistry  # noqa: E402
from secutil import make_engine  # noqa: E402

G = GoalStatus
PAGES = {
    "a": ("Auto Pflege Nord", "<p>Fahrzeugaufbereitung in Köln.</p><p>Innenreinigung ab 50,00 € inklusive Staubsaugen.</p><p>Außenwäsche ab 25 €.</p>"
          "<p>Wir sind der beste Anbieter der Region!</p>"),
    "b": ("Glanzwerk Süd", "<p>Fahrzeugaufbereitung mit Meisterbetrieb.</p><p>Innenreinigung ab 80 € inklusive Polster.</p><p>Außenwäsche ab 27 €.</p>"),
    "c": ("Shop C West", "<p>Fahrzeugaufbereitung günstig.</p><p>Innenreinigung ab 52,50 € und Außenwäsche ab 24,90 €.</p>"
          "<p>Kontakt: api_key=sk-ABCDEFGHIJKLMNOPQRSTUV123456</p>"),
}


def make_handler(key: str):
    title, body = PAGES[key]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            data = f"<!doctype html><html><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return H


@contextmanager
def market():
    servers = {k: ThreadingHTTPServer(("127.0.0.1", 0), make_handler(k)) for k in PAGES}
    for s in servers.values():
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        yield {k: f"http://127.0.0.1:{s.server_address[1]}/" for k, s in servers.items()}
    finally:
        for s in servers.values():
            s.shutdown()
            s.server_close()


class Real:
    def __init__(self, tmp: Path, answers=None, agents=None) -> None:
        self.prompts = ScriptedConfirmation([ONCE] * 3000 if answers is None else answers)
        self.engine, self.sink, self.ws = make_engine(tmp, confirmation=self.prompts)
        bs = BrowserSettings(enabled=True, headless=True, private_hosts_allowed=("127.0.0.1",), navigation_timeout=8.0, max_actions_per_minute=0, max_actions_per_session=0, action_timeout=5.0)
        self.controller = BrowserController(PlaywrightProvider(), bs)
        self.engine.update_policy(Policy(tuple(self.engine.policy.rules) + tuple(baseline_rules(bs))))
        self.registry = ToolRegistry(self.engine)
        register_browser_tools(self.registry, self.controller)
        reg = AgentRegistry()
        for a in agents or [ResearchAgent(private_hosts_allowed=("127.0.0.1",)), BusinessAgent(), FinanceAgent()]:
            reg.register(a)
        self.orch = AgentOrchestrator(reg, tools=self.registry, cancel_grace=5.0)                      # real threads, real timers
        self.planner = AgentPlanner(reg)
        self.goals = GoalEngine(self.orch, GoalPlanner(self.planner), goal_timeout=120, step_timeout=60, cancel_wait=8.0)

    def probe_or_skip(self) -> None:
        for kind in ([os.environ["JARVIS_TEST_BROWSER"]] if os.environ.get("JARVIS_TEST_BROWSER") else []) + ["chromium", "msedge", "chrome"]:
            s = BrowserSettings(**{**self.controller.settings.__dict__, **({"executable_path": kind} if os.path.isabs(kind) else {"browser": kind})})
            self.controller.settings = s
            out = self.registry.execute("browser", action="start")
            if out.success:
                self.registry.execute("browser", action="stop")
                self.prompts.requests.clear()                                                              # the probe's own questions are not part of the test
                return
            last = out.error
        pytest.skip(f"no usable browser for the real research tests ({str(last)[:120]})")

    def close(self) -> None:
        self.goals.shutdown(5)
        self.orch.shutdown(5)
        try:
            self.registry.execute("browser", action="stop")
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def real(tmp_path):
    r = Real(tmp_path)
    r.probe_or_skip()
    yield r
    r.close()


def run_goal(r: Real, template: str, objective: str, **ctx):
    return r.goals.run(r.goals.create(objective, context={"template": template, **ctx}).goal_id)


def test_real_1_a_real_page_is_read_in_a_real_browser(real):
    with market() as m:
        res = real.orch.run(AgentTask("Recherchiere die Preise", agent_id="research", input={"urls": [m["a"]], "questions": ["Innenreinigung Preis"]},
                                      required_capabilities=frozenset({"research.web"})), timeout=60)
    o = res.output
    assert res.status is TaskStatus.SUCCEEDED, (res.error, o)
    src = o["sources"][0]
    assert src["status"] == "ok" and src["title"] == "Auto Pflege Nord" and src["retrieved_at"] and src["source"] == "127.0.0.1"
    assert any(f["value"] == 50.0 and f["unit"] == "EUR" and "innenreinigung" in f["label"] for f in o["figures"])
    assert "start" in [q.action for q in real.prompts.requests] and "goto" in [q.action for q in real.prompts.requests]           # the engine asked, the browser rules applied


def test_real_2_several_sources_are_compared_and_the_conflict_is_shown(real):
    with market() as m:
        res = run_goal(real, "research_web", "Recherchiere die Preise der Wettbewerber", research={"urls": [m["a"], m["b"], m["c"]], "questions": ["Innenreinigung Preise Außenwäsche"]})
    assert res.status is G.SUCCEEDED, res.summary
    o = res.steps[0].result.output
    assert len([s for s in o["sources"] if s["status"] == "ok"]) == 3 and {s["title"] for s in o["sources"]} == {"Auto Pflege Nord", "Glanzwerk Süd", "Shop C West"}
    conflict = next(c for c in o["conflicts"] if c["label"] == "innenreinigung")
    assert conflict["status"] == "CONFLICT" and {e["value"] for e in conflict["entries"]} == {50.0, 80.0, 52.5}
    assert any(c["kind"] == "INFERENCE" for c in o["claims"]) and "sk-ABCDEFGHIJKLMNOPQRSTUV123456" not in json.dumps(o)     # the secret on page C is redacted


def test_real_3_competitor_analysis_with_positioning(real):
    with market() as m:
        res = run_goal(real, "competitor_analysis", "Vergleiche die Wettbewerber", research={"urls": [m["a"], m["b"], m["c"]], "questions": ["Innenreinigung Preise Außenwäsche"]},
                       business={"competitors": [{"name": "Glanzwerk Süd", "url": m["b"]}]})
        res_urls = m
    assert res.status is G.SUCCEEDED, res.summary
    comps = {c["name"]: c for c in res.steps[1].result.output["competitors"]}
    assert comps["Glanzwerk Süd"]["positioning"] == "premium" and comps["Glanzwerk Süd"]["positioning_basis"] == "INFERENCE"
    assert len(comps) == 3 and all(c["prices"] for c in comps.values()) and {s["url"] for s in res.steps[1].result.output["sources"]} == set(res_urls.values())


def test_real_4_business_calculation_with_the_researched_data(real):
    with market() as m:
        res = run_goal(real, "business_plan", "Untersuche den Markt und rechne die Wirtschaftlichkeit durch", research={"urls": [m["a"], m["c"]], "questions": ["Außenwäsche Preise"]},
                       business={"plan": {"offer": "Außenwäsche", "price_label": "außenwäsche", "variable_cost": 8, "fixed_costs": 900, "units": {"pessimistic": 30, "base": 60, "optimistic": 90},
                                          "investment": 4000}})
    assert res.status is G.SUCCEEDED, res.summary
    calc = res.steps[1].result.output["calculations"]
    a = {x["name"]: x for x in res.steps[1].result.output["assumptions"]}
    # the two pages state different Außenwäsche prices (25 and 24.90): within tolerance, so the first sourced figure is used as a flagged ESTIMATE
    assert calc["break_even"]["status"] == "COMPUTED" and a["price"]["basis"] == "ESTIMATE" and calc["break_even"]["units"] == pytest.approx(900 / (calc["break_even"]["inputs"]["price"] - 8))
    assert calc["scenarios"]["base"]["units"] == 60


def test_real_5_and_6_financial_calculation_and_a_paper_trade_scenario(real):
    f = run_goal(real, "financial_analysis", "Analysiere ACME", finance={"company": {"name": "ACME", "price": 100, "eps": 5, "market_cap": 10_000, "revenue": 5_000, "revenue_previous": 4_000,
                                                                                    "net_income": 500, "ebitda": 1_000, "debt": 2_000, "cash": 500, "equity": 4_000,
                                                                                    "operating_cash_flow": 900, "capex": 300}})
    m = {x["name"]: x["value"] for x in f.steps[0].result.output["metrics"]}
    assert f.status is G.SUCCEEDED and m["P/E"] == 20 and m["Revenue growth"] == 0.25 and m["Free cash flow"] == 600
    p = run_goal(real, "paper_trade_analysis", "Paper-Trade", finance={"account": 10_000, "ideas": [
        {"symbol": "AAPL", "direction": "long", "entry": 100, "stop": 95, "target": 115, "position_size": 20, "confidence": 0.6, "prices": [100, 104, 116]},
        {"symbol": "TSLA", "direction": "short", "entry": 50, "stop": 52, "target": 44, "position_size": 40, "prices": [50, 53]}]})
    t = p.steps[0].result.output
    assert p.status is G.SUCCEEDED and t["trades"][0]["paper_trade"]["pnl"] == 300 and t["trades"][1]["paper_trade"]["outcome"] == "stop" and t["paper"] is True
    assert not real.prompts.requests                                                                    # pure analysis: nothing asked, nothing touched


def test_real_7_a_declined_navigation_blocks_the_chain(tmp_path):
    r = Real(tmp_path, [ONCE, NO, NO, NO])
    try:
        r.probe_or_skip()
        r.prompts.requests.clear()
        with market() as m:
            res = run_goal(r, "market_analysis", "Analysiere den Markt", research={"urls": [m["a"], m["b"]], "questions": ["Preise"]})
        s = {x.step_id: x for x in res.steps}
        assert res.status is G.BLOCKED and s["s1"].result.error_code == "permission_denied" and s["s1"].result.attempts == 1 and s["s2"].status is StepStatus.BLOCKED
        assert not [t for t in r.orch.list() if t.agent_id == "business"]
    finally:
        r.close()


def test_real_8_an_external_action_without_confirmation_cannot_happen(real):
    for kind in ("send_email", "outreach", "send_message", "payment"):
        res = real.orch.run(AgentTask("Kontaktiere den Lead", agent_id="business", input={"kind": kind, "to": "lead@example.com"}, required_capabilities=frozenset({"business.analyze"})), timeout=30)
        assert res.status is TaskStatus.BLOCKED and res.error_code == "external_action_not_supported"
    assert not real.prompts.requests


def test_real_9_a_live_order_cannot_be_placed_in_any_way(real):
    direct = real.orch.run(AgentTask("Kaufe Aktien", agent_id="finance", input={"kind": "place_order", "symbol": "AAPL", "quantity": 10}, required_capabilities=frozenset({"finance.analyze"})), timeout=30)
    assert direct.status is TaskStatus.BLOCKED and direct.error_code == "live_trading_not_supported"
    before = len(real.orch.list())
    via_goal = run_goal(real, "business_plan", "Plan", business={"plan": {"price": 10, "variable_cost": 1, "fixed_costs": 5}}, finance={"kind": "place_order", "symbol": "AAPL"})
    assert via_goal.status is G.BLOCKED and via_goal.reason_code == "invalid_plan" and len(real.orch.list()) == before          # refused at plan validation: no task at all
    assert not real.prompts.requests


def test_real_10_secrets_and_credentials_never_travel(real):
    with market() as m:
        res = run_goal(real, "market_analysis", "Analysiere", research={"urls": [m["c"], m["a"].replace("http://", "http://user:secretpw@")], "questions": ["Preise"]})
    blob = json.dumps([s.result.output for s in res.steps if s.result]) + repr(res)
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV123456" not in blob and "secretpw" not in blob
    srcs = res.steps[0].result.output["sources"]
    assert any(s["status"] == "blocked" and "credentials" in s["note"] for s in srcs)


def test_real_11_windows_style_urls_and_paths_are_refused_before_the_browser(real):
    bad = ["https://example.com\\@evil.test/", "C:\\Windows\\win.ini", "\\\\server\\share\\x.html", "file:///C:/Windows/win.ini", "http://127.0.0.1\\x"]
    res = real.orch.run(AgentTask("Recherchiere", agent_id="research", input={"urls": bad, "questions": ["x"]}, required_capabilities=frozenset({"research.web"})), timeout=30)
    assert res.status is TaskStatus.FAILED and res.error_code == "no_sources_available" and all(s["status"] == "blocked" for s in res.output["sources"])
    assert not [q for q in real.prompts.requests if q.action == "goto"] and (sys.platform in ("win32", "linux", "darwin"))


def test_real_12_the_research_timeout_is_enforced_with_a_real_clock(tmp_path):
    from jarvis.research.models import ResearchLimits
    r = Real(tmp_path, agents=[ResearchAgent(ResearchLimits(timeout=0.001), private_hosts_allowed=("127.0.0.1",))])
    try:
        r.probe_or_skip()
        with market() as m:
            res = r.orch.run(AgentTask("Recherchiere", agent_id="research", input={"urls": [m["a"], m["b"], m["c"]], "questions": ["x"]}, required_capabilities=frozenset({"research.web"})), timeout=60)
        assert res.status in (TaskStatus.FAILED, TaskStatus.SUCCEEDED) and any(s["status"] == "skipped" and "timeout" in s["note"] for s in res.output["sources"])
    finally:
        r.close()


def test_real_13_cancelling_a_goal_stops_the_research_chain(tmp_path):
    r = Real(tmp_path)
    try:
        r.probe_or_skip()
        with market() as m:
            g = r.goals.create("Analysiere den Markt", context={"template": "market_analysis", "research": {"urls": [m["a"], m["b"], m["c"]], "questions": ["Preise"]}})
            assert r.goals.cancel(g.goal_id).accepted                                                         # cancelled before it starts: nothing is read
            assert r.goals.run(g.goal_id).status is G.CANCELLED and not r.orch.list()
    finally:
        r.close()


@pytest.mark.skipif(os.environ.get("JARVIS_TEST_PUBLIC_WEB") != "1", reason="set JARVIS_TEST_PUBLIC_WEB=1 to read the public https://example.com/ (needs internet)")
def test_real_public_web_example_com(real):
    res = real.orch.run(AgentTask("Recherchiere Beispiel", agent_id="research", input={"urls": ["https://example.com/"], "questions": ["Example Domain"]},
                                  required_capabilities=frozenset({"research.web"})), timeout=90)
    assert res.status is TaskStatus.SUCCEEDED, (res.error, res.output)
    src = res.output["sources"][0]
    assert src["status"] == "ok" and "Example Domain" in src["title"] and src["source"] == "example.com" and src["retrieved_at"]
