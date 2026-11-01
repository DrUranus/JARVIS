"""Einmalig freigegebener Entwicklungsplan: Plan-Block im Backlog, Abnahmekriterien, Start eines Backlog-Schritts per ID, wahrheitsgemaesses 'done',
Fortsetzung nach einem vom Besitzer gemergten PR. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_jarvis_automation import NOW, ROOT, FakeApi, Fire, cfg, finish, state_of  # noqa: E402
from test_merge_gate import GateApi  # noqa: E402

import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

ACC = ["Tests gruen", "Doku aktualisiert"]


def backlog(plan=None, items=None):
    items = items if items is not None else [
        {"id": "a", "task": "Aufgabe A", "approved": False, "depends_on": [], "acceptance": ACC, "timeout_minutes": 45},
        {"id": "b", "task": "Aufgabe B", "approved": False, "depends_on": ["a"], "acceptance": ACC},
        {"id": "c", "task": "Aufgabe C", "approved": False, "depends_on": ["b"]},
    ]
    p = Path(tempfile.mkdtemp()) / "backlog.json"
    p.write_text(json.dumps({"plan": plan, "items": items} if plan is not None else {"items": items}))
    return p


PLAN = {"id": "pc-v1", "approved": True, "approved_items": ["a", "b"]}


# ---- Plan-Block ------------------------------------------------------------------------------------------------------------------------
def test_plan_approval_marks_exactly_the_listed_items_as_approved():
    items = ja.load_backlog(backlog(PLAN))
    assert {i["id"]: i["approved"] for i in items} == {"a": True, "b": True, "c": False}


def test_unapproved_plan_approves_nothing():
    items = ja.load_backlog(backlog({**PLAN, "approved": False}))
    assert not any(i["approved"] for i in items)


def test_items_are_never_approved_by_the_plan_when_not_listed():
    items = ja.load_backlog(backlog({**PLAN, "approved_items": ["a"]}))
    assert [i["id"] for i in items if i["approved"]] == ["a"]
    assert ja.select_next_item(items, {"a"}, set()) is None            # b is not approved, c depends on b


@pytest.mark.parametrize("plan", [
    {"id": "x y", "approved": True, "approved_items": ["a"]},               # invalid plan id
    {"id": "pc-v1", "approved": "yes", "approved_items": ["a"]},            # not a real boolean
    {"id": "pc-v1", "approved": True, "approved_items": "a"},               # not a list
    {"id": "pc-v1", "approved": True, "approved_items": ["zzz"]},           # unknown item
    {"id": "pc-v1", "approved": True, "approved_items": ["c"]},             # approved item without acceptance criteria
    {"id": "pc-v1", "approved": True},                                       # no item list
])
def test_invalid_plans_are_rejected(plan):
    with pytest.raises(ja.AutomationError):
        ja.load_backlog(backlog(plan))


@pytest.mark.parametrize("acceptance", ["Tests gruen", [], [""], ["x" * 401], ["ok"] * 11, [1]])
def test_invalid_acceptance_criteria_are_rejected(acceptance):
    items = [{"id": "a", "task": "A", "approved": False, "depends_on": [], "acceptance": acceptance}]
    with pytest.raises(ja.AutomationError):
        ja.load_backlog(backlog(items=items))


def test_a_legacy_backlog_without_plan_still_loads_unchanged():
    items = ja.load_backlog(ROOT / ".github/automation/backlog.json")
    assert all(isinstance(i["approved"], bool) for i in items)


def test_an_item_may_not_approve_itself_into_an_unapproved_plan_and_a_flag_in_the_item_still_counts():
    items = [{"id": "a", "task": "A", "approved": True, "depends_on": []}]
    assert ja.load_backlog(backlog(items=items))[0]["approved"] is True        # per-item approval keeps working exactly as before


# ---- Aufgabentext mit Abnahmekriterien ------------------------------------------------------------------------------------------
def test_item_task_lists_the_acceptance_criteria():
    text = ja.item_task({"id": "a", "task": "Aufgabe A", "acceptance": ACC})
    assert text.startswith("Aufgabe A") and "ABNAHMEKRITERIEN" in text and "- Tests gruen" in text and "- Doku aktualisiert" in text
    assert ja.item_task({"id": "x", "task": "Nur Text"}) == "Nur Text"


def test_protocol_demands_evidence_per_criterion_for_backlog_steps_only():
    api, fire = FakeApi(), Fire()
    ja.start_job(api, cfg(), task="t", base_branch=None, auto_continue=False, chain_budget=1, timeout_minutes=60, run_id="1", run_attempt="1",
                 fire_url="https://example.invalid/f", fire_token="T", fire=fire, now=NOW, item_id="a")
    assert "Abnahmekriterium" in fire.calls[0] and "partial" in fire.calls[0]
    api2, fire2 = FakeApi(), Fire()
    ja.start_job(api2, cfg(), task="t", base_branch=None, auto_continue=False, chain_budget=1, timeout_minutes=60, run_id="2", run_attempt="1",
                 fire_url="https://example.invalid/f", fire_token="T", fire=fire2, now=NOW)
    assert "Abnahmekriterium" not in fire2.calls[0]


# ---- Start eines Backlog-Schritts per ID ------------------------------------------------------------------------------------------
def begin(api, ref, path=None, fire=None, **kw):
    args = dict(item_ref=ref, backlog_path=path or backlog(PLAN), auto_continue=True, chain_budget=3, run_id="500", run_attempt="1",
                fire_url="https://example.invalid/f", fire_token="T", fire=fire or Fire(), now=NOW)
    args.update(kw)
    return ja.start_backlog_job(api, cfg(), **args)


def test_next_starts_the_first_approved_open_item_with_its_limits_and_criteria():
    api, fire = FakeApi(), Fire()
    r = begin(api, "next", fire=fire)
    st = state_of(api, r["issue"])
    assert st["chain"]["item_id"] == "a" and st["chain"]["auto_continue"] is True and st["timeout_minutes"] == 45
    assert "Aufgabe A" in fire.calls[0] and "- Tests gruen" in fire.calls[0]


def test_an_explicit_id_starts_that_item_only_when_approved_open_and_its_dependencies_are_done():
    api = FakeApi()
    with pytest.raises(ja.AutomationError, match="Abhaengigkeit"):
        begin(api, "b")                                                       # a is not done yet
    with pytest.raises(ja.AutomationError, match="nicht freigegeben"):
        begin(api, "c")
    with pytest.raises(ja.AutomationError, match="unbekannt"):
        begin(api, "zzz")
    with pytest.raises(ja.AutomationError, match="ungueltig"):
        begin(api, "../x")
    assert api.issues == {}                                                    # nothing was created by the refusals


def test_a_done_item_is_never_started_again():
    api = FakeApi()
    path = backlog(PLAN, items=[{"id": "a", "task": "A", "approved": False, "depends_on": [], "acceptance": ACC, "done": True},
                                {"id": "b", "task": "B", "approved": False, "depends_on": ["a"], "acceptance": ACC}])
    with pytest.raises(ja.AutomationError, match="erledigt"):
        begin(api, "a", path=path)
    assert state_of(api, begin(api, "next", path=path)["issue"])["chain"]["item_id"] == "b"


def test_next_without_an_open_item_refuses():
    api = FakeApi()
    with pytest.raises(ja.AutomationError, match="(?i)kein freigegebener"):
        begin(api, "next", path=backlog({**PLAN, "approved_items": []}))


def test_the_start_still_enforces_the_single_active_job_and_the_chain_cap():
    api = FakeApi()
    begin(api, "next")
    with pytest.raises(ja.AutomationError, match="laeuft bereits"):
        begin(api, "next", run_id="501")
    r = begin(FakeApi(), "next", chain_budget=99)
    assert r["state"]["chain"]["budget"] == ja.HARD_MAX_CHAIN_JOBS or r["state"]["chain"]["budget"] <= cfg().max_chain


def test_main_starts_a_backlog_item_from_the_environment(monkeypatch, tmp_path):
    api, fire = FakeApi(), Fire()
    monkeypatch.setattr(ja, "_api", lambda c, e: api)
    monkeypatch.setitem(ja.start_backlog_job.__kwdefaults__, "fire", fire)          # the default argument was bound at definition time
    monkeypatch.setattr(ja, "utcnow", lambda: NOW)
    path = backlog(PLAN)
    env = {"GITHUB_REPOSITORY": "DrUranus/JARVIS", "GITHUB_TOKEN": "t", "DEFAULT_BRANCH": "main", "BACKLOG_ITEM": "next", "BACKLOG_PATH": str(path),
           "AUTO_CONTINUE": "true", "CHAIN_BUDGET": "2", "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1",
           "ROUTINE_FIRE_URL": "https://example.invalid/f", "ROUTINE_FIRE_TOKEN": "T"}
    assert ja.main(["x", "start"], env) == 0 and state_of(api, 1)["chain"]["item_id"] == "a"
    assert ja.main(["x", "start"], {**env, "BACKLOG_ITEM": "", "CONTEXT": ""}) == 1          # neither item nor text: refused, nothing new
    assert len(api.issues) == 1


# ---- 'done' ist nur, was wirklich gemergt wurde ---------------------------------------------------------------------------------
def completed(api, item_id, *, branch="claude/work", pr_url="https://github.com/DrUranus/JARVIS/pull/7", merged=False):
    ja.start_job(api, cfg(), task="t", base_branch=None, auto_continue=True, chain_budget=3, timeout_minutes=60,
                 run_id=str(100 + len(api.issues)), run_attempt="1", fire_url="https://example.invalid/f", fire_token="T", fire=Fire(), now=NOW, item_id=item_id)
    n = max(api.issues)
    ja.set_state(api, api.get_issue(n), state_of(api, n), "completed", extra={"report": {
        "branch": branch, "pr_url": pr_url, "commits": ["d" * 40], "tests": [], "next_action": "continue", "status": "success"}})
    if merged:
        ja.mark_merged(api, n, pr_number=7, sha="d" * 40, now=NOW)
    return n


def test_with_auto_merge_an_item_counts_as_done_only_after_its_pr_was_merged():
    api = FakeApi()
    completed(api, "a")
    assert "a" in ja.completed_item_ids(api)                                   # unchanged default behaviour
    assert "a" not in ja.completed_item_ids(api, require_merge=True)
    api2 = FakeApi()
    completed(api2, "a", merged=True)
    assert "a" in ja.completed_item_ids(api2, require_merge=True)
    api3 = FakeApi()
    completed(api3, "a", branch=None, pr_url=None)                             # a read-only job has nothing to merge
    assert "a" in ja.completed_item_ids(api3, require_merge=True)


# ---- Fortsetzung nach einem vom Besitzer gemergten PR -----------------------------------------------------------------------
def merged_api(**pr_over):
    api = GateApi(reviews=[])
    completed(api, "a")
    api.pr.update({"merged": True, "merge_commit_sha": "e" * 40, "state": "closed", **pr_over})
    return api


def advance(api, **env):
    return mg.advance_merged(api, cfg(JARVIS_AUTO_CONTINUE_ENABLED="true", JARVIS_AUTO_MERGE_ENABLED="true", **env), now=NOW)


def test_an_owner_merged_pr_advances_the_chain_exactly_once():
    api = merged_api()
    out = advance(api)
    assert any("gemergt" in line for line in out) and state_of(api, 1)["merged"]["pr"] == 7
    assert [d[0] for d in api.dispatched] == ["jarvis-controller.yml"] and api.dispatched[0][2] == {"after_job": "1"}
    assert advance(api) == [] and len(api.dispatched) == 1                     # second run: nothing new, no second dispatch


@pytest.mark.parametrize("over", [{"merged": False}, {"base": {"ref": "claude/other"}},
                                  {"head": {"ref": "claude/anderer-branch", "sha": "d" * 40, "repo": {"full_name": "DrUranus/JARVIS"}}}])
def test_an_unmerged_or_foreign_pr_advances_nothing(over):
    api = merged_api(**over)
    advance(api)
    assert "merged" not in state_of(api, 1) and api.dispatched == []


def test_halt_and_disabled_switches_advance_nothing():
    api = merged_api()
    advance(api, JARVIS_AUTOMATION_HALT="true")
    assert api.dispatched == []
    api2 = merged_api()
    mg.advance_merged(api2, cfg(), now=NOW)                                    # neither switch set
    assert api2.dispatched == [] and "merged" not in state_of(api2, 1)


def test_the_gate_run_also_looks_for_merged_prs(tmp_path):
    api = merged_api()
    out = mg.run_gate(api, cfg(JARVIS_AUTO_CONTINUE_ENABLED="true", JARVIS_AUTO_MERGE_ENABLED="true"), backlog_path=backlog(PLAN))
    assert any("gemergt" in line for line in out) and state_of(api, 1)["merged"]["pr"] == 7 and len(api.dispatched) == 1


# ---- Workflow ----------------------------------------------------------------------------------------------------------------------
def test_start_workflow_offers_a_backlog_item_input_and_no_longer_requires_free_text():
    doc = yaml.safe_load((ROOT / ".github/workflows/claude-routine-fire.yml").read_text(encoding="utf-8"))
    inputs = doc[True]["workflow_dispatch"]["inputs"]
    assert "backlog_item" in inputs and inputs["context"]["required"] is False
    text = (ROOT / ".github/workflows/claude-routine-fire.yml").read_text(encoding="utf-8")
    assert "BACKLOG_ITEM: ${{ inputs.backlog_item }}" in text and "${{ inputs." not in text.split("run:")[-1]


def test_flipping_the_single_plan_switch_in_the_shipped_backlog_approves_exactly_the_plan_steps():
    raw = json.loads((ROOT / ".github/automation/backlog.json").read_text(encoding="utf-8"))
    raw["plan"]["approved"] = True                                              # the one-time owner action: one line
    path = Path(tempfile.mkdtemp()) / "backlog.json"
    path.write_text(json.dumps(raw))
    items = ja.load_backlog(path)
    assert {i["id"] for i in items if i["approved"]} == set(raw["plan"]["approved_items"]) | {"autonomy-invariants", "session-budget"}
    assert all(i.get("acceptance") for i in items if i["id"] in raw["plan"]["approved_items"])
    done = {i["id"] for i in items if i.get("done")}
    order, finished = [], set(done)
    while True:                                                                  # the whole plan unrolls in dependency order, each step once
        nxt = ja.select_next_item(items, finished, set())
        if not nxt:
            break
        order.append(nxt["id"])
        finished.add(nxt["id"])
    assert "windows-capture-tests" in done and "windows-capture-tests" in raw["plan"]["approved_items"]       # erledigt, aber weiter Teil der sieben freigegebenen Schritte
    assert order == [i for i in raw["plan"]["approved_items"] if i not in done]                              # nur offene Schritte laufen, jeder genau einmal
    for sensitive in ("audit-hash-chain", "cli-confirm-timeout", "smartphone-api-design"):        # llm-goal-planning/coding-llm-edits: ausdrueckliche Besitzerfreigabe (Release-Plan)
        assert not next(i for i in items if i["id"] == sensitive)["approved"]


# ---- die ausgelieferte Freigabe: die vier LLM-Schritte laufen nacheinander ueber die vorhandene Routine ------------------------------------
SHIPPED = ROOT / ".github/automation/backlog.json"


def test_the_shipped_plan_starts_the_open_steps_one_by_one_through_the_existing_routine():
    from test_jarvis_automation import RELEASE_ORDER
    api, fire = FakeApi(), Fire()
    first = begin(api, "next", path=SHIPPED, fire=fire, chain_budget=5)
    st = state_of(api, first["issue"])
    assert st["chain"]["item_id"] == "llm-compat-vetting" and st["chain"]["budget"] == 5 and st["chain"]["auto_continue"] is True
    assert "ABNAHMEKRITERIEN" in fire.calls[0]
    for ref, why in (("llm-compat-provider", "(?i)abhaengigkeit"), ("llm-routing-policy", "(?i)abhaengigkeit"), ("stt-local-provider", "(?i)abhaengigkeit"),
                     ("research-search-interface", "(?i)abhaengigkeit"), ("coding-llm-edits", "(?i)abhaengigkeit"), ("llm-goal-planning", "(?i)abhaengigkeit"),
                     ("task-resume", "(?i)abhaengigkeit"), ("cc-shell", "(?i)abhaengigkeit"), ("agent-router", "(?i)abhaengigkeit"),
                     ("audit-hash-chain", "(?i)nicht freigegeben"), ("mail-provider", "(?i)nicht freigegeben"), ("smartphone-api-design", "(?i)nicht freigegeben")):
        with pytest.raises(ja.AutomationError, match=why):
            begin(FakeApi(), ref, path=SHIPPED)
    order, api2 = [], FakeApi()
    for _ in RELEASE_ORDER:
        r = ja.start_backlog_job(api2, cfg(JARVIS_MAX_JOBS_PER_DAY="50"), item_ref="next", backlog_path=SHIPPED, auto_continue=True, chain_budget=5, run_id=str(600 + len(order)),
                                 run_attempt="1", fire_url="https://example.invalid/f", fire_token="T", fire=Fire(), now=NOW)         # Standard-Tageslimit ist 10: 16 Schritte brauchen mehr
        item = state_of(api2, r["issue"])["chain"]["item_id"]
        order.append(item)
        n = r["issue"]
        ja.set_state(api2, api2.get_issue(n), state_of(api2, n), "completed", extra={"report": {"branch": f"claude/{item}", "pr_url": f"https://github.com/DrUranus/JARVIS/pull/{100 + len(order)}",
                                                                                                "commits": ["d" * 40], "tests": [], "next_action": "continue", "status": "success"}})
        ja.mark_merged(api2, n, pr_number=100 + len(order), sha="d" * 40, now=NOW)
    assert order == RELEASE_ORDER
    with pytest.raises(ja.AutomationError, match="(?i)kein freigegebener"):
        ja.start_backlog_job(api2, cfg(JARVIS_MAX_JOBS_PER_DAY="50"), item_ref="next", backlog_path=SHIPPED, auto_continue=True, chain_budget=5, run_id="699", run_attempt="1",
                             fire_url="https://example.invalid/f", fire_token="T", fire=Fire(), now=NOW)                    # danach ist nichts mehr freigegeben
