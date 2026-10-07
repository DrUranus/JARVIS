"""Composition root: the only place that wires concrete implementations together."""
from __future__ import annotations

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
    from jarvis.coding.factory import build_coding
    core.subsystems["coding"] = build_coding(settings, tools, permissions, llm=provider)
    # Multi-agent orchestration sits ABOVE those subsystems: agents only use their tools through the registry (and so the permission engine).
    from jarvis.agents.factory import build_agents
    core.subsystems["agents"] = build_agents(settings, tools, memory, core.tasks, core.subsystems)
    # The goal engine sits above the agent layer and talks to it only through the orchestrator.
    from jarvis.goals.factory import build_goals
    core.subsystems["goals"] = build_goals(settings, core.subsystems["agents"])
    # Research / Business / Finance are agents of that layer; these objects only describe them (status) and add small GREEN calculation tools for /run.
    from jarvis.agents.groups import build_analysis_subsystems
    from jarvis.tools.analysis import register_analysis_tools
    core.subsystems.update(build_analysis_subsystems(settings, core.subsystems["agents"]))
    register_analysis_tools(tools, core.subsystems, tuple(settings.browser.private_hosts_allowed))
    # Self-repair also sits above the agent layer: its only way to act is a Coding-Agent task through the orchestrator.
    from jarvis.self_repair.factory import build_self_repair
    core.subsystems["self_repair"] = build_self_repair(settings, core.subsystems["agents"], core.subsystems.get("coding"))
    return core


def build_voice_session(settings: Settings, core: JarvisCore, display=print, input_fn=input):
    """Assemble the voice front-end around an existing core.

    Raises VoiceError subclasses (e.g. VoiceUnavailableError) if the configured engines cannot be created;
    callers decide how to degrade (the CLI falls back to text mode).
    """
    from jarvis.voice import VoiceSession, build_listener, build_speaker

    v = settings.voice
    return VoiceSession(core, build_listener(v, input_fn), build_speaker(v, display), wake_word=v.wake_word,
                        require_wake_word=v.require_wake_word, speak_responses=v.speak_responses,
                        display=display)
