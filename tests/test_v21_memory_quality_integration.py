"""V2.1 Integration M3 (Projektgedaechtnis) + M7 (Quality Engine): beide Kerne zusammen, ohne Verdrahtung und ohne Persistenz.

Geprueft: Projekttrennung, Widersprueche, Quellen, Qualitaetssicherung, Not-Aus-Verhalten (reine Kerne), Budgetgrenzen, Persistenzbedarf (nur Snapshot, kein Dateizugriff),
und dass kein Integrationspunkt aktiv ist. Zeiten werden uebergeben (keine Uhr), alles deterministisch."""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.business import calc
from jarvis.control_center.mission import MissionView
from jarvis.errors import MemoryNotFoundError, MemoryValidationError, SecretRejectedError
from jarvis.memory.project_memory import ProjectMemory
from jarvis.quality.engine import conflicts, evaluate

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
T0 = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
URL_A, URL_B = "https://a.example/preise", "https://b.example/liste"


def pm_with_two_projects():
    m = ProjectMemory()
    a = m.add("alpha", "knowledge", "preis_innen", "50 EUR", source=URL_A, now=T0, quality=4)
    m.add("beta", "knowledge", "preis_innen", "80 EUR", source=URL_B, now=T0, quality=2)
    return m, a


# ---- Projekttrennung ---------------------------------------------------------------------------------------------------------------------------------
def test_projects_are_strictly_separated_and_the_same_key_in_two_projects_is_no_conflict():
    m, a = pm_with_two_projects()
    assert m.conflicts("alpha") == [] and m.conflicts("beta") == []
    assert [r.value for r in m.recall("alpha", key="preis_innen")] == ["50 EUR"] and [r.value for r in m.recall("beta", key="preis_innen")] == ["80 EUR"]
    with pytest.raises(MemoryNotFoundError):
        m.confirm("beta", a.id, by="owner", now=T0)                 # eine Satz-ID gilt nur in ihrem Projekt
    assert m.recall("gamma") == []


def test_the_quality_engine_has_no_project_concept_and_cannot_read_another_projects_figures():
    m, _ = pm_with_two_projects()
    fa = [{"label": r.key, "unit": "EUR", "value": float(r.value.split()[0]), "source": r.sources[0]} for r in m.recall("alpha")]
    assert conflicts(fa) == []                                       # nur was der Aufrufer hereinreicht; beta fliesst nie ein
    both = fa + [{"label": r.key, "unit": "EUR", "value": float(r.value.split()[0]), "source": r.sources[0]} for r in m.recall("beta")]
    assert [c["label"] for c in conflicts(both)] == ["preis_innen"]  # erst die bewusste Vermischung durch den Aufrufer erzeugt den Widerspruch


# ---- Widersprueche -------------------------------------------------------------------------------------------------------------------------------------
def test_a_contradiction_inside_a_project_is_reported_with_both_sides_and_never_resolved_silently():
    m, _ = pm_with_two_projects()
    m.add("alpha", "knowledge", "preis_innen", "80 EUR", source=URL_B, now=T0 + timedelta(days=1), quality=2)
    c = m.conflicts("alpha")
    assert len(c) == 1 and len(c[0]["sides"]) == 2 and c[0]["resolved"] is False and c[0]["preferred"]["value"] == "50 EUR" and "quality" in c[0]["preferred"]["why"]
    assert all(r.conflict for r in m.recall("alpha", key="preis_innen"))


def test_contradicting_memory_values_make_the_quality_verdict_fail_unless_shown_as_a_conflict():
    m, _ = pm_with_two_projects()
    m.add("alpha", "knowledge", "preis_innen", "80 EUR", source=URL_B, now=T0, quality=2)
    figures = [{"label": r.key, "unit": "EUR", "value": float(r.value.split()[0]), "source": r.sources[0]} for r in m.recall("alpha")]
    report = {"status": "SUCCEEDED", "requirements": [{"id": "r1"}], "coverage": {"r1": ["s1"]}, "statements": [{"id": "s1", "basis": "FACT", "sources": [URL_A]}],
              "sources": [{"url": URL_A, "status": "ok"}], "figures": figures, "required_fields": {"x": 1}}
    v = evaluate(report, file_exists=lambda p: True)
    assert not v.accepted and "consistency" in v.failed


# ---- Quellen / Qualitaetssicherung ---------------------------------------------------------------------------------------------------------------------
def test_memory_demands_a_source_and_the_quality_engine_demands_that_a_fact_source_was_really_read():
    m = ProjectMemory()
    with pytest.raises(MemoryValidationError):
        m.add("alpha", "knowledge", "k", "v", source="", now=T0)
    report = {"status": "SUCCEEDED", "requirements": [{"id": "r1"}], "coverage": {"r1": ["s1"]}, "statements": [{"id": "s1", "basis": "FACT", "sources": [URL_A]}],
              "sources": [{"url": URL_A, "status": "failed"}], "required_fields": {"x": 1}}
    v = evaluate(report, file_exists=lambda p: True)
    assert not v.accepted and "sources" in v.failed                  # die Quelle wurde nie gelesen: das Gedaechtnis allein macht daraus keinen Beleg


def test_an_agent_success_message_alone_is_never_accepted_even_with_memory_suggestions():
    m, _ = pm_with_two_projects()
    assert m.suggestions("alpha") == []
    v = evaluate({"status": "SUCCEEDED"}, file_exists=None)
    assert not v.accepted and v.self_reported == "SUCCEEDED"


def test_unconfirmed_notes_never_become_suggestions_only_confirmed_records_and_recurring_issues():
    m = ProjectMemory()
    w = m.add("alpha", "working", "note", "vielleicht", source="agent", now=T0, task="t1")
    m.add("alpha", "issue", "timeout", "Timeout bei Quelle A", source="agent", now=T0)
    m.add("alpha", "issue", "timeout", "Timeout bei Quelle A", source="agent", now=T0)
    kinds = {s["kind"] for s in m.suggestions("alpha")}
    assert kinds == {"issue"}
    m.confirm("alpha", w.id, by="owner", now=T0)
    assert {s["kind"] for s in m.suggestions("alpha")} == {"issue", "confirmed"}


# ---- Budgetgrenzen --------------------------------------------------------------------------------------------------------------------------------------
def test_an_exhausted_or_unknown_binding_budget_fails_the_verdict_closed():
    base = {"status": "SUCCEEDED", "requirements": [{"id": "r1"}], "coverage": {"r1": ["s1"]}, "statements": [{"id": "s1", "basis": "ESTIMATE"}], "required_fields": {"x": 1}}
    over = evaluate(dict(base, budgets=[{"name": "llm_calls", "limit": 10, "used": 11, "binding": True}]), file_exists=None)
    unknown = evaluate(dict(base, budgets=[{"name": "llm_calls", "limit": 10, "binding": True}]), file_exists=None)
    ok = evaluate(dict(base, budgets=[{"name": "llm_calls", "limit": 10, "used": 3, "binding": True}]), file_exists=None)
    assert "budgets" in over.failed and not unknown.accepted and "budgets" not in ok.failed


def test_the_memory_has_a_hard_record_limit_per_project():
    m = ProjectMemory(max_records=3)
    for i in range(3):
        m.add("alpha", "knowledge", f"k{i}", f"v{i}", source=URL_A, now=T0)
    with pytest.raises(MemoryValidationError):
        m.add("alpha", "knowledge", "k9", "v9", source=URL_A, now=T0)
    m.add("beta", "knowledge", "k0", "v", source=URL_A, now=T0)      # ein anderes Projekt ist davon nicht betroffen


# ---- Geheimnisse ----------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Authorization: Bearer " + "Zx9" + "Qw4" * 6 + "p0", "token = " + "sk-" + "a1" * 12, "kontakt: max@example.com"])
def test_secrets_and_unnecessary_personal_data_are_refused_by_the_memory(text):
    with pytest.raises((SecretRejectedError, MemoryValidationError)):
        ProjectMemory().add("alpha", "knowledge", "k", text, source=URL_A, now=T0)


# ---- Persistenzbedarf: nur Snapshot, kein Dateizugriff -----------------------------------------------------------------------------------------------
def test_the_snapshot_roundtrips_exactly_and_a_tampered_snapshot_is_refused():
    m, _ = pm_with_two_projects()
    m.add("alpha", "decision", "ziel", "Webdesign zuerst", source="owner", now=T0)
    snap = json.loads(json.dumps(m.to_dict()))
    assert ProjectMemory.from_dict(snap).to_dict() == m.to_dict()
    for bad in (dict(snap, version=99), {"version": 1, "projects": {"alpha": "x"}}):
        with pytest.raises(MemoryValidationError):
            ProjectMemory.from_dict(bad)
    forged = json.loads(json.dumps(snap))
    forged["projects"]["alpha"][0]["value"] = "Authorization: Bearer " + "Zx9" + "Qw4" * 6 + "p0"
    with pytest.raises((SecretRejectedError, MemoryValidationError)):
        ProjectMemory.from_dict(forged)                               # die Pruefung laeuft beim Laden erneut: kein Umweg ueber eine manipulierte Datei
    moved = json.loads(json.dumps(snap))
    moved["projects"]["beta"] = moved["projects"].pop("alpha")
    with pytest.raises(MemoryValidationError):
        ProjectMemory.from_dict(moved)                                # Datensatz gehoert zu einem anderen Projekt


def test_the_cores_do_no_io_start_no_threads_and_know_neither_permissions_nor_emergency_stop():
    banned = {"os", "sys", "io", "pathlib", "shutil", "sqlite3", "socket", "subprocess", "threading", "http", "urllib", "pickle", "tempfile", "time"}
    for rel in ("memory/project_memory.py", "quality/engine.py"):
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not mods & banned, (rel, mods & banned)
        assert not any(isinstance(n, ast.Name) and n.id in ("open", "eval", "exec", "__import__") for n in ast.walk(tree)), rel
        assert not any(m.startswith(("jarvis.permissions", "jarvis.agents", "jarvis.tools", "jarvis.bootstrap")) for m in [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]), rel


def test_no_integration_point_is_active_the_memory_is_wired_nowhere_and_the_quality_engine_only_through_the_disabled_gate():
    allowed_quality = {SRC / "memory" / "project_memory.py", SRC / "quality" / "engine.py", SRC / "quality" / "__init__.py", SRC / "quality" / "gate.py", SRC / "agents" / "factory.py"}
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path != SRC / "memory" / "project_memory.py":
            assert "project_memory" not in text and "ProjectMemory" not in text, path
        if path not in allowed_quality:
            assert "jarvis.quality" not in text, path
    from jarvis.config import Settings
    assert Settings().agents.quality_gate is False and Settings().agents.quality_gate_agents == ()


# ---- Zusammenspiel mit Mission Control ------------------------------------------------------------------------------------------------------------------
def test_overview_feeds_the_mission_view_with_counts_only_and_the_verdict_shape_fits_the_quality_section():
    m, _ = pm_with_two_projects()
    m.add("alpha", "knowledge", "preis_innen", "80 EUR", source=URL_B, now=T0, quality=2)
    m.add("alpha", "issue", "timeout", "Timeout", source="agent", now=T0)
    rows = m.overview()
    alpha = next(r for r in rows if r["project"] == "alpha")
    assert alpha["counts"] == {"knowledge": 2, "issue": 1} and alpha["conflicts"] == 1 and "Timeout" not in json.dumps(rows)
    verdict = evaluate({"status": "SUCCEEDED"}, file_exists=None).to_dict()
    view = MissionView(agents_source=lambda n: {"agents": [], "tasks": []}, memory_source=lambda: rows,
                       quality_source=lambda n: [{"task_id": "t1", **verdict}]).snapshot(10)
    assert view["memory"]["projects"][0] == {"project": "alpha", "counts": {"knowledge": 2, "issue": 1}, "conflicts": 1, "stale": 0, "suggestions": 0} and view["quality"]["rejected"] == 1 and view["quality"]["items"][0]["self_reported"] == "SUCCEEDED"
