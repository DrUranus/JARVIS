"""AgentPlanner: which agent is *suitable* for a task? Rule based (keywords), deliberately small. It does not plan how a goal is
solved, it does not call an LLM and it grants nothing: the chosen agent still acts only through ToolRegistry + PermissionEngine."""
from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.agents import policy as P
from jarvis.agents.registry import AgentRegistry
from jarvis.agents.state import AgentStatus

# (pattern, weight); German and English. Matched case-insensitively against the objective.
_RULES: dict[str, tuple[tuple[str, int], ...]] = {
    "browser": ((r"https?://", 4), (r"\b(webseite|website|web-?seite|browser|url|link|homepage|google|seite öffnen|öffne (die )?seite|navigier\w*|formular|web page|webpage)\b", 3),
                (r"\b(öffne|open|besuche|visit)\b.*\b(\w+\.(com|de|org|net|io)|webseite|website|seite)\b", 3), (r"\b(suche|search)\b.*\b(google|im (internet|web)|online)\b", 3)),
    "coding": ((r"\b(code|quellcode|datei|dateien|file|files|funktion|function|klasse|class|modul|module|repository|repo|projekt|project|bug|fehler im code|refactor\w*|implementier\w*|unittest|pytest|tests?|testlauf|test suite|pull request|diff|commit|programm\w*)\b", 2),
               (r"\.(py|js|ts|java|c|cpp|go|rs|toml|json|md|txt)\b", 3), (r"\b(führe|run|starte)\b.*\btests?\b", 3), (r"\b(ändere|change|edit|schreibe|write|lösche|delete)\b.*\b(datei|file|code|funktion|function)\b", 3)),
    "computer": ((r"\b(klick\w*|click|tipp\w*|type|maus|mouse|tastatur|keyboard|screenshot|bildschirm\w*|screen|fenster|window|notepad|editor öffnen|taskleiste|desktop|cursor|programm starten|starte (das )?programm|drücke|press)\b", 3),
                 (r"\b(notepad|calc|rechner|paint|explorer)\b", 3)),
    "business": ((r"\b(marktanalyse|wettbewerbsanalyse|geschäftsmodell|businessplan|business plan|break-?even|konkurrenzanalyse|geschäftsdaten|marketingkonzept|zielgruppenanalyse|market analysis|competitor analysis|business model)\b", 4),),
    "finance": ((r"\b(finanzanalyse|aktienanalyse|unternehmensanalyse|kennzahlen\w*|bewertungskennzahlen|paper-?trad\w*|portfolio\w*|risikoanalyse|szenarioanalyse|financial analysis|stock analysis|company analysis|valuation)\b", 4),),
    "research": ((r"\b(recherchier\w*|research|finde heraus|find out|informiere dich|informationen (über|zu)|information about|quellen|sources|vergleiche|compare|zusammenfassung von|literatur)\b", 4),),
}
THRESHOLD = 3


@dataclass(frozen=True)
class Selection:
    agent_id: str | None
    capabilities: frozenset[str] = frozenset()
    score: int = 0
    reason: str = ""
    candidates: tuple[tuple[str, int], ...] = ()

    @property
    def found(self) -> bool:
        return self.agent_id is not None


def _capabilities(agent_id: str, text: str) -> frozenset[str]:
    t = text.lower()
    has = lambda pat: bool(re.search(pat, t))  # noqa: E731
    if agent_id == "browser":
        caps = {P.BROWSER_READ}
        if has(r"\b(klick\w*|click|fülle|fill|tippe|type|sende|submit|absenden|anmeld\w*|download\w*|lade\b.*\bherunter|upload|hochladen|suche|search|öffne|open|navigier\w*)\b"):
            caps.add(P.BROWSER_INTERACT)
        return frozenset(caps)
    if agent_id == "coding":
        caps = {P.CODING_READ}
        if has(r"\b(ändere|change|edit|schreibe|write|erstelle|create|lösche|delete|füge\b.*\bhinzu|implementier\w*|fix\w*|behebe|repar\w*|refactor\w*)\b"):
            caps.add(P.CODING_WRITE)
        if has(r"\b(tests?|testlauf|pytest|unittest|prüf\w*|check)\b"):
            caps.add(P.CODING_TEST)
        return frozenset(caps)
    if agent_id == "computer":
        caps = {P.COMPUTER_SCREEN}
        if has(r"\b(klick\w*|click|tipp\w*|type|maus|mouse|tastatur|keyboard|drücke|press|starte|start|öffne|open|fenster|window)\b"):
            caps.add(P.COMPUTER_INPUT)
        return frozenset(caps)
    if agent_id == "business":
        return frozenset({P.BUSINESS_ANALYZE})
    if agent_id == "finance":
        return frozenset({P.FINANCE_ANALYZE})
    return frozenset({P.RESEARCH_WEB})


class AgentPlanner:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def score(self, objective: str) -> dict[str, int]:
        scores: dict[str, int] = {}
        for agent_id, rules in _RULES.items():
            # every DISTINCT keyword of a rule counts (at most 3 per rule): "Browser ... Link ... Formular" outweighs a lone "klicke"
            total = sum(w * min(3, len({m.group(0).lower() for m in re.finditer(pat, objective, re.IGNORECASE)})) for pat, w in rules)
            if total:
                scores[agent_id] = total
        return scores

    def select(self, objective: str, required: frozenset[str] = frozenset()) -> Selection:
        """The best REGISTERED, not disabled/failed agent for the objective; `required` capabilities must all be offered."""
        if not isinstance(objective, str) or not objective.strip():
            return Selection(None, reason="empty objective")
        scores = self.score(objective)
        usable = {a.id: a for a in self._registry.list() if a.status in (AgentStatus.AVAILABLE, AgentStatus.BUSY)}
        ranked = sorted(((s, i) for i, s in scores.items() if i in usable and required <= usable[i].capabilities), reverse=True)
        cands = tuple((i, s) for s, i in ranked)
        if not ranked:
            if required and not scores:  # no keyword hit at all: fall back to pure capability matching
                by_cap = self._registry.find(required)
                if len(by_cap) == 1:
                    a = by_cap[0]
                    return Selection(a.id, required, 0, "matched by required capabilities", ((a.id, 0),))
            return Selection(None, reason="no suitable agent is available for this objective", candidates=cands)
        best_score, best = ranked[0]
        if best_score < THRESHOLD:
            return Selection(None, reason="the objective does not clearly name an agent's domain", candidates=cands)
        if len(ranked) > 1 and ranked[1][0] == best_score:
            return Selection(None, reason=f"ambiguous: {best} and {ranked[1][1]} fit equally well", candidates=cands)
        caps = _capabilities(best, objective) | required
        caps = frozenset(c for c in caps if c in usable[best].capabilities) | required
        return Selection(best, caps, best_score, f"keywords of the {best} domain", cands)
