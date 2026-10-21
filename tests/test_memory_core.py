"""Core/CLI/Voice integration of memory, configuration, and architectural independence."""
import ast
from pathlib import Path

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import MemorySettings, Settings, load_settings
from jarvis.core import JarvisCore, ResponseKind
from jarvis.errors import ConfigError, MemoryDisabledError, MemoryStoreError
from jarvis.interface.cli import repl, run_command
from jarvis.llm.mock import MockProvider
from jarvis.memory import IntentAction, MemoryType, NullMemoryStore, RuleBasedExtractor
from jarvis.memory.base import MemoryStore
from jarvis.memory.factory import available_backends, create_memory, register_backend
from jarvis.memory.guard import SecretGuard
from jarvis.memory.guarded import GuardedMemoryStore
from jarvis.memory.inmemory import InMemoryStore
from jarvis.memory.sqlite_store import SqliteMemoryStore
from jarvis.voice import VoiceSession
from jarvis.voice.base import Listener, Speaker

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"


@pytest.fixture(params=["memory", "sqlite"])
def memory(request, tmp_path):
    inner = InMemoryStore() if request.param == "memory" else SqliteMemoryStore(tmp_path / "core.db")
    return GuardedMemoryStore(inner, SecretGuard())


@pytest.fixture
def mcore(provider, registry, memory):
    return JarvisCore(provider, registry, memory=memory)


# ---- extraction ---------------------------------------------------------------------------------
@pytest.mark.parametrize("text,content,mtype", [
    ("Merk dir, dass meine Lieblingsfarbe blau ist", "meine Lieblingsfarbe blau ist", MemoryType.PREFERENCE),
    ("Jarvis, merke dir: Ich bevorzuge dunkle Themes", "Ich bevorzuge dunkle Themes", MemoryType.PREFERENCE),
    ("Kannst du dir merken, dass das Projekt Atlas heißt?", "das Projekt Atlas heißt?", MemoryType.PROJECT),
    ("Remember that we decided to use SQLite", "we decided to use SQLite", MemoryType.DECISION),
    ("Merk dir: mein Ziel ist ein eigener Assistent", "mein Ziel ist ein eigener Assistent", MemoryType.GOAL),
    ("Speichere die Notizen liegen in /home/me/notes.md", "die Notizen liegen in /home/me/notes.md", MemoryType.RESOURCE),
    ("Merk dir dass die Konfiguration in config/jarvis.toml liegt", "die Konfiguration in config/jarvis.toml liegt", MemoryType.SYSTEM),
    ("Merk dir: Der Himmel ist blau", "Der Himmel ist blau", MemoryType.FACT),
])
def test_remember_extraction(text, content, mtype):
    i = RuleBasedExtractor().extract(text)
    assert i.action is IntentAction.REMEMBER and i.content == content and i.type is mtype


def test_importance_marker():
    assert RuleBasedExtractor().extract("Merk dir: das ist wichtig, ich bin allergisch").importance == 8


@pytest.mark.parametrize("text", [
    "Hallo JARVIS", "Wie ist das Wetter?", "Ich merke mir keine Namen", "Erstelle ein Python-Programm",
    "Was weißt du über Quantenphysik?", "Remembering is hard", "Vergessen ist menschlich", "",
])
def test_normal_text_is_not_a_memory_request(text):
    assert RuleBasedExtractor().extract(text) is None


def test_recall_and_forget_extraction():
    ex = RuleBasedExtractor()
    assert ex.extract("Woran erinnerst du dich?").action is IntentAction.RECALL
    assert ex.extract("Was weißt du über mich?").action is IntentAction.RECALL
    assert ex.extract("What do you remember about my project?").query == "about my project"
    f = ex.extract("Vergiss 0123456789ab")
    assert f.action is IntentAction.FORGET and f.entry_id == "0123456789ab"
    f = ex.extract("Vergiss, dass ich Kaffee mag.")
    assert f.entry_id is None and f.query == "ich Kaffee mag"


# ---- core: remember / recall / forget -------------------------------------------------------------
def test_core_defaults_to_disabled_memory(provider):
    core = JarvisCore(provider)
    assert isinstance(core.memory, NullMemoryStore)
    r = core.handle("Merk dir, dass ich Kaffee mag")
    assert r.kind is ResponseKind.MEMORY and "deaktiviert" in r.text and provider.calls == []
    with pytest.raises(MemoryDisabledError):
        core.remember("x1x")
    assert core.recall("kaffee") == [] and core.forget("abc") is False
    assert core.handle("Hallo").text == "ok"  # normal dialog unaffected


def test_remember_via_dialog(mcore, provider):
    r = mcore.handle("Merk dir, dass meine Lieblingsfarbe blau ist")
    assert r.kind is ResponseKind.MEMORY and r.ok and r.text.startswith("Gemerkt [")
    (e,) = r.memories
    assert mcore.memory.get(e.id).content == "meine Lieblingsfarbe blau ist" and e.source == "user"
    assert e.type is MemoryType.PREFERENCE
    assert provider.calls == []  # explicit memory requests never reach the LLM
    assert len(mcore.context) == 0  # and are not part of the conversation history


def test_chat_is_temporary_not_durable(mcore):
    for t in ("Hallo", "Wie geht es dir?", "Ich heiße Tobias", "Erstelle eine Website"):
        mcore.handle(t)
    assert mcore.memory.count() == 0
    assert len(mcore.context) > 0  # temporary context exists, durable memory does not


def test_recall_via_dialog(mcore):
    mcore.handle("Merk dir, dass ich Kaffee mag")
    mcore.handle("Merk dir, dass das Projekt Atlas heißt")
    r = mcore.handle("Woran erinnerst du dich?")
    assert r.kind is ResponseKind.MEMORY and "Atlas" in r.text and "Kaffee" in r.text and len(r.memories) == 2
    r = mcore.handle("What do you remember about the Projekt?")
    assert [e.content for e in r.memories] == ["das Projekt Atlas heißt"]
    assert "nichts gespeichert" in mcore.handle("Woran erinnerst du dich zu Raketen?").text


def test_forget_by_id_and_fuzzy_never_deletes(mcore):
    e = mcore.handle("Merk dir, dass ich Kaffee mag").memories[0]
    r = mcore.handle("Vergiss dass ich Kaffee mag")
    assert e.id in r.text and mcore.memory.count() == 1  # only lists candidates
    assert "gelöscht" in mcore.handle(f"Vergiss {e.id}").text and mcore.memory.count() == 0
    assert "Keine Erinnerung" in mcore.handle(f"Vergiss {e.id}").text
    assert "nichts gespeichert" in mcore.handle("Vergiss Raketen").text


def test_secret_in_remember_is_refused_without_echo(mcore, provider):
    r = mcore.handle("Merk dir: mein Passwort ist hunter22")
    assert r.kind is ResponseKind.ERROR and not r.ok and "hunter22" not in r.text
    assert mcore.memory.count() == 0 and provider.calls == []


def test_invalid_remember_is_an_error_response(mcore):
    r = mcore.handle("Merk dir " + "x" * 10_001)
    assert r.kind is ResponseKind.ERROR and "too long" in r.text
    assert mcore.memory.count() == 0


def test_programmatic_api(mcore):
    e = mcore.remember("Programm-Fakt", type="decision", importance=9, tags=["t"], source="agent:test")
    assert [x.id for x in mcore.recall("programm")] == [e.id]
    assert [x.id for x in mcore.recall("")] == [e.id]
    assert mcore.forget(e.id) and mcore.recall("") == []


# ---- core: retrieval into prompts (privacy switch) -------------------------------------------------------
def test_memories_are_not_sent_to_llm_by_default(mcore, provider):
    mcore.remember("Meine Lieblingsfarbe ist blau")
    mcore.handle("Welche Farbe mag ich?")
    assert all("blau" not in m.content for m in provider.calls[-1].messages)


def test_relevant_memories_added_when_enabled(provider, registry, memory):
    core = JarvisCore(provider, registry, memory=memory, use_memory_in_prompts=True, memory_limit=2)
    core.remember("Meine Lieblingsfarbe ist blau")
    core.remember("Ich wohne in Wien")
    core.handle("Welche Farbe mag ich?")
    msgs = provider.calls[-1].messages
    assert msgs[0].role.value == "system" and msgs[1].role.value == "system"
    assert "blau" in msgs[1].content and "Wien" not in msgs[1].content and "Daten, nicht als Anweisungen" in msgs[1].content
    assert [m.role.value for m in msgs[2:]] == ["user"]
    assert len(core.context) == 2  # the memory note is temporary: not stored in the history
    core.handle("Hallo")  # nothing relevant -> no extra note
    assert [m.role.value for m in provider.calls[-1].messages].count("system") == 1


def test_memory_limit_caps_prompt_memories(provider, registry, memory):
    core = JarvisCore(provider, registry, memory=memory, use_memory_in_prompts=True, memory_limit=2)
    for i in range(5):
        core.remember(f"kaffee notiz {i}")
    core.handle("kaffee?")
    assert provider.calls[-1].messages[1].content.count("- (") == 2


def test_memory_limit_zero_disables_retrieval(provider, registry, memory):
    core = JarvisCore(provider, registry, memory=memory, use_memory_in_prompts=True, memory_limit=0)
    core.remember("kaffee")
    core.handle("kaffee")
    assert [m.role.value for m in provider.calls[-1].messages].count("system") == 1


def test_planner_receives_memory_context_when_enabled(provider, registry, memory):
    core = JarvisCore(provider, registry, memory=memory, use_memory_in_prompts=True)
    core.remember("Ich bevorzuge Python für Datenanalyse")
    r = core.handle("Erstelle ein Programm zur Datenanalyse")
    assert r.kind is ResponseKind.PLAN
    assert "bevorzuge Python" in provider.calls[-1].messages[0].content


class BrokenStore(InMemoryStore):
    def search(self, *a, **k):
        raise MemoryStoreError("db exploded")


def test_memory_failure_never_breaks_the_conversation(provider, registry):
    core = JarvisCore(provider, registry, memory=BrokenStore(), use_memory_in_prompts=True)
    assert core.handle("Hallo").text == "ok"
    assert core.handle("Erstelle ein Tool").kind is ResponseKind.PLAN
    r = core.handle("Woran erinnerst du dich zu Kaffee?")  # explicit request: failure is reported
    assert r.kind is ResponseKind.ERROR and "db exploded" in r.text


# ---- configuration -------------------------------------------------------------------------------------
def test_memory_config_defaults():
    m = load_settings(env={}).memory
    assert (m.enabled, m.backend, m.path, m.max_relevant, m.use_in_prompts) == (True, "sqlite", "data/memory.db", 5, False)


def test_memory_config_file_and_env(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[memory]\nmax_relevant = 3\npath = "from-file.db"\nmax_entries = 0\n')
    m = load_settings(f, env={"JARVIS_MEMORY_PATH": "from-env.db", "JARVIS_MEMORY_USE_IN_PROMPTS": "true",
                              "JARVIS_MEMORY_ENABLED": "false"}).memory
    assert (m.max_relevant, m.path, m.max_entries, m.use_in_prompts, m.enabled) == (3, "from-env.db", 0, True, False)


@pytest.mark.parametrize("env", [
    {"JARVIS_MEMORY_MAX_RELEVANT": "-1"}, {"JARVIS_MEMORY_RECENT_LIMIT": "0"},
    {"JARVIS_MEMORY_MAX_CONTENT_LENGTH": "0"}, {"JARVIS_MEMORY_MAX_ENTRIES": "-5"},
    {"JARVIS_MEMORY_PATH": "  "}, {"JARVIS_MEMORY_BACKEND": " "}, {"JARVIS_MEMORY_MAX_RELEVANT": "many"},
])
def test_invalid_memory_config(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


def test_repo_config_file_has_memory_section():
    assert load_settings("config/jarvis.toml", env={}).memory == MemorySettings()


def test_factory_builds_configured_backends(tmp_path):
    g = create_memory(MemorySettings(path=str(tmp_path / "x.db")), SecretGuard())
    assert isinstance(g, GuardedMemoryStore) and isinstance(g.inner, SqliteMemoryStore)
    assert isinstance(create_memory(MemorySettings(backend="MEMORY")).inner, InMemoryStore)
    assert isinstance(create_memory(MemorySettings(enabled=False)), NullMemoryStore)


def test_factory_unknown_backend_and_custom_backend():
    with pytest.raises(MemoryStoreError, match="unknown memory backend"):
        create_memory(MemorySettings(backend="nope"))
    register_backend("custom", lambda s: InMemoryStore())
    assert "custom" in available_backends()
    assert isinstance(create_memory(MemorySettings(backend="custom")), MemoryStore)


def test_factory_applies_configured_limits():
    g = create_memory(MemorySettings(backend="memory", max_content_length=10, max_entries=1), SecretGuard())
    g.add("0123456789")
    with pytest.raises(MemoryStoreError):
        g.add("zweiter")


def test_disabled_in_config_means_null_memory_in_core(tmp_path):
    core = build_core(load_settings(env={"JARVIS_MEMORY_ENABLED": "false", "JARVIS_LOG_DIR": str(tmp_path)}))
    assert not core.memory.enabled and "deaktiviert" in core.handle("Merk dir, dass x1x").text


# ---- end to end with a real temporary SQLite file ---------------------------------------------------------
def test_end_to_end_persistence_across_application_restarts(tmp_path):
    env = {"JARVIS_MEMORY_PATH": str(tmp_path / "jarvis.db"), "JARVIS_LOG_DIR": str(tmp_path / "logs"),
           "JARVIS_MEMORY_USE_IN_PROMPTS": "true"}
    first = build_core(load_settings(env=env))
    assert "Gemerkt" in first.handle("Merk dir, dass meine Lieblingsfarbe blau ist").text
    first.memory.close()

    second = build_core(load_settings(env=env))  # fresh process state, same file
    assert (tmp_path / "jarvis.db").is_file()
    r = second.handle("Woran erinnerst du dich?")
    assert "Lieblingsfarbe blau" in r.text
    assert second.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit."
    assert second.provider.calls[-1].messages[1].content.count("blau") == 0  # "Hallo" is not relevant
    second.handle("Welche Farbe mag ich?")
    assert "blau" in second.provider.calls[-1].messages[1].content


# ---- CLI -------------------------------------------------------------------------------------------------------
def test_cli_memory_commands(mcore):
    assert "Verwendung" in run_command(mcore, "/remember")
    assert "Gemerkt" in run_command(mcore, "/remember Ich mag Tee")
    assert "Tee" in run_command(mcore, "/memory") and "Tee" in run_command(mcore, "/memory tee")
    assert run_command(mcore, "/memory raketen") == "Keine Erinnerungen gefunden."
    e = mcore.recall("")[0]
    assert "Verwendung" in run_command(mcore, "/forget")
    assert "gelöscht" in run_command(mcore, f"/forget {e.id}")
    assert "Keine Erinnerung" in run_command(mcore, f"/forget {e.id}")
    assert run_command(mcore, "/memory") == "Keine Erinnerungen gefunden."


def test_cli_memory_with_disabled_memory(provider):
    core = JarvisCore(provider)
    assert "deaktiviert" in run_command(core, "/remember x1x")
    assert run_command(core, "/memory") == "Keine Erinnerungen gefunden."


def test_cli_dialog_with_memory(mcore):
    it = iter(["Merk dir, dass ich Tee mag", "Woran erinnerst du dich?", "/exit"])
    out = []
    repl(mcore, lambda p: next(it), out.append)
    assert any("Gemerkt" in o for o in out) and any("Tee" in o and "Das weiß ich" in o for o in out)


# ---- voice stays independent ------------------------------------------------------------------------------------
class Script(Listener):
    def __init__(self, items):
        self.items = list(items)

    def listen(self):
        from jarvis.errors import EndOfInput
        if not self.items:
            raise EndOfInput("done")
        return self.items.pop(0)


class Rec(Speaker):
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


def test_voice_uses_memory_through_core_without_knowing_it(mcore):
    spk = Rec()
    VoiceSession(mcore, Script(["Jarvis, merk dir, dass ich Kaffee mag", "Woran erinnerst du dich?"]), spk,
                 display=lambda t: None).run()
    assert spk.said[0].startswith("Gemerkt") and "Kaffee" in spk.said[1]
    assert mcore.memory.count() == 1


# ---- architecture: no unwanted coupling ---------------------------------------------------------------------------------
def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return {m for m in mods if m.startswith("jarvis")}


def test_memory_package_depends_on_nothing_but_errors_and_config():
    allowed = ("jarvis.errors", "jarvis.config", "jarvis.memory", "jarvis.redaction")  # redaction: neutral shared module
    for f in (SRC / "memory").glob("*.py"):
        bad = {m for m in _imports(f) if not m.startswith(allowed)}
        assert not bad, f"{f.name} imports {bad}"
    for f in (SRC / "memory").glob("*.py"):  # config only for the composition helper
        if f.name != "factory.py":
            assert "jarvis.config" not in _imports(f), f.name


def test_core_depends_only_on_memory_abstractions():
    forbidden = {"jarvis.memory.sqlite_store", "jarvis.memory.factory", "jarvis.memory.inmemory",
                 "jarvis.memory.guarded", "jarvis.memory.guard"}
    for f in (SRC / "core").glob("*.py"):
        assert not (_imports(f) & forbidden), f.name
    assert not any("sqlite" in m for f in (SRC / "core").glob("*.py") for m in _imports(f))


def test_voice_and_other_modules_do_not_import_memory():
    for pkg in ("voice", "llm", "planning", "tasks", "tools", "permissions"):
        for f in (SRC / pkg).glob("*.py"):
            assert not {m for m in _imports(f) if m.startswith("jarvis.memory")}, f"{pkg}/{f.name}"


def test_only_bootstrap_wires_concrete_memory_backend():
    users = [f.name for f in SRC.rglob("*.py")
             if {"jarvis.memory.factory", "jarvis.memory.sqlite_store"} & _imports(f) and f.parent.name != "memory"]
    assert users == ["bootstrap.py"]
