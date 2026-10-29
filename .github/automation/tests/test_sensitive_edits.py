"""Sensible Pfade ohne pauschale Dateisperre: der genehmigte Auftrag deklariert im Plan konkret, was er aendern darf (additiv oder frei), das Gate prueft den echten
Patch dagegen. Nur die Dateien, die festlegen WER WAS genehmigen darf (Backlog, CODEOWNERS, CLAUDE.md, .claude/), sind nie per Auftrag freigebbar. Die Freigaben des
Plans wirken erst nach plan.scopes_approved (Besitzer, einmalig). Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_awaiting_ci import ACC, ALL, ClosingApi, report  # noqa: E402
from test_jarvis_automation import NOW, ROOT, cfg, state_of  # noqa: E402
from test_merge_gate import GOOD_RUN, HEAD  # noqa: E402

import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

BOOT = "src/jarvis/bootstrap.py"
ADD = {"mode": "additive", "added": [r"from jarvis\.history\.factory import build_history", r"core\.history = build_history\(settings, core, guard\)"], "max_added": 6}
ALLOW = {BOOT: ADD}
# the real hunk of PR #41 (persistent-results): three added lines before register_emergency_components(core)
REAL_PATCH = '''@@ -64,6 +64,9 @@ def build_core(settings: Settings) -> JarvisCore:
     core.subsystems["self_improvement"] = build_self_improvement(
         settings, goals=getattr(core.subsystems.get("goals"), "engine", None), repairs=getattr(core.subsystems.get("self_repair"), "engine", None),
         audit=permissions.audit, llm=provider, confirmation=lambda: permissions.confirmation, detector=guard)
+    # Opt-in history of FINISHED work (default off, no file). Display only: after a restart nothing is resumed or started.
+    from jarvis.history.factory import build_history
+    core.history = build_history(settings, core, guard)
     register_emergency_components(core)
     return core
'''
SMALL = "@@ -1,2 +1,3 @@\n context\n+x = 1\n context\n"


def patch_with(*added, removed=()):
    body = "".join(f"+    {a}\n" for a in added) + "".join(f"-    {r}\n" for r in removed)
    return "@@ -64,6 +64,9 @@ def build_core(settings):\n     core.subsystems['x'] = 1\n" + body + "     register_emergency_components(core)\n"


def backlog(allow=ALLOW, active=True, scope=None, approved=True):
    """One plan step 'a' (approved through the plan); its declarations are active only with plan.scopes_approved."""
    p = Path(tempfile.mkdtemp()) / "backlog.json"
    item = {"id": "a", "task": "Aufgabe A", "approved": False, "depends_on": [], "acceptance": ACC}
    if allow is not None:
        item["sensitive_edits"] = allow
    if scope is not None:
        item["scope"] = scope
    plan = {"id": "pc-test", "approved": approved, "scopes_approved": active, "approved_items": ["a"]}
    p.write_text(json.dumps({"plan": plan, "items": [item]}))
    return p


def pr_api(files=None, patches=None, statuses=None, **kw):
    files = files or [BOOT, "src/jarvis/history/store.py"]
    return ClosingApi(reviews=[], files=files, file_patches={BOOT: REAL_PATCH, **(patches or {})}, file_status=statuses or {}, **kw)


def run(api, path, c=None):
    c = c or cfg(**ALL)
    n = ja.start_backlog_job(api, c, item_ref="a", backlog_path=path, auto_continue=True, chain_budget=3, run_id="1", run_attempt="1",
                             fire_url="https://example.invalid/f", fire_token="T", fire=lambda *a: ("session_0001", "https://claude.ai/code/session_0001"), now=NOW)["issue"]
    assert report(api, n, c) == "accepted"
    return n, mg.run_gate(api, c, backlog_path=path, dispatch=api.dispatch_workflow)


def status(api):
    return api.comments[7][0]["body"]


# ---- additive Verdrahtung (wie bisher), aber an die Aktivierung des Plans gebunden ----------------------------------------------------------
def test_declared_additive_wiring_is_merged_automatically_with_the_checked_commit_once_the_plan_scopes_are_active():
    api = pr_api()
    n, _ = run(api, backlog())
    assert api.merged == [{"sha": HEAD, "merge_method": "squash"}] and state_of(api, n)["merged"]["pr"] == 7
    assert "sensible Dateien" in status(api) and "gedeckt" in status(api) and BOOT in status(api)


def test_the_declarations_are_inert_until_the_owner_activates_them_with_one_switch():
    api = pr_api()
    run(api, backlog(active=False))
    assert api.merged == [] and "nicht aktiviert" in status(api) and "scopes_approved" in status(api)


def test_the_real_pr41_hunk_passes_with_the_proposed_snippet_and_the_shipped_backlog_declares_it_inactive():
    assert mg.verify_sensitive_edits([{"filename": BOOT, "status": "modified", "patch": REAL_PATCH}], ALLOW) == []
    raw = json.loads((ROOT / ".github/automation/backlog.json").read_text(encoding="utf-8"))
    assert raw["plan"]["scopes_approved"] is False                                       # the owner decides; nothing is active by default
    declared = {i["id"]: i["sensitive_edits"] for i in raw["items"] if i.get("sensitive_edits")}
    assert list(declared) == ["persistent-results"] and list(declared["persistent-results"]) == [BOOT]
    assert mg.verify_sensitive_edits([{"filename": BOOT, "status": "modified", "patch": REAL_PATCH}], declared["persistent-results"]) == []
    flipped = {**raw, "plan": {**raw["plan"], "scopes_approved": True}}
    path = Path(tempfile.mkdtemp()) / "backlog.json"
    path.write_text(json.dumps(flipped))
    items = {i["id"]: i for i in ja.load_backlog(path)}
    assert items["persistent-results"]["_scopes_active"] is True and not items["onboarding-windows"].get("sensitive_edits")


# ---- freie Freigabe konkreter sensibler Dateien (z. B. PermissionEngine, Workflow) ------------------------------------------------------------
def test_an_approved_step_may_change_exactly_the_sensitive_files_it_declares_in_free_mode():
    eng, wf = "src/jarvis/permissions/audit.py", ".github/workflows/pr-tests.yml"
    allow = {eng: {"mode": "free"}, wf: {"mode": "free"}}
    api = pr_api(files=[eng, wf, "src/jarvis/x.py"], patches={eng: SMALL, wf: SMALL})
    n, _ = run(api, backlog(allow=allow))
    assert api.merged == [{"sha": HEAD, "merge_method": "squash"}] and state_of(api, n)["merged"]


def test_a_free_declaration_covers_a_directory_prefix_but_not_a_sibling():
    allow = {"src/jarvis/permissions/": {"mode": "free"}}
    ok = pr_api(files=["src/jarvis/permissions/audit.py"], patches={"src/jarvis/permissions/audit.py": SMALL})
    run(ok, backlog(allow=allow))
    assert ok.merged
    other = pr_api(files=["src/jarvis/permissions/audit.py", BOOT], patches={"src/jarvis/permissions/audit.py": SMALL})
    run(other, backlog(allow=allow))
    assert other.merged == [] and "nicht freigegeben" in status(other)


def test_free_mode_refuses_deleting_or_renaming_oversized_changes_and_weakened_security_tests():
    big = "@@ -1 +1,9 @@\n context\n" + "".join(f"+l{i} = {i}\n" for i in range(9))
    sec = "tests/test_security_engine.py"
    cases = [
        ({"src/jarvis/permissions/audit.py": {"mode": "free"}}, "src/jarvis/permissions/audit.py", SMALL, "removed", "Loeschen"),
        ({"src/jarvis/permissions/audit.py": {"mode": "free"}}, "src/jarvis/permissions/audit.py", SMALL, "renamed", "Loeschen"),
        ({"src/jarvis/permissions/audit.py": {"mode": "free", "max_changed": 5}}, "src/jarvis/permissions/audit.py", big, "modified", "mehr als 5"),
        ({sec: {"mode": "free"}}, sec, "@@ -1,2 +1,1 @@\n context\n-    assert limit <= 50\n", "modified", "Sicherheitstest"),
        ({"src/jarvis/permissions/audit.py": {"mode": "free"}}, "src/jarvis/permissions/audit.py", None, "modified", "kein Patch"),
    ]
    for allow, path, patch, st, reason in cases:
        probs = mg.verify_sensitive_edits([{"filename": path, "status": st, "patch": patch}], allow)
        assert probs and any(reason in p for p in probs), (reason, probs)
    assert mg.verify_sensitive_edits([{"filename": sec, "status": "modified", "patch": "@@ -1 +1,2 @@\n context\n+    assert limit <= 50\n"}], {sec: {"mode": "free"}}) == []   # adding is fine


@pytest.mark.parametrize("line", ["      - uses: x\n    env:\n      T: ${{ secrets.ROUTINE_FIRE_TOKEN }}", "on:\n  pull_request_target:", "permissions:\n  contents: write", "ROUTINE_FIRE_URL: x"])
def test_workflow_and_automation_changes_cannot_add_secret_access_or_write_permissions_even_when_declared(line):
    wf = ".github/workflows/pr-tests.yml"
    patch = "@@ -1 +1,2 @@\n context\n" + "".join(f"+{l}\n" for l in line.splitlines())
    assert mg.verify_sensitive_edits([{"filename": wf, "status": "modified", "patch": patch}], {wf: {"mode": "free"}})
    py = ".github/automation/merge_gate.py"
    assert mg.verify_sensitive_edits([{"filename": py, "status": "modified", "patch": "@@ -1 +1,2 @@\n context\n+tok = os.environ['ROUTINE_FIRE_TOKEN']\n"}], {py: {"mode": "free"}})
    t = ".github/automation/tests/test_x.py"
    assert mg.verify_sensitive_edits([{"filename": t, "status": "modified", "patch": "@@ -1 +1,2 @@\n context\n+assert 'secrets.' not in text\n"}], {t: {"mode": "free"}}) == []   # tests may mention them


# ---- was nie per Auftrag freigebbar ist ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("never", [".github/automation/backlog.json", ".github/CODEOWNERS", "CLAUDE.md", ".claude/settings.json", ".claude/"])
def test_the_files_that_decide_who_may_approve_what_can_never_be_declared(never):
    with pytest.raises(ja.AutomationError, match="(?i)freigabe-instanz|nie|nicht freigebbar"):
        ja.load_backlog(backlog(allow={never: {"mode": "free"}}))


@pytest.mark.parametrize("never", [".github/automation/backlog.json", ".github/CODEOWNERS", "CLAUDE.md", ".claude/settings.json"])
def test_a_pr_touching_them_is_never_merged_automatically_even_with_a_broad_declaration(never):
    api = pr_api(files=[never, "src/jarvis/x.py"], patches={never: SMALL})
    run(api, backlog(allow={".github/": {"mode": "free"}}))
    assert api.merged == [] and ("Freigabe-Instanz" in status(api) or "nicht freigegeben" in status(api))


def test_a_declaration_cannot_be_broader_than_the_sensitive_areas_and_must_be_well_formed():
    bad = [{"src/": {"mode": "free"}}, {"README.md": {"mode": "free"}}, {"/etc/passwd": {"mode": "free"}}, {"src/jarvis/permissions/../x": {"mode": "free"}},
           {"src/jarvis/permissions/*": {"mode": "free"}}, {}, [], "all", {BOOT: "free"}, {BOOT: {"mode": "everything"}}, {BOOT: {"mode": "free", "added": ["x"]}},
           {BOOT: {"mode": "free", "max_changed": 0}}, {BOOT: {"mode": "free", "max_changed": 1001}}, {BOOT: {"mode": "free", "extra": 1}},
           {BOOT: {"mode": "additive", "added": [], "max_added": 3}}, {BOOT: {"mode": "additive", "added": [".*"], "max_added": 3}},
           {BOOT: {"mode": "additive", "added": [r"core\.\w+ = .*"], "max_added": 3}}, {BOOT: {"mode": "additive", "added": ["("], "max_added": 3}},
           {BOOT: {"mode": "additive", "added": ["a"] * 6, "max_added": 3}}, {BOOT: {"mode": "additive", "added": ["a"], "max_added": 21}},
           {BOOT: {"mode": "additive", "added": ["a"]}}, {f"src/jarvis/permissions/p{i}.py": {"mode": "free"} for i in range(11)}]
    for allow in bad:
        with pytest.raises(ja.AutomationError):
            ja.load_backlog(backlog(allow=allow))


# ---- Aufgabenbereich (scope) ---------------------------------------------------------------------------------------------------------------
def test_a_step_with_a_scope_cannot_merge_changes_outside_it_and_declared_sensitive_files_count_as_inside():
    inside = pr_api(files=[BOOT, "src/jarvis/history/store.py", "tests/test_history_store.py", "README.md"])
    run(inside, backlog(scope=["src/jarvis/history/", "tests/test_history", "README.md"]))
    assert inside.merged
    outside = pr_api(files=[BOOT, "src/jarvis/history/store.py", "src/jarvis/goals/engine.py"])
    run(outside, backlog(scope=["src/jarvis/history/", "tests/test_history", "README.md"]))
    assert outside.merged == [] and "ausserhalb des Auftrags" in status(outside) and "src/jarvis/goals/engine.py" in status(outside)


def test_a_scope_is_inert_without_the_owner_switch_and_validated_always():
    api = pr_api(files=[BOOT, "src/jarvis/goals/engine.py"])
    run(api, backlog(scope=["src/jarvis/history/"], active=False))
    assert "ausserhalb des Auftrags" not in status(api)                                   # inert: no restriction (and the sensitive part is not active either)
    for bad in ("src/", ["/abs"], [".."], ["a/../b"], ["*"], [""], ["x"] * 31):
        with pytest.raises(ja.AutomationError):
            ja.load_backlog(backlog(scope=bad))


# ---- Auftragsbindung ------------------------------------------------------------------------------------------------------------------------
def test_without_a_declaration_or_a_matching_approved_job_sensitive_changes_stay_with_the_owner():
    api = pr_api()
    run(api, backlog(allow=None))
    assert api.merged == [] and "Besitzer" in status(api)
    api2 = pr_api()
    api2.reviews = [{"user": {"login": "DrUranus"}, "state": "APPROVED", "commit_id": HEAD, "submitted_at": "2026-10-29T10:00:00Z"}]
    mg.run_gate(api2, cfg(**ALL), backlog_path=backlog(), dispatch=api2.dispatch_workflow)      # an owner review alone is not an approved order
    assert api2.merged == [] and "Besitzer" in status(api2)


def test_a_declaration_on_a_step_that_is_not_approved_changes_nothing():
    with pytest.raises(ja.AutomationError, match="nicht freigegeben"):
        run(pr_api(), backlog(approved=False))


def test_ordinary_files_of_an_approved_step_merge_without_any_declaration():
    api = pr_api(files=["src/jarvis/history/store.py", "docs/x.md"])
    run(api, backlog(allow=None, active=False))
    assert api.merged == [{"sha": HEAD, "merge_method": "squash"}]


# ---- was die additive Pruefung ablehnt (wie zuvor) ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("patch,reason", [
    (patch_with("from jarvis.history.factory import build_history", "core.history = build_history(settings, core, guard)", "core.extra = 1"), "nicht freigegeben"),
    (patch_with("from jarvis.history.factory import build_history", removed=["register_emergency_components(core)"]), "Zeilen entfernt"),
    (patch_with(*["from jarvis.history.factory import build_history"] * 7), "mehr als"),
    (patch_with("from jarvis.history.factory import build_history", 'core.history = build_history(settings, core, guard); permissions.reset()'), "nicht freigegeben"),
    (None, "kein Patch"), ("", "kein Patch"),
])
def test_anything_beyond_the_declared_additive_lines_is_refused(patch, reason):
    probs = mg.verify_sensitive_edits([{"filename": BOOT, "status": "modified", "patch": patch}], ALLOW)
    assert probs and any(reason in p for p in probs), probs
    api = pr_api(patches={BOOT: patch})
    run(api, backlog())
    assert api.merged == [] and "Besitzer" in status(api)


@pytest.mark.parametrize("status_", ["added", "removed", "renamed", "copied"])
def test_additive_mode_only_accepts_a_plain_modification(status_):
    assert mg.verify_sensitive_edits([{"filename": BOOT, "status": status_, "patch": REAL_PATCH}], ALLOW)


def test_denylisted_security_words_in_an_added_line_are_refused_even_if_a_pattern_would_match():
    allow = {BOOT: {"mode": "additive", "added": [r"core\.extra = .*"], "max_added": 3}}
    for line in ('core.extra = os.environ["TOKEN"]', "core.extra = permissions.budget", "core.extra = subprocess.run(x)", "core.extra = open(secret_file)",
                 "core.extra = emergency_stop", "core.extra = confirmation", "core.extra = audit_off", "core.extra = lockdown_off"):
        assert mg.verify_sensitive_edits([{"filename": BOOT, "status": "modified", "patch": patch_with(line)}], allow), line
    assert mg.verify_sensitive_edits([{"filename": BOOT, "status": "modified", "patch": patch_with("core.extra = 1", "# permissions are untouched here")}], allow) == []


def test_the_verifier_never_covers_a_never_declarable_file_even_if_validation_was_bypassed():
    for other in ("CLAUDE.md", ".claude/settings.json", ".github/automation/backlog.json", ".github/CODEOWNERS"):
        probs = mg.verify_sensitive_edits([{"filename": other, "status": "modified", "patch": SMALL}], {other: {"mode": "free"}})
        assert probs, other


# ---- Pruefbefunde bei doppelten Check-Runs ----------------------------------------------------------------------------------------------
def test_the_newest_check_run_per_name_decides_when_a_commit_has_a_pull_request_and_a_dispatch_run():
    old = {**GOOD_RUN, "id": 1, "name": "tests-linux", "conclusion": "failure", "started_at": "2026-10-29T20:00:00Z"}
    new = {**GOOD_RUN, "id": 2, "name": "tests-linux", "conclusion": "success", "started_at": "2026-10-29T20:30:00Z"}
    win = {**GOOD_RUN, "id": 3, "name": "tests-windows"}
    assert mg.latest_by_name([new, old, win])["tests-linux"]["id"] == 2
    still = {**new, "id": 4, "status": "in_progress", "conclusion": None, "started_at": "2026-10-29T20:45:00Z"}
    assert mg.latest_by_name([old, new, still, win])["tests-linux"]["id"] == 4
