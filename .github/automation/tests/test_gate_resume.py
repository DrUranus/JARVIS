"""Wiederaufnahme des Merge-Gates nach der CI: Ein pr-tests-Lauf, den das Gate per workflow_dispatch mit GITHUB_TOKEN startet, loest weder ein workflow_run-
noch ein anderes Ereignis aus (GitHub: Ereignisse von GITHUB_TOKEN starten keine Workflows, ausser workflow_dispatch/repository_dispatch), und der Zeitplan laeuft nur
unregelmaessig. Darum startet das Gate mit der CI einen Warte-Lauf (jarvis-gate-resume.yml, Code des Standard-Branches), der nach den Pflichtpruefungen das Gate genau
einmal anstoesst. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_jarvis_automation import ROOT, cfg, state_of  # noqa: E402
from test_merge_gate import GOOD_RUN  # noqa: E402
from test_pr_update import NEW, UpdApi, awaiting_job, gate  # noqa: E402

import gate_resume as gr  # noqa: E402
import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

SHA = "9" * 40
RESUME = "jarvis-gate-resume.yml"


class RunsApi:
    """Checklaeufe eines Commits; jeder Abruf spielt den naechsten Stand ab (der letzte bleibt)."""

    def __init__(self, *snapshots, dispatch_error=None):
        self.snapshots, self.calls, self.dispatched, self.dispatch_error, self.repo = list(snapshots), 0, [], dispatch_error, "DrUranus/JARVIS"

    def request(self, method, path, body=None):
        assert method == "GET" and "/check-runs" in path and SHA in path, (method, path)
        snap = self.snapshots[min(self.calls, len(self.snapshots) - 1)]
        self.calls += 1
        return {"check_runs": snap}

    def dispatch_workflow(self, workflow_file, ref, inputs):
        self.dispatched.append((workflow_file, ref, inputs))
        if self.dispatch_error:
            raise self.dispatch_error


def run(name, status="completed", conclusion="success", sha=SHA, slug="github-actions", rid=1):
    return {"id": rid, "name": name, "status": status, "conclusion": conclusion if status == "completed" else None, "head_sha": sha, "app": {"slug": slug}}


BOTH_DONE = [run("tests-linux", rid=1), run("tests-windows", rid=2)]


# ---- das Gate startet die Wiederaufnahme zusammen mit der CI ------------------------------------------------------------------------
def test_starting_the_ci_also_starts_the_resume_run_on_the_default_branch_for_exactly_that_head():
    api = UpdApi(reviews=[])
    n = awaiting_job(api)
    gate(api)
    assert ("pr-tests.yml", "claude/work", {}) in api.dispatched
    assert (RESUME, "main", {"sha": NEW}) in api.dispatched                       # Code des Standard-Branches, nie des PR-Branches
    assert [d for d in api.dispatched if d[0] == RESUME] == [(RESUME, "main", {"sha": NEW})]
    assert state_of(api, n)["ci_dispatched"] == [NEW]


def test_the_resume_run_is_not_started_twice_for_the_same_head_nor_without_the_ci_start():
    api = UpdApi(reviews=[])
    awaiting_job(api)
    gate(api)
    api.request("PUT", "/x/update-branch")        # no-op for the fake; the next gate run sees the same head
    gate(api)
    gate(api)
    assert len([d for d in api.dispatched if d[0] == RESUME]) == 1 and len([d for d in api.dispatched if d[0] == "pr-tests.yml"]) == 1
    api2 = UpdApi(reviews=[])
    awaiting_job(api2)
    real = api2.dispatch_workflow

    def refuse_ci(workflow, ref, inputs):
        if workflow == "pr-tests.yml":
            raise ja.ApiError("nope", status=403)
        real(workflow, ref, inputs)

    api2.dispatch_workflow = refuse_ci
    out = gate(api2)
    assert [d for d in api2.dispatched if d[0] == RESUME] == [] and any("nicht gestartet" in line for line in out)


def test_a_refused_resume_run_does_not_break_the_gate_and_is_not_retried_in_a_loop():
    api = UpdApi(reviews=[])
    n = awaiting_job(api)
    real = api.dispatch_workflow

    def refuse_resume(workflow, ref, inputs):
        if workflow == RESUME:
            raise ja.ApiError("nope", status=403)
        real(workflow, ref, inputs)

    api.dispatch_workflow = refuse_resume
    gate(api)
    assert state_of(api, n)["ci_dispatched"] == [NEW] and len(api.updates) == 1
    gate(api)
    assert len(api.updates) == 1 and len([d for d in api.dispatched if d[0] == "pr-tests.yml"]) == 1


# ---- Warten auf genau die Pflichtpruefungen des Commits -----------------------------------------------------------------------------
def test_waiting_ends_when_both_required_checks_of_the_exact_commit_are_completed(monkeypatch):
    slept = []
    api = RunsApi([run("tests-linux", "in_progress")], [run("tests-linux"), run("tests-windows", "in_progress", rid=2)], BOTH_DONE)
    assert gr.wait_for_checks(api, SHA, sleep=slept.append) == "done"
    assert api.calls == 3 and len(slept) == 2


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "success"])
def test_waiting_also_ends_for_failed_checks_the_gate_decides_what_to_do(conclusion):
    api = RunsApi([run("tests-linux", conclusion=conclusion), run("tests-windows", conclusion="success", rid=2)])
    assert gr.wait_for_checks(api, SHA, sleep=lambda s: None) == "done"


def test_checks_of_other_commits_or_other_apps_never_end_the_waiting():
    other_sha = [run("tests-linux", sha="1" * 40), run("tests-windows", sha="1" * 40, rid=2)]
    other_app = [run("tests-linux", slug="evil-app"), run("tests-windows", slug="evil-app", rid=2)]
    for snap in (other_sha, other_app, [run("tests-linux")], []):
        api = RunsApi(snap)
        assert gr.wait_for_checks(api, SHA, sleep=lambda s: None, tries=4) == "timeout" and api.calls == 4


def test_waiting_is_bounded_and_the_newest_run_per_name_counts():
    api = RunsApi([run("tests-linux", "in_progress")])
    assert gr.wait_for_checks(api, SHA, sleep=lambda s: None) == "timeout" and api.calls == gr.MAX_TRIES
    assert gr.MAX_TRIES * gr.POLL_SECONDS <= 70 * 60                              # unter dem Zeitlimit des Workflows
    rerun = [run("tests-linux", rid=1), run("tests-windows", rid=2), run("tests-linux", "in_progress", rid=3)]
    assert gr.wait_for_checks(RunsApi(rerun), SHA, sleep=lambda s: None, tries=2) == "timeout"


# ---- genau ein Anstoss des Gates -------------------------------------------------------------------------------------------------------
def test_main_dispatches_the_gate_once_on_the_default_branch_and_nothing_else():
    api = RunsApi(BOTH_DONE)
    assert gr.resume(api, "main", SHA, sleep=lambda s: None) == "done"
    assert api.dispatched == [("jarvis-merge-gate.yml", "main", {})]              # alle PRs, die Entscheidung trifft allein das Gate


def test_on_timeout_the_gate_is_still_started_once_so_it_reports_the_state():
    api = RunsApi([run("tests-linux", "in_progress")])
    assert gr.resume(api, "main", SHA, sleep=lambda s: None) == "timeout"
    assert api.dispatched == [("jarvis-merge-gate.yml", "main", {})]


def test_a_refused_gate_dispatch_is_an_error_without_retry():
    api = RunsApi(BOTH_DONE, dispatch_error=ja.ApiError("nope", status=403))
    with pytest.raises(ja.ApiError):
        gr.resume(api, "main", SHA, sleep=lambda s: None)
    assert len(api.dispatched) == 1


@pytest.mark.parametrize("sha", ["", "main", "9" * 39, "9" * 41, "g" * 40, SHA + " ", "../" + SHA, "$(id)" + "0" * 35])
def test_only_a_full_commit_sha_is_accepted(sha):
    api = RunsApi(BOTH_DONE)
    assert gr.main(["x"], {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "DrUranus/JARVIS", "RESUME_SHA": sha, "DEFAULT_BRANCH": "main"}, api=api) == 1
    assert api.calls == 0 and api.dispatched == []


def test_main_runs_with_a_valid_sha_and_reports_ok():
    api = RunsApi(BOTH_DONE)
    assert gr.main(["x"], {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "DrUranus/JARVIS", "RESUME_SHA": SHA, "DEFAULT_BRANCH": "main"}, api=api, sleep=lambda s: None) == 0
    assert api.dispatched == [("jarvis-merge-gate.yml", "main", {})]


def test_the_emergency_halt_stops_the_resume_run_too():
    api = RunsApi(BOTH_DONE)
    env = {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "DrUranus/JARVIS", "RESUME_SHA": SHA, "DEFAULT_BRANCH": "main", "JARVIS_AUTOMATION_HALT": "true"}
    assert gr.main(["x"], env, api=api, sleep=lambda s: None) == 0 and api.calls == 0 and api.dispatched == []


# ---- Workflow-Regeln -----------------------------------------------------------------------------------------------------------------------
def test_the_resume_workflow_runs_only_trusted_default_branch_code_with_minimal_rights():
    text = (ROOT / ".github/workflows" / RESUME).read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert list(doc[True]) == ["workflow_dispatch"] and list(doc[True]["workflow_dispatch"]["inputs"]) == ["sha"]
    assert doc["permissions"] == {"actions": "write", "checks": "read"}
    assert "secrets." not in text and "pull_request" not in text and "head.ref" not in text and "head.sha" not in text and "ref: ${{ github.event.repository.default_branch }}" in text
    assert "if: ${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}" in text    # nie ein anderer Branch
    (job,) = doc["jobs"].values()
    assert job["timeout-minutes"] <= 75 and "gate_resume.py" in text and "persist-credentials: false" in text
    assert doc["concurrency"]["cancel-in-progress"] is False and "inputs.sha" in doc["concurrency"]["group"]
    assert "RESUME_SHA: ${{ inputs.sha }}" in text and "${{ inputs.sha }}" not in text.split("run:")[-1]        # die Eingabe geht nur ueber env in die Shell


def test_the_gate_workflow_keeps_the_dispatch_rights_it_needs_for_the_resume_run():
    doc = yaml.safe_load((ROOT / ".github/workflows/jarvis-merge-gate.yml").read_text(encoding="utf-8"))
    assert doc["permissions"]["actions"] == "write" and mg.RESUME_WORKFLOW == RESUME
