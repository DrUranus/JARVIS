"""Builds the history recorder from the settings. Disabled (the default) -> None and no file."""
from __future__ import annotations

from typing import Any

from jarvis.config import Settings
from jarvis.history.recorder import HistoryRecorder
from jarvis.history.store import HistoryStore
from jarvis.redaction import SecretDetector


def build_history(settings: Settings, core: Any, detector: SecretDetector) -> HistoryRecorder | None:
    h = settings.history
    if not h.enabled:
        return None
    subs = core.subsystems
    store = HistoryStore(h.path, max_entries=h.max_entries, max_text_length=h.max_text_length, detector=detector)
    return HistoryRecorder(store, goals=getattr(subs.get("goals"), "engine", None), repairs=getattr(subs.get("self_repair"), "engine", None),
                           agents=getattr(subs.get("agents"), "orchestrator", None), tasks=core.tasks)
