"""Secrets must never be persisted as memories."""
import sqlite3

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.errors import MemoryLimitError, MemoryValidationError, SecretRejectedError
from jarvis.memory import SecretGuard
from jarvis.memory.guarded import GuardedMemoryStore
from jarvis.memory.inmemory import InMemoryStore
from jarvis.memory.sqlite_store import SqliteMemoryStore

SECRETS = [
    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123",
    "OPENAI_API_KEY=abcd1234",
    "api key: 12345678",
    "Mein Passwort ist hunter22",
    "password=abc12345",
    "Das Passwort lautet geheim123",
    "token: abcdefgh",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "AKIAIOSFODNN7EXAMPLE",
    "xoxb-1234567890-abcdefghij",
    "postgres://admin:s3cret@db.example.com/prod",
    "Authorization: Bearer abc.def.ghi",
    "-----BEGIN RSA PRIVATE KEY-----",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV",
    "xK3jH9sL2mN8pQ4rT7vW1yZ5aB6cD0eF9gH",
    "AIzaSyA1234567890abcdefghijklmnopqrstuv",
]

BENIGN = [
    "Meine Lieblingsfarbe ist blau",
    "Das Projekt heißt Atlas und startet im Mai",
    "Ich mag Python 3.13",
    "Commit a3f9c1d2e4b5a6978877665544332211aabbccdd ist der Release",
    "Der Token-Verbrauch des Modells ist gering",
    "Meine Sekretärin heißt Anna",
    "Konfiguration liegt in /home/user/project/config/jarvis.toml",
    "Entscheidung: wir nutzen SQLite statt Postgres",
]


@pytest.fixture
def guarded():
    return GuardedMemoryStore(InMemoryStore(), SecretGuard())


@pytest.mark.parametrize("text", SECRETS)
def test_secret_patterns_are_rejected(guarded, text):
    with pytest.raises(SecretRejectedError):
        guarded.add(text)
    assert guarded.count() == 0


@pytest.mark.parametrize("text", BENIGN)
def test_benign_text_is_accepted(guarded, text):
    assert guarded.add(text).content == text


def test_error_message_never_contains_the_secret(guarded):
    with pytest.raises(SecretRejectedError) as exc:
        guarded.add("Mein Passwort ist hunter22")
    assert "hunter22" not in str(exc.value)


def test_secret_rejection_is_a_validation_error(guarded):
    with pytest.raises(MemoryValidationError):
        guarded.add("password=abc12345")


def test_secrets_in_tags_source_and_metadata_are_rejected(guarded):
    with pytest.raises(SecretRejectedError):
        guarded.add("harmlos", tags=["password=abc12345"])
    with pytest.raises(SecretRejectedError):
        guarded.add("harmlos", source="token: abcdefgh")
    with pytest.raises(SecretRejectedError):
        guarded.add("harmlos", metadata={"cfg": {"api_key": "api_key=zzzz9999"}})
    assert guarded.count() == 0


def test_update_cannot_smuggle_secrets_in(guarded):
    e = guarded.add("harmlos")
    with pytest.raises(SecretRejectedError):
        guarded.update(e.id, content="jetzt mit password=abc12345")
    with pytest.raises(SecretRejectedError):
        guarded.update(e.id, tags=["token: abcdefgh"])
    assert guarded.get(e.id).content == "harmlos"


def test_known_secret_values_are_rejected_even_without_pattern():
    guard = SecretGuard(known_secrets=["plain-value-no-pattern", None, "short"])
    g = GuardedMemoryStore(InMemoryStore(), guard)
    with pytest.raises(SecretRejectedError):
        g.add("Der Wert plain-value-no-pattern ist wichtig")
    assert g.add("short ist kein Geheimnis (zu kurz fuer den Abgleich)")  # <8 chars: not tracked


def test_guard_from_environment_uses_secret_named_variables():
    guard = SecretGuard.from_environment({"MY_SERVICE_TOKEN": "tok-value-12345", "PATH": "/usr/bin:/bin",
                                          "EDITOR": "vimvimvim"})
    assert guard.find("x tok-value-12345 y")
    assert guard.find("PATH ist /usr/bin:/bin") is None and guard.find("vimvimvim") is None


def test_settings_secrets_never_become_memories(tmp_path, monkeypatch):
    """Keys from the real configuration/environment cannot be persisted, even when the user asks."""
    monkeypatch.setenv("SOME_OTHER_API_TOKEN", "env-token-value-777")
    db = tmp_path / "m.db"
    settings = load_settings(env={
        "JARVIS_LLM_PROVIDER": "openai", "JARVIS_LLM_API_KEY": "llmplainsecret4711",
        "JARVIS_VOICE_API_KEY": "voiceplainsecret0815", "JARVIS_MEMORY_PATH": str(db),
        "JARVIS_LOG_DIR": str(tmp_path / "logs")})
    core = build_core(settings)
    secrets = ["llmplainsecret4711", "voiceplainsecret0815", "env-token-value-777"]
    for s in secrets:
        r = core.handle(f"Merk dir, dass das hier wichtig ist: {s}")
        assert not r.ok, s
        assert s not in r.text
        with pytest.raises(SecretRejectedError):
            core.remember(s)
    assert core.memory.count() == 0 and not db.exists()
    core.remember("Ein normaler Fakt")  # the store still works for harmless content
    raw = db.read_bytes()
    assert b"Ein normaler Fakt" in raw and not any(s.encode() in raw for s in secrets)
    assert "llmplainsecret4711" not in repr(settings)


def test_secrets_not_present_in_sqlite_file_after_rejections(tmp_path):
    db = tmp_path / "m.db"
    g = GuardedMemoryStore(SqliteMemoryStore(db), SecretGuard())
    g.add("harmlos")
    for text in SECRETS:
        with pytest.raises(SecretRejectedError):
            g.add(text)
    g.close()
    with sqlite3.connect(db) as raw:
        rows = raw.execute("SELECT content FROM memories").fetchall()
    assert rows == [("harmlos",)]


def test_chat_is_not_persisted_automatically(tmp_path):
    core = build_core(load_settings(env={"JARVIS_MEMORY_PATH": str(tmp_path / "m.db"),
                                         "JARVIS_LOG_DIR": str(tmp_path / "l")}))
    core.handle("Hallo JARVIS")
    core.handle("Mein Name ist Tobias und ich mag Kaffee")
    core.handle("Erstelle ein Python-Programm")
    assert core.memory.count() == 0 and not (tmp_path / "m.db").exists()


# ---- limits -----------------------------------------------------------------------------------------
def test_content_length_limit_is_configurable():
    g = GuardedMemoryStore(InMemoryStore(), max_content_length=20)
    assert g.add("x" * 20)
    with pytest.raises(MemoryValidationError, match="too long"):
        g.add("x" * 21)


def test_max_entries_limit():
    g = GuardedMemoryStore(InMemoryStore(), max_entries=2)
    g.add("eins1"), g.add("zwei2")
    with pytest.raises(MemoryLimitError):
        g.add("drei3")
    first = g.recent(5)[-1]
    g.delete(first.id)
    assert g.add("drei3")  # space freed
    unlimited = GuardedMemoryStore(InMemoryStore(), max_entries=0)
    for i in range(30):
        unlimited.add(f"eintrag {i}")
    assert unlimited.count() == 30


def test_guarded_store_delegates_everything():
    g = GuardedMemoryStore(InMemoryStore())
    e = g.add("Lieblingsfarbe blau", type="preference", tags=["a"])
    assert g.get(e.id) == e and g.search("farbe")[0].entry == e and g.count("preference") == 1
    assert g.update(e.id, importance=9).importance == 9
    assert g.recent(1)[0].id == e.id and g.enabled and isinstance(g.inner, InMemoryStore)
    assert g.delete(e.id) and not g.delete(e.id)
    g.close()
