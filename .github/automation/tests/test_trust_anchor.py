"""Vertrauensanker je Auftrag: Jeder vom Gate vollstaendig geprueften Kopf (Auftragsfreigabe, Scope, sensible Aenderungen, Commit-Historie) wird im Auftragszustand
vermerkt (trust_anchors). Spaetere Pruefungen muessen dann nur bis zum juengsten Anker zurueckgehen statt bis zum ersten gemeldeten Commit. Reine Aktualisierungen
mit dem Standard-Branch zaehlen nur, wenn sie vom Update-Bot des Gates (hoechstens MAX_BRANCH_UPDATES) oder vom Besitzer (hoechstens MAX_MANUAL_UPDATES) stammen.
Die harte Grenze von drei automatischen Aktualisierungen je Auftrag bleibt unveraendert. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_awaiting_ci import ALL  # noqa: E402
from test_jarvis_automation import cfg, state_of  # noqa: E402
from test_merge_gate import HEAD  # noqa: E402
from test_pr_update import api_behind, awaiting_job, ci_green, completed_job, gate  # noqa: E402

import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

BOT, OWNER = "github-actions[bot]", "DrUranus"


def h(i: int) -> str:
    return f"{i:040x}"


def chain(api, steps, base=HEAD):
    """steps: Autoren der aufeinander gestapelten Aktualisierungen ueber `base` (von unten nach oben). Gibt die Koepfe zurueck."""
    heads, below = [], base
    for i, author in enumerate(steps, start=1):
        sha, main = h(0xA00 + i), h(0xB00 + i)
        api.parents[sha] = [below, main]
        api.authors[sha] = author
        api.ahead[main] = 0
        heads.append(sha)
        below = sha
    return heads


def at_head(api, sha):
    api.behind = 0
    api.pr["head"]["sha"] = sha
    ci_green(api, sha)


def merged_shas(api):
    return [m["sha"] for m in api.merged]


def set_anchors(api, n, anchors):
    st = state_of(api, n)
    ja.set_state(api, api.get_issue(n), st, "completed", extra={"trust_anchors": anchors})


# ---- die reale Kette von PR #41: drei Bot-Updates ueber einem manuellen Update des Besitzers ---------------------------------------------
def test_the_real_chain_of_pr_41_is_approved():
    api = api_behind()
    completed_job(api)
    heads = chain(api, [OWNER, BOT, BOT, BOT])
    at_head(api, heads[-1])
    gate(api)
    assert merged_shas(api) == [heads[-1]]


def test_the_same_chain_was_not_recognized_before_because_it_is_longer_than_the_old_bound():
    assert mg.MAX_BRANCH_UPDATES + 1 < 5                                              # 4 Updates + der gemeldete Commit: der alte Lauf endete davor


@pytest.mark.parametrize("steps,ok", [
    ([BOT, BOT, BOT], True),
    ([BOT] * 4, False),                                                              # mehr automatische Updates als die harte Grenze
    ([OWNER] * mg.MAX_MANUAL_UPDATES, True),
    ([OWNER] * (mg.MAX_MANUAL_UPDATES + 1), False),
    ([OWNER, BOT, OWNER, BOT, OWNER, BOT], True),                                    # gemischt, jeweils innerhalb der Grenzen
    ([BOT, "claude", BOT], False),                                                   # fremder Autor mitten in der Kette
    ([BOT, "mallory", BOT], False),
    ([BOT, "", BOT], False),
])
def test_chain_hops_are_limited_by_author_and_count(steps, ok):
    api = api_behind()
    completed_job(api)
    heads = chain(api, steps)
    at_head(api, heads[-1])
    gate(api)
    assert (merged_shas(api) == [heads[-1]]) is ok


def test_a_hop_without_a_known_author_is_never_approved():
    api = api_behind()
    completed_job(api)
    heads = chain(api, [BOT])
    api.authors.pop(heads[0])
    real = api.request

    def no_author(method, path, body=None):
        out = real(method, path, body)
        if isinstance(out, dict) and "parents" in out:
            out = {"parents": out["parents"]}
        return out

    api.request = no_author
    at_head(api, heads[-1])
    gate(api)
    assert api.merged == []


def test_an_extra_commit_inside_the_chain_is_not_approved():
    api = api_behind()
    completed_job(api)
    heads = chain(api, [BOT, BOT])
    extra = h(0xC01)                                                                 # ordinary commit (one parent) between two updates
    api.parents[extra], api.authors[extra] = [heads[0]], BOT
    api.parents[heads[1]] = [extra, h(0xB02)]
    at_head(api, heads[1])
    gate(api)
    assert api.merged == []


# ---- Anker: nur nach vollstaendiger Pruefung gespeichert ----------------------------------------------------------------------------------
def test_a_fully_checked_head_is_stored_once_as_trust_anchor_even_if_it_cannot_merge_yet():
    api = api_behind()
    n = completed_job(api)
    heads = chain(api, [BOT, BOT])
    api.pr["head"]["sha"] = heads[-1]
    api.behind, api.visible = 1, False                                               # still behind main (the update is not visible yet): not mergeable now, but the content was checked
    gate(api)
    gate(api)
    assert state_of(api, n)["trust_anchors"] == [heads[-1]]


def test_the_reported_commit_itself_is_never_stored_as_anchor():
    api = api_behind()
    n = completed_job(api)
    api.behind = 0
    ci_green(api, HEAD)
    api.pr["head"]["sha"] = HEAD
    gate(api)
    assert "trust_anchors" not in state_of(api, n) or state_of(api, n)["trust_anchors"] == []


@pytest.mark.parametrize("what", ["undeclared_protected", "unknown_chain", "no_job", "halt", "draft"])
def test_no_anchor_without_a_complete_check(what):
    api = api_behind(files=[".github/workflows/x.yml"]) if what == "undeclared_protected" else api_behind()
    n = completed_job(api)
    heads = chain(api, [BOT])
    sha = heads[-1]
    kw = {}
    if what == "unknown_chain":
        api.parents[sha] = [h(0xDEAD), h(0xB01)]                                    # first parent unknown: not the approved line
    if what == "no_job":
        api.list_job_issues = lambda **k: []
    if what == "halt":
        kw["JARVIS_AUTOMATION_HALT"] = "true"
    if what == "draft":
        api.pr["draft"] = True
    api.pr["head"]["sha"] = sha
    api.behind = 1
    gate(api, **kw)
    assert state_of(api, n).get("trust_anchors", []) == []


def test_anchors_are_bounded():
    api = api_behind()
    n = completed_job(api)
    set_anchors(api, n, [h(0x900 + i) for i in range(mg.MAX_ANCHORS)])
    heads = chain(api, [BOT])
    api.pr["head"]["sha"] = heads[-1]
    api.behind = 1
    gate(api)
    assert len(state_of(api, n)["trust_anchors"]) == mg.MAX_ANCHORS and heads[-1] not in state_of(api, n)["trust_anchors"]


# ---- Anker verkuerzen die Rueckverfolgung, ersetzen aber keine Pruefung ---------------------------------------------------------------------
def test_with_an_anchor_a_longer_history_is_approved_but_without_it_it_is_not():
    steps = [BOT, BOT, BOT, OWNER, BOT, BOT, BOT]                                    # 7 updates above the reported commit: more than any walk may take
    api = api_behind()
    completed_job(api)
    heads = chain(api, steps)
    at_head(api, heads[-1])
    gate(api)
    assert api.merged == []
    api2 = api_behind()
    n = completed_job(api2)
    heads2 = chain(api2, steps)
    set_anchors(api2, n, [heads2[3]])                                                # verified earlier: 3 updates below the head
    at_head(api2, heads2[-1])
    gate(api2)
    assert merged_shas(api2) == [heads2[-1]]


@pytest.mark.parametrize("anchors", [
    "x" * 40, 5, {"a": "b"}, [5, None, {}], ["short"], ["G" * 40], [("9" * 40).upper()], ["9" * 39], [" " + "9" * 40], [h(0xFFF)],       # garbage or not part of this chain
])
def test_manipulated_or_foreign_anchors_never_approve(anchors):
    steps = [BOT] * 3 + [OWNER] + [BOT] * 3
    api = api_behind()
    n = completed_job(api)
    heads = chain(api, steps)
    set_anchors(api, n, anchors)
    at_head(api, heads[-1])
    gate(api)
    assert api.merged == []


def test_an_anchor_on_another_branch_or_job_is_not_used():
    steps = [BOT] * 3 + [OWNER] + [BOT] * 3
    api = api_behind()
    n = completed_job(api)
    heads = chain(api, steps)
    st = state_of(api, n)
    other = {**st, "report": {**st["report"], "branch": "claude/other"}, "trust_anchors": [heads[3]]}
    ja.set_state(api, api.get_issue(n), other, "completed", extra={})
    at_head(api, heads[-1])
    gate(api)
    assert api.merged == []


def test_an_anchor_does_not_cover_changes_made_after_it():
    api = api_behind()
    n = completed_job(api)
    heads = chain(api, [BOT])
    set_anchors(api, n, [heads[0]])
    later = h(0xC77)
    api.parents[later], api.authors[later] = [heads[0]], "claude"                    # a normal commit on top of the verified state
    at_head(api, later)
    gate(api)
    assert api.merged == []


# ---- harte Grenzen bleiben ---------------------------------------------------------------------------------------------------------------
def test_the_hard_limit_of_three_automatic_updates_is_unchanged_and_anchors_do_not_reset_it():
    assert mg.MAX_BRANCH_UPDATES == 3
    api = api_behind()
    api.visible = False
    n = awaiting_job(api)
    for _ in range(6):
        gate(api)
    assert len(api.updates) == 3 and len(state_of(api, n)["branch_updates"]) == 3
    set_anchors(api, n, [h(0x901)])
    for _ in range(3):
        gate(api)
    assert len(api.updates) == 3


def test_sha_scope_and_sensitive_checks_still_apply_on_an_anchored_chain():
    for mutate in (lambda a: a.runs[1].update(conclusion="failure"), lambda a: setattr(a, "files", ["CLAUDE.md"]), lambda a: setattr(a, "files", [".github/workflows/x.yml"])):
        api = api_behind()
        n = completed_job(api)
        heads = chain(api, [BOT, BOT])
        set_anchors(api, n, [heads[0]])
        at_head(api, heads[-1])
        mutate(api)
        gate(api)
        assert api.merged == [], mutate
