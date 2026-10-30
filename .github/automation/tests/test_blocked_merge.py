"""mergeable_state 'blocked' allein ist kein Grund, den Merge nicht zu versuchen: GitHub meldet es auch fuer Regeln, die das Gate nicht kennt (z. B. Ruleset-Freigaben).
Das Gate hat alle eigenen Bedingungen geprueft; die Merge-API erzwingt die Regeln selbst, lehnt sonst ab und nennt den Grund, der dann im Statuskommentar steht.
Alle anderen Gate-Bedingungen, Konflikte und der Not-Aus bleiben unveraendert maßgeblich. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_jarvis_automation import state_of  # noqa: E402
from test_merge_gate import HEAD  # noqa: E402
from test_pr_update import api_behind, awaiting_job, gate, status_text  # noqa: E402

REASON = "Review required by someone other than the author of unattributed changes"


def blocked_api(**kw):
    api = api_behind(**kw)
    api.behind = 0
    api.pr["mergeable_state"] = "blocked"
    return api


def test_a_blocked_pr_with_all_gate_conditions_met_gets_a_merge_attempt_with_the_checked_sha():
    api = blocked_api()
    awaiting_job(api)
    gate(api)
    assert [m["sha"] for m in api.merged] == [HEAD] and api.pr["merged"] is True


def test_when_github_refuses_the_reason_is_shown_and_nothing_continues():
    api = blocked_api()
    n = awaiting_job(api)
    api.merge_message = REASON
    gate(api)
    assert api.merged == [] and "HTTP 405" in status_text(api) and "unattributed changes" in status_text(api)
    assert "merged" not in state_of(api, n)


@pytest.mark.parametrize("mutate", [
    lambda a: setattr(a, "no_job", True),                                            # no approved backlog job and no owner review: nobody approved this commit
    lambda a: setattr(a, "files", [".github/workflows/x.yml"]),
    lambda a: setattr(a, "files", ["CLAUDE.md"]),
    lambda a: setattr(a, "runs", a.runs[:1]),
    lambda a: a.runs[1].update(status="in_progress", conclusion=None),
    lambda a: a.runs[1].update(conclusion="failure"),
    lambda a: a.runs[1].update(app={"slug": "evil-app"}),
    lambda a: setattr(a, "behind", 2),
    lambda a: a.pr["head"].update(sha="e" * 40),                                     # not the reported commit and not a verified update
])
def test_blocked_never_overrides_another_gate_condition(mutate):
    api = blocked_api()
    awaiting_job(api)
    mutate(api)
    if getattr(api, "no_job", False):
        api.list_job_issues = lambda **k: []
    gate(api)
    assert api.merged == []


@pytest.mark.parametrize("state, mergeable", [("dirty", False), ("behind", True), ("blocked", False), ("clean", False)])
def test_conflicts_and_stale_branches_still_stop_the_merge(state, mergeable):
    api = blocked_api()
    awaiting_job(api)
    api.pr.update(mergeable_state=state, mergeable=mergeable)
    gate(api)
    assert api.merged == []


def test_the_halt_stops_a_blocked_merge_too():
    api = blocked_api()
    awaiting_job(api)
    gate(api, JARVIS_AUTOMATION_HALT="true")
    assert api.merged == []
