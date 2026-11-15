"""V2.1 M3 Persistenz - NUR ein isolierter Testadapter (tests/support/project_memory_file_adapter.py), keine produktive Verdrahtung. Prueft das Konzept aus docs/v21/M3_PERSISTENZ.md:
Format, Projektisolation, atomares Schreiben, Wiederherstellung nach Abbruch, Manipulation, Geheimnisschutz, Loeschen, Aufbewahrung. Deterministisch (uebergebene Zeit, tmp_path)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.memory.project_memory import ProjectMemory
from support.project_memory_file_adapter import FileAdapter

KEY = b"k" * 32
T0 = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
URL = "https://a.example/preise"


def memory():
    m = ProjectMemory()
    m.add("alpha", "knowledge", "preis", "50 EUR", source=URL, now=T0, quality=4)
    m.add("alpha", "decision", "ziel", "Webdesign zuerst", source="owner", now=T0)
    m.add("beta", "knowledge", "preis", "80 EUR", source=URL, now=T0)
    return m


def test_roundtrip_is_exact_and_each_project_has_its_own_file(tmp_path):
    a, m = FileAdapter(tmp_path, KEY), memory()
    a.save_all(m, T0)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["alpha.json", "beta.json"]
    loaded, bad = a.load()
    assert bad == [] and loaded.to_dict() == m.to_dict()
    assert "80 EUR" not in (tmp_path / "alpha.json").read_text(encoding="utf-8") and "Webdesign" not in (tmp_path / "beta.json").read_text(encoding="utf-8")      # keine Vermischung


def test_a_crash_between_write_and_replace_leaves_the_old_state_intact_and_the_leftover_is_ignored(tmp_path):
    a, m = FileAdapter(tmp_path, KEY), memory()
    a.save_all(m, T0)
    m.add("alpha", "knowledge", "neu", "neuer Wert", source=URL, now=T0)
    with pytest.raises(KeyboardInterrupt):
        a.save_project(m, "alpha", T0 + timedelta(hours=1), crash_before_replace=True)
    assert (tmp_path / ".alpha.json.tmp").exists()
    loaded, bad = a.load()
    assert bad == [] and [r.key for r in loaded.recall("alpha")].count("neu") == 0 and len(loaded.recall("alpha")) == 2           # alter Stand, kein halber Stand
    a.save_project(m, "alpha", T0 + timedelta(hours=2))                                                                                # Wiederholung nach dem Neustart
    assert a.load()[0].to_dict() == m.to_dict()


def test_a_tampered_file_is_quarantined_and_the_other_projects_still_load(tmp_path):
    a = FileAdapter(tmp_path, KEY)
    a.save_all(memory(), T0)
    doc = json.loads((tmp_path / "alpha.json").read_text(encoding="utf-8"))
    doc["records"][0]["value"] = "1 EUR"                                                       # Inhalt geaendert, MAC nicht
    (tmp_path / "alpha.json").write_text(json.dumps(doc), encoding="utf-8")
    loaded, bad = a.load()
    assert bad == ["alpha"] and loaded.projects() == ["beta"]
    assert FileAdapter(tmp_path, b"x" * 32).load()[1] == ["alpha", "beta"]                      # falscher Schluessel: nichts wird geladen, nichts angenommen


def test_a_file_moved_to_another_project_name_is_refused(tmp_path):
    a = FileAdapter(tmp_path, KEY)
    a.save_all(memory(), T0)
    (tmp_path / "alpha.json").rename(tmp_path / "gamma.json")
    loaded, bad = a.load()
    assert bad == ["gamma"] and "gamma" not in loaded.projects()


def test_a_secret_smuggled_into_a_validly_signed_file_is_still_refused_on_load(tmp_path):
    a = FileAdapter(tmp_path, KEY)
    a.save_all(memory(), T0)
    import hashlib, hmac
    doc = json.loads((tmp_path / "alpha.json").read_text(encoding="utf-8"))
    doc.pop("mac")
    doc["records"][0]["value"] = "token = " + "sk-" + "a1" * 12
    doc["mac"] = hmac.new(KEY, json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), hashlib.sha256).hexdigest()
    (tmp_path / "alpha.json").write_text(json.dumps(doc), encoding="utf-8")
    loaded, bad = a.load()
    assert bad == ["alpha"] and loaded.projects() == ["beta"]                                  # selbst mit gueltigem MAC: die Inhaltspruefung laeuft beim Laden erneut


def test_delete_removes_exactly_one_project_and_the_rest_stays(tmp_path):
    a = FileAdapter(tmp_path, KEY)
    a.save_all(memory(), T0)
    assert a.delete_project("alpha") is True and a.delete_project("alpha") is False
    assert a.load()[0].projects() == ["beta"]
    for bad_name in ("../x", "A b", "", "a/b"):
        with pytest.raises(ValueError):
            a.delete_project(bad_name)


def test_retention_marks_old_records_stale_and_nothing_is_deleted_by_age(tmp_path):
    a, m = FileAdapter(tmp_path, KEY), memory()
    m.add("alpha", "working", "notiz", "kurzlebig", source="agent", now=T0, task="t1")
    stale = m.mark_stale(T0 + timedelta(days=2))
    assert [r.key for r in stale] == ["notiz"]
    a.save_all(m, T0 + timedelta(days=2))
    loaded, _ = a.load()
    assert any(r.key == "notiz" for r in loaded.recall("alpha", include_stale=True)) and not any(r.key == "notiz" for r in loaded.recall("alpha"))   # veraltet, nicht geloescht


def test_the_adapter_is_a_test_helper_and_wired_nowhere():
    src = Path(__file__).resolve().parents[1] / "src" / "jarvis"
    assert not any("project_memory_file_adapter" in p.read_text(encoding="utf-8") for p in src.rglob("*.py"))
    with pytest.raises(ValueError):
        FileAdapter(Path("."), b"short")
