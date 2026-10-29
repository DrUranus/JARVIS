"""Zwischenzustand awaiting_ci: ein Bericht vor Abschluss der CI beendet die Kette nicht mehr; das Gate prueft die CI selbst, setzt den Auftrag fort,
mergt nur mit vollstaendigem Nachweis und haelt sicher an. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_jarvis_automation import NOW, REPO, ROOT, Fire, cfg, report_comment, state_of  # noqa: E402
from test_merge_gate import GOOD_RUN, HEAD, GateApi  # noqa: E402

import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

ACC = ["Tests gruen", "Windows-CI gruen"]
GOOD_ACC = [{"criterion": 1, "result": "met", "evidence": "lokal"}, {"criterion": 2, "result": "awaiting_ci", "evidence": "CI laeuft"}]
ALL = dict(JARVIS_AUTO_CONTINUE_ENABLED="true", JARVIS_AUTO_MERGE_ENABLED="true")


def backlog():
    p = Path(tempfile.mkdtemp()) / "backlog.json"
    p.write_text(json.dumps({"items": [
        {"id": "a", "task": "Aufgabe A", "approved": True, "depends_on": [], "acceptance": ACC},
        {"id": "b", "task": "Aufgabe B", "approved": True, "depends_on": ["a"], "acceptance": ACC}]}))
    return p


BACKLOG = backlog()


def started(api, c=None, budget=3):
    r = ja.start_backlog_job(api, c or cfg(**ALL), item_ref="a", backlog_path=BACKLOG, auto_continue=True, chain_budget=budget, run_id="10", run_attempt="1",
                             fire_url="https://example.invalid/f", fire_token="T", fire=Fire(), now=NOW)
    return r["issue"]


def report(api, n, c=None, **over):
    data = dict(status="success", next_action={"type": "await_ci", "reason": "CI laeuft"}, branch="claude/work", commits=[HEAD],
                pr_url=f"https://github.com/{REPO}/pull/7", acceptance=GOOD_ACC)
    data.update(over)
    return ja.process_comment(api, c or cfg(**ALL), api.get_issue(n), report_comment(state_of(api, n), **data))


def awaiting(api, c=None, **over):
    n = started(api, c)
    assert report(api, n, c, **over) == "accepted"
    return n


def gate(api, c=None, **env):
    return mg.run_gate(api, c or cfg(**{**ALL, **env}), backlog_path=BACKLOG, dispatch=api.dispatch_workflow)


class ClosingApi(GateApi):
    """Like GitHub: a merged PR is closed and merged; a second merge attempt would be refused."""

    def request(self, method, path, body=None):
        if method == "PUT" and path.endswith("/merge") and self.pr.get("merged"):
            raise ja.ApiError("already merged", status=405)
        result = super().request(method, path, body)
        if method == "PUT" and path.endswith("/merge"):
            self.pr.update({"merged": True, "state": "closed", "merge_commit_sha": "e" * 40})
        return result


def api_with_pr(**kw):
    api = ClosingApi(reviews=[], **kw)
    api.pr["head"]["sha"] = HEAD
    return api


# ---- Bericht kommt vor Abschluss der CI -----------------------------------------------------------------------------------------------
def test_a_report_before_ci_finishes_enters_awaiting_ci_instead_of_ending_the_chain():
    api = api_with_pr()
    n = awaiting(api)
    st = state_of(api, n)
    assert st["status"] == "awaiting_ci" and st["ci_deadline"] and api.issues[n]["state"] == "open"
    assert {"jarvis:awaiting_ci"} <= {l["name"] for l in api.issues[n]["labels"]}
    assert st["report"]["next_action"] == "await_ci" and st["report"]["acceptance"][1]["result"] == "awaiting_ci"
    assert not st.get("followup")


def test_awaiting_ci_holds_the_single_job_slot_and_triggers_no_followup():
    api = api_with_pr()
    n = awaiting(api)
    assert ja.request_followup(api, cfg(**ALL), n, "main") is False and api.dispatched == []
    with pytest.raises(ja.AutomationError, match="laeuft bereits"):
        ja.start_job(api, cfg(**ALL), task="t", base_branch=None, auto_continue=False, chain_budget=1, timeout_minutes=60, run_id="11", run_attempt="1",
                     fire_url="https://example.invalid/f", fire_token="T", fire=Fire(), now=NOW)
    with pytest.raises(ja.AutomationError, match="noch nicht abgeschlossen"):
        ja.run_controller(api, cfg(**ALL), after_job=n, backlog_path=BACKLOG, run_id="12", run_attempt="1", fire_url="u", fire_token="t", fire=Fire(), now=NOW)


@pytest.mark.parametrize("over,reason", [
    ({"acceptance": None}, "Abnahmekriterien"),
    ({"acceptance": [{"criterion": 1, "result": "met", "evidence": "x"}]}, "Abnahmekriterien"),                       # incomplete
    ({"acceptance": [{"criterion": 1, "result": "met", "evidence": "x"}, {"criterion": 2, "result": "not_met", "evidence": "x"}]}, "nicht erfuellt"),
    ({"pr_url": None}, "Pull Request"),
    ({"branch": None}, "Pull Request"),
    ({"commits": []}, "Pull Request"),
    ({"status": "partial"}, "success"),
    ({"status": "failed"}, "success"),
])
def test_an_invalid_await_ci_report_falls_back_to_partial_needs_human(over, reason):
    api = api_with_pr()
    n = started(api)
    assert report(api, n, **over) == "accepted"
    st = state_of(api, n)
    assert st["status"] in ("partial", "failed") and st["report"]["next_action"] == "needs_human"
    assert reason in " ".join(x["body"] for x in api.comments[n])
    assert api.issues[n]["state"] == "closed"


def test_the_same_report_twice_changes_nothing():
    api = api_with_pr()
    n = awaiting(api)
    before = api.issues[n]["body"]
    assert report(api, n) == "ignored:auftrag-nicht-gestartet" and api.issues[n]["body"] == before


# ---- CI wird danach erfolgreich ---------------------------------------------------------------------------------------------------------
def test_pending_ci_keeps_waiting_without_any_action():
    api = api_with_pr()
    n = awaiting(api)
    api.runs[1].update(status="in_progress", conclusion=None)
    gate(api)
    assert state_of(api, n)["status"] == "awaiting_ci" and api.merged == [] and api.dispatched == []


def test_successful_ci_completes_the_job_and_the_gate_merges_with_the_checked_commit_and_continues_once():
    api = api_with_pr()
    n = awaiting(api)
    out = gate(api)
    st = state_of(api, n)
    assert st["status"] == "completed" and st["ci"]["result"] == "success" and st["ci_gated"] is True and st["report"]["next_action"] == "continue"
    assert api.merged == [{"sha": HEAD, "merge_method": "squash"}] and st["merged"]["pr"] == 7
    assert [d[:2] for d in api.dispatched] == [("jarvis-controller.yml", "main")] and api.dispatched[0][2] == {"after_job": str(n)}
    assert any("gemergt" in line for line in out)
    gate(api)                                                                                 # a duplicate event: no second merge, no second dispatch
    assert len(api.merged) == 1 and len(api.dispatched) == 1


def test_with_auto_merge_off_the_job_completes_but_nothing_is_merged_and_the_chain_waits_for_the_owner():
    api = api_with_pr()
    c = cfg(JARVIS_AUTO_CONTINUE_ENABLED="true")
    n = awaiting(api, c)
    gate(api, c)
    assert state_of(api, n)["status"] == "completed" and api.merged == [] and api.dispatched == []
    api.pr.update({"merged": True, "state": "closed", "merge_commit_sha": "e" * 40})            # the owner merges by hand
    gate(api, c)
    assert state_of(api, n)["merged"]["pr"] == 7 and len(api.dispatched) == 1                  # the chain continues without JARVIS_AUTO_MERGE_ENABLED


def test_the_controller_then_starts_the_next_step_on_main_and_never_the_same_step_twice():
    api = api_with_pr()
    n = awaiting(api)
    gate(api)
    fire = Fire()
    out = ja.run_controller(api, cfg(**ALL), after_job=n, backlog_path=BACKLOG, run_id="20", run_attempt="1", fire_url="https://example.invalid/f",
                            fire_token="T", fire=fire, now=NOW)
    assert out.startswith("started:") and state_of(api, int(out.split(":")[1]))["chain"]["item_id"] == "b" and state_of(api, int(out.split(":")[1]))["base_branch"] == "main"
    assert "Aufgabe B" in fire.calls[0] and "- Windows-CI gruen" in fire.calls[0]
    assert ja.run_controller(api, cfg(**ALL), after_job=n, backlog_path=BACKLOG, run_id="21", run_attempt="1", fire_url="u", fire_token="t", fire=Fire(), now=NOW) == "already-decided"


# ---- CI schlaegt fehl ------------------------------------------------------------------------------------------------------------------
def failing_api():
    api = api_with_pr()
    api.runs[1].update(conclusion="failure")
    api.annots[2] = [{"title": "Test fehlgeschlagen", "message": "tests.test_x::test_a"}]
    return api


def test_failed_ci_completes_the_job_without_merge_and_hands_over_to_the_bounded_repair_loop():
    api = failing_api()
    n = awaiting(api)
    out = gate(api)
    st = state_of(api, n)
    assert st["status"] == "completed" and st["ci"]["result"] == "failed" and "merged" not in st and api.merged == []
    assert api.dispatched == [("jarvis-controller.yml", "main", {"repair_pr": "7", "repair_sha": HEAD})]
    assert any("repair" in line for line in out) and "tests.test_x::test_a" in api.comments[7][0]["body"]


def finish_repair(api, status="failed"):
    i = max(api.issues)
    ja.set_state(api, api.get_issue(i), state_of(api, i), status)


def test_repairs_are_limited_to_three_then_the_chain_stops_safely():
    api = failing_api()
    n = awaiting(api)
    gate(api)
    c = cfg(**ALL)
    for k in range(1, 4):
        out = mg.run_repair(api, c, pr_number=7, sha=HEAD, backlog_path=BACKLOG, run_id=str(300 + k), run_attempt="1", fire_url="https://example.invalid/f",
                            fire_token="T", fire=Fire(), now=NOW)
        assert out.startswith("started"), k
        finish_repair(api)
    assert mg.run_repair(api, c, pr_number=7, sha=HEAD, backlog_path=BACKLOG, run_id="399", run_attempt="1", fire_url="u", fire_token="t", fire=Fire()) == "ignored:blocked"
    gate(api)
    assert "ausgeschoepft" in api.comments[7][0]["body"] and api.merged == []
    assert ja.run_controller(api, c, after_job=n, backlog_path=BACKLOG, run_id="400", run_attempt="1", fire_url="u", fire_token="t", fire=Fire(), now=NOW) == "deferred:wartet-auf-merge"
    assert not state_of(api, n).get("merged") and "a" not in ja.completed_item_ids(api, require_merge=True)


def test_a_green_repair_then_merges_and_the_chain_continues():
    api = failing_api()
    n = awaiting(api)
    gate(api)
    mg.run_repair(api, cfg(**ALL), pr_number=7, sha=HEAD, backlog_path=BACKLOG, run_id="500", run_attempt="1", fire_url="https://example.invalid/f",
                  fire_token="T", fire=Fire(), now=NOW)
    ja.set_state(api, api.get_issue(max(api.issues)), state_of(api, max(api.issues)), "completed",
                 extra={"report": {"branch": "claude/work", "commits": [HEAD], "tests": [], "next_action": "none", "status": "success"}})
    api.runs[1].update(conclusion="success")                                                    # the repaired commit passes
    api.dispatched.clear()
    gate(api)
    assert api.merged == [{"sha": HEAD, "merge_method": "squash"}] and state_of(api, n)["merged"]["pr"] == 7
    assert [d[2] for d in api.dispatched] == [{"after_job": str(n)}]


# ---- PR vom Besitzer gemergt / geschlossen / geschuetzt -----------------------------------------------------------------------------
def test_a_pr_merged_by_the_owner_while_ci_is_pending_completes_the_job_and_continues():
    api = api_with_pr()
    n = awaiting(api)
    api.runs[1].update(status="in_progress", conclusion=None)
    api.pr.update({"merged": True, "state": "closed", "merge_commit_sha": "e" * 40})
    gate(api)
    st = state_of(api, n)
    assert st["status"] == "completed" and st["ci"]["result"] == "owner_merged" and st["merged"]["pr"] == 7 and len(api.dispatched) == 1


def test_a_pr_closed_without_merge_blocks_the_job():
    api = api_with_pr()
    n = awaiting(api)
    api.pr.update({"merged": False, "state": "closed"})
    gate(api)
    assert state_of(api, n)["status"] == "blocked" and api.dispatched == [] and api.merged == []


def test_a_branch_that_moved_after_the_report_blocks_the_job():
    api = api_with_pr()
    n = awaiting(api)
    api.pr["head"]["sha"] = "f" * 40
    for r in api.runs:
        r["head_sha"] = "f" * 40
    gate(api)
    assert state_of(api, n)["status"] == "blocked" and api.merged == []


def test_a_protected_pr_is_never_merged_automatically_but_the_chain_continues_after_the_owner_merges():
    api = api_with_pr(files=["src/jarvis/permissions/engine.py"])
    n = awaiting(api)
    gate(api)
    assert state_of(api, n)["status"] == "completed" and api.merged == [] and api.dispatched == []
    assert "Besitzer" in api.comments[7][0]["body"]
    api.pr.update({"merged": True, "state": "closed", "merge_commit_sha": "e" * 40})
    gate(api)
    assert state_of(api, n)["merged"] and len(api.dispatched) == 1


def test_halt_stops_the_resolution_and_the_continuation():
    api = api_with_pr()
    n = awaiting(api)
    gate(api, JARVIS_AUTOMATION_HALT="true")
    assert state_of(api, n)["status"] == "awaiting_ci" and api.merged == [] and api.dispatched == []


# ---- Kettenbudget, Tageslimit, Abnahmekriterien -----------------------------------------------------------------------------------------
def merged_job(api, c=None, budget=3):
    n = started(api, c, budget)
    report(api, n, c)
    gate(api, c)
    return n


def test_chain_budget_and_daily_limit_still_stop_the_chain_after_the_merge():
    api = api_with_pr()
    n = merged_job(api, budget=1)
    out = ja.run_controller(api, cfg(**ALL), after_job=n, backlog_path=BACKLOG, run_id="600", run_attempt="1", fire_url="u", fire_token="t", fire=Fire(), now=NOW)
    assert out == "stopped" and "Auftragsbudget" in " ".join(x["body"] for x in api.comments[n])
    api2 = api_with_pr()
    n2 = merged_job(api2)
    c = cfg(**ALL, JARVIS_MAX_JOBS_PER_DAY="1")
    out2 = ja.run_controller(api2, c, after_job=n2, backlog_path=BACKLOG, run_id="601", run_attempt="1", fire_url="u", fire_token="t", fire=Fire(), now=NOW)
    assert out2 == "stopped" and "Tageslimit" in " ".join(x["body"] for x in api2.comments[n2])


def test_incomplete_acceptance_evidence_never_continues_the_chain():
    api = api_with_pr()
    c = cfg(JARVIS_AUTO_CONTINUE_ENABLED="true")                                              # no merge gating: the decision itself must refuse
    n = started(api, c)
    assert report(api, n, c, status="success", next_action={"type": "continue", "reason": "x"}, acceptance=None, pr_url=None, branch=None, commits=[]) == "accepted"
    out = ja.run_controller(api, c, after_job=n, backlog_path=BACKLOG, run_id="700", run_attempt="1", fire_url="u", fire_token="t", fire=Fire(), now=NOW)
    assert out == "stopped" and "Abnahmekriterien" in " ".join(x["body"] for x in api.comments[n])


def test_a_not_met_criterion_never_continues_even_after_a_merge():
    api = api_with_pr()
    n = started(api)
    bad = [{"criterion": 1, "result": "met", "evidence": "x"}, {"criterion": 2, "result": "not_met", "evidence": "x"}]
    report(api, n, status="success", next_action={"type": "continue", "reason": "x"}, acceptance=bad)
    ja.mark_merged(api, n, pr_number=7, sha=HEAD, now=NOW)
    out = ja.run_controller(api, cfg(**ALL), after_job=n, backlog_path=BACKLOG, run_id="701", run_attempt="1", fire_url="u", fire_token="t", fire=Fire(), now=NOW)
    assert out == "stopped" and "Abnahmekriterien" in " ".join(x["body"] for x in api.comments[n])


# ---- Watchdog ------------------------------------------------------------------------------------------------------------------------
def test_watchdog_times_out_a_job_that_waits_too_long_for_ci_and_leaves_a_fresh_one_alone():
    import datetime as dt
    api = api_with_pr()
    n = awaiting(api)
    assert not [a for a in ja.run_watchdog(api, cfg(**ALL), now=ja.utcnow() + dt.timedelta(minutes=5), dispatch_ref="main") if "timeout" in a]
    assert state_of(api, n)["status"] == "awaiting_ci"
    out = ja.run_watchdog(api, cfg(**ALL), now=ja.utcnow() + dt.timedelta(minutes=ja.CI_WAIT_MIN + 5), dispatch_ref="main")
    assert any("timeout" in a for a in out) and state_of(api, n)["status"] == "timeout" and api.dispatched == []


def test_watchdog_stop_label_ends_an_awaiting_job():
    api = api_with_pr()
    n = awaiting(api)
    api.issues[n]["labels"].append({"name": ja.STOP_LABEL})
    ja.run_watchdog(api, cfg(**ALL), now=ja.utcnow(), dispatch_ref="main")
    assert state_of(api, n)["status"] == "stopped"


def test_the_state_machine_allows_only_the_intended_transitions():
    assert ja.TRANSITIONS["running"] >= {"awaiting_ci"} and ja.TRANSITIONS["awaiting_ci"] == {"completed", "failed", "blocked", "timeout", "stopped"}
    assert "awaiting_ci" in ja.NONTERMINAL and "awaiting_ci" not in ja.TERMINAL


# ---- Protokoll und Workflows ---------------------------------------------------------------------------------------------------------
def test_the_protocol_teaches_await_ci_and_the_acceptance_report():
    api = api_with_pr()
    fire = Fire()
    ja.start_backlog_job(api, cfg(**ALL), item_ref="a", backlog_path=BACKLOG, auto_continue=True, chain_budget=1, run_id="800", run_attempt="1",
                         fire_url="https://example.invalid/f", fire_token="T", fire=fire, now=NOW)
    text = fire.calls[0]
    assert "await_ci" in text and '"acceptance"' in text and "awaiting_ci" in text and "Warte nicht auf die CI" in text
    assert "needs_human | await_ci" in text


def test_the_gate_workflow_shares_the_state_concurrency_group_and_still_runs_only_default_branch_code():
    text = (ROOT / ".github/workflows/jarvis-merge-gate.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert doc["concurrency"]["group"] == "jarvis-state" and doc["concurrency"]["cancel-in-progress"] is False
    assert "pull_request_target" not in text and "head.sha" not in text and "secrets." not in text
