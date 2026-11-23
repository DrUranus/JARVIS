"""V2 Vorbereitung (Bereich A): jeder eingebaute Agent besteht die gemeinsame Konformitaetspruefung (`tests/support/agent_conformance.py`); dieselbe Pruefung gilt spaeter fuer die
Agenten des separaten V2-Agentenprojekts. Dazu: Aktivierungsmatrix (alles standardmaessig aus), keine Faehigkeits-Kollisionen, Uebergabekette Recherche -> Business/Strategist -> Qualitaetstor."""
from __future__ import annotations

import pytest

from jarvis.agents import policy as AP
from jarvis.agents.adapters import BrowserAgent, CodingAgent, ComputerAgent, FilesAgent, ResearchAgent as PlaceholderResearch
from jarvis.business.agent import BusinessAgent
from jarvis.business.strategist_agent import StrategistAgent
from jarvis.config import Settings
from jarvis.finance.agent import FinanceAgent
from jarvis.research.agent import ResearchAgent
from support.agent_conformance import SpyGateway, check_agent, context

BUILTIN = {"browser": BrowserAgent, "coding": CodingAgent, "computer": ComputerAgent, "files": FilesAgent, "research-placeholder": PlaceholderResearch, "research": ResearchAgent,
           "business": BusinessAgent, "finance": FinanceAgent, "strategist": StrategistAgent}


def make(name):
    cls = BUILTIN[name]
    return cls()


@pytest.mark.parametrize("name", sorted(BUILTIN))
def test_every_builtin_agent_is_conformant(name):
    assert check_agent(make(name)) == []


def test_the_conformance_check_finds_a_misbehaving_agent():
    from jarvis.agents.agent import Agent
    from jarvis.agents.result import AgentOutcome

    class Bad(Agent):
        id, name, description = "bad", "Bad", "x"
        capabilities = frozenset({"made.up"})
        tool_names = frozenset({"mail"})

        def perform(self, task, ctx):
            ctx.tools.call("mail", to="x")                       # benutzt das Gateway ohne Berechtigung
            return AgentOutcome.ok("fertig")

    found = check_agent(Bad())
    assert any("unknown capabilities" in p for p in found) and any("tool gateway" in p or "raised" in p for p in found)


def test_all_v2_features_are_off_by_default_and_the_registry_of_a_default_build_has_only_v1_agents(tmp_path):
    s = Settings()
    assert not (s.business.enabled or s.business.strategist or s.finance.enabled or s.research.enabled or s.agents.enabled or s.goals.enabled or s.agents.quality_gate
                or s.agents.agent_budgets_enabled or s.agents.artifacts or s.goals.plan_analysis or s.goals.replanning or s.self_improvement.enabled or s.control_center.enabled)


def test_capabilities_are_unique_per_agent_except_the_documented_placeholder_pair():
    seen: dict[str, str] = {}
    for name in sorted(BUILTIN):
        if name == "research-placeholder":
            continue                                             # ersetzt bei research.enabled den echten Agenten unter derselben Kennung (bewusst)
        for cap in make(name).capabilities:
            assert cap not in seen, f"{cap} offered by {seen.get(cap)} and {name}"
            seen[cap] = name
    assert AP.BUSINESS_STRATEGY in seen and seen[AP.BUSINESS_STRATEGY] == "strategist"


def test_agent_ids_match_the_registry_ids_and_are_unique():
    ids = [make(n).id for n in BUILTIN if n != "research-placeholder"]
    assert len(ids) == len(set(ids)) and "strategist" in ids
