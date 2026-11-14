"""StrategistAgent (V2.1, Mission 2): the Business Strategist as a SEPARATE agent around the pure core `jarvis.business.strategist`.

* id `strategist`, capability `business.strategy`; registered only when `business.strategist = true` (OFF by default) and the multi-agent layer is on.
* NO tools (`tool_names` is empty): it computes and drafts, it cannot read the web, write a file or contact anybody. Research enters only as a finished parent result
  (same hand-over as the BusinessAgent); starting research stays a separate, approved step. Outreach, registration, offers, payments ... are refused before anything is
  computed. Permissions, budgets, timeouts and the emergency stop are the orchestrator's: nothing here duplicates them.
* All numbers come from `business.calc` through the core (no second calculation engine); every number carries its basis (FACT / GIVEN / INFERENCE / ESTIMATE / UNKNOWN).
* The result is typed plain data (`kind = strategist_result`, `task`, `result`, `sources`, `note`). Typed hand-over ARTIFACTS (E5) are deliberately not produced yet: the E5 guard
  tests allow only the orchestrator and the research hand-over to touch that module; widening that list is an owner decision (docs/V21_ARCHITEKTUR.md)."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping

from jarvis.agents import policy as AP
from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext
from jarvis.agents.errors import TaskCancelled
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentOutcome
from jarvis.business import strategist as S
from jarvis.business.agent import EXTERNAL_KINDS, BusinessAgent
from jarvis.business.errors import InvalidBusinessInput
from jarvis.business.models import clip
from jarvis.redaction import SecretDetector
from jarvis.research.handoff import collect

KINDS = ("discover", "research_brief", "audit", "financial_model", "rank", "explain", "blueprint")
_EXTERNAL = EXTERNAL_KINDS | {"register", "register_business", "book", "sign", "apply", "invoice", "buy", "hire", "sell"}
_EXTERNAL_WORDS = ("send", "mail", "outreach", "contract", "payment", "purchase", "publish", "offer", "contact", "register", "invoice")
NOTE = "analysis and drafts only: nothing was sent, ordered, registered or published; every step is a proposal for the owner"


class StrategistAgent(Agent):
    id = "strategist"
    name = "Business Strategist"
    description = ("Business idea hypotheses matched to the owner's profile, research briefs, financial model with scenarios and sensitivity, explained ranking and a "
                   "30/90-day blueprint. Every number is labelled; UNKNOWN when data is missing. Drafts and analyses only - sends and orders nothing.")
    capabilities = frozenset({AP.BUSINESS_STRATEGY})
    tool_names = frozenset()

    def __init__(self, *, max_steps: int = 20, timeout: float = 120.0, max_result_chars: int = 20_000,
                 monotonic: Callable[[], float] = time.monotonic, detector: SecretDetector | None = None) -> None:
        super().__init__()
        self.max_steps, self.timeout, self.max_result_chars = max_steps, timeout, max_result_chars
        self._mono = monotonic
        self._detector = detector or SecretDetector.from_environment()

    # ---- perform ---------------------------------------------------------------------------------------------------------------------
    def perform(self, task: AgentTask, ctx: AgentContext) -> AgentOutcome:
        if AP.BUSINESS_STRATEGY not in ctx.allowed_capabilities:
            return AgentOutcome.blocked("this task does not allow the capability business.strategy", code="capability_not_allowed")
        data = dict(task.input)
        kind = str(data.get("kind", "")).lower().strip()
        if kind in _EXTERNAL or any(w in kind for w in _EXTERNAL_WORDS):
            return AgentOutcome.blocked("this agent sends nothing and contacts nobody: outreach, offers, registrations and payments need a separate, permission-checked "
                                        "action and your explicit confirmation", code="external_action_not_supported")
        if kind not in KINDS:
            return AgentOutcome.failed(f"unknown strategist task kind {kind[:30]!r}; known: {', '.join(KINDS)}", code="invalid_input")
        deadline = self._mono() + self.timeout
        try:
            ctx.check_cancelled()
            research = collect(ctx.parent_results, data.get("research"))
            payload, summary = getattr(self, "_" + kind)(data)
            ctx.check_cancelled()
        except TaskCancelled:
            return AgentOutcome.cancelled()
        except InvalidBusinessInput as exc:
            return AgentOutcome.failed(str(exc), code="invalid_input")
        if self._mono() > deadline:
            return AgentOutcome.failed("the strategist task exceeded its time limit", code="timeout")
        out: dict[str, Any] = {"kind": "strategist_result", "task": kind, "result": payload, "sources": list(BusinessAgent._sources(research)), "note": NOTE}
        out = self._fit(out)
        summary = clip(self._detector.redact(summary), 400)
        return AgentOutcome.ok(summary, out)

    # ---- the kinds: each returns (payload, summary) -----------------------------------------------------------------------------------
    def _list(self, value: Any, what: str) -> list[Any]:
        if not isinstance(value, (list, tuple)) or len(value) > self.max_steps:
            raise InvalidBusinessInput(f"{what} is a list of at most {self.max_steps} entries")
        return list(value)

    def _discover(self, data: Mapping[str, Any]) -> tuple[Any, str]:
        found = S.discover(data.get("profile"), data.get("limit", 5))
        return found, f"{len(found)} idea hypothesis(es) from the profile - no market figures, research questions first"

    def _research_brief(self, data: Mapping[str, Any]) -> tuple[Any, str]:
        brief = S.research_brief(data.get("archetype"), data.get("region"))
        return brief, f"research brief for {brief['title']} (draft, needs your approval)"

    def _audit(self, data: Mapping[str, Any]) -> tuple[Any, str]:
        problems = S.audit_statements(self._list(data.get("statements"), "statements"))
        return problems, f"{len(problems)} statement(s) without a source or an assumption label"

    def _financial_model(self, data: Mapping[str, Any]) -> tuple[Any, str]:
        model = S.financial_model(data.get("model"))
        return model, f"financial model, basis {model['basis']}; {len(model['missing'])} input(s) UNKNOWN"

    def _rank(self, data: Mapping[str, Any]) -> tuple[Any, str]:
        ranking = S.rank(self._list(data.get("items"), "items"), data.get("weights"))
        top = ranking["ranking"][0]
        return ranking, f"ranking of {len(ranking['ranking'])} idea(s); first: {top['name']}" + ("" if top["score"] is not None else " (no overall score: too little evidence)")

    def _explain(self, data: Mapping[str, Any]) -> tuple[Any, str]:
        text = S.explain(data.get("a"), data.get("b"), data.get("weights"))
        return text, text

    def _blueprint(self, data: Mapping[str, Any]) -> tuple[Any, str]:
        model = data.get("model")
        if model is None and "model_input" in data:
            model = S.financial_model(data.get("model_input"))          # computed here, from the given inputs only
        steps = self._list(data.get("next_steps") or [], "next_steps")
        bp = S.blueprint(data.get("name"), model, data.get("archetype"), steps)
        return bp, f"30/90-day blueprint for {bp['name']}: {len(bp['days_30'])} + {len(bp['days_90'])} proposed step(s), none executed"

    # ---- output size -----------------------------------------------------------------------------------------------------
    def _fit(self, out: dict[str, Any]) -> dict[str, Any]:
        """Keeps the stored result within `max_result_chars`: lists lose their tail, anything else is replaced by an honest marker. Never silent: `truncated` is set."""
        def size() -> int:
            return len(json.dumps(out, ensure_ascii=False))
        if size() <= self.max_result_chars:
            return out
        res = out["result"]
        out = dict(out, truncated=True)
        if isinstance(res, list):
            while res and len(json.dumps(dict(out, result=res), ensure_ascii=False)) > self.max_result_chars:
                res = res[: len(res) // 2]
            out["result"] = res
        elif isinstance(res, dict) and "ranking" in res and len(json.dumps(dict(out, result={"ranking": res["ranking"][:1]}), ensure_ascii=False)) <= self.max_result_chars:
            out["result"] = {"ranking": res["ranking"][:1], "truncated_to": 1}
        else:
            out["result"] = {"truncated": True, "keys": sorted(res)[:20] if isinstance(res, dict) else []}
        if len(json.dumps(out, ensure_ascii=False)) > self.max_result_chars:
            out["sources"] = []
        return out
