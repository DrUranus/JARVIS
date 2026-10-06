"""Persistent long-term memory.

This package is independent of Core, Voice and every future consumer: it imports nothing from them.
Consumers depend on `MemoryStore`; concrete backends live in `jarvis.memory.factory`.
"""
from jarvis.memory.base import MemoryStore
from jarvis.memory.extraction import IntentAction, MemoryExtractor, MemoryIntent, RuleBasedExtractor
from jarvis.memory.guard import SecretGuard
from jarvis.memory.models import MemoryEntry, MemoryHit, MemoryType
from jarvis.memory.null import NullMemoryStore

__all__ = ["MemoryStore", "MemoryEntry", "MemoryHit", "MemoryType", "NullMemoryStore", "SecretGuard",
           "MemoryExtractor", "MemoryIntent", "IntentAction", "RuleBasedExtractor"]
