"""Rig for the research / business / finance tests: a REAL permission engine + ToolRegistry + browser controller on the FAKE browser provider with a
configurable web, and a real AgentOrchestrator (inline executor, manual scheduler) holding the real agents."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents_util import FakeClock, InlineExecutor, ManualScheduler
from browser_util import ONCE, NO
from jarvis.agents import AgentOrchestrator, AgentPlanner, AgentRegistry, AgentTask, TaskStatus
from jarvis.browser import BrowserController
from jarvis.browser.policy import baseline_rules
from jarvis.browser.providers.fake import FakeBrowserProvider, FakeDoc, FakeWeb, el
from jarvis.browser.tools import register_browser_tools
from jarvis.config import BrowserSettings
from jarvis.permissions import Policy, ScriptedConfirmation
from jarvis.research.agent import ResearchAgent
from jarvis.research.models import ResearchLimits
from jarvis.tools import ToolRegistry
from secutil import make_engine

SHOP_A = "https://wash-a.example.com/"
SHOP_B = "https://wash-b.example.org/"
SHOP_C = "https://wash-c.example.net/"


def make_web() -> FakeWeb:
    web = FakeWeb()
    web.add(FakeDoc(SHOP_A, "Auto Pflege A", "Fahrzeugaufbereitung in der Region. Innenreinigung ab 50,00 € inklusive Staubsaugen. Außenwäsche ab 25 €. "
                    "Wir sind der beste Anbieter der Region!", elements=[el("a", name="Preise Fahrzeugaufbereitung", href=SHOP_A + "preise")]))
    web.add(FakeDoc(SHOP_A + "preise", "Preise A", "Preisliste Fahrzeugaufbereitung: Innenreinigung ab 50 € und Komplettaufbereitung ab 199 €."))
    web.add(FakeDoc(SHOP_B, "Glanzwerk B", "Fahrzeugaufbereitung mit Meisterbetrieb. Innenreinigung ab 80 € inklusive Polster. Außenwäsche ab 27 €. "
                    "Preise angeblich ab 19 € bei Aktion."))
    web.add(FakeDoc(SHOP_C, "Shop C", "Fahrzeugaufbereitung günstig. Innenreinigung ab 52,50 € und Außenwäsche ab 24,90 €."))
    web.add(FakeDoc("https://empty.example.com/", "Leer", "   "))
    web.slow.add("https://slow.example.com/")
    web.add(FakeDoc("https://secrets.example.com/", "Secrets", "Fahrzeugaufbereitung Kontakt. api_key=sk-ABCDEFGHIJKLMNOPQRSTUV123456 Innenreinigung ab 60 €."))
    web.redirects["https://redirect.example.com/"] = "http://10.0.0.5/secret"
    web.add(FakeDoc("http://10.0.0.5/secret", "Secret", "internal"))
    web.add(FakeDoc("https://big.example.com/", "Big", " ".join(f"Fahrzeugaufbereitung Paket{i} ab {i + 10} €." for i in range(400))))
    return web


@dataclass
class Rig:
    engine: Any
    prompts: Any
    registry: ToolRegistry
    provider: FakeBrowserProvider
    browser: BrowserController
    orch: AgentOrchestrator
    reg: AgentRegistry
    planner: AgentPlanner

    def run(self, agent_id: str, input: dict, *, caps: set[str] | None = None, objective: str = "Recherchiere die Preise", **kw: Any):
        return self.orch.run(AgentTask(objective, agent_id=agent_id, input=input, required_capabilities=frozenset(caps or {"research.web"}), **kw))


def make_rig(tmp_path: Path, answers=None, *, web: FakeWeb | None = None, agents: list[Any] | None = None, limits: ResearchLimits | None = None,
             private_ok: tuple[str, ...] = (), **orch_kw: Any) -> Rig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = ScriptedConfirmation([ONCE] * 400 if answers is None else answers)
    engine, sink, ws = make_engine(tmp_path, confirmation=prompts)
    bs = BrowserSettings(enabled=True, provider="fake", headless=True, max_actions_per_minute=0, max_actions_per_session=0)
    provider = FakeBrowserProvider(web or make_web())
    browser = BrowserController(provider, bs)
    engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(bs))))
    registry = ToolRegistry(engine)
    register_browser_tools(registry, browser)
    reg = AgentRegistry()
    for a in agents if agents is not None else [ResearchAgent(limits or ResearchLimits(), private_hosts_allowed=private_ok)]:
        reg.register(a)
    orch_kw.setdefault("clock", FakeClock())
    orch_kw.setdefault("scheduler", ManualScheduler())
    orch_kw.setdefault("executor", InlineExecutor())
    orch = AgentOrchestrator(reg, tools=registry, **orch_kw)
    return Rig(engine, prompts, registry, provider, browser, orch, reg, AgentPlanner(reg))


def plain_orch(agents: list[Any], **kw: Any):
    """An orchestrator (inline) with the given agents and no tools: Business/Finance need none."""
    reg = AgentRegistry()
    for a in agents:
        reg.register(a)
    kw.setdefault("clock", FakeClock())
    kw.setdefault("scheduler", ManualScheduler())
    kw.setdefault("executor", InlineExecutor())
    return AgentOrchestrator(reg, **kw), reg


def research_output(prices_by_shop: dict[str, dict[str, float]] | None = None, conflicts: list | None = None, status_by_url: dict | None = None) -> dict:
    """A research_result as the ResearchAgent produces it (for the agents that consume it)."""
    prices_by_shop = prices_by_shop if prices_by_shop is not None else {SHOP_A: {"innenreinigung": 50.0, "außenwäsche": 25.0}, SHOP_B: {"innenreinigung": 80.0, "außenwäsche": 27.0},
                                                                         SHOP_C: {"innenreinigung": 52.5, "außenwäsche": 24.9}}
    sources = [{"url": u, "title": f"Shop {i}", "source": u.split("/")[2], "retrieved_at": "2026-01-01T00:00:00+00:00", "relevance": 0.5,
                "status": (status_by_url or {}).get(u, "ok"), "note": ""} for i, u in enumerate(prices_by_shop)]
    figures = [{"label": label, "value": v, "unit": "EUR", "source_url": u, "context": f"{label} ab {v}"} for u, d in prices_by_shop.items() for label, v in d.items()]
    claims = [{"text": f"{label} ab {v} €", "kind": "FACT", "sources": [u], "corroborated": False} for u, d in prices_by_shop.items() for label, v in d.items()]
    return {"kind": "research_result", "objective": "x", "summary": "s", "sources": sources, "figures": figures, "claims": claims, "conflicts": conflicts or [],
            "uncertainties": [], "actions_used": 3, "truncated": False}


def run_with_parent(orch: AgentOrchestrator, agent_id: str, caps: set[str], data: dict, parent_output: dict | None = None, objective: str = "Analyse"):
    """Run one task of `agent_id`, optionally after a succeeded 'research' parent task whose output is `parent_output` (the real hand-off path)."""
    deps: tuple[str, ...] = ()
    if parent_output is not None:
        parent = AgentTask("Recherchiere", agent_id="research", required_capabilities=frozenset({"research.web"}), task_id="parent-1")
        orch.submit(parent)
        orch.start("parent-1")
        deps = ("parent-1",)
    return orch.run(AgentTask(objective, agent_id=agent_id, input=data, required_capabilities=frozenset(caps), dependencies=deps))
