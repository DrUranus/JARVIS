"""Scope-Reparatur: Dateien ausserhalb des Aufgabenbereichs sind ein gewoehnliches Entwicklungsproblem, solange sie nicht kritisch sind. Das Gate fordert dann
(wie bei roter CI) hoechstens drei begrenzte Korrekturauftraege an; der Scope wird dabei nie erweitert. Kritische Dateien (X0-Vertrag, Berechtigungen, Notaus, Sicherheitstests,
Konfiguration, Automatisierung) bleiben beim Besitzer. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_awaiting_ci import ALL, report  # noqa: E402
from test_jarvis_automation import NOW, Fire, cfg, state_of  # noqa: E402
from test_merge_gate import HEAD  # noqa: E402
from test_sensitive_edits import backlog, pr_api  # noqa: E402

import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

SCOPE = ["src/jarvis/history/", "tests/test_history", "README.md"]
INSIDE = ["src/jarvis/history/store.py", "tests/test_history_store.py"]


def setup(files, *, scope=SCOPE, **kw):
    """Genehmigter Plan-Schritt 'a' mit Scope; der Auftrag hat berichtet, der PR liegt vor."""
    api = pr_api(files=files, **kw)
    path = backlog(allow=None, scope=scope)
    c = cfg(**ALL)
    n = ja.start_backlog_job(api, c, item_ref="a", backlog_path=path, auto_continue=True, chain_budget=3, run_id="1", run_attempt="1",
                             fire_url="https://example.invalid/f", fire_token="T", fire=lambda *a: ("session_0001", "https://claude.ai/code/session_0001"), now=NOW)["issue"]
    assert report(api, n, c) == "accepted"
    mg.resolve_awaiting_ci(api, c, now=NOW)                  # wie im Betrieb: der Auftrag mit feststehendem CI-Ergebnis wird abgeschlossen, dann bewertet das Gate den PR
    return api, path, c


def verdict(api, path, c):
    return mg.evaluate_pr(api, mg.GateConfig(c), api.pr, ja.load_backlog(path))


def status(api):
    return api.comments[7][0]["body"]


def test_a_non_critical_file_outside_the_scope_is_repaired_instead_of_stopping_the_chain():
    api, path, c = setup([*INSIDE, "tests/test_other.py"])
    v = verdict(api, path, c)
    assert v.action == "repair" and v.scope_outside == ["tests/test_other.py"] and api.merged == []
    mg.run_gate(api, c, backlog_path=path, dispatch=api.dispatch_workflow)
    assert api.merged == [] and ("jarvis-controller.yml", "main", {"repair_pr": "7", "repair_sha": HEAD}) in api.dispatched
    assert "tests/test_other.py" in status(api) and "Korrekturversuch 1/3" in status(api)


def test_the_repair_job_gets_a_scope_task_that_never_widens_the_scope():
    api, path, c = setup([*INSIDE, "tests/test_other.py"])
    fire = Fire()
    out = mg.run_repair(api, c, pr_number=7, sha=HEAD, backlog_path=path, run_id="2", run_attempt="1", fire_url="https://example.invalid/f", fire_token="SECRET-TOKEN",
                        fire=fire, now=NOW)
    assert out.startswith("started")
    text = fire.calls[0]
    assert "tests/test_other.py" in text and "Aufgabenbereich" in text and "nie" in text and "blocked" in text and "SECRET-TOKEN" not in text
    assert state_of(api, int(out.split(":")[1]))["chain"]["repair_of"] == 7


@pytest.mark.parametrize("critical", ["tests/test_ui_contract.py", "src/jarvis/ui_contract/schema.py", "src/jarvis/ui_contract/schema/ui-events.schema.json",
                                      "src/jarvis/permissions/engine.py", "src/jarvis/permissions/emergency.py", "tests/test_security_paths.py", "tests/test_emergency_stop.py",
                                      "config/jarvis.toml", "src/jarvis/bootstrap.py", ".github/automation/merge_gate.py", "src/jarvis/redaction.py"])
def test_critical_files_outside_the_scope_stay_with_the_owner_and_are_never_auto_repaired(critical):
    api, path, c = setup([*INSIDE, critical])
    v = verdict(api, path, c)
    assert v.action == "blocked" and not getattr(v, "scope_outside", None)
    mg.run_gate(api, c, backlog_path=path, dispatch=api.dispatch_workflow)
    assert api.merged == [] and api.dispatched == [] and "Besitzer" in status(api)


def test_a_mix_of_critical_and_ordinary_outside_files_is_not_repaired():
    api, path, c = setup([*INSIDE, "tests/test_other.py", "tests/test_ui_contract.py"])
    assert verdict(api, path, c).action == "blocked"


def test_repairs_are_limited_to_three_for_scope_problems_too_then_the_owner_decides():
    api, path, c = setup([*INSIDE, "tests/test_other.py"])
    for k in range(1, 4):
        out = mg.run_repair(api, c, pr_number=7, sha=HEAD, backlog_path=path, run_id=str(10 + k), run_attempt="1", fire_url="https://example.invalid/f", fire_token="T", fire=Fire(), now=NOW)
        assert out.startswith("started"), k
        i = max(api.issues)
        ja.set_state(api, api.get_issue(i), state_of(api, i), "failed", extra={"report": {"branch": "claude/work", "commits": [], "tests": [], "next_action": "none", "status": "failed"}})
    v = verdict(api, path, c)
    assert mg.count_repairs(api, 7) == 3 and v.action == "blocked" and "ausgeschoepft" in " ".join(v.reasons)
    assert mg.run_repair(api, c, pr_number=7, sha=HEAD, backlog_path=path, run_id="99", run_attempt="1", fire_url="u", fire_token="t", fire=Fire()) == "ignored:blocked"


def test_no_scope_repair_while_ci_runs_without_approval_or_when_disabled():
    api, path, c = setup([*INSIDE, "tests/test_other.py"])
    api.runs[1]["status"] = "in_progress"
    assert verdict(api, path, c).action == "blocked" or verdict(api, path, c).action == "wait"
    assert verdict(api, path, c).action != "repair"
    api.runs[1]["status"] = "completed"
    mg.run_gate(api, cfg(JARVIS_AUTO_MERGE_ENABLED="true"), backlog_path=path, dispatch=api.dispatch_workflow)     # Auto-Fortsetzung aus: nur Hinweis, nichts angefordert
    assert api.dispatched == [] and "nicht aktiviert" in status(api)


def test_a_clean_pr_inside_the_scope_still_merges_and_the_scope_stays_inert_without_the_owner_switch():
    api, path, c = setup(INSIDE)
    mg.run_gate(api, c, backlog_path=path, dispatch=api.dispatch_workflow)
    assert api.merged and not any("repair_pr" in d[2] for d in api.dispatched)
    assert [d[2] for d in api.dispatched] == [{"after_job": "1"}]                    # genau eine Fortsetzung nach dem Merge (der Controller startet den naechsten Schritt)
    mg.run_gate(api, c, backlog_path=path, dispatch=api.dispatch_workflow)            # zweiter Lauf: kein zweiter Merge, keine zweite Fortsetzung durch das Gate
    assert len(api.merged) == 1
    inert, path2, c2 = setup([*INSIDE, "tests/test_other.py"])
    ok = backlog(allow=None, scope=SCOPE, active=False)
    assert verdict(inert, ok, c2).scope_outside == []


def test_a_failing_ci_with_a_scope_problem_is_repaired_with_both_findings_in_one_task():
    api, path, c = setup([*INSIDE, "tests/test_other.py"])
    api.runs[1].update(conclusion="failure")
    api.annots[2] = [{"title": "Test fehlgeschlagen", "message": "tests.test_x::test_a"}]
    v = verdict(api, path, c)
    assert v.action == "repair" and v.scope_outside == ["tests/test_other.py"]
    fire = Fire()
    out = mg.run_repair(api, c, pr_number=7, sha=HEAD, backlog_path=path, run_id="5", run_attempt="1", fire_url="https://example.invalid/f", fire_token="T", fire=fire, now=NOW)
    assert out.startswith("started") and "tests.test_x::test_a" in fire.calls[0] and "tests/test_other.py" in fire.calls[0]


def test_the_critical_list_covers_every_protected_path_and_the_contract_files():
    for p in ja.SENSITIVE_PATHS:
        probe = p if not p.endswith("_") else p + "x.py"
        assert mg.is_critical(probe), probe
    for p in ("tests/test_ui_contract.py", "src/jarvis/ui_contract/schema.py", "src/jarvis/ui_contract/backend.py", "src/jarvis/ui_contract/fake.py",
              "src/jarvis/ui_contract/conformance.py", "src/jarvis/redaction.py", "src/jarvis/permissions/emergency.py"):
        assert mg.is_critical(p), p
    for p in ("tests/test_other.py", "docs/TESTING.md", "src/jarvis/ui_contract/bus.py", "src/jarvis/interface/ui_events.py", "README.md"):
        assert not mg.is_critical(p), p
