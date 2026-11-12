"""E6: build_core wiring - disabled means the IDENTICAL provider object; enabled wraps once, for every consumer."""
from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import LlmBudgetSettings, Settings
from jarvis.errors import LLMError
from jarvis.permissions.audit import MemoryAuditSink
from jarvis.llm.budgeted import BudgetedProvider


def settings(**kw):
    return replace(Settings(), llm_budget=replace(LlmBudgetSettings(), **kw))


def test_disabled_keeps_the_provider_object_untouched_and_has_no_subsystem_status():
    core = build_core(settings(enabled=False))
    assert not isinstance(core.provider, BudgetedProvider)
    assert core.subsystems.get("llm_budget") is None


def test_enabled_wraps_once_and_every_consumer_shares_the_same_object():
    core = build_core(settings(enabled=True, max_calls=2))
    assert isinstance(core.provider, BudgetedProvider)
    assert core.subsystems["llm_budget"] is core.provider
    assert core.provider.status()["enabled"] is True
    coding = core.subsystems["coding"]
    llm = getattr(coding, "llm", None) or getattr(getattr(coding, "controller", None), "_llm", None)
    if llm is not None:
        assert llm is core.provider


def test_enabled_core_stops_calling_the_model_after_the_call_limit():
    core = build_core(settings(enabled=True, max_calls=2))
    core.provider.complete_text("s", "u", max_tokens=10)
    core.provider.complete_text("s", "u", max_tokens=10)
    with pytest.raises(LLMError, match="LLM-Budget"):
        core.provider.complete_text("s", "u", max_tokens=10)
    st = core.subsystems["llm_budget"].status()
    assert st["calls"] == 2 and st["refused"] == 1


def test_emergency_stop_blocks_llm_calls_and_is_not_reset_by_the_wrapper():
    core = build_core(settings(enabled=True))
    perms = core.tools.permissions if hasattr(core.tools, "permissions") else None
    assert perms is not None
    perms.emergency.engage("test", source="test")
    with pytest.raises(LLMError, match="Not-Aus"):
        core.provider.complete_text("s", "u", max_tokens=10)
    assert perms.emergency.engaged is True


def test_budget_exhaustion_is_audited_without_content():
    core = build_core(settings(enabled=True, max_calls=1))
    perms = core.tools.permissions
    sink = MemoryAuditSink()
    perms.audit.sinks.append(sink)
    core.provider.complete_text("s", "geheimer-prompt-123", max_tokens=10)
    with pytest.raises(LLMError):
        core.provider.complete_text("s", "geheimer-prompt-123", max_tokens=10)
    events = [e for e in sink.tail(50) if e.get("type") == "budget_exhausted" and e.get("tool") == "llm"]
    assert events and "geheimer-prompt-123" not in repr(events)
