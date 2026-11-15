"""V2.1 Mission 3: Projektgedaechtnis (Arbeits-, Langzeit-, Entscheidungs-, Fehler- und Wissensgedaechtnis je Projekt). Reine Logik mit eingespritzter Uhr; kein Dateizugriff."""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.errors import MemoryNotFoundError, MemoryValidationError, SecretRejectedError
from jarvis.memory.project_memory import KINDS, ProjectMemory

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
T0 = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"


def mem():
    return ProjectMemory()


def add(m, kind="knowledge", key="preis.innenreinigung", value="ab 50 EUR", project="autopflege", source="https://a.example/preise", now=T0, **kw):
    return m.add(project, kind, key, value, source=source, now=now, **kw)


def test_five_kinds_exist_and_records_carry_source_and_time():
    assert set(KINDS) == {"working", "confirmed", "decision", "issue", "knowledge"}
    m = mem()
    r = add(m, quality=4)
    assert (r.project, r.kind, r.key, r.value, r.sources, r.quality, r.created_at, r.status) == ("autopflege", "knowledge", "preis.innenreinigung", "ab 50 EUR", ("https://a.example/preise",), 4, T0, "active")


def test_projects_are_strictly_separated():
    m = mem()
    add(m, project="autopflege")
    add(m, project="webdesign", key="preis.seite", value="ab 900 EUR")
    assert [r.key for r in m.recall("autopflege")] == ["preis.innenreinigung"] and [r.key for r in m.recall("webdesign")] == ["preis.seite"]
    assert m.recall("unbekannt") == [] and m.projects() == ["autopflege", "webdesign"]
    assert m.conflicts("autopflege") == []
    with pytest.raises(MemoryNotFoundError):
        m.correct("webdesign", m.recall("autopflege")[0].id, "x", by="user", reason="falsches Projekt", now=T0)   # eine Kennung gilt nur in ihrem Projekt


def test_secrets_credentials_and_personal_data_are_never_stored():
    m = mem()
    for bad in (f"API-Schlüssel {KEY}", "password=SuperGeheim123!", "Bearer abcdefghijklmnopqrstuvwxyz012345"):
        with pytest.raises(SecretRejectedError):
            add(m, value=bad)
    for personal in ("Kontakt: max.mustermann@example.com", "Telefon +49 170 1234567", "IBAN DE89 3704 0044 0532 0130 00"):
        with pytest.raises(MemoryValidationError):
            add(m, value=personal)
    with pytest.raises(SecretRejectedError):
        add(m, key="notiz", value="harmlos", source=f"https://a.example/?token={KEY}")
    assert m.recall("autopflege") == [] and KEY not in json.dumps(m.to_dict())
    ok = add(m, value="Ansprechpartner per Formular auf der Webseite", key="kontaktweg")
    assert ok.status == "active"


def test_duplicates_are_merged_and_their_sources_collected():
    m = mem()
    a = add(m)
    b = add(m, value="  AB 50   eur ", source="https://b.example/liste", now=T0 + timedelta(hours=1))
    assert a.id == b.id and len(m.recall("autopflege")) == 1
    assert b.sources == ("https://a.example/preise", "https://b.example/liste") and b.seen == 2 and b.updated_at == T0 + timedelta(hours=1)


def test_contradictions_are_reported_with_both_sides_and_never_resolved_silently():
    m = mem()
    add(m, value="ab 50 EUR", quality=4)
    add(m, value="ab 80 EUR", source="https://b.example/x", quality=2)
    (c,) = m.conflicts("autopflege")
    assert c["key"] == "preis.innenreinigung" and {s["value"] for s in c["sides"]} == {"ab 50 EUR", "ab 80 EUR"}
    assert c["preferred"]["value"] == "ab 50 EUR" and "quality" in c["preferred"]["why"]
    assert len(m.recall("autopflege", key="preis.innenreinigung")) == 2            # beide bleiben sichtbar
    assert all(r.conflict for r in m.recall("autopflege", key="preis.innenreinigung"))


def test_confirmed_information_outranks_better_looking_unconfirmed_sources():
    m = mem()
    r = add(m, value="ab 55 EUR", source="user", quality=None)
    m.confirm("autopflege", r.id, by="user", now=T0)
    add(m, value="ab 80 EUR", source="https://b.example/x", quality=5)
    assert m.conflicts("autopflege")[0]["preferred"]["value"] == "ab 55 EUR" and "confirmed" in m.conflicts("autopflege")[0]["preferred"]["why"]


def test_old_information_is_marked_stale_not_deleted():
    m = mem()
    add(m, kind="working", key="zwischenstand", value="Seite A gelesen", source="agent:research")
    add(m, kind="knowledge")
    add(m, kind="decision", key="zielgruppe", value="Privatkunden", source="user")
    changed = m.mark_stale(T0 + timedelta(days=2))
    assert [r.key for r in changed] == ["zwischenstand"]
    assert [r.key for r in m.recall("autopflege")] == ["preis.innenreinigung", "zielgruppe"]
    assert "zwischenstand" in [r.key for r in m.recall("autopflege", include_stale=True)]
    m.mark_stale(T0 + timedelta(days=400))
    keys = [r.key for r in m.recall("autopflege")]
    assert keys == ["zielgruppe"]                                               # Entscheidungen veralten nicht von selbst, Marktwissen schon


def test_user_corrections_are_traceable_and_the_old_value_stays_in_history():
    m = mem()
    r = add(m)
    new = m.correct("autopflege", r.id, "ab 65 EUR", by="user", reason="Preisliste von heute", now=T0 + timedelta(days=1))
    assert new.value == "ab 65 EUR" and new.confirmed and new.supersedes == r.id and new.status == "active"
    assert [x.value for x in m.recall("autopflege", key="preis.innenreinigung")] == ["ab 65 EUR"]
    old = m.get("autopflege", r.id)
    assert old.status == "superseded" and m.history("autopflege", "preis.innenreinigung") == [
        {"id": r.id, "value": "ab 50 EUR", "status": "superseded", "at": T0.isoformat(), "by": "https://a.example/preise", "reason": ""},
        {"id": new.id, "value": "ab 65 EUR", "status": "active", "at": (T0 + timedelta(days=1)).isoformat(), "by": "user", "reason": "Preisliste von heute"}]
    assert m.conflicts("autopflege") == []


def test_a_wrong_memory_can_be_retracted_and_then_no_longer_counts():
    m = mem()
    r = add(m)
    add(m, value="ab 80 EUR", source="https://b.example/x")
    m.retract("autopflege", r.id, by="user", reason="Seite war veraltet", now=T0)
    assert m.conflicts("autopflege") == [] and [x.value for x in m.recall("autopflege")] == ["ab 80 EUR"] and m.get("autopflege", r.id).status == "retracted"


def test_working_memory_ends_with_the_task_and_only_explicit_confirmation_makes_it_long_term():
    m = mem()
    w = add(m, kind="working", key="befund", value="Anbieter B nennt 80 EUR", source="task:t1", task="t1")
    add(m, kind="working", key="notiz", value="zweite Quelle fehlt", source="task:t1", task="t1")
    kept = m.confirm("autopflege", w.id, by="user", now=T0)
    assert kept.kind == "confirmed" and kept.confirmed
    assert m.end_task("autopflege", "t1") == 1 and [r.key for r in m.recall("autopflege", include_stale=True)] == ["befund"]


def test_the_issue_memory_counts_recurrences_and_feeds_suggestions_only_from_confirmed_records():
    m = mem()
    for i in range(3):
        add(m, kind="issue", key="browser.timeout", value="Seite wash-c lädt nicht", source="agent:research", now=T0 + timedelta(hours=i))
    add(m, kind="working", key="idee", value="vielleicht ohne wash-c", source="agent:research")
    r = add(m, kind="knowledge", key="quelle.wash-c", value="häufig nicht erreichbar", source="agent:research")
    assert m.suggestions("autopflege") == [{"kind": "issue", "key": "browser.timeout", "seen": 3, "hint": "Seite wash-c lädt nicht"}]
    m.confirm("autopflege", r.id, by="user", now=T0)
    assert {"kind": "confirmed", "key": "quelle.wash-c", "seen": 1, "hint": "häufig nicht erreichbar"} in m.suggestions("autopflege")
    assert not any(s["key"] == "idee" for s in m.suggestions("autopflege"))      # Unbestaetigtes fliesst nicht in Vorschlaege


@pytest.mark.parametrize("kw", [{"kind": "magic"}, {"key": ""}, {"key": "x" * 200}, {"value": ""}, {"value": "x" * 5000}, {"project": "Bad Project!"}, {"quality": 9}, {"quality": True},
                                {"source": ""}, {"key": "confirmed"}])
def test_invalid_records_are_refused(kw):
    with pytest.raises(MemoryValidationError):
        add(mem(), **kw)


def test_limits_hold_and_the_snapshot_round_trips_without_secrets():
    m = ProjectMemory(max_records=5)
    for i in range(5):
        add(m, key=f"k{i}", value=f"v{i}")
    with pytest.raises(MemoryValidationError):
        add(m, key="k5", value="v5")
    snap = m.to_dict()
    again = ProjectMemory.from_dict(json.loads(json.dumps(snap)))
    assert again.to_dict() == snap and [r.key for r in again.recall("autopflege")] == [f"k{i}" for i in range(5)]
    for broken in ({}, {"version": 99, "projects": {}}, {"version": 1, "projects": {"p": [{"id": "x"}]}}, "kaputt"):
        with pytest.raises(MemoryValidationError):
            ProjectMemory.from_dict(broken)
    tampered = json.loads(json.dumps(snap))
    tampered["projects"]["autopflege"][0]["value"] = f"Schlüssel {KEY}"
    with pytest.raises(MemoryValidationError):
        ProjectMemory.from_dict(tampered)                                        # auch beim Laden wird nichts Geheimes uebernommen


def test_the_module_is_pure_and_changes_no_model_or_program():
    tree = ast.parse((SRC / "memory" / "project_memory.py").read_text(encoding="utf-8"))
    mods = {a.name for x in ast.walk(tree) if isinstance(x, ast.Import) for a in x.names} | {x.module for x in ast.walk(tree) if isinstance(x, ast.ImportFrom)}
    assert mods <= {"__future__", "dataclasses", "datetime", "re", "typing", "uuid", "jarvis.errors", "jarvis.redaction"}, mods
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not calls & {"open", "exec", "eval", "compile", "__import__"}
