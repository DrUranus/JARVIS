"""Journal nach hartem Prozessende (Aufgabe 9): ein Kindprozess schreibt Eintraege in Dauerschleife und wird ohne Aufraeumen beendet (kill, auch unter Windows).
Danach muss die Datei konsistent lesbar sein, der unterbrochene Eintrag als unterbrochen auftauchen, und das Auflisten darf nichts starten oder anlegen.
Keine Geheimnisse im Journal. Echte SQLite-Datei in tmp_path, kein Netzwerk."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from jarvis.journal import JournalStore
from test_journal_resume import Rig

SRC = str(Path(__file__).resolve().parents[1] / "src")
CHILD = """
import sys, time
from pathlib import Path
sys.path.insert(0, {src!r})
from jarvis.journal import JournalStore
db, flag = Path(sys.argv[1]), Path(sys.argv[2])
s = JournalStore(db)
n = 0
while True:
    n += 1
    steps = [{{"step_id": f"s{{i}}", "status": "SUCCEEDED" if i < 3 else "PENDING", "text": f"schritt {{i}}", "side_effect": i == 3}} for i in range(1, 6)]
    s.record("goal", "g-kill", "RUNNING", "Ziel beim Absturz", steps=steps)
    s.record("goal", f"g-old-{{n % 7}}", "SUCCEEDED", "alt", result="fertig")
    if n == 3:
        flag.write_text("ready")
"""


def kill_child(tmp_path: Path) -> Path:
    db, flag = tmp_path / "j.db", tmp_path / "flag"
    proc = subprocess.Popen([sys.executable, "-I", "-c", CHILD.format(src=SRC), str(db), str(flag)])
    try:
        end = time.monotonic() + 30
        while not flag.exists() and time.monotonic() < end and proc.poll() is None:
            time.sleep(0.05)
        assert flag.exists(), "Kindprozess hat nicht geschrieben"
        time.sleep(0.3)                                                                 # mitten in der Schreibschleife
    finally:
        proc.kill()                                                                     # hart: kein close(), kein finally im Kind
        proc.wait(timeout=15)
    return db


def test_the_journal_file_is_consistent_after_a_hard_kill_during_writes(tmp_path):
    db = kill_child(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    store = JournalStore(db)
    entry = store.get("goal", "g-kill")
    assert entry is not None and entry.status == "RUNNING"
    assert len(entry.steps) == 5 and [s.step_no for s in entry.steps] == [1, 2, 3, 4, 5]          # Schritte vollstaendig oder gar nicht ersetzt, nie halb
    assert [s.status for s in entry.steps] == ["SUCCEEDED", "SUCCEEDED", "PENDING", "PENDING", "PENDING"]
    assert all(e.steps is not None for e in store.list(50))
    store.close()


def test_the_killed_goal_is_listed_as_interrupted_and_listing_starts_nothing(tmp_path):
    db = kill_child(tmp_path)
    r = Rig(tmp_path)                                                                    # nutzt tmp_path/j.db: dieselbe Datei wie das Kind
    before = JournalStore(db).count()
    found = r.manager().interrupted()
    ids = [i.ref_id for i in found]
    assert "g-kill" in ids and not any(i.startswith("g-old-") for i in ids)               # nur Unfertiges
    assert not r.asked and JournalStore(db).count() == before                              # keine Rueckfrage, kein neuer Eintrag


def test_a_controlled_resume_after_the_hard_kill_needs_a_new_confirmation_for_side_effects(tmp_path):
    db = kill_child(tmp_path)
    r = Rig(tmp_path, answer=False)                                                      # der Mensch lehnt ab
    mgr = r.manager()
    result = mgr.resume("g-kill")
    assert r.asked, "ein offener Schritt mit Wirkung muss neu bestaetigt werden"
    assert result.status == "DECLINED" and result.new_goal_id is None                    # abgelehnt: kein neues Ziel, nichts gestartet
    assert JournalStore(db).get("goal", "g-kill").status == "RUNNING"                      # Eintrag bleibt unveraendert
