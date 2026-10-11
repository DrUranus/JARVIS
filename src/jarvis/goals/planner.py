"""GoalPlanner: turns an objective into a short, validated sequence of steps - deterministically (templates), without an LLM and without
inventing capabilities. Agents are chosen ONLY by the existing AgentPlanner; the plan consists of structured tool steps for the existing
agents. An objective it cannot map to a template is not guessed at: the goal ends BLOCKED with the reason.

Templates (driven by what the user explicitly gave in the context or wrote in the objective):
  web page     url (context or objective)              -> research agent reads the page -> evaluate
  coding       workspace (+ optional edits/test)       -> analyse project [-> write edits] [-> run tests] -> evaluate [-> stop session]
  screen       screenshot / window list wording        -> computer agent (screen capability only) -> evaluate
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Protocol, Sequence

from jarvis.agents.planner import AgentPlanner
from jarvis.goals import policy as P
from jarvis.goals.context import GoalContext
from jarvis.goals.errors import PlanningError
from jarvis.goals.models import Goal, GoalStep
from jarvis.goals.state import StepStatus

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com|de|org|net|io|eu|ch|at|info|dev|app|co\.uk))\b(/[^\s<>\"']*)?", re.IGNORECASE)
_WRITE = re.compile(r"\b(fix\w*|behebe|repar\w*|ändere|ändern|change|edit|schreibe|write|erstelle|create|lösche|delete|implementier\w*|refactor\w*|füge)\b", re.IGNORECASE)
_TEST = re.compile(r"\b(tests?|testlauf|pytest|unittest|prüf\w*|teste)\b", re.IGNORECASE)
_SCREEN = re.compile(r"\b(screenshot|bildschirm\w*|fenster|windows?)\b", re.IGNORECASE)
_INPUT = re.compile(r"\b(klick\w*|click|tipp\w*|type|maus|mouse|tastatur|keyboard|drücke|press|öffne|open|starte|start)\b", re.IGNORECASE)
_RUNNERS = ("pytest", "python -m pytest", "python -m unittest", "npm test")
_EDIT_KEYS = frozenset({"path", "content", "mode", "old_text", "new_text", "expected_sha256"})
MAX_EDITS = 10
MAX_READS = 5


class Planner(Protocol):
    def plan(self, goal: Goal, ctx: GoalContext, max_steps: int) -> Sequence[GoalStep]: ...


# A replanner proposes candidate step specs after a failure: (goal, context, max_steps, feedback) -> list of spec dicts. It is untrusted: GoalPlanner.replan
# re-checks everything and chooses the agents itself.
Replanner = Callable[[Goal, GoalContext, int, Mapping[str, Any]], Sequence[Mapping[str, Any]]]


def find_url(objective: str, ctx: dict[str, Any]) -> str | None:
    u = ctx.get("url")
    if isinstance(u, str) and u.strip():
        return u.strip()
    m = _URL.search(objective)
    if m:
        return m.group(0).rstrip(".,;:!?)")
    d = _DOMAIN.search(objective)
    return "https://" + d.group(1) + ((d.group(2) or "").rstrip(".,;:!?)") or "/") if d else None


class GoalPlanner:
    def __init__(self, agent_planner: AgentPlanner | None, *, max_attempts: int = 2, step_timeout: float | None = None,
                 replanner: Replanner | None = None) -> None:
        self._agents = agent_planner
        self._replanner = replanner
        self._max_attempts, self._step_timeout = max(1, max_attempts), step_timeout

    # ---- public ------------------------------------------------------------------------------------------------------------------------
    def plan(self, goal: Goal, ctx: GoalContext, max_steps: int) -> tuple[GoalStep, ...]:
        if self._agents is None:
            raise PlanningError("no agent planner is available (the multi-agent layer is off)")
        user = dict(ctx.explicit_user_context)
        if user.get("template") is not None:               # an explicitly chosen analysis template wins over every heuristic
            specs = self._analysis(goal, user)
            steps = self._build(goal, specs)
            if len(steps) > max_steps:
                raise PlanningError(f"the plan needs {len(steps)} steps; the limit is {max_steps}")
            return steps
        objective = goal.objective
        matches = []
        url = find_url(objective, user)
        if url is not None:
            matches.append("web")
        if isinstance(user.get("workspace"), str) and user["workspace"].strip():
            matches.append("coding")
        if not matches and _SCREEN.search(objective) and "url" not in user:
            matches.append("screen")
        if not matches:
            raise PlanningError("no plan: the objective names no web page (url), no coding workspace and no screen question; "
                                "give a url or a workspace explicitly")
        if len(matches) > 1:
            raise PlanningError("the objective is ambiguous: it fits more than one kind of goal")
        kind = matches[0]
        specs = {"web": self._web, "coding": self._coding, "screen": self._screen}[kind](goal, objective, user, url)
        steps = self._build(goal, specs)
        if len(steps) > max_steps:
            raise PlanningError(f"the plan needs {len(steps)} steps; the limit is {max_steps}")
        return steps

    # ---- replanning (Phase 14) ---------------------------------------------------------------------------------------------------------------
    @property
    def supports_replanning(self) -> bool:
        return self._replanner is not None and self._agents is not None

    def replan(self, goal: Goal, ctx: GoalContext, max_steps: int, feedback: Mapping[str, Any]) -> tuple[GoalStep, ...]:
        """An alternative plan for the same goal. The replanner's candidate is DATA: this method checks keys, capabilities, dependencies, input rules and that
        outstanding work is still covered, picks every agent through the AgentPlanner and numbers the steps r<n>-s<i>. validate_plan (engine) comes after."""
        if not self.supports_replanning:
            raise PlanningError("replanning is not available")
        previous: tuple[GoalStep, ...] = tuple(feedback.get("previous_plan", ()))
        if not previous:
            raise PlanningError("there is no previous plan to replace")
        used = frozenset().union(*(s.required_capabilities for s in previous))
        allowed = used & self._agents.available_capabilities()                  # never more than the goal already used - and only what some agent can do now
        fb = dict(feedback)
        fb["allowed_capabilities"] = allowed
        raw = self._replanner(goal, ctx, max_steps, fb)
        specs = self._check_candidate(raw, previous, allowed, max_steps)
        return self._build(goal, specs, prefix=f"r{int(feedback.get('attempt', 1))}-s")

    def _check_candidate(self, raw: Sequence[Mapping[str, Any]], previous: tuple[GoalStep, ...], allowed: frozenset[str], max_steps: int) -> list[dict[str, Any]]:
        if not isinstance(raw, (list, tuple)) or not raw or len(raw) > max_steps:
            raise PlanningError(f"the candidate needs 1..{max_steps} steps")
        by_id = {s.step_id: s for s in previous}
        specs: list[dict[str, Any]] = []
        agent_idx: list[int] = []
        for i, item in enumerate(raw):
            if not isinstance(item, Mapping) or set(item) - P.REPLAN_KEYS:
                raise PlanningError(f"step {i}: only the keys {sorted(P.REPLAN_KEYS)} are accepted (agents, tools and permissions cannot be chosen)")
            after_raw = item.get("depends_on")
            if after_raw is None:
                after = [len(specs) - 1] if specs else []
            elif isinstance(after_raw, list) and all(isinstance(j, int) and not isinstance(j, bool) and 0 <= j < i for j in after_raw) and len(set(after_raw)) == len(after_raw):
                after = list(after_raw)
            else:
                raise PlanningError(f"step {i}: depends_on must list distinct indexes of EARLIER steps")
            if item.get("evaluate") is True:
                if i != len(raw) - 1 or set(item) - {"evaluate", "depends_on"}:
                    raise PlanningError("the evaluation step must be the last step and carries nothing else")
                specs.append({"evaluate": True, "after": after})
                continue
            if "evaluate" in item:
                raise PlanningError(f"step {i}: evaluate must be true")
            obj, caps = item.get("objective"), item.get("capabilities")
            if not isinstance(obj, str) or not 5 <= len(obj.strip()) <= 300 or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in obj):
                raise PlanningError(f"step {i}: objective must be 5..300 characters of plain text")
            if not isinstance(caps, list) or not caps or len(caps) > 4 or not all(isinstance(c, str) for c in caps):
                raise PlanningError(f"step {i}: capabilities must be a short list of names")
            capset = frozenset(caps)
            if not capset <= allowed:
                raise PlanningError(f"step {i}: capabilities outside the goal's own set are refused: {sorted(capset - allowed)[:3]}")
            src, own = item.get("input_from"), item.get("input")
            if (src is None) == (own is None):
                raise PlanningError(f"step {i}: give exactly one of input_from / input")
            if src is not None:
                origin = by_id.get(src) if isinstance(src, str) else None
                if origin is None or origin.is_evaluation or P.is_cleanup_input(origin.input):
                    raise PlanningError(f"step {i}: input_from must name an ordinary step of the previous plan")
                if not capset <= origin.required_capabilities:
                    raise PlanningError(f"step {i}: reused input needs capabilities within those of {src}")
                inp = {k: v for k, v in origin.input.items() if k != "cleanup"}
                inp_origin = origin.step_id
            else:
                research_only = capset == {"research.web"}
                if not (capset <= P.REPLAN_AUTHORABLE or research_only):
                    raise PlanningError(f"step {i}: input may only be written for {sorted(P.REPLAN_AUTHORABLE)} or research.web; reuse another step's input with input_from")
                if not isinstance(own, Mapping) or P.find_reserved(own):
                    raise PlanningError(f"step {i}: invalid input")
                if research_only:                                       # research may be re-arranged over the URLs the plan already had - never pointed somewhere new
                    urls = own.get("urls", [])
                    if set(own) - P.RESEARCH_INPUT_KEYS or own.get("kind") != "research_web" or not isinstance(urls, list) or not urls \
                            or not set(urls) <= P.known_urls([s.input for s in previous]):
                        raise PlanningError(f"step {i}: research input may only re-use URLs of the previous plan (keys: {sorted(P.RESEARCH_INPUT_KEYS)})")
                try:
                    P.check_plain(own, "input")
                except ValueError as exc:
                    raise PlanningError(f"step {i}: {exc}") from None
                inp, inp_origin = P.plain_copy(own), None
            specs.append({"objective": obj.strip(), "caps": capset, "input": inp, "after": after, "_origin": inp_origin})
            agent_idx.append(len(specs) - 1)
        if not agent_idx:
            raise PlanningError("the candidate contains no work step")
        if not specs[-1].get("evaluate"):                                    # the goal is still judged by an evaluation of the last result
            specs.append({"evaluate": True, "after": [agent_idx[-1]]})
        elif not specs[-1]["after"]:
            specs[-1]["after"] = [agent_idx[-1]]
        outstanding = frozenset().union(*(s.required_capabilities for s in previous if s.status is not StepStatus.SUCCEEDED and not s.is_evaluation
                                          and not P.is_cleanup_input(s.input)), frozenset())
        covered = frozenset().union(*(specs[i]["caps"] for i in agent_idx))
        if not outstanding <= covered:
            raise PlanningError(f"the candidate drops outstanding work: {sorted(outstanding - covered)[:3]} is no longer covered")
        # a session opened by a reused step is closed again, exactly as the previous plan did
        for c in previous:
            if P.is_cleanup_input(c.input):
                for i in agent_idx:
                    if specs[i].get("_origin") == c.input["cleanup"]:
                        specs.append({"objective": c.objective, "caps": set(c.required_capabilities),
                                      "input": {k: v for k, v in c.input.items() if k != "cleanup"}, "cleanup_of": i})
                        break
        for sp in specs:
            sp.pop("_origin", None)
        return specs

    # ---- templates: lists of (objective, caps, input, depends_on_previous_work) ---------------------------------------------------------
    def _web(self, goal: Goal, objective: str, user: dict[str, Any], url: str | None) -> list[dict[str, Any]]:
        if not P.valid_url(url):
            raise PlanningError("the url must be an http(s) address")
        return [
            {"objective": "Recherchiere und lese die Webseite " + url[:200] + " (Browser)", "caps": {"research.web"}, "input": {"url": url}},
            {"evaluate": True},
        ]

    def _coding(self, goal: Goal, objective: str, user: dict[str, Any], url: str | None) -> list[dict[str, Any]]:
        ws = str(user["workspace"]).strip()
        edits = user.get("edits")
        if edits is not None and (not isinstance(edits, list) or not edits or len(edits) > MAX_EDITS or not all(
                isinstance(e, dict) and isinstance(e.get("path"), str) and set(e) <= _EDIT_KEYS for e in edits)):
            raise PlanningError(f"edits must be a list of 1..{MAX_EDITS} objects with path/content/mode/old_text/new_text")
        if _WRITE.search(goal.objective) and not edits:
            raise PlanningError("changing code needs explicit edits in the context: this version does not write code on its own")
        reads = user.get("read_paths") or []
        if not isinstance(reads, list) or len(reads) > MAX_READS or not all(isinstance(r, str) and r for r in reads):
            raise PlanningError(f"read_paths must be a list of up to {MAX_READS} relative paths")
        runner = user.get("runner")
        if runner is not None and runner not in _RUNNERS:
            raise PlanningError(f"unknown test runner; known: {', '.join(_RUNNERS)}")
        want_test = bool(_TEST.search(goal.objective)) or bool(edits) or runner is not None
        first = [{"action": "start", "workspace": ws}, {"action": "info"}] + [{"action": "read", "path": r} for r in reads]
        specs: list[dict[str, Any]] = [{"objective": "Analysiere das Projekt im Workspace (Code, Dateien, Projekt)", "caps": {"coding.read"},
                                        "input": {"steps": first}}]
        if edits:
            specs.append({"objective": "Ändere die Dateien im Projekt (Code schreiben, Datei)", "caps": {"coding.write"},
                          "input": {"steps": [{"action": "write", **e} for e in edits]}, "after": [0]})
        if want_test:
            t: dict[str, Any] = {"action": "test"}
            if runner:
                t["runner"] = runner
            if user.get("test_args"):
                t["args"] = str(user["test_args"])
            specs.append({"objective": "Führe die Tests des Projekts aus (Code, Tests, pytest)", "caps": {"coding.test"}, "input": {"steps": [t]},
                          "after": [len(specs) - 1]})
        specs.append({"evaluate": True, "after": [len(specs) - 1]})
        specs.append({"objective": "Beende die Projekt-Sitzung (Code, Projekt)", "caps": {"coding.read"}, "input": {"steps": [{"action": "stop"}]},
                      "cleanup_of": 0})
        return specs

    def _screen(self, goal: Goal, objective: str, user: dict[str, Any], url: str | None) -> list[dict[str, Any]]:
        if _INPUT.search(goal.objective):
            raise PlanningError("goals that operate mouse, keyboard or programs are not planned automatically in this version")
        action = "screenshot" if re.search(r"screenshot", goal.objective, re.IGNORECASE) else "windows"
        return [{"objective": "Schaue auf den Bildschirm: Fenster und Screenshot (Computer)", "caps": {"computer.screen"},
                 "input": {"steps": [{"tool": "screen", "action": action}]}}, {"evaluate": True}]

    # ---- analysis templates (Phase 10): research -> business -> finance chains; data comes only from the explicit context --------------------------------
    _BUSINESS_OBJECTIVE = {"market_analysis": "Erstelle die Marktanalyse (Geschäftsmodell, Wettbewerber, Preise)",
                           "competitor_analysis": "Erstelle die Wettbewerbsanalyse (Konkurrenzanalyse, Positionierung)",
                           "business_analysis": "Analysiere die Geschäftsdaten (Schwachstellen, Marge)",
                           "business_plan": "Erstelle den Businessplan (Geschäftsmodell, Break-even, Szenarien)"}
    _FINANCE_OBJECTIVE = {"financial_analysis": "Erstelle die Finanzanalyse (Kennzahlen, Bewertungskennzahlen)",
                          "company_analysis": "Erstelle die Unternehmensanalyse (Kennzahlen, Vergleich)",
                          "paper_trade_analysis": "Analysiere die Paper-Trading Szenarien (Risikoanalyse, Portfolio)"}
    _DEFAULT_FINANCE_KIND = {"financial_analysis": "financial_analysis", "company_analysis": "company_analysis", "paper_trade_analysis": "paper_trade_analysis"}
    _NEEDS = {"business_analysis": ("business", "rows"), "business_plan": ("business", "plan"), "financial_analysis": ("finance", "company"),
              "company_analysis": ("finance", "companies"), "paper_trade_analysis": ("finance", "ideas")}

    def _analysis(self, goal: Goal, user: dict[str, Any]) -> list[dict[str, Any]]:
        t = user.get("template")
        if not isinstance(t, str) or t not in P.ANALYSIS_TEMPLATES:
            raise PlanningError(f"unknown template; known: {', '.join(P.ANALYSIS_TEMPLATES)}")
        blocks: dict[str, dict[str, Any]] = {}
        for key in ("research", "business", "finance"):
            v = user.get(key)
            if v is not None and (not isinstance(v, dict) or len(v) > 30):
                raise PlanningError(f"{key} must be an object with up to 30 entries")
            blocks[key] = dict(v or {})
        need = self._NEEDS.get(t)
        if need and not blocks[need[0]].get(need[1]):
            raise PlanningError(f"the template {t} needs {need[0]}.{need[1]} in the context (no data is invented)")
        has_research = bool(blocks["research"].get("urls"))
        if t in ("research_web", "market_analysis", "competitor_analysis") and not has_research:
            raise PlanningError(f"the template {t} needs research.urls in the context (this version reads the pages it is given)")
        specs: list[dict[str, Any]] = []
        if has_research:
            specs.append({"objective": "Recherchiere die Quellen und Informationen (Recherche, Quellen)", "caps": {"research.web"},
                          "input": {"kind": "research_web", **blocks["research"]}})
        last = len(specs) - 1
        if t in self._BUSINESS_OBJECTIVE:
            specs.append({"objective": self._BUSINESS_OBJECTIVE[t], "caps": {"business.analyze"}, "input": {"kind": t, **blocks["business"]}, "after": [last] if last >= 0 else []})
            last = len(specs) - 1
        fin = blocks["finance"]
        if t in self._FINANCE_OBJECTIVE or (t in ("business_plan", "market_analysis") and fin.get("kind")):
            kind = str(fin.get("kind") or self._DEFAULT_FINANCE_KIND.get(t, ""))
            specs.append({"objective": self._FINANCE_OBJECTIVE.get(t, "Erstelle die Finanzanalyse (Szenarioanalyse, Kennzahlen)"), "caps": {"finance.analyze"},
                          "input": {**{k: v for k, v in fin.items() if k != "kind"}, "kind": kind}, "after": [last] if last >= 0 else []})
        specs.append({"evaluate": True, "after": [len(specs) - 1]})
        return specs

    # ---- assembling --------------------------------------------------------------------------------------------------------------------
    def _build(self, goal: Goal, specs: list[dict[str, Any]], prefix: str = "s") -> tuple[GoalStep, ...]:
        ids = [f"{prefix}{i + 1}" for i in range(len(specs))]
        steps: list[GoalStep] = []
        for i, spec in enumerate(specs):
            after = spec.get("after", [i - 1] if i > 0 else [])
            if "cleanup_of" in spec:
                after = [j for j in range(i) if "cleanup_of" not in specs[j]]
            deps = tuple(ids[j] for j in after)
            if spec.get("evaluate"):
                steps.append(GoalStep(ids[i], goal.goal_id, "Ergebnis prüfen: wurde das Ziel erreicht?", frozenset(), None, deps,
                                      max_attempts=1, input={P.EVALUATE: True}))
                continue
            caps = frozenset(spec["caps"])
            sel = self._agents.select(spec["objective"], caps) if self._agents else None
            if sel is None or not sel.found:
                raise PlanningError(f"no agent can do step {ids[i]}: {sel.reason if sel else 'no planner'}")
            inp = dict(spec["input"])
            if "cleanup_of" in spec:
                inp["cleanup"] = ids[spec["cleanup_of"]]
            steps.append(GoalStep(ids[i], goal.goal_id, spec["objective"], caps, sel.agent_id, deps, max_attempts=self._max_attempts,
                                  timeout=self._step_timeout, input=inp))
        return tuple(steps)
