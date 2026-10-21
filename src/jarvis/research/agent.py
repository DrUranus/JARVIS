"""ResearchAgent: reads the public web pages it is given (and, if asked, relevant links of the same site) through the permission-checked
browser tool, extracts passages and figures, cross-checks the sources and returns a structured, SOURCED result.

Workflow: request -> plan -> source selection (URL policy) -> retrieval (browser tool via ToolGateway) -> extraction -> cross-check -> synthesis -> result.
It has exactly one tool (`browser`), uses only read-style actions after goto, never fills or clicks, and every navigation is still judged by the
browser controller and the permission engine. What cannot be read is reported as `unavailable`; nothing is invented, nothing is claimed to be current
beyond the retrieval time stored with each source."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from jarvis.agents import policy as AP
from jarvis.agents.agent import Agent
from jarvis.agents.context import AgentContext
from jarvis.agents.errors import TaskCancelled, ToolAccessError
from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentOutcome
from jarvis.redaction import SecretDetector
from jarvis.research import analysis as A
from jarvis.research import extract as X
from jarvis.research.errors import InvalidResearchRequest
from jarvis.research.models import (Claim, ClaimKind, Figure, ResearchLimits, ResearchPlan, ResearchResult, Source, SourceStatus, build_plan, clip)
from jarvis.research.urls import ResearchUrlPolicy

MAX_PASSAGES = 6
MAX_LINKS = 20


class ResearchAgent(Agent):
    id = "research"
    name = "Research Agent"
    description = ("Reads the given public web pages through the browser tool, extracts passages and figures, cross-checks the sources and returns a sourced, "
                   "structured result (FACT / INFERENCE / OPINION / UNCERTAIN; conflicts and unavailable sources are shown). No search engine, no interaction.")
    capabilities = frozenset({AP.RESEARCH_WEB})
    tool_names = frozenset({"browser"})

    def __init__(self, limits: ResearchLimits | None = None, *, private_hosts_allowed: tuple[str, ...] = (), monotonic: Callable[[], float] = time.monotonic,
                 detector: SecretDetector | None = None) -> None:
        super().__init__()
        self.limits = limits or ResearchLimits()
        self._private_ok = tuple(private_hosts_allowed)
        self._mono = monotonic
        self._detector = detector or SecretDetector.from_environment()

    # ---- entry ------------------------------------------------------------------------------------------------------------------------
    def perform(self, task: AgentTask, ctx: AgentContext) -> AgentOutcome:
        if AP.RESEARCH_WEB not in ctx.allowed_capabilities:
            return AgentOutcome.blocked("this task does not allow the capability research.web", code="capability_not_allowed")
        data = dict(task.input)
        if "url" in data and "urls" not in data:                      # the Phase-8 single-page form
            data["urls"] = [data.pop("url")]
        data.pop("kind", None)
        try:
            plan = build_plan(task.objective, data, self.limits)
        except InvalidResearchRequest as exc:
            return AgentOutcome.failed(str(exc), code="invalid_input")
        gw = ctx.tools
        if gw is None or not gw.available("browser"):
            return AgentOutcome.failed("the browser tool is not available (enable browser.enabled)", code="tool_unavailable")
        run = _Run(self, plan, ctx, gw)
        try:
            return run.read_all()
        except TaskCancelled:
            return AgentOutcome.cancelled()
        except ToolAccessError as exc:
            return AgentOutcome.failed(str(exc), code="tool_access_denied")
        finally:
            run.cleanup()


class _Denied(Exception):
    """A navigation or tool call was refused by the permission system."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step, self.message = step, message


class _Run:
    def __init__(self, agent: ResearchAgent, plan: ResearchPlan, ctx: AgentContext, gw: Any) -> None:
        self.a, self.plan, self.ctx, self.gw = agent, plan, ctx, gw
        self.policy = ResearchUrlPolicy(plan.allowed_domains, plan.excluded_domains, agent._private_ok)
        self.deadline = agent._mono() + plan.timeout
        self.actions = 0
        self.started_here = False
        self.sources: list[Source] = []
        self.per_source: dict[str, list[str]] = {}
        self.figs: list[Figure] = []
        self.kws = X.keywords([plan.objective, *plan.questions])

    # ---- tool access --------------------------------------------------------------------------------------------------------------------
    def _call(self, step: str, **kw: Any) -> Any:
        if self.actions >= self.plan.max_actions:
            raise _OutOfBudget()
        self.actions += 1
        res = self.gw.call("browser", **kw)
        if res.success:
            return res.output if isinstance(res.output, dict) else {}
        denied = getattr(res.permission, "status", None) is not None and not getattr(res.permission, "allowed", True)
        msg = clip(str(res.error or "failed"), 200)
        if denied:
            raise _Denied(step, msg)
        raise _Failed(msg)

    def _timed_out(self) -> bool:
        return self.a._mono() >= self.deadline

    # ---- workflow -----------------------------------------------------------------------------------------------------------------------
    def read_all(self) -> AgentOutcome:
        queue = self._select_sources()
        if not queue:
            return self._finish(note="no readable source")
        try:
            status = self._call("status", action="status")
            if not status.get("running"):
                self._call("start", action="start")
                self.started_here = True
            read = 0
            while queue and read < self.plan.max_sources:
                if self.ctx.is_cancelled():
                    raise TaskCancelled("cancelled")
                if self._timed_out():
                    self._skip_rest(queue, "research timeout reached")
                    break
                url = queue.pop(0)
                try:
                    page = self._retrieve(url)
                except _OutOfBudget:
                    self.sources.append(Source(url, status=SourceStatus.SKIPPED, note="action budget used up"))
                    self._skip_rest(queue, "action budget used up")
                    break
                except _Failed as exc:
                    self.sources.append(Source(url, source=urlsplit(url).hostname or "", status=SourceStatus.UNAVAILABLE, note=str(exc)))
                    read += 1
                    continue
                read += 1
                if page and self.plan.follow_links and read < self.plan.max_sources:
                    for link in self._links(url):
                        if link not in queue and link not in {s.url for s in self.sources} and len(queue) + read < self.plan.max_sources:
                            queue.append(link)
            self._skip_rest(queue, "over max_sources")
        except _Denied as exc:
            return AgentOutcome.blocked(f"{exc.step}: {exc.message}", code="permission_denied", output=self._result("blocked by the permission system").to_dict(self.a.limits.max_result_chars))
        except _OutOfBudget:
            self._skip_rest(queue, "action budget used up")
        except _Failed as exc:
            return AgentOutcome.failed(f"the browser could not be used: {exc}", code="step_failed")
        return self._finish()

    def _select_sources(self) -> list[str]:
        seen: set[str] = set()
        queue: list[str] = []
        for raw in self.plan.urls:
            d = self.policy.check(raw)
            if not d.ok:
                self.sources.append(Source(clip(str(raw), 200) if not d.host else clip(str(raw).split("?")[0], 200), source=d.host, status=SourceStatus.BLOCKED, note=d.reason))
                continue
            if d.key in seen:
                continue
            seen.add(d.key)
            queue.append(d.url)
        return queue

    def _skip_rest(self, queue: list[str], why: str) -> None:
        while queue:
            self.sources.append(Source(queue.pop(0), status=SourceStatus.SKIPPED, note=why))

    def _retrieve(self, url: str) -> bool:
        self._call("goto", action="goto", url=url)
        page = self._call("text", action="text")
        final = self.policy.check(str(page.get("url") or url))
        host = urlsplit(url).hostname or ""
        if not final.ok:                                           # a redirect led somewhere this layer refuses: discard what was read
            self.sources.append(Source(url, source=host, status=SourceStatus.BLOCKED, note="redirected to a refused address: " + final.reason))
            return False
        text = self.a._detector.redact(str(page.get("text") or ""))[: self.a.limits.max_page_chars]
        if not text.strip():
            self.sources.append(Source(url, source=host, status=SourceStatus.UNAVAILABLE, note="the page has no readable text"))
            return False
        shown_url = final.url or url
        psg = X.passages(text, self.kws, MAX_PASSAGES)
        self.per_source[shown_url] = psg
        self.figs.extend(X.figures(text, shown_url))
        self.sources.append(Source(shown_url, clip(self.a._detector.redact(str(page.get("title") or "")), 200), final.host or host,
                                   datetime.now(timezone.utc).isoformat(timespec="seconds"), X.relevance(text, self.kws), SourceStatus.OK,
                                   "text was truncated by the browser tool" if page.get("truncated") else "", psg[0] if psg else clip(text, 300)))
        return True

    def _links(self, page_url: str) -> list[str]:
        try:
            out = self._call("links", action="links", limit=MAX_LINKS)
        except (_Failed, _OutOfBudget):
            return []
        base = urlsplit(page_url).hostname or ""
        found: list[str] = []
        for link in out.get("links", []):
            href, name = str(link.get("href", "")), str(link.get("name", ""))
            if not href or not any(k in name.lower() or k in href.lower() for k in self.kws):
                continue
            d = self.policy.check(href.split("?")[0].split("…")[0])      # hrefs come masked (no query values): follow the path only
            if d.ok and (d.host == base or d.host.endswith("." + base) or base.endswith("." + d.host)):
                found.append(d.url)
        return list(dict.fromkeys(found))

    # ---- result -------------------------------------------------------------------------------------------------------------------------------
    def _result(self, note: str = "") -> ResearchResult:
        conflicts = A.crosscheck(self.figs)
        claims = A.build_claims(self.per_source, conflicts)
        claims += A.price_inferences(self.figs, conflicts)
        unc = A.uncertainties(self.sources, claims, conflicts)
        if note:
            unc.insert(0, note)
        sources = tuple(sorted(self.sources, key=lambda s: (s.status is not SourceStatus.OK, -s.relevance)))
        return ResearchResult(self.plan.objective, A.summarize(self.plan.objective, self.sources, claims, conflicts), sources, tuple(claims), tuple(self.figs[:200]),
                              tuple(conflicts), tuple(unc), self.actions, False, self.plan)

    def _finish(self, note: str = "") -> AgentOutcome:
        result = self._result(note)
        out = result.to_dict(self.a.limits.max_result_chars)
        if not any(s.status is SourceStatus.OK for s in result.sources):
            return AgentOutcome.failed("no source could be read: " + result.summary, code="no_sources_available", output=out)
        return AgentOutcome.ok(result.summary, out)

    def cleanup(self) -> None:
        if self.started_here and not self.ctx.is_cancelled():
            try:
                self.gw.call("browser", action="stop")
            except Exception:  # noqa: BLE001 - tidy-up is best effort; the permission engine may still ask
                pass


class _Failed(Exception):
    pass


class _OutOfBudget(Exception):
    pass
