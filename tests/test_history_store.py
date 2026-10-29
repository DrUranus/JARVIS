"""Persistente Historie abgeschlossener Arbeit (Ziele, Agenten-Tasks, Reparaturlaeufe, Plaene).

Nur Historie und Anzeige: nach einem Neustart wird nichts fortgesetzt. Alles mit tmp_path, ohne Netzwerk, ohne Wartezeiten."""
import ast
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents_util import FakeAgent
from goals_util import chain, rig
from jarvis.config import HistorySettings, Settings, load_settings
from jarvis.core import JarvisCore
from jarvis.errors import ConfigError
from jarvis.history import HistoryError, HistoryRecorder, HistoryStore, build_history
from jarvis.interface.cli import run_command
from jarvis.interface.gui_model import GuiController
from jarvis.llm.mock import MockProvider
from jarvis.redaction import SecretDetector
from jarvis.self_repair.models import RepairRun
from jarvis.self_repair.state import RepairStatus
from jarvis.tasks.manager import TaskManager
from jarvis.tasks.task import Task

ROOT = Path(__file__).resolve().parents[1]
KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"          # sieht aus wie ein API-Schluessel
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def store_at(path, **kw):
    return HistoryStore(path, **kw)


# ---------------------------------------------------------------- Speicher, Neustart
def test_entries_survive_a_restart(tmp_path):
    db = tmp_path / "h.db"
    s = store_at(db)
    s.add("goal", "g1", "SUCCEEDED", "Marktanalyse fertig", created_at=T0, finished_at=T0)
    s.add("repair", "r1", "FAILED", "Tests rot", error="tests_failed")
    s.close()
    again = store_at(db)                                   # "Neustart": neues Objekt, gleiche Datei
    got = {(e.kind, e.ref_id): e for e in again.list()}
    assert set(got) == {("goal", "g1"), ("repair", "r1")}
    assert got[("goal", "g1")].status == "SUCCEEDED" and got[("goal", "g1")].summary == "Marktanalyse fertig"
    assert got[("goal", "g1")].finished_at == T0 and got[("repair", "r1")].error == "tests_failed"


def test_nothing_is_created_before_the_first_write_and_reads_on_a_missing_db_are_empty(tmp_path):
    db = tmp_path / "sub" / "h.db"
    s = store_at(db)
    assert s.list() == [] and s.count() == 0 and not db.exists() and not db.parent.exists()


def test_same_item_is_updated_not_duplicated(tmp_path):
    s = store_at(tmp_path / "h.db")
    s.add("task", "t1", "FAILED", "x", error="boom")
    s.add("task", "t1", "COMPLETED", "x")
    assert s.count() == 1 and s.list()[0].status == "COMPLETED" and s.list()[0].error is None


def test_a_foreign_or_corrupt_file_is_reported_and_never_overwritten(tmp_path):
    db = tmp_path / "h.db"
    db.write_bytes(b"das ist keine sqlite-datei" * 20)
    before = db.read_bytes()
    s = store_at(db)
    with pytest.raises(HistoryError):
        s.add("goal", "g", "SUCCEEDED", "x")
    with pytest.raises(HistoryError):
        s.list()
    assert db.read_bytes() == before


# ---------------------------------------------------------------- Obergrenze
def test_the_number_of_entries_is_capped_and_the_newest_survive(tmp_path):
    s = store_at(tmp_path / "h.db", max_entries=5)
    for i in range(12):
        s.add("goal", f"g{i}", "SUCCEEDED", f"ziel {i}")
    assert s.count() == 5
    assert [e.ref_id for e in s.list(limit=50)] == ["g11", "g10", "g9", "g8", "g7"]


def test_text_length_is_capped(tmp_path):
    s = store_at(tmp_path / "h.db", max_text_length=50)
    s.add("goal", "g", "SUCCEEDED", "x" * 5000, error="y" * 5000)
    e = s.list()[0]
    assert len(e.summary) <= 50 and len(e.error) <= 50


def test_store_limits_are_validated(tmp_path):
    for bad in (0, -1, 100_001):
        with pytest.raises(HistoryError):
            store_at(tmp_path / "h.db", max_entries=bad)
    with pytest.raises(HistoryError):
        store_at(tmp_path / "h.db", max_text_length=0)


# ---------------------------------------------------------------- Datenschutz
def test_no_secret_reaches_the_file(tmp_path):
    db = tmp_path / "h.db"
    det = SecretDetector(known_secrets=["geheimer-wert-12345"])
    s = store_at(db, detector=det)
    s.add("goal", "g1", "FAILED", f"Nutze {KEY} und password=hunter2hunter2 sowie geheimer-wert-12345",
          error=f"Authorization: Bearer {KEY}")
    s.add("task", "t1", "COMPLETED", "ok")
    s.close()
    raw = db.read_bytes()
    for secret in (KEY.encode(), b"hunter2hunter2", b"geheimer-wert-12345"):
        assert secret not in raw
    con = sqlite3.connect(db)
    dump = "\n".join(con.iterdump())
    con.close()
    assert KEY not in dump and "hunter2" not in dump and "[REDACTED]" in dump


def test_secrets_in_ids_and_kinds_are_not_stored_either(tmp_path):
    db = tmp_path / "h.db"
    s = store_at(db)
    with pytest.raises(HistoryError):
        s.add("goal", f"id-{KEY}", "SUCCEEDED", "x")
    with pytest.raises(HistoryError):
        s.add("geheim", "g", "SUCCEEDED", "x")           # nur bekannte Arten
    assert s.count() == 0


# ---------------------------------------------------------------- Recorder mit echten Quellen
def finished_goal_rig():
    engine, orch, *_ = rig([FakeAgent("fake")], chain("s1"))
    goal = engine.create("Marktanalyse erstellen")
    engine.run(goal.goal_id)
    return engine, orch, goal


def test_finished_goal_and_agent_tasks_survive_a_restart(tmp_path):
    db = tmp_path / "h.db"
    engine, orch, goal = finished_goal_rig()
    tasks = TaskManager()
    done = tasks.create("Webseite bauen")
    done.transition(done.status.__class__.RUNNING)
    done.complete(f"fertig, Token {KEY}")
    rec = HistoryRecorder(store_at(db), goals=engine, agents=orch, tasks=tasks)
    assert rec.sync() >= 3
    # Neustart: alle Laufzeitobjekte weg, nur die Datei bleibt
    again = store_at(db)
    got = {(e.kind, e.ref_id): e for e in again.list(limit=100)}
    assert got[("goal", goal.goal_id)].status == "SUCCEEDED" and "Marktanalyse" in got[("goal", goal.goal_id)].summary
    assert any(k == "agent_task" for k, _ in got)
    t = got[("task", done.id)]
    assert t.status == "COMPLETED" and KEY not in t.summary


def test_finished_repair_survives_a_restart(tmp_path):
    db = tmp_path / "h.db"
    run = RepairRun(objective="Tests reparieren", workspace="ws", status=RepairStatus.FAILED, created_at=T0, finished_at=T0,
                    failure_summary="3 Tests rot", final_summary="aufgegeben")
    repairs = SimpleNamespace(list=lambda status=None, limit=None: [run],
                              result=lambda rid: SimpleNamespace(reason_code="max_attempts", run=run))
    HistoryRecorder(store_at(db), repairs=repairs).sync()
    e = store_at(db).list()[0]
    assert (e.kind, e.ref_id, e.status, e.error) == ("repair", run.run_id, "FAILED", "max_attempts")
    assert "Tests reparieren" in e.summary and e.finished_at == T0


def test_unfinished_work_is_not_recorded(tmp_path):
    engine, orch, *_ = rig([FakeAgent("fake")], chain("s1"))
    pending = engine.create("noch offen")                 # PENDING
    tasks = TaskManager()
    tasks.create("offener Plan")
    rec = HistoryRecorder(store_at(tmp_path / "h.db"), goals=engine, agents=orch, tasks=tasks)
    assert rec.sync() == 0 and rec.store.count() == 0
    assert engine.get(pending.goal_id).status.value == "PENDING"


def test_sync_is_idempotent(tmp_path):
    engine, orch, _ = finished_goal_rig()
    rec = HistoryRecorder(store_at(tmp_path / "h.db"), goals=engine, agents=orch)
    rec.sync()
    n = rec.store.count()
    rec.sync()
    assert rec.store.count() == n


def test_a_broken_source_or_store_never_breaks_the_caller(tmp_path):
    bad_source = SimpleNamespace(list=lambda **kw: (_ for _ in ()).throw(RuntimeError("kaputt")))
    tasks = TaskManager()
    t = tasks.create("x")
    t.transition(t.status.__class__.CANCELLED)
    rec = HistoryRecorder(store_at(tmp_path / "h.db"), goals=bad_source, tasks=tasks)
    assert rec.sync() == 1                                # die anderen Quellen laufen weiter
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"x" * 500)
    assert HistoryRecorder(store_at(junk), tasks=tasks).sync() == 0


# ---------------------------------------------------------------- Nach Neustart laeuft nichts weiter
class Tripwire:
    """Jeder Aufruf, der etwas starten, anlegen oder fortsetzen wuerde, schlaegt fehl."""
    def __getattr__(self, name):
        if name in {"list", "result", "get", "steps"}:
            return lambda *a, **k: []
        raise AssertionError(f"history touched {name!r}")


def test_a_restart_with_stored_history_starts_nothing(tmp_path):
    db = tmp_path / "h.db"
    s = store_at(db)
    s.add("goal", "g1", "FAILED", "x")      # selbst ein exotischer Eintrag loest nichts aus
    s.add("repair", "r1", "FAILED", "x")
    s.close()
    core = JarvisCore(MockProvider())
    core.subsystems["goals"] = SimpleNamespace(engine=Tripwire())
    core.subsystems["self_repair"] = SimpleNamespace(engine=Tripwire())
    core.subsystems["agents"] = SimpleNamespace(orchestrator=Tripwire())
    core.history = HistoryRecorder(store_at(db), goals=Tripwire(), repairs=Tripwire(), agents=Tripwire(), tasks=core.tasks)
    assert [e.ref_id for e in core.history_entries()] == ["r1", "g1"]
    assert core.tasks.open_tasks() == []                  # nichts wieder aufgenommen
    out = run_command(core, "/history")
    assert "g1" in out and "r1" in out
    assert core.tasks.open_tasks() == []


def test_history_code_never_starts_creates_or_executes_anything():
    forbidden = {"run", "run_goal", "run_repair", "create", "create_goal", "create_repair", "submit", "start", "resume", "execute", "authorize",
                 "approve", "halt", "reset", "plan", "handle", "wait", "Thread", "Popen", "system", "cancel", "enable"}
    files = sorted((ROOT / "src" / "jarvis" / "history").glob("*.py"))
    assert files
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        banned = forbidden - ({"execute"} if f.name == "store.py" else set())       # store.py: sqlite3's own execute (SQL), not tool execution
        assert not used & banned, f"{f.name}: {used & banned}"
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                assert not any(m.split(".")[0] in {"threading", "subprocess", "socket", "urllib", "http", "requests", "asyncio", "sched"} for m in mods if not (m == "threading" and f.name == "store.py")), f.name       # store.py: only a Lock (Thread is banned above)


# ---------------------------------------------------------------- Opt-in, Standardverhalten
def test_default_is_off_and_validated():
    assert HistorySettings().enabled is False and Settings().history.enabled is False
    assert build_history(Settings(), JarvisCore(MockProvider()), SecretDetector()) is None
    for kv in ({"max_entries": 0}, {"max_entries": 100_001}, {"max_text_length": 0}, {"path": ""}):
        with pytest.raises(ConfigError):
            Settings(history=HistorySettings(enabled=True, **kv)).validate()


def test_shipped_config_keeps_history_off():
    s = load_settings(ROOT / "config" / "jarvis.toml", env={})
    assert s.history.enabled is False


def test_opt_in_through_env_and_toml(tmp_path):
    assert load_settings(env={"JARVIS_HISTORY_ENABLED": "true"}).history.enabled is True
    cfg = tmp_path / "c.toml"
    cfg.write_text('[history]\nenabled = true\nmax_entries = 7\n', encoding="utf-8")
    s = load_settings(cfg, env={})
    assert s.history.enabled and s.history.max_entries == 7


def test_default_core_has_no_history_and_writes_no_file(tmp_path, monkeypatch):
    from jarvis.bootstrap import build_core
    monkeypatch.chdir(tmp_path)
    core = build_core(Settings(mode="production", log_dir=str(tmp_path / "logs")))
    assert core.history is None and core.history_entries() == []
    assert not list(tmp_path.glob("data/history.db"))
    assert "deaktiviert" in run_command(core, "/history")


def test_opt_in_core_records_after_a_run_and_creates_the_file_on_first_write(tmp_path, monkeypatch):
    from jarvis.bootstrap import build_core
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "hist.db"
    settings = Settings(mode="production", log_dir=str(tmp_path / "logs"),
                        history=HistorySettings(enabled=True, path=str(db)))
    core = build_core(settings)
    assert core.history is not None and not db.exists()
    t = core.tasks.create("Plan A")
    core.tasks.cancel(t.id)
    assert [e.ref_id for e in core.history_entries()] == [t.id] and db.exists()
    restarted = build_core(settings)                      # Neustart
    assert [e.ref_id for e in restarted.history_entries()] == [t.id]
    assert restarted.tasks.open_tasks() == [] and restarted.tasks.list() == []


def test_run_goal_and_cancel_record_into_the_history(tmp_path):
    engine, orch, *_ = rig([FakeAgent("fake")], chain("s1"))
    core = JarvisCore(MockProvider())
    core.subsystems["goals"] = SimpleNamespace(engine=engine)
    core.history = HistoryRecorder(store_at(tmp_path / "h.db"), goals=engine, agents=orch)
    goal = core.create_goal("Bericht schreiben")
    core.run_goal(goal.goal_id)
    assert any(e.ref_id == goal.goal_id and e.status == "SUCCEEDED" for e in core.history.store.list(limit=100))


# ---------------------------------------------------------------- GUI-Status
def test_gui_status_shows_the_history_lines(tmp_path):
    core = JarvisCore(MockProvider())
    core.history = HistoryRecorder(store_at(tmp_path / "h.db"), tasks=core.tasks)
    t = core.tasks.create("Plan A")
    core.tasks.cancel(t.id)
    snap = GuiController(core).collect_activity()
    assert any("Plan A" in line and "CANCELLED" in line for line in snap.history)
    assert GuiController(JarvisCore(MockProvider())).collect_activity().history == ()
