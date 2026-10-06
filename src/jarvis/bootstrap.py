"""Composition root: the only place that wires concrete implementations together."""
from __future__ import annotations

from jarvis.config import Settings
from jarvis.core import JarvisCore
from jarvis.llm.factory import create_provider
from jarvis.logging_setup import setup_logging
from jarvis.tools.builtin import register_builtin_tools
from jarvis.tools.registry import ToolRegistry


def build_core(settings: Settings) -> JarvisCore:
    setup_logging(settings.effective_log_level, settings.log_dir)
    provider = create_provider(settings.llm)
    tools = register_builtin_tools(ToolRegistry())
    return JarvisCore(provider=provider, tools=tools)
