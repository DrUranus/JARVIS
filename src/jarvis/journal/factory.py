"""Builds the journal recorder from the settings. Disabled (the default) -> None and no file. Not wired into bootstrap yet (assistant-e2e)."""
from __future__ import annotations

from typing import Any

from jarvis.config import Settings
from jarvis.journal.recorder import JournalRecorder
from jarvis.journal.store import JournalStore
from jarvis.redaction import SecretDetector


def build_journal(settings: Settings, core: Any, detector: SecretDetector) -> JournalRecorder | None:
    j = settings.journal
    if not j.enabled:
        return None
    subs = core.subsystems
    store = JournalStore(j.path, max_entries=j.max_entries, max_steps_per_entry=j.max_steps_per_entry, max_text_length=j.max_text_length,
                         max_evidence=j.max_evidence, detector=detector)
    return JournalRecorder(store, goals=getattr(subs.get("goals"), "engine", None), agents=getattr(subs.get("agents"), "orchestrator", None))
