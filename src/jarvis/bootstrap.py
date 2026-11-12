"""Composition root: the only place that wires concrete implementations together."""
from __future__ import annotations

import sys
from typing import Any, Callable

from jarvis.config import Settings
from jarvis.core import JarvisCore
from jarvis.llm.factory import create_provider
from jarvis.memory.factory import create_memory
from jarvis.memory.guard import SecretGuard
from jarvis.logging_setup import setup_logging
from jarvis.permissions.factory import build_permission_engine
from jarvis.tools.builtin import register_builtin_tools
from jarvis.tools.registry import ToolRegistry


def build_core(settings: Settings) -> JarvisCore:
    setup_logging(settings.effective_log_level, settings.log_dir)
    provider = create_provider(settings.llm)
    # Secrets of this very configuration (and secret-looking env vars) can never be stored as memories,
    # and are redacted from every permission message, prompt, audit event and tool error.
    guard = SecretGuard.from_environment(extra=[settings.llm.api_key, settings.voice.api_key])
    # Every tool call goes through this engine (strict: restrictive defaults, fail closed). A broken policy
    # file raises PolicyError here: JARVIS refuses to start rather than run with an unintended policy.
    permissions = build_permission_engine(settings, redactor=guard)
    tools = register_builtin_tools(ToolRegistry(permissions), include_demo=not settings.is_production)
    memory = create_memory(settings.memory, guard)
    core = JarvisCore(provider=provider, tools=tools, memory=memory, memory_limit=settings.memory.max_relevant,
                      use_memory_in_prompts=settings.memory.use_in_prompts)
    # Computer control is opt-in and optional: when disabled or unusable the subsystem only carries the reason
    # and JARVIS starts normally. Its tools are ordinary ProtectedTools in the registry above.
    from jarvis.computer.factory import build_computer
    core.subsystems["computer"] = build_computer(settings, tools, permissions)
    # The browser agent is a separate, equally opt-in subsystem with its own controller; it never drives mouse/keyboard.
    from jarvis.browser.factory import build_browser
    core.subsystems["browser"] = build_browser(settings, tools, permissions)
    # The coding agent is a third, equally opt-in subsystem with its own controller. It reuses the Core's LLM abstraction (only for
    # the explicit, confirmed `plan` action) and never drives the browser or the PC.
    from jarvis.coding.factory import build_coding, register_provider
    if sys.platform == "win32":
        # Windows: the local provider ends the whole process tree (timeout / flood / halt) through the existing Job Object module instead of only the root process.
        from jarvis.coding.providers.local import LocalProvider
        from jarvis.self_improvement import winjob
        register_provider("local", lambda _s: LocalProvider(job_factory=winjob.attach, resume=winjob.resume))
    core.subsystems["coding"] = build_coding(settings, tools, permissions, llm=provider)
    # The file tools are a fourth, equally opt-in subsystem (files.enabled = false by default): one ProtectedTool, only inside confirmed roots, no delete.
    from jarvis.files.factory import build_files
    core.subsystems["files"] = build_files(settings, tools, permissions)
    # Office files (office-docs, O1) are a fifth, equally opt-in subsystem (office.enabled = false by default): read and create NEW .xlsx/.docx inside confirmed roots,
    # never macros, never overwriting. The libraries come from the optional extra `office` and are imported lazily.
    from jarvis.office.factory import build_office
    core.subsystems["office"] = build_office(settings, tools, permissions, baseline_rules=office_baseline_rules())
    # Multi-agent orchestration sits ABOVE those subsystems: agents only use their tools through the registry (and so the permission engine).
    from jarvis.agents.factory import build_agents
    core.subsystems["agents"] = build_agents(settings, tools, memory, core.tasks, core.subsystems, budget_audit=agent_budget_audit(permissions.audit))
    # Assistant (assistant-e2e, off by default): the agent router decides per goal step. It only SELECTS (rules; no LLM call); decisions become `routing`
    # events and audit entries. Without assistant.enabled and agents.router.enabled the goal layer uses the AgentPlanner exactly as before.
    from jarvis.interface.assistant import RoutingSink
    routing_sink = RoutingSink()
    goal_agents = _routed_agents(settings, core.subsystems["agents"], routing_sink, permissions.audit)
    # The goal engine sits above the agent layer and talks to it only through the orchestrator.
    from jarvis.goals.factory import build_goals
    core.subsystems["goals"] = build_goals(settings, goal_agents, provider)
    # Research / Business / Finance are agents of that layer; these objects only describe them (status) and add small GREEN calculation tools for /run.
    from jarvis.agents.groups import build_analysis_subsystems
    from jarvis.tools.analysis import register_analysis_tools
    core.subsystems.update(build_analysis_subsystems(settings, core.subsystems["agents"]))
    register_analysis_tools(tools, core.subsystems, tuple(settings.browser.private_hosts_allowed))
    # Opt-in web search source (Brave, OFF by default, key only from the environment): refuses on emergency stop and on an exhausted session budget.
    from jarvis.agents.factory import build_research_search
    core.subsystems["research_search"] = build_research_search(settings, budget_check=recording_guard(core))
    # Self-repair also sits above the agent layer: its only way to act is a Coding-Agent task through the orchestrator.
    from jarvis.self_repair.factory import build_self_repair
    core.subsystems["self_repair"] = build_self_repair(settings, core.subsystems["agents"], core.subsystems.get("coding"))
    # Self-improvement (Phase 15) is a DISABLED PROPOSAL WORKFLOW: it reads what the goal/repair engines and the audit log recorded and keeps proposals. It never
    # prepares, tests, merges or activates code (the factory builds no workspace and a locked ExecutionGuard). The Core does not import it.
    from jarvis.self_improvement.factory import build_self_improvement
    core.subsystems["self_improvement"] = build_self_improvement(
        settings, goals=getattr(core.subsystems.get("goals"), "engine", None), repairs=getattr(core.subsystems.get("self_repair"), "engine", None),
        audit=permissions.audit, llm=provider, confirmation=lambda: permissions.confirmation, detector=guard)
    # Opt-in history of FINISHED work (default off, no file). Display only: after a restart nothing is resumed or started.
    from jarvis.history.factory import build_history
    core.history = build_history(settings, core, guard)
    # LLM routing policy (docs/LLM_ROUTING.md): a decision helper only, OFF by default. It calls no provider and changes no existing call path;
    # every decision is an `llm_route` audit event.
    from jarvis.llm.routing import LLMRouter
    core.subsystems["llm_routing"] = LLMRouter(settings.llm_routing, default_provider=settings.llm.provider, audit=routing_audit(permissions.audit))
    # Assistant (assistant-e2e): journal + UI-contract adapter around the existing layers; nothing starts by itself. Questions of the permission engine then
    # run through the contract (`confirmation_request`); unanswered, timed out, detached, emergency or failing means DENIED.
    from jarvis.interface.assistant import build_assistant
    from jarvis.interface.ui_events import ControllerUiBackend
    from jarvis.journal.factory import build_journal
    from jarvis.permissions.confirmation import ConfirmationChoice
    assistant_on = settings.assistant.enabled
    ui_factory = lambda ctl: ControllerUiBackend(ctl, choice_enum=ConfirmationChoice, name="jarvis",  # noqa: E731
                                                 confirmation_timeout_s=settings.assistant.confirmation_timeout_seconds)
    core.subsystems["assistant"] = build_assistant(settings, core, ui_factory=ui_factory, sink=routing_sink,
                                                   journal=build_journal(settings, core, guard) if assistant_on else None,
                                                   router=getattr(goal_agents, "router", None))
    assistant_ui = getattr(core.subsystems["assistant"], "ui", None)
    if assistant_ui is not None and settings.security.confirmation != "deny":
        permissions.set_confirmation_provider(assistant_ui.confirmation_provider, source="assistant")
    register_emergency_components(core)
    return core


def agent_budget_audit(logger) -> Callable[[dict], bool]:
    """Adapter: the first exhaustion of an agent budget (numbers only) -> one `budget_exhausted` event in the existing audit log (tool="agent"). Never prompts, inputs or results."""
    from jarvis.permissions.audit import AuditEvent, AuditEventType

    def record(meta) -> bool:
        m = dict(meta)
        return logger.record(AuditEvent(AuditEventType.BUDGET_EXHAUSTED, tool="agent", action=str(m.pop("agent", "")), status="blocked", detail=f"agent budget exhausted: {m.get('limit')}",
                                        extra={k: str(v) for k, v in m.items()}))
    return record


def _routed_agents(settings: Settings, agents: Any, sink: Callable[[str, dict], Any], audit: Any) -> Any:
    """The agents subsystem as the goal layer sees it. Only with assistant.enabled AND agents.router.enabled the planner is replaced by a router-backed one
    (same interface: select / available_capabilities); otherwise the original object is returned untouched."""
    if not (settings.assistant.enabled and settings.agents.router.enabled) or getattr(agents, "orchestrator", None) is None:
        return agents
    from types import SimpleNamespace

    from jarvis.agents.router import AgentRouter, RoutingPlanner, audit_listener, event_listener
    from jarvis.permissions.audit import AuditEvent, AuditEventType
    r = settings.agents.router
    router = AgentRouter(agents.registry, agents.planner, llm=None, timeout=r.timeout_seconds, max_objective_chars=r.max_objective_chars,
                         max_reason_chars=r.max_reason_chars)
    router.add_listener(event_listener(sink))
    router.add_listener(audit_listener(lambda m: audit.record(AuditEvent(AuditEventType.LLM_ROUTE, **m))))
    return SimpleNamespace(orchestrator=agents.orchestrator, planner=RoutingPlanner(router, agents.planner), router=router)


def routing_audit(logger) -> Callable[[dict], bool]:
    """Adapter: routing decisions (metadata dicts) -> `llm_route` audit events in the existing audit log. Returns False if a sink failed."""
    from jarvis.permissions.audit import AuditEvent, AuditEventType

    def record(meta) -> bool:
        m = dict(meta)
        return logger.record(AuditEvent(AuditEventType.LLM_ROUTE, tool="llm", action="route", status=m.pop("status", None), rule=m.pop("rule", None), extra=m))
    return record


def recording_guard(core: JarvisCore) -> Callable[[], str | None]:
    """Why a microphone recording must not start or continue: central emergency stop or exhausted session budget (else None). Only reads state."""
    def guard() -> str | None:
        em = core.permissions.emergency
        if em.engaged:
            return f"Notaus aktiv ({em.reason})"
        budget = core.permissions.budget
        return budget.refusal() if budget is not None else None
    return guard


def build_voice_session(settings: Settings, core: JarvisCore, display=print, input_fn=input, on_state=None):
    """Assemble the voice front-end around an existing core.

    Raises VoiceError subclasses (e.g. VoiceUnavailableError) if the configured engines cannot be created;
    callers decide how to degrade (the CLI falls back to text mode).
    """
    from jarvis.voice import VoiceSession, build_listener, build_speaker

    v = settings.voice
    return VoiceSession(core, build_listener(v, input_fn, guard=recording_guard(core)), build_speaker(v, display), wake_word=v.wake_word,
                        require_wake_word=v.require_wake_word, speak_responses=v.speak_responses,
                        display=display, on_state=on_state)


# ---- emergency stop wiring (composition root) ---------------------------------------------------------------------------------
def register_emergency_components(core: JarvisCore) -> None:
    """Register what the central emergency stop (`core.permissions.emergency`) can stop. The latch itself lives in the permission engine; these are the components
    that need an additional nudge: the controllers' own halt (further steps are refused, a running test process is aborted) and the cancellation of goals, agent
    tasks and repair runs. Each stopper reports honestly (stopped / only requested / nothing / failed) and never claims to have undone anything."""
    from jarvis.permissions.emergency import StopOutcome, StopResult

    em = core.permissions.emergency
    subs = core.subsystems

    def halting(name: str, detail: str):
        sub = subs.get(name)
        if sub is None or not hasattr(sub, "halt"):
            return

        def stop(reason: str) -> StopResult:
            if not getattr(sub, "available", False):
                return StopResult(StopOutcome.NOTHING, "off or unavailable")
            return (StopResult(StopOutcome.STOPPED, detail) if sub.halt(f"Notaus: {reason}")
                    else StopResult(StopOutcome.NOTHING, "no controller"))
        em.register(name, stop, resumer=lambda: sub.resume() if hasattr(sub, "resume") else None)

    halting("computer", "further steps are refused; actions already executed (clicks, typed text, started programs) stay as they are")
    halting("browser", "further steps are refused; pages already loaded or forms already sent stay as they are")
    halting("files", "further steps are refused and pending organize plans are dropped; files already created, changed or moved stay as they are")
    halting("office", "further steps are refused and a running read is aborted; files already created stay as they are")
    halting("research_search", "further searches are refused; requests already sent to the search provider cannot be recalled")
    halting("coding", "further steps are refused and a running test process is aborted; files already written stay as they are")

    def cancelling(name: str, handle: Callable[[Any], Any], items: Callable[[Any], list[tuple[str, Any]]], terminal: Any) -> None:
        sub = subs.get(name)
        if sub is None:
            return

        def stop(reason: str) -> StopResult:
            target = handle(sub)
            if target is None:
                return StopResult(StopOutcome.NOTHING, "off")
            stopped = requested = 0
            failed: list[str] = []
            for ident, status in items(target):
                if status in terminal:
                    continue
                try:
                    report = target.cancel(ident)
                except Exception as exc:
                    failed.append(f"{ident}: {type(exc).__name__}")
                    continue
                if report.status in terminal:
                    stopped += 1
                elif report.accepted:
                    requested += 1
                else:
                    failed.append(f"{ident}: {report.message}")
            detail = f"{stopped} cancelled, {requested} cancellation requested (cooperative; the work may continue until the agent notices)"
            if failed:
                return StopResult(StopOutcome.FAILED, detail + "; could NOT be cancelled: " + "; ".join(failed)[:200])
            if requested:
                return StopResult(StopOutcome.REQUESTED, detail)
            return StopResult(StopOutcome.STOPPED if stopped else StopOutcome.NOTHING, detail if stopped else "nothing running")
        em.register(name, stop)

    sub_assistant = subs.get("assistant")
    if getattr(sub_assistant, "ui", None) is not None:
        def stop_assistant(reason: str) -> StopResult:
            n = sub_assistant.ui.deny_pending()
            return StopResult(StopOutcome.STOPPED if n else StopOutcome.NOTHING, f"{n} open question(s) of the assistant answered with DENY")
        em.register("assistant", stop_assistant)

    from jarvis.agents.state import TERMINAL as TASK_TERMINAL
    from jarvis.goals.state import GOAL_TERMINAL
    from jarvis.self_repair.state import RUN_TERMINAL
    cancelling("goals", lambda sub: getattr(sub, "engine", None), lambda e: [(g.goal_id, g.status) for g in e.list()], GOAL_TERMINAL)
    cancelling("agents", lambda sub: getattr(sub, "orchestrator", None), lambda o: [(r.task_id, r.status) for r in o.list()], TASK_TERMINAL)
    cancelling("self_repair", lambda sub: getattr(sub, "engine", None), lambda e: [(r.run_id, r.status) for r in e.list()], RUN_TERMINAL)


def office_baseline_rules() -> list:
    """Rules merged into the permission policy when the office tool is installed (visible in /permissions). `confirm` = ask every time and never offer a
    session permission; deny > confirm > allow, so a user `allow` rule cannot switch the question off: every new Office file is confirmed on its own."""
    from jarvis.office.factory import RULE_ID
    from jarvis.permissions import Effect, Rule
    return [Rule(id=RULE_ID, effect=Effect.CONFIRM, tool="office", action="create", description="Every new Office file is confirmed one by one, with a preview")]
