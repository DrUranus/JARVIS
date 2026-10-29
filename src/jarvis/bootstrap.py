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
    # Multi-agent orchestration sits ABOVE those subsystems: agents only use their tools through the registry (and so the permission engine).
    from jarvis.agents.factory import build_agents
    core.subsystems["agents"] = build_agents(settings, tools, memory, core.tasks, core.subsystems)
    # The goal engine sits above the agent layer and talks to it only through the orchestrator.
    from jarvis.goals.factory import build_goals
    core.subsystems["goals"] = build_goals(settings, core.subsystems["agents"], provider)
    # Research / Business / Finance are agents of that layer; these objects only describe them (status) and add small GREEN calculation tools for /run.
    from jarvis.agents.groups import build_analysis_subsystems
    from jarvis.tools.analysis import register_analysis_tools
    core.subsystems.update(build_analysis_subsystems(settings, core.subsystems["agents"]))
    register_analysis_tools(tools, core.subsystems, tuple(settings.browser.private_hosts_allowed))
    # Self-repair also sits above the agent layer: its only way to act is a Coding-Agent task through the orchestrator.
    from jarvis.self_repair.factory import build_self_repair
    core.subsystems["self_repair"] = build_self_repair(settings, core.subsystems["agents"], core.subsystems.get("coding"))
    # Self-improvement (Phase 15) is a DISABLED PROPOSAL WORKFLOW: it reads what the goal/repair engines and the audit log recorded and keeps proposals. It never
    # prepares, tests, merges or activates code (the factory builds no workspace and a locked ExecutionGuard). The Core does not import it.
    from jarvis.self_improvement.factory import build_self_improvement
    core.subsystems["self_improvement"] = build_self_improvement(
        settings, goals=getattr(core.subsystems.get("goals"), "engine", None), repairs=getattr(core.subsystems.get("self_repair"), "engine", None),
        audit=permissions.audit, llm=provider, confirmation=lambda: permissions.confirmation, detector=guard)
    register_emergency_components(core)
    return core


def build_voice_session(settings: Settings, core: JarvisCore, display=print, input_fn=input, on_state=None):
    """Assemble the voice front-end around an existing core.

    Raises VoiceError subclasses (e.g. VoiceUnavailableError) if the configured engines cannot be created;
    callers decide how to degrade (the CLI falls back to text mode).
    """
    from jarvis.voice import VoiceSession, build_listener, build_speaker

    v = settings.voice
    return VoiceSession(core, build_listener(v, input_fn), build_speaker(v, display), wake_word=v.wake_word,
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

    from jarvis.agents.state import TERMINAL as TASK_TERMINAL
    from jarvis.goals.state import GOAL_TERMINAL
    from jarvis.self_repair.state import RUN_TERMINAL
    cancelling("goals", lambda sub: getattr(sub, "engine", None), lambda e: [(g.goal_id, g.status) for g in e.list()], GOAL_TERMINAL)
    cancelling("agents", lambda sub: getattr(sub, "orchestrator", None), lambda o: [(r.task_id, r.status) for r in o.list()], TASK_TERMINAL)
    cancelling("self_repair", lambda sub: getattr(sub, "engine", None), lambda e: [(r.run_id, r.status) for r in e.list()], RUN_TERMINAL)
