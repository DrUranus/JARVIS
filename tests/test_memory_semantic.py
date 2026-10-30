"""Lokales, netzfreies Suchbackend (gehashte TF-IDF-Vektoren) hinter MemoryStore."""
import socket

import pytest

from jarvis.config import MemorySettings, load_settings
from jarvis.errors import ConfigError, MemoryStoreError, SecretRejectedError
from jarvis.memory.factory import available_backends, create_memory
from jarvis.memory.guard import SecretGuard
from jarvis.memory.guarded import GuardedMemoryStore
from jarvis.memory.models import MemoryHit
from jarvis.memory.semantic import SemanticInMemoryStore, SemanticSqliteStore, rank_semantic
from jarvis.memory.validation import MAX_LIMIT


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    s = SemanticInMemoryStore() if request.param == "memory" else SemanticSqliteStore(tmp_path / "s.db")
    yield s
    s.close()


def _texts(hits):
    return [h.entry.content for h in hits]


def test_german_ranking_finds_inflected_and_compound_words(store):
    store.add("Meine Lieblingsfarbe ist Blau")
    store.add("Ich fahre jeden Morgen mit dem Fahrrad zur Arbeit")
    store.add("Das Projekt nutzt PostgreSQL als Datenbank")
    assert _texts(store.search("Welche Farben mag ich?", limit=1)) == ["Meine Lieblingsfarbe ist Blau"]
    assert _texts(store.search("Fahrräder", limit=1))[0].startswith("Ich fahre")
    assert _texts(store.search("Datenbanken", limit=1))[0].startswith("Das Projekt")


def test_english_ranking_finds_inflected_words(store):
    store.add("I prefer drinking coffee in the morning")
    store.add("The server runs on Ubuntu with nginx")
    store.add("Birthday party planned for next Friday")
    assert _texts(store.search("what coffees do I drink", limit=1)) == ["I prefer drinking coffee in the morning"]
    assert _texts(store.search("servers", limit=1))[0].startswith("The server")
    assert _texts(store.search("birthdays", limit=1))[0].startswith("Birthday")


def test_scores_are_positive_and_sorted(store):
    store.add("Kaffee mit Milch am Morgen")
    store.add("Kaffee")
    store.add("Tee am Abend")
    hits = store.search("Kaffee am Morgen", limit=5)
    assert all(isinstance(h, MemoryHit) and h.score > 0 for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert hits[0].entry.content == "Kaffee mit Milch am Morgen"


def test_empty_cases(store):
    assert store.search("irgendwas") == []
    store.add("Kaffee am Morgen")
    assert store.search("") == []
    assert store.search("der die das") == []  # nur Stopwörter
    assert store.search("Kaffee", limit=0) == []
    assert store.search("Zeppelin Quantenphysik") == []  # nichts Aehnliches


def test_limit_and_filters(store):
    for i in range(8):
        store.add(f"Kaffee Notiz {i}", tags=["a"] if i % 2 else ["b"], importance=1 + i % 3)
    assert len(store.search("Kaffee", limit=3)) == 3
    assert len(store.search("Kaffee", limit=MAX_LIMIT + 1000)) <= MAX_LIMIT
    assert all("a" in h.entry.tags for h in store.search("Kaffee", limit=10, tags=["a"]))
    assert all(h.entry.importance >= 3 for h in store.search("Kaffee", limit=10, min_importance=3))
    with pytest.raises(MemoryStoreError):
        store.search("Kaffee", limit=-1)


def test_tags_contribute_to_matching(store):
    store.add("Treffen am Donnerstag", tags=["arbeit"])
    store.add("Einkaufsliste Brot Butter")
    assert _texts(store.search("arbeit", limit=1)) == ["Treffen am Donnerstag"]


def test_candidate_cap_is_bounded():
    from jarvis.memory import semantic
    s = SemanticInMemoryStore()
    for i in range(semantic.CANDIDATE_LIMIT + 20):
        s.add(f"Notiz {i} Kaffee")
    assert len(s.search("Kaffee", limit=MAX_LIMIT)) <= MAX_LIMIT


def test_rank_semantic_pure_function():
    assert rank_semantic([], "Kaffee", 5) == []
    assert rank_semantic([], "", 5) == []


def test_no_network(store, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    store.add("Kaffee am Morgen")
    assert store.search("Kaffees")


def test_no_new_required_dependency():
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    deps = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M).group(1)
    assert "numpy" not in deps.lower() and "scikit" not in deps.lower()
    src = (Path(__file__).resolve().parent.parent / "src/jarvis/memory/semantic.py").read_text()
    assert "numpy" not in src and "import requests" not in src and "urllib" not in src


# ---- Konfiguration, Standard, Schutzmechanismen ------------------------------------------------
def test_default_backend_unchanged():
    assert MemorySettings().backend == "sqlite"
    assert load_settings("config/jarvis.toml", env={}).memory.backend == "sqlite"


def test_backends_selectable_by_config(tmp_path):
    assert {"semantic", "semantic-memory"} <= set(available_backends())
    g = create_memory(MemorySettings(backend="semantic", path=str(tmp_path / "x.db")), SecretGuard())
    assert isinstance(g, GuardedMemoryStore) and isinstance(g.inner, SemanticSqliteStore)
    g.close()
    g2 = create_memory(MemorySettings(backend="Semantic-Memory"), SecretGuard())
    assert isinstance(g2.inner, SemanticInMemoryStore)
    assert load_settings(env={"JARVIS_MEMORY_BACKEND": "semantic"}).memory.backend == "semantic"


def test_semantic_sqlite_requires_path():
    with pytest.raises(ConfigError):
        load_settings(env={"JARVIS_MEMORY_BACKEND": "semantic", "JARVIS_MEMORY_PATH": " "})


def test_secret_protection_unchanged(tmp_path):
    g = create_memory(MemorySettings(backend="semantic-memory"), SecretGuard())
    with pytest.raises(SecretRejectedError):
        g.add("Mein Schluessel ist sk-abcdefghijklmnopqrstuvwxyz0123456789")
    assert g.count() == 0


def test_remember_only_on_explicit_request_unchanged():
    from jarvis.core import JarvisCore
    from jarvis.llm.mock import MockProvider
    mem = create_memory(MemorySettings(backend="semantic-memory"), SecretGuard())
    core = JarvisCore(provider=MockProvider(), memory=mem)
    core.handle("Ich mag Kaffee am Morgen und trinke gern Tee")
    assert mem.count() == 0
    core.handle("Merk dir, dass ich Kaffee mag")
    assert mem.count() == 1
