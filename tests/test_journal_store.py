"""Aufgaben-Journal (Ziele, Agenten-Tasks, Schritte): nur Speichern und Lesen, nichts wird fortgesetzt oder gestartet.

Alles mit tmp_path, ohne Netzwerk, ohne Wartezeiten."""
import ast
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents_util import FakeAgent
from goals_util import chain, rig
from jarvis.config import JournalSettings, Settings, load_settings
from jarvis.core import JarvisCore
from jarvis.errors import ConfigError
from jarvis.journal import JournalError, JournalRecorder, JournalStore, build_journal
from jarvis.llm.mock import MockProvider
from jarvis.redaction import SecretDetector

ROOT = Path(__file__).resolve().parents[1]
KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def step(n, side=False, **kw):
    return {"step_id": f"s{n}", "status": "SUCCEEDED", "text": f"schritt {n}", "side_effect": side, **kw}


# ---------------------------------------------------------------- Neustart
def test_journal_survives_a_restart_with_steps_and_markers(tmp_path):
    db = tmp_path / "j.db"
    s = JournalStore(db)
    s.record("goal", "g1", "SUCCEEDED", "Ziel", result="fertig", evidence=["datei a", "datei b"], created_at=T0, finished_at=T0,
             steps=[step(1, False, started_at=T0, finished_at=T0), step(2, True, result="geschrieben", evidence=["x.txt"], error="e")])
    s.record("agent_task", "t1", "FAILED", "agent", error="boom")
    s.close()
    again = JournalStore(db)                                       # "Neustart"
    g = again.get("goal", "g1")
    assert g.status == "SUCCEEDED" and g.result == "fertig" and g.evidence == ("datei a", "datei b") and g.finished_at == T0
    assert [(x.step_no, x.step_id, x.side_effect) for x in g.steps] == [(1, "s1", False), (2, "s2", True)]
    assert g.steps[1].result == "geschrieben" and g.steps[1].evidence == ("x.txt",) and g.steps[1].error == "e" and g.steps[0].started_at == T0
    assert {e.ref_id for e in again.list()} == {"g1", "t1"} and again.count() == 2
    assert again.get("goal", "nope") is None


def test_rerecording_replaces_steps_without_duplicates(tmp_path):
    s = JournalStore(tmp_path / "j.db")
    s.record("goal", "g", "RUNNING", "x", steps=[step(1), step(2)])
    s.record("goal", "g", "SUCCEEDED", "x", steps=[step(1)])
    e = s.get("goal", "g")
    assert s.count() == 1 and e.status == "SUCCEEDED" and len(e.steps) == 1


def test_nothing_is_created_before_the_first_write(tmp_path):
    db = tmp_path / "sub" / "j.db"
    s = JournalStore(db)
    assert s.list() == [] and s.count() == 0 and s.get("goal", "g") is None and not db.exists() and not db.parent.exists()


# ---------------------------------------------------------------- Obergrenzen
def test_entries_are_capped_and_orphan_steps_removed(tmp_path):
    db = tmp_path / "j.db"
    s = JournalStore(db, max_entries=3)
    for i in range(8):
        s.record("goal", f"g{i}", "SUCCEEDED", f"z{i}", steps=[step(1)])
    assert [e.ref_id for e in s.list(50)] == ["g7", "g6", "g5"]
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM journal_steps").fetchone()[0] == 3


def test_steps_text_and_evidence_are_capped(tmp_path):
    s = JournalStore(tmp_path / "j.db", max_steps_per_entry=4, max_text_length=40, max_evidence=2)
    s.record("goal", "g", "SUCCEEDED", "x" * 999, result="r" * 999, evidence=["e" * 999] * 9, error="y" * 999,
             steps=[step(i, text="t" * 999, result="r" * 999, evidence=["z" * 999] * 7) for i in range(1, 30)])
    e = s.get("goal", "g")
    assert len(e.steps) == 4 and [x.step_no for x in e.steps] == [1, 2, 3, 4]
    assert len(e.text) <= 40 and len(e.result) <= 40 and len(e.error) <= 40 and len(e.evidence) == 2 and all(len(x) <= 40 for x in e.evidence)
    assert all(len(x.text) <= 40 and len(x.result) <= 40 and len(x.evidence) == 2 for x in e.steps)


def test_limits_and_inputs_are_validated(tmp_path):
    for kw in ({"max_entries": 0}, {"max_entries": 100_001}, {"max_steps_per_entry": 0}, {"max_steps_per_entry": 201},
               {"max_text_length": 0}, {"max_evidence": 0}, {"max_evidence": 21}):
        with pytest.raises(JournalError):
            JournalStore(tmp_path / "j.db", **kw)
    s = JournalStore(tmp_path / "j.db")
    with pytest.raises(JournalError):
        s.record("plan", "g", "SUCCEEDED")
    with pytest.raises(JournalError):
        s.record("goal", "../x", "SUCCEEDED")
    with pytest.raises(JournalError):
        s.record("goal", "g", "succeeded")
    with pytest.raises(JournalError):
        s.record("goal", "g", "SUCCEEDED", steps=[{"step_id": "s1", "status": "SUCCEEDED", "text": "x"}])      # side_effect fehlt
    with pytest.raises(JournalError):
        s.record("goal", "g", "SUCCEEDED", steps=[step(1, side=1)])                                           # kein bool
    assert s.count() == 0


# ---------------------------------------------------------------- Redaktion
def test_no_secret_reaches_the_file(tmp_path):
    db = tmp_path / "j.db"
    s = JournalStore(db, detector=SecretDetector(known_secrets=["geheimer-wert-12345"]))
    s.record("goal", "g1", "FAILED", f"Nutze {KEY} und password=hunter2hunter2", result="geheimer-wert-12345", evidence=[f"Bearer {KEY}"],
             error=f"Authorization: Bearer {KEY}",
             steps=[step(1, True, text=f"key {KEY}", result="password=hunter2hunter2", evidence=["geheimer-wert-12345"], error=f"{KEY}")])
    with pytest.raises(JournalError):
        s.record("goal", KEY, "FAILED", "x")                                  # ID mit Secret abgelehnt
    raw = db.read_bytes()
    for secret in (KEY.encode(), b"hunter2hunter2", b"geheimer-wert-12345"):
        assert secret not in raw
    assert "[REDACTED]" in s.get("goal", "g1").text


# ---------------------------------------------------------------- Kaputte Datei
def test_a_foreign_or_corrupt_file_is_reported_and_never_overwritten(tmp_path):
    db = tmp_path / "j.db"
    db.write_bytes(b"das ist keine sqlite-datei" * 20)
    before = db.read_bytes()
    s = JournalStore(db)
    with pytest.raises(JournalError):
        s.record("goal", "g", "SUCCEEDED", "x")
    for call in (s.list, s.count, lambda: s.get("goal", "g")):
        with pytest.raises(JournalError):
            call()
    assert db.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["j.db"]                 # nichts verschoben, nichts daneben angelegt


def test_recorder_survives_a_corrupt_file(tmp_path):
    db = tmp_path / "j.db"
    db.write_bytes(b"kaputt" * 50)
    before = db.read_bytes()
    eng, *_ = rig([FakeAgent("fake")], chain("s1"))
    eng.run(eng.create("Ziel").goal_id)
    rec = JournalRecorder(JournalStore(db), goals=eng)
    assert rec.sync() == 0 and db.read_bytes() == before


# ---------------------------------------------------------------- Recorder: nur lesen
def test_recorder_copies_goals_with_steps_and_marks_side_effects(tmp_path):
    eng, orch, *_ = rig([FakeAgent("fake")], chain("s1", "s2"))
    gid = eng.create("Markt analysieren").goal_id
    eng.run(gid)
    rec = JournalRecorder(JournalStore(tmp_path / "j.db"), goals=eng, agents=orch)
    got = {(e.kind, e.ref_id): e for e in rec.entries()}
    g = got[("goal", gid)]
    assert g.status == "SUCCEEDED" and g.text == "Markt analysieren" and len(g.steps) >= 2
    assert all(isinstance(x.side_effect, bool) for x in g.steps) and [x.step_no for x in g.steps] == list(range(1, len(g.steps) + 1))
    assert any(k == "agent_task" for k, _ in got)


def test_side_effect_marking_is_conservative():
    from jarvis.journal.recorder import side_effect
    assert side_effect({"browser.read"}, "a") is False and side_effect({"computer.screen", "coding.plan"}, "a") is False
    assert side_effect({"browser.read", "coding.write"}, "a") is True and side_effect({"computer.input"}, "a") is True
    assert side_effect({"weird"}, "a") is True and side_effect(set(), "a") is True and side_effect(set(), None) is False


def test_recorder_tolerates_broken_sources(tmp_path):
    class Boom:
        def list(self, *a, **k):
            raise RuntimeError("kaputt")
    rec = JournalRecorder(JournalStore(tmp_path / "j.db"), goals=Boom(), agents=Boom())
    assert rec.sync() == 0 and rec.entries() == []


# ---------------------------------------------------------------- Standard aus, Konfiguration
def test_default_is_off_and_validated():
    assert JournalSettings().enabled is False and Settings().journal.enabled is False
    assert build_journal(Settings(), JarvisCore(MockProvider()), SecretDetector()) is None
    for kv in ({"max_entries": 0}, {"max_entries": 100_001}, {"max_steps_per_entry": 0}, {"max_steps_per_entry": 201},
               {"max_text_length": 0}, {"max_evidence": 0}, {"max_evidence": 21}, {"path": ""}):
        with pytest.raises(ConfigError):
            Settings(journal=JournalSettings(enabled=True, **kv)).validate()


def test_disabled_creates_no_file(tmp_path):
    p = tmp_path / "j.db"
    assert build_journal(Settings(journal=JournalSettings(path=str(p))), JarvisCore(MockProvider()), SecretDetector()) is None and not p.exists()


def test_enabled_builds_a_recorder(tmp_path):
    s = Settings(journal=JournalSettings(enabled=True, path=str(tmp_path / "j.db")))
    assert isinstance(build_journal(s, JarvisCore(MockProvider()), SecretDetector()), JournalRecorder)


def test_shipped_config_is_untouched_and_journal_is_off():
    assert "journal" not in (ROOT / "config" / "jarvis.toml").read_text(encoding="utf-8")
    assert load_settings(ROOT / "config" / "jarvis.toml", env={}).journal.enabled is False


def test_opt_in_through_env_and_toml(tmp_path):
    assert load_settings(env={"JARVIS_JOURNAL_ENABLED": "true"}).journal.enabled is True
    cfg = tmp_path / "c.toml"
    cfg.write_text('[journal]\nenabled = true\nmax_entries = 7\n', encoding="utf-8")
    s = load_settings(cfg, env={})
    assert s.journal.enabled and s.journal.max_entries == 7


def test_not_wired_and_no_new_dependency():
    assert "journal" not in (ROOT / "src" / "jarvis" / "bootstrap.py").read_text(encoding="utf-8")
    import tomllib
    assert tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"] == []


# ---------------------------------------------------------------- Strukturtest: nichts starten, nichts fortsetzen
def test_journal_code_never_starts_creates_resumes_or_executes_anything():
    forbidden = {"run", "run_goal", "create", "create_goal", "submit", "start", "resume", "execute", "authorize", "approve", "halt", "reset",
                 "plan", "handle", "wait", "Thread", "Timer", "Popen", "system", "cancel", "enable", "subscribe"}
    files = sorted((ROOT / "src" / "jarvis" / "journal").glob("*.py"))
    assert {f.name for f in files} >= {"store.py", "recorder.py", "factory.py"}
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        banned = forbidden - ({"execute"} if f.name == "store.py" else set())       # store.py: sqlite3-eigenes execute (SQL)
        assert not used & banned, f"{f.name}: {used & banned}"
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                assert not any(m.split(".")[0] in {"subprocess", "socket", "urllib", "http", "requests", "asyncio", "sched", "jarvis.tools"}
                               or m.startswith("jarvis.tools") or m.startswith("jarvis.permissions") for m in mods), f.name


def test_recorder_only_reads_sources(tmp_path):
    calls = []

    class Spy:
        def __getattr__(self, name):
            calls.append(name)
            if name in ("list", "result"):
                return lambda *a, **k: []
            raise AssertionError(f"unexpected call {name}")
    JournalRecorder(JournalStore(tmp_path / "j.db"), goals=Spy(), agents=Spy()).sync()
    assert set(calls) <= {"list", "result"}
