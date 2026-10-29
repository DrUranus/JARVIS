"""Veraltete PR-Branches: das Gate aktualisiert sie (nur freigegebene, nie ohne Nachweis), startet die CI fuer den neuen Stand selbst (Pushes mit GITHUB_TOKEN loesen
keine Workflows aus), wartet auf die Pflichtpruefungen und mergt erst dann. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_awaiting_ci import ALL, BACKLOG, report, started  # noqa: E402
from test_jarvis_automation import NOW, ROOT, cfg, state_of  # noqa: E402
from test_merge_gate import GOOD_RUN, HEAD, GateApi  # noqa: E402

import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

NEW = "9" * 40                       # head of the PR branch after "update branch"
MAIN = "a" * 40                      # the main commit that was merged into the branch
mg._sleep = lambda s: None          # no real waiting in tests


class UpdApi(GateApi):
    """GateApi + the update-branch endpoint, commit parents and compare with ahead_by. A merged PR is closed (like GitHub)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.updates, self.parents, self.ahead = [], {}, {}
        self.update_status = None            # e.g. 422: GitHub refuses (merge conflict)
        self.visible = True                  # False: GitHub accepts (202) but the new head is not there yet
        self.merge_message = None
        self.pr["head"]["sha"] = HEAD
        self.behind = 2

    def request(self, method, path, body=None):
        if method == "PUT" and path.endswith("/update-branch"):
            self.updates.append(body)
            if self.update_status:
                raise ja.ApiError("update refused", status=self.update_status, detail="merge conflict between base and head")
            if self.visible:
                self.parents[NEW] = [HEAD, MAIN]
                self.ahead[MAIN] = 0
                self.pr["head"]["sha"] = NEW
                self.behind, self.runs = 0, []
            return {"message": "Updating pull request branch."}
        if method == "GET" and "/commits/" in path and "/check-runs" not in path:
            return {"parents": [{"sha": p} for p in self.parents.get(path.rsplit("/", 1)[1], [])]}
        if method == "GET" and "/compare/" in path:
            tip = path.rsplit("...", 1)[1]
            return {"behind_by": self.behind if tip == self.pr["head"]["sha"] else 0, "ahead_by": self.ahead.get(tip, 1)}
        if method == "PUT" and path.endswith("/merge"):
            if self.merge_message:
                raise ja.ApiError("merge refused", status=405, detail=self.merge_message)
            if self.pr.get("merged"):
                raise ja.ApiError("already merged", status=405)
            result = super().request(method, path, body)
            self.pr.update({"merged": True, "state": "closed", "merge_commit_sha": "e" * 40})
            return result
        return super().request(method, path, body)


def api_behind(**kw):
    return UpdApi(reviews=[], **kw)


def awaiting_job(api, c=None):
    c = c or cfg(**ALL)
    n = started(api, c)
    assert report(api, n, c) == "accepted"
    return n


def gate(api, c=None, **env):
    return mg.run_gate(api, c or cfg(**{**ALL, **env}), backlog_path=BACKLOG, dispatch=api.dispatch_workflow)


def completed_job(api, c=None):
    """A job that already completed (CI verified for the reported commit): the approval chain is then the only thing that decides about a new head."""
    c = c or cfg(**ALL)
    n = awaiting_job(api, c)
    st = state_of(api, n)
    ja.set_state(api, api.get_issue(n), st, "completed", extra={"report": {**st["report"], "next_action": "continue"}, "ci": {"result": "success"}, "ci_gated": True})
    return n


def ci_green(api, sha):
    api.runs = [{**GOOD_RUN, "id": 1, "name": "tests-linux", "head_sha": sha}, {**GOOD_RUN, "id": 2, "name": "tests-windows", "head_sha": sha}]


def status_text(api):
    return api.comments[7][0]["body"]


# ---- veralteter Branch wird aktualisiert, CI neu gestartet, erst danach gemergt ---------------------------------------------------------
def test_a_stale_approved_branch_is_updated_with_the_expected_head_and_ci_is_restarted_for_the_new_head():
    api = api_behind()
    n = awaiting_job(api)
    out = gate(api)
    assert api.updates == [{"expected_head_sha": HEAD}]
    assert ("pr-tests.yml", "claude/work", {}) in api.dispatched                      # the push by GITHUB_TOKEN starts no workflow: the gate starts the CI
    assert api.merged == [] and any("aktualisiert" in line for line in out)
    assert len(state_of(api, n)["branch_updates"]) == 1 and state_of(api, n)["branch_updates"][0]["from"] == HEAD
    assert "aktualisiert" in status_text(api)


def test_after_the_update_the_merge_waits_for_the_ci_of_the_new_head_and_then_uses_exactly_that_commit():
    api = api_behind()
    n = awaiting_job(api)
    gate(api)
    out = gate(api)                                                                 # CI of the new head is not there yet
    assert api.merged == [] and len(api.updates) == 1                               # no second update, no premature merge
    ci_green(api, NEW)
    gate(api)
    assert api.merged == [{"sha": NEW, "merge_method": "squash"}] and state_of(api, n)["merged"]["pr"] == 7
    assert [d[0] for d in api.dispatched if d[0] == "jarvis-controller.yml"] == ["jarvis-controller.yml"]


def test_duplicate_gate_runs_after_the_update_change_nothing():
    api = api_behind()
    n = awaiting_job(api)
    gate(api)
    before = (len(api.updates), len(api.dispatched), state_of(api, n)["branch_updates"])
    for _ in range(3):
        gate(api)
    assert (len(api.updates), len([d for d in api.dispatched if d[0] == "pr-tests.yml"]), state_of(api, n)["branch_updates"]) == (before[0], 1, before[2])


def test_the_ci_is_started_once_for_an_update_head_that_became_visible_later():
    api = api_behind()
    api.visible = False                                                             # 202 Accepted, but the head does not move within the polling time
    n = awaiting_job(api)
    gate(api)
    assert len(api.updates) == 1 and [d for d in api.dispatched if d[0] == "pr-tests.yml"] == []
    api.parents[NEW], api.ahead[MAIN] = [HEAD, MAIN], 0                             # now the update is there
    api.pr["head"]["sha"], api.behind, api.runs = NEW, 0, []
    gate(api)
    gate(api)
    assert len([d for d in api.dispatched if d[0] == "pr-tests.yml"]) == 1 and len(api.updates) == 1
    assert state_of(api, n)["ci_dispatched"] == [NEW]


# ---- Sicherheit der Aktualisierung --------------------------------------------------------------------------------------------------
def test_an_unapproved_branch_is_never_updated():
    api = api_behind()
    n = awaiting_job(api)
    st = state_of(api, n)
    ja.set_state(api, api.get_issue(n), st, "completed", extra={"report": {**st["report"], "commits": ["f" * 40]}, "ci_gated": True})   # reported another commit
    gate(api)
    assert api.updates == [] and api.merged == []


def test_a_protected_pr_is_kept_up_to_date_but_never_merged():
    api = api_behind(files=["src/jarvis/bootstrap.py"])
    n = awaiting_job(api)
    gate(api)
    assert len(api.updates) == 1                                                     # the owner can merge without clicking 'update branch'
    ci_green(api, NEW)
    gate(api)
    assert api.merged == [] and "Besitzer" in status_text(api)


def test_a_branch_that_is_not_behind_is_not_touched():
    api = api_behind()
    api.behind = 0
    awaiting_job(api)
    gate(api)
    assert api.updates == [] and [d for d in api.dispatched if d[0] == "pr-tests.yml"] == []


def test_failing_ci_gets_the_repair_loop_first_not_an_update():
    api = api_behind()
    api.runs[1].update(conclusion="failure")
    awaiting_job(api)
    gate(api)
    assert api.updates == [] and any(d[0] == "jarvis-controller.yml" and "repair_pr" in d[2] for d in api.dispatched)


@pytest.mark.parametrize("parents,ahead", [
    ({NEW: [HEAD]}, {}),                                                            # not a merge commit (an ordinary extra commit)
    ({NEW: ["c" * 40, MAIN]}, {MAIN: 0}),                                           # first parent is not the approved head
    ({NEW: [HEAD, MAIN]}, {MAIN: 3}),                                               # second parent is not in main
    ({NEW: [HEAD, MAIN, "d" * 40]}, {MAIN: 0}),                                     # octopus merge
])
def test_a_new_head_that_is_not_a_clean_merge_of_main_into_the_approved_head_is_not_approved(parents, ahead):
    api = api_behind()
    completed_job(api)
    api.behind = 0
    api.pr["head"]["sha"] = NEW
    api.parents, api.ahead = parents, ahead
    ci_green(api, NEW)
    gate(api)
    assert api.merged == [] and "keine Freigabe" in status_text(api)


def test_the_update_chain_is_bounded():
    api = api_behind()
    completed_job(api)
    api.behind = 0
    chain = [HEAD] + [str(i) * 40 for i in range(1, 6)]
    for old, new in zip(chain, chain[1:]):
        api.parents[new] = [old, MAIN]
    api.ahead[MAIN] = 0
    api.pr["head"]["sha"] = chain[-1]                                               # five stacked merges: more than the gate ever creates
    ci_green(api, chain[-1])
    gate(api)
    assert api.merged == []


def test_a_clean_merge_of_main_into_the_approved_head_is_approved_and_one_more_stacked_update_still_is():
    api = api_behind()
    completed_job(api)
    api.behind = 0
    mid, top = "b" * 40, NEW
    api.parents.update({mid: [HEAD, MAIN], top: [mid, MAIN]})
    api.ahead[MAIN] = 0
    api.pr["head"]["sha"] = top
    ci_green(api, top)
    gate(api)
    assert api.merged == [{"sha": top, "merge_method": "squash"}]


# ---- Grenzen, Konflikte, Fehler ---------------------------------------------------------------------------------------------------------
def test_a_conflict_stops_with_a_clear_reason_and_does_not_loop():
    api = api_behind()
    api.update_status = 422
    n = awaiting_job(api)
    gate(api)
    gate(api)
    assert api.merged == [] and [d for d in api.dispatched if d[0] == "pr-tests.yml"] == []
    assert "Konflikt" in status_text(api) or "merge conflict" in status_text(api)
    assert len(api.updates) <= 2 and len(state_of(api, n).get("branch_updates", [])) <= 2


def test_updates_are_limited_to_three_per_job_then_the_owner_is_needed():
    api = api_behind()
    api.visible = False
    n = awaiting_job(api)
    for _ in range(6):
        gate(api)
    assert len(api.updates) == mg.MAX_BRANCH_UPDATES == 3 and len(state_of(api, n)["branch_updates"]) == 3
    assert "ausgeschoepft" in status_text(api) and api.merged == []


def test_halt_stops_updates_and_ci_starts():
    api = api_behind()
    awaiting_job(api)
    gate(api, JARVIS_AUTOMATION_HALT="true")
    assert api.updates == [] and api.dispatched == []


def test_a_refused_merge_names_githubs_reason_and_continues_nothing():
    api = api_behind()
    api.behind = 0
    n = awaiting_job(api)
    api.merge_message = "Review required by someone other than the author of unattributed changes"
    gate(api)
    assert api.merged == [] and "HTTP 405" in status_text(api) and "unattributed changes" in status_text(api)
    assert "merged" not in state_of(api, n) and not any(d[0] == "jarvis-controller.yml" and "after_job" in d[2] for d in api.dispatched)


def test_api_errors_carry_githubs_message(monkeypatch):
    body = io.BytesIO(json.dumps({"message": "Required status check \"tests-windows\" is expected.", "documentation_url": "x"}).encode())
    err = urllib.error.HTTPError("https://api.github.com/x", 405, "Method Not Allowed", {}, body)
    monkeypatch.setattr(ja.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(err))
    with pytest.raises(ja.ApiError) as exc:
        ja.GitHubApi("DrUranus/JARVIS", "T").request("PUT", "/repos/DrUranus/JARVIS/pulls/7/merge", {})
    assert exc.value.status == 405 and "tests-windows" in exc.value.detail and "T" not in exc.value.detail.replace("tests-windows", "").replace("Required status check", "")


# ---- Workflow ----------------------------------------------------------------------------------------------------------------------------
def test_pr_tests_can_be_started_by_the_gate_for_a_claude_branch_and_still_tests_exactly_the_checked_out_head():
    text = (ROOT / ".github/workflows/pr-tests.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert "workflow_dispatch" in doc[True] and "pull_request" in doc[True] and "pull_request_target" not in text
    assert doc["permissions"] == {"contents": "read"} and "secrets." not in text
    for job in doc["jobs"].values():
        assert "startsWith(github.ref_name, 'claude/')" in job["if"] and "startsWith(github.head_ref, 'claude/')" in job["if"]
        assert job["steps"][0]["with"]["ref"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    assert text.count("HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}") == 2
    assert doc["concurrency"]["group"] == "pr-tests-${{ github.event.pull_request.number || github.ref }}"
    assert tuple(doc["jobs"]) == mg.REQUIRED_CHECKS


def test_the_gate_workflow_keeps_its_permissions_and_trust_boundary():
    doc = yaml.safe_load((ROOT / ".github/workflows/jarvis-merge-gate.yml").read_text(encoding="utf-8"))
    assert doc["permissions"] == {"contents": "write", "pull-requests": "write", "issues": "write", "checks": "read", "actions": "write"}
