"""Nach einem Merge zuverlaessig fortsetzen: Gate-Ausloeser bei jedem Push auf main, 'erledigt' nur nach nachgewiesenem Merge, kein doppelter Start desselben
Schritts, sicherer Stopp bei unklarer PR-Zuordnung. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_awaiting_ci import ACC, ALL, BACKLOG, ClosingApi, api_with_pr, awaiting, gate, report, started  # noqa: E402
from test_jarvis_automation import NOW, REPO, ROOT, Fire, cfg, state_of  # noqa: E402
from test_merge_gate import GateApi, HEAD  # noqa: E402

import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

ONLY_CONTINUE = dict(JARVIS_AUTO_CONTINUE_ENABLED="true")


def begin(api, ref="next", c=None, path=None, **kw):
    args = dict(item_ref=ref, backlog_path=path or BACKLOG, auto_continue=True, chain_budget=3, run_id=kw.pop("run_id", "70"), run_attempt="1",
                fire_url="https://example.invalid/f", fire_token="T", fire=Fire(), now=NOW)
    args.update(kw)
    return ja.start_backlog_job(api, c or cfg(**ALL), **args)


def controller(api, n, c=None, run_id="80"):
    return ja.run_controller(api, c or cfg(**ALL), after_job=n, backlog_path=BACKLOG, run_id=run_id, run_attempt="1", fire_url="https://example.invalid/f",
                             fire_token="T", fire=Fire(), now=NOW)


def owner_merges(api):
    api.pr.update({"merged": True, "state": "closed", "merge_commit_sha": "e" * 40})


# ---- 1/2/3: erledigt nur nach nachgewiesenem Merge ---------------------------------------------------------------------------------------
def test_merged_pr_marks_the_step_done_and_selects_the_next_approved_step():
    api = api_with_pr()
    n = awaiting(api)
    gate(api)
    assert state_of(api, n)["merged"]["pr"] == 7 and "a" in ja.completed_item_ids(api, require_merge=True)
    out = controller(api, n)
    assert out.startswith("started:") and state_of(api, int(out.split(":")[1]))["chain"]["item_id"] == "b"


def test_green_ci_with_an_open_pr_is_not_done_and_the_step_cannot_be_started_again():
    api = api_with_pr()
    c = cfg(**ONLY_CONTINUE)
    n = awaiting(api, c)
    gate(api, c)
    st = state_of(api, n)
    assert st["status"] == "completed" and st["ci"]["result"] == "success" and "merged" not in st
    assert "a" not in ja.completed_item_ids(api, require_merge=True)
    with pytest.raises(ja.AutomationError, match="wartet auf den Merge"):
        begin(api, c=c)                                                                       # 'next' would pick 'a' again: refused instead
    with pytest.raises(ja.AutomationError, match="wartet auf den Merge"):
        begin(api, "a", c=c)
    assert api.dispatched == [] and len(api.issues) == 1


def test_a_pr_closed_without_merge_is_never_done_and_never_continues_but_frees_the_step():
    api = api_with_pr()
    c = cfg(**ONLY_CONTINUE)
    n = awaiting(api, c)
    gate(api, c)                                                                              # job completes (CI green), nothing merged
    api.pr.update({"merged": False, "state": "closed"})
    out = gate(api, c)
    st = state_of(api, n)
    assert "merged" not in st and st.get("abandoned", {}).get("pr") == 7 and api.dispatched == []
    assert any("ohne Merge" in line for line in out)
    assert "a" not in ja.completed_item_ids(api, require_merge=True)
    assert begin(api, "a")["state"]["chain"]["item_id"] == "a"                                  # may be tried again, deliberately and once


# ---- 4/5/6: Idempotenz, schon erledigt, kein vorzeitiger Start ------------------------------------------------------------------------
def test_processing_the_same_merge_twice_changes_nothing():
    api = api_with_pr()
    c = cfg(**ONLY_CONTINUE)
    n = awaiting(api, c)
    gate(api, c)
    owner_merges(api)
    gate(api, c)
    first = state_of(api, n)["merged"]
    assert len(api.dispatched) == 1
    gate(api, c)
    gate(api, c)
    assert state_of(api, n)["merged"] == first and len(api.dispatched) == 1


def test_an_already_done_step_is_not_processed_or_started_again():
    path = Path(tempfile.mkdtemp()) / "backlog.json"
    path.write_text(json.dumps({"items": [{"id": "a", "task": "A", "approved": True, "done": True, "depends_on": [], "acceptance": ACC},
                                          {"id": "b", "task": "B", "approved": True, "depends_on": ["a"], "acceptance": ACC}]}))
    api = api_with_pr()
    with pytest.raises(ja.AutomationError, match="erledigt"):
        begin(api, "a", path=path)
    assert state_of(api, begin(api, path=path)["issue"])["chain"]["item_id"] == "b"


def test_merge_detected_but_the_marker_cannot_be_written_means_no_continuation_yet():
    api = api_with_pr()
    c = cfg(**ONLY_CONTINUE)
    n = awaiting(api, c)
    gate(api, c)
    owner_merges(api)
    real = api.update_issue
    api.update_issue = lambda *a, **k: (_ for _ in ()).throw(ja.ApiError("down", status=502))
    gate(api, c)
    assert api.dispatched == [] and "merged" not in state_of(api, n)
    api.update_issue = real
    gate(api, c)                                                                              # the next run catches up, exactly once
    assert state_of(api, n)["merged"]["pr"] == 7 and len(api.dispatched) == 1


# ---- 8: bereits aktiver Folgeauftrag ----------------------------------------------------------------------------------------------------
def test_an_active_followup_job_prevents_a_second_start_of_the_same_or_any_step():
    api = api_with_pr()
    n = awaiting(api)
    gate(api)
    out = controller(api, n)
    job2 = int(out.split(":")[1])
    assert controller(api, n, run_id="81") == "already-decided"
    with pytest.raises(ja.AutomationError, match="laeuft bereits"):
        begin(api, "next", run_id="82")
    with pytest.raises(ja.AutomationError, match="laeuft bereits"):
        begin(api, "b", run_id="83")
    assert state_of(api, job2)["status"] == "running" and len([i for i in api.issues.values() if ja.own_job_issue(i)]) == 2


def test_the_controller_refuses_a_step_that_is_already_waiting_for_its_merge():
    api = api_with_pr()
    n = awaiting(api)
    gate(api)
    other = ja.start_job(api, cfg(**ALL), task="b", base_branch="main", auto_continue=True, chain_budget=3, timeout_minutes=60, run_id="90", run_attempt="1",
                         fire_url="https://example.invalid/f", fire_token="T", fire=Fire(), now=NOW, item_id="b", acceptance_count=2)["issue"]
    ja.set_state(api, api.get_issue(other), state_of(api, other), "completed", extra={"report": {
        "branch": "claude/other", "pr_url": f"https://github.com/{REPO}/pull/9", "commits": ["d" * 40], "tests": [], "next_action": "none", "status": "success"}})
    out = controller(api, n, run_id="91")
    assert out == "stopped" and "wartet auf den Merge" in " ".join(x["body"] for x in api.comments[n])


# ---- 9/10: Budget, Freigabe, sicherheitskritische Schritte --------------------------------------------------------------------------------
def test_chain_budget_exhausted_means_no_continuation_after_the_merge():
    api = api_with_pr()
    n = started(api, budget=1)
    report(api, n)
    gate(api)
    assert controller(api, n) == "stopped" and "Auftragsbudget" in " ".join(x["body"] for x in api.comments[n])


def test_unapproved_and_security_critical_steps_are_never_started_or_selected():
    path = Path(tempfile.mkdtemp()) / "backlog.json"
    path.write_text(json.dumps({"items": [
        {"id": "a", "task": "A", "approved": True, "depends_on": [], "acceptance": ACC, "done": True},
        {"id": "audit-hash-chain", "task": "sicherheitskritisch", "approved": False, "depends_on": []},
        {"id": "b", "task": "B", "approved": False, "depends_on": ["a"]}]}))
    api = api_with_pr()
    for ref in ("audit-hash-chain", "b"):
        with pytest.raises(ja.AutomationError, match="nicht freigegeben"):
            begin(api, ref, path=path)
    with pytest.raises(ja.AutomationError, match="(?i)kein freigegebener"):
        begin(api, "next", path=path)
    assert api.issues == {}


def test_the_shipped_plan_never_selects_a_security_critical_step():
    items = ja.load_backlog(ROOT / ".github/automation/backlog.json")
    raw = json.loads((ROOT / ".github/automation/backlog.json").read_text(encoding="utf-8"))
    approved_by_plan = set(raw["plan"]["approved_items"])
    for step in ("audit-hash-chain", "cli-confirm-timeout", "llm-goal-planning", "coding-llm-edits", "smartphone-api-design"):
        assert step not in approved_by_plan and not next(i for i in items if i["id"] == step).get("approved")


# ---- 11: CI fehlgeschlagen -> begrenzte Korrekturschleife --------------------------------------------------------------------------------
def test_failed_ci_uses_the_bounded_repair_loop_on_the_same_pr_and_then_stops():
    api = api_with_pr()
    api.runs[1].update(conclusion="failure")
    n = awaiting(api)
    gate(api)
    assert api.dispatched[-1] == ("jarvis-controller.yml", "main", {"repair_pr": "7", "repair_sha": HEAD})
    c = cfg(**ALL)
    for k in range(3):
        assert mg.run_repair(api, c, pr_number=7, sha=HEAD, backlog_path=BACKLOG, run_id=str(500 + k), run_attempt="1", fire_url="https://example.invalid/f",
                             fire_token="T", fire=Fire(), now=NOW).startswith("started")
        ja.set_state(api, api.get_issue(max(api.issues)), state_of(api, max(api.issues)), "failed")
    assert mg.run_repair(api, c, pr_number=7, sha=HEAD, backlog_path=BACKLOG, run_id="599", run_attempt="1", fire_url="u", fire_token="t", fire=Fire()) == "ignored:blocked"
    assert "merged" not in state_of(api, n)


# ---- 12: unklare oder nicht vertrauenswuerdige PR-Zuordnung -> sicherer Stopp ------------------------------------------------------------
@pytest.mark.parametrize("pr_url,pr_over", [
    ("https://github.com/evil/JARVIS/pull/7", {}),                                            # PR of another repository
    (f"https://github.com/{REPO}/pull/7/files", {}),                                          # not a plain PR URL
    (f"https://github.com/{REPO}/issues/7", {}),
    (f"https://github.com/{REPO}/pull/7", {"base": {"ref": "claude/other"}}),                 # merged, but into a different base
    (f"https://github.com/{REPO}/pull/7", {"head": {"ref": "claude/anderer", "sha": HEAD, "repo": {"full_name": REPO}}}),   # other branch than reported
    (f"https://github.com/{REPO}/pull/7", {"head": {"ref": "claude/work", "sha": HEAD, "repo": {"full_name": "evil/JARVIS"}}}),   # fork
])
def test_an_untrusted_or_inconsistent_pr_association_never_marks_or_continues(pr_url, pr_over):
    api = ClosingApi(reviews=[])
    n = awaiting(api, cfg(**ONLY_CONTINUE))
    st = state_of(api, n)
    ja.set_state(api, api.get_issue(n), st, "completed", extra={"report": {**st["report"], "pr_url": pr_url, "next_action": "continue"}, "ci_gated": True,
                                                                  "ci": {"result": "success"}})
    api.pr.update({"merged": True, "state": "closed", **pr_over})
    out = mg.advance_merged(api, cfg(**ONLY_CONTINUE), now=NOW)
    assert "merged" not in state_of(api, n) and api.dispatched == [] and not any("gemergt" in line for line in out)


# ---- Ausloeser --------------------------------------------------------------------------------------------------------------------------
def test_the_gate_runs_on_every_push_to_main_so_a_merge_is_noticed_immediately():
    text = (ROOT / ".github/workflows/jarvis-merge-gate.yml").read_text(encoding="utf-8")
    on = yaml.safe_load(text)[True]
    assert on["push"] == {"branches": ["main"]} and "workflow_run" in on and "schedule" in on and "workflow_dispatch" in on
    assert "pull_request_target" not in on and "pull_request" not in on and "pull_request_review" not in on
    assert "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)" in text and "ref: ${{ github.event.repository.default_branch }}" in text
    assert "secrets." not in text and "head.sha" not in text and "head.ref" not in text
