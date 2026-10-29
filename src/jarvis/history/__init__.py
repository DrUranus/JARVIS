"""Persistent history of FINISHED work (goals, agent tasks, repair runs, stored plans). Display only: it never resumes, starts or creates anything."""
from jarvis.errors import HistoryError
from jarvis.history.factory import build_history
from jarvis.history.recorder import HistoryRecorder
from jarvis.history.store import HistoryEntry, HistoryStore

__all__ = ["HistoryEntry", "HistoryError", "HistoryRecorder", "HistoryStore", "build_history"]
