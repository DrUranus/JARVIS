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
    return JarvisCore(provider=provider, tools=tools, memory=memory, memory_limit=settings.memory.max_relevant,
                      use_memory_in_prompts=settings.memory.use_in_prompts)


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
