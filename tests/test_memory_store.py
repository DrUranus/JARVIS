"""Backend contract tests (run against every backend) plus SQLite-specific behaviour. Temp databases only."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.errors import MemoryNotFoundError, MemoryStoreError, MemoryValidationError
from jarvis.memory import MemoryEntry, MemoryHit, MemoryStore, MemoryType, NullMemoryStore
from jarvis.memory.inmemory import InMemoryStore
from jarvis.memory.ranking import tokenize
from jarvis.memory.sqlite_store import SCHEMA_VERSION, SqliteMemoryStore


class Clock:
    """Deterministic clock: every call is one second later."""

    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    clock = Clock()
    s = InMemoryStore(clock=clock) if request.param == "memory" else SqliteMemoryStore(tmp_path / "m.db", clock=clock)
    yield s
    s.close()


# ---- contract: store / get / metadata -----------------------------------------------------------
def test_is_a_memory_store(store):
    assert isinstance(store, MemoryStore) and store.enabled


def test_add_and_get_with_full_metadata(store):
    e = store.add("Meine Lieblingsfarbe ist blau", type="preference", importance=8, tags=["Farbe", " Favoriten "],
                  source="user", metadata={"origin": {"chat": 1}})
    assert isinstance(e, MemoryEntry) and len(e.id) == 12
    got = store.get(e.id)
    assert got == e
    assert (got.type, got.importance, got.source) == (MemoryType.PREFERENCE, 8, "user")
    assert got.tags == ("farbe", "favoriten")  # normalised
    assert got.metadata == {"origin": {"chat": 1}}
    assert got.created_at == got.updated_at and got.created_at.tzinfo is not None


def test_defaults(store):
    e = store.add("  Ein Fakt  ")
    assert (e.content, e.type, e.importance, e.tags, e.source, e.metadata) == ("Ein Fakt", MemoryType.FACT, 5, (), None, {})


def test_ids_are_unique(store):
    assert len({store.add(f"eintrag {i}").id for i in range(50)}) == 50


def test_get_unknown(store):
    with pytest.raises(MemoryNotFoundError):
        store.get("doesnotexist")


def test_metadata_is_detached_copy(store):
    meta = {"a": [1]}
    e = store.add("x1x", metadata=meta)
    meta["a"].append(2)
    assert store.get(e.id).metadata == {"a": [1]}


def test_all_memory_types_roundtrip(store):
    for t in MemoryType:
        assert store.get(store.add(f"typ {t.value}", type=t).id).type is t


# ---- contract: search -------------------------------------------------------------------------
def test_search_matches_substrings_and_ignores_stopwords(store):
    store.add("Meine Lieblingsfarbe ist blau")
    store.add("Das Projekt Atlas startet im Mai")
    hits = store.search("Welche Farbe mag ich?")
    assert [h.entry.content for h in hits] == ["Meine Lieblingsfarbe ist blau"]
    assert isinstance(hits[0], MemoryHit) and hits[0].score > 0


def test_search_is_case_and_umlaut_insensitive(store):
    store.add("Treffen mit ÄRZTIN am Montag")
    assert store.search("ärztin")


def test_search_ranking_prefers_more_matching_terms_then_importance_then_recency(store):
    a = store.add("python projekt alpha", importance=5)
    b = store.add("python", importance=5)
    c = store.add("python projekt beta", importance=9)
    d = store.add("python projekt gamma", importance=5)
    ids = [h.entry.id for h in store.search("python projekt")]
    assert ids == [c.id, d.id, a.id, b.id]  # 2 terms: importance 9 first, then newest; 1 term last


def test_search_tags_boost_and_filter(store):
    store.add("alpha beta", tags=["x"])
    store.add("alpha beta", tags=["y"])
    assert [h.entry.tags for h in store.search("alpha", tags=["y"])] == [("y",)]
    assert len(store.search("alpha", tags=["x", "y"])) == 0  # all tags must match
    store.add("nothing here", tags=["python"])
    assert [h.entry.content for h in store.search("python")] == ["nothing here"]  # tag match counts


def test_search_filters_type_importance_limit(store):
    store.add("kaffee fakt", type="fact", importance=3)
    store.add("kaffee vorliebe", type="preference", importance=9)
    assert [h.entry.type for h in store.search("kaffee", type="preference")] == [MemoryType.PREFERENCE]
    assert [h.entry.importance for h in store.search("kaffee", min_importance=5)] == [9]
    assert len(store.search("kaffee", limit=1)) == 1
    assert store.search("kaffee", limit=0) == []


def test_search_no_match_and_empty_queries(store):
    store.add("etwas anderes")
    assert store.search("zzzzzz") == []
    assert store.search("") == [] and store.search("   ") == [] and store.search("der die das") == []


def test_search_treats_wildcards_literally(store):
    store.add("a_b literal")
    store.add("axb other")
    store.add("100% sicher")
    assert [h.entry.content for h in store.search("a_b")] == ["a_b literal"]
    assert store.search("%%%") == []
    assert [h.entry.content for h in store.search("100% sicher")] == ["100% sicher"]


def test_search_survives_sql_injection_text(store):
    evil = "x'); DROP TABLE memories; --"
    e = store.add(evil)
    assert store.get(e.id).content == evil
    assert store.search("DROP TABLE memories") and store.count() == 1
    assert store.search("' OR '1'='1") == []


# ---- contract: update --------------------------------------------------------------------------
def test_update_fields_and_timestamps(store):
    e = store.add("alter inhalt", tags=["a"], importance=3, source="user", metadata={"k": 1})
    u = store.update(e.id, content="neuer inhalt", type="decision", importance=9, tags=["b", "c"],
                     source="agent:x", metadata={"k": 2})
    assert (u.content, u.type, u.importance, u.tags, u.source, u.metadata) == \
           ("neuer inhalt", MemoryType.DECISION, 9, ("b", "c"), "agent:x", {"k": 2})
    assert u.id == e.id and u.created_at == e.created_at and u.updated_at > e.updated_at
    assert store.get(e.id) == u


def test_partial_update_keeps_other_fields(store):
    e = store.add("inhalt", tags=["a"], importance=4)
    u = store.update(e.id, importance=7)
    assert (u.content, u.tags, u.importance) == ("inhalt", ("a",), 7)
    assert store.update(e.id, tags=[]).tags == ()  # empty list clears tags, None keeps them


def test_update_makes_new_content_searchable(store):
    e = store.add("erste fassung")
    store.update(e.id, content="zweite version")
    assert store.search("erste") == [] and len(store.search("zweite")) == 1


def test_update_unknown_and_invalid(store):
    with pytest.raises(MemoryNotFoundError):
        store.update("nope", content="x1x")
    e = store.add("inhalt")
    with pytest.raises(MemoryValidationError):
        store.update(e.id, content="   ")
    with pytest.raises(MemoryValidationError):
        store.update(e.id, importance=99)
    assert store.get(e.id).content == "inhalt"  # failed update changed nothing


# ---- contract: delete / count / recent -------------------------------------------------------
def test_delete(store):
    e = store.add("loeschen", tags=["t"])
    assert store.delete(e.id) is True
    assert store.delete(e.id) is False and store.delete("never-existed") is False
    with pytest.raises(MemoryNotFoundError):
        store.get(e.id)
    assert store.count() == 0 and store.search("loeschen") == []


def test_recent_ordering_and_pagination(store):
    ids = [store.add(f"eintrag {i}").id for i in range(5)]
    assert [e.id for e in store.recent(3)] == ids[::-1][:3]  # newest first
    assert [e.id for e in store.recent(10, offset=3)] == ids[::-1][3:]
    assert store.recent(0) == []


def test_recent_same_timestamp_uses_insertion_order(tmp_path):
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for s in (InMemoryStore(clock=lambda: fixed), SqliteMemoryStore(tmp_path / "t.db", clock=lambda: fixed)):
        ids = [s.add(f"gleich {i}").id for i in range(4)]
        assert [e.id for e in s.recent(4)] == ids[::-1]


def test_recent_filters(store):
    store.add("fakt", type="fact", tags=["a"])
    p = store.add("pref", type="preference", tags=["a", "b"])
    assert [e.id for e in store.recent(10, type="preference")] == [p.id]
    assert [e.id for e in store.recent(10, tags=["b"])] == [p.id]
    assert store.count("fact") == 1 and store.count() == 2


def test_update_does_not_reorder_recent(store):
    a, b = store.add("erste"), store.add("zweite")
    store.update(a.id, importance=9)
    assert [e.id for e in store.recent(2)] == [b.id, a.id]  # ordered by creation time


# ---- contract: empty store & invalid input -------------------------------------------------------
def test_empty_store(store):
    assert store.count() == 0 and store.recent() == [] and store.search("irgendwas") == []
    assert store.delete("x") is False
    with pytest.raises(MemoryNotFoundError):
        store.get("x")


@pytest.mark.parametrize("kwargs", [
    {"content": ""}, {"content": "   "}, {"content": None}, {"content": 5}, {"content": "x" * 10_001},
    {"content": "ok", "type": "bogus"}, {"content": "ok", "type": 3},
    {"content": "ok", "importance": 0}, {"content": "ok", "importance": 11}, {"content": "ok", "importance": "5"},
    {"content": "ok", "importance": True}, {"content": "ok", "importance": 5.0},
    {"content": "ok", "tags": "abc"}, {"content": "ok", "tags": [""]}, {"content": "ok", "tags": [1]},
    {"content": "ok", "tags": ["t"] * 2 + [f"t{i}" for i in range(25)]}, {"content": "ok", "tags": ["x" * 51]},
    {"content": "ok", "source": 5}, {"content": "ok", "source": "s" * 201},
    {"content": "ok", "metadata": "str"}, {"content": "ok", "metadata": {1: 2}},
    {"content": "ok", "metadata": {"a": object()}}, {"content": "ok", "metadata": {"a": "x" * 5000}},
])
def test_add_rejects_invalid_input(store, kwargs):
    with pytest.raises(MemoryValidationError):
        store.add(**kwargs)
    assert store.count() == 0


@pytest.mark.parametrize("kwargs", [{"query": None}, {"query": 5}, {"query": "ok", "limit": -1},
                                    {"query": "ok", "limit": "3"}, {"query": "ok", "type": "bogus"},
                                    {"query": "ok", "min_importance": 0}])
def test_search_rejects_invalid_input(store, kwargs):
    with pytest.raises(MemoryValidationError):
        store.search(**kwargs)


def test_recent_rejects_invalid_input(store):
    with pytest.raises(MemoryValidationError):
        store.recent(-1)
    with pytest.raises(MemoryValidationError):
        store.recent(5, type="bogus")


def test_validation_errors_are_memory_store_errors(store):
    with pytest.raises(MemoryStoreError):
        store.add("")


def test_unicode_and_multiline_content(store):
    text = "Zeile 1\nZeile 2 – äöüß 日本語 🚀"
    assert store.get(store.add(text).id).content == text


def test_tokenize():
    assert tokenize("Welche Farbe mag ich? Farbe!") == ["farbe"]
    assert tokenize("") == [] and tokenize("ab io") == []


# ---- null / disabled store -----------------------------------------------------------------------
def test_null_store_is_disabled_and_inert():
    from jarvis.errors import MemoryDisabledError
    n = NullMemoryStore()
    assert not n.enabled and n.search("x") == [] and n.recent() == [] and n.count() == 0 and n.delete("x") is False
    for call in (lambda: n.add("x1x"), lambda: n.get("x"), lambda: n.update("x", content="y")):
        with pytest.raises(MemoryDisabledError):
            call()


# ---- SQLite specifics: real files, persistence, robustness -------------------------------------------
def test_database_is_created_lazily_and_automatically(tmp_path):
    path = tmp_path / "deep" / "dir" / "m.db"
    s = SqliteMemoryStore(path)
    assert s.recent() == [] and s.count() == 0 and s.search("etwas") == [] and s.delete("x") is False
    assert not path.exists() and not path.parent.exists()  # reads never create anything
    with pytest.raises(MemoryNotFoundError):
        s.get("x")
    s.add("erster eintrag")
    assert path.is_file()
    with sqlite3.connect(path) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"memories", "memory_tags"} <= tables
    s.close()


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "m.db"
    first = SqliteMemoryStore(path)
    e = first.add("Ich bevorzuge dunkle Themes", type="preference", importance=7, tags=["ui", "Theme"],
                  source="user", metadata={"k": [1, 2]})
    other = first.add("zweiter", tags=["x"])
    first.update(other.id, content="zweiter geaendert")
    first.delete(first.add("wird geloescht").id)
    first.close()

    second = SqliteMemoryStore(path)  # "application restart"
    assert second.get(e.id) == e
    assert second.get(other.id).content == "zweiter geaendert"
    assert second.count() == 2
    assert [h.entry.id for h in second.search("dunkle themes")] == [e.id]
    assert [x.id for x in second.recent(5)] == [other.id, e.id]
    second.add("dritter")
    second.close()
    assert SqliteMemoryStore(path).count() == 3


def test_two_open_instances_share_data(tmp_path):
    a, b = SqliteMemoryStore(tmp_path / "m.db"), SqliteMemoryStore(tmp_path / "m.db")
    e = a.add("geteilt")
    assert b.get(e.id).content == "geteilt"
    a.close(); b.close()


def test_store_is_usable_after_close(tmp_path):
    s = SqliteMemoryStore(tmp_path / "m.db")
    e = s.add("vor close")
    s.close(); s.close()  # idempotent
    assert s.get(e.id).content == "vor close"
    s.close()


def test_context_manager_and_in_memory_db(tmp_path):
    with SqliteMemoryStore(":memory:") as s:
        assert s.recent() == []
        e = s.add("fluechtig")
        assert s.get(e.id).content == "fluechtig"


def test_empty_existing_file_is_initialised(tmp_path):
    path = tmp_path / "empty.db"
    path.write_bytes(b"")
    s = SqliteMemoryStore(path)
    assert s.count() == 0
    s.add("jetzt mit schema")
    assert SqliteMemoryStore(path).count() == 1


def test_corrupt_database_raises_clean_error_and_is_not_overwritten(tmp_path):
    path = tmp_path / "bad.db"
    junk = b"this is definitely not a sqlite database" * 20
    path.write_bytes(junk)
    s = SqliteMemoryStore(path)
    for call in (lambda: s.add("x1x"), lambda: s.recent(), lambda: s.count(), lambda: s.search("irgendwas")):
        with pytest.raises(MemoryStoreError, match="memory database"):
            call()
    assert path.read_bytes() == junk


def test_path_that_is_a_directory(tmp_path):
    with pytest.raises(MemoryStoreError):
        SqliteMemoryStore(tmp_path).add("x1x")


def test_unusable_parent_path(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(MemoryStoreError, match="cannot create"):
        SqliteMemoryStore(blocker / "sub" / "m.db").add("x1x")


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as raw:
        raw.execute("PRAGMA user_version = 99")
    with pytest.raises(MemoryStoreError, match="newer"):
        SqliteMemoryStore(path).count()


def test_tags_cascade_on_delete(tmp_path):
    path = tmp_path / "m.db"
    s = SqliteMemoryStore(path)
    s.delete(s.add("mit tags", tags=["a", "b"]).id)
    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT COUNT(*) FROM memory_tags").fetchone()[0] == 0


def test_concurrent_writers(tmp_path):
    s = SqliteMemoryStore(tmp_path / "m.db")
    errors = []

    def work(n):
        try:
            for i in range(10):
                s.add(f"thread {n} eintrag {i}")
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and s.count() == 80


def test_database_file_never_receives_unvalidated_content_types(tmp_path):
    s = SqliteMemoryStore(tmp_path / "m.db")
    with pytest.raises(MemoryValidationError):
        s.add(b"bytes")
    assert s.count() == 0
