"""Freigabe geschuetzter Pfade fuer den genehmigten Auftrag: nur die Kompositionswurzel (bootstrap.py), nur wenn der Plan es fuer genau diesen Schritt ausdruecklich
deklariert (protected_edits im Backlog, Besitzer-Aenderung), nur als geprueft additive Verdrahtung. PermissionEngine, Not-Aus, Geheimnisse, Sicherheitsgrenzen,
Sicherheitstests und die Automatisierung selbst bleiben immer beim Besitzer. Fake-GitHub, kein Netzwerk, keine Secrets."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_awaiting_ci import ACC, ALL, ClosingApi, report  # noqa: E402
from test_jarvis_automation import NOW, cfg, state_of  # noqa: E402
from test_merge_gate import GOOD_RUN, HEAD  # noqa: E402

import jarvis_automation as ja  # noqa: E402
import merge_gate as mg  # noqa: E402

BOOT = "src/jarvis/bootstrap.py"
ALLOW = {BOOT: {"added": [r"from jarvis\.history\.factory import build_history", r"core\.history = build_history\(settings, core, guard\)"], "max_added": 6}}
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


def patch_with(*added, removed=()):
    body = "".join(f"+    {a}\n" for a in added) + "".join(f"-    {r}\n" for r in removed)
    return "@@ -64,6 +64,9 @@ def build_core(settings):\n     core.subsystems['x'] = 1\n" + body + "     register_emergency_components(core)\n"


def backlog(allow=ALLOW, approved=True):
    p = Path(tempfile.mkdtemp()) / "backlog.json"
    item = {"id": "a", "task": "Aufgabe A", "approved": approved, "depends_on": [], "acceptance": ACC}
    if allow is not None:
        item["protected_edits"] = allow
    p.write_text(json.dumps({"items": [item]}))
    return p


def pr_api(files=None, patch=REAL_PATCH, status="modified", **kw):
    return ClosingApi(reviews=[], files=files or [BOOT, "src/jarvis/history/store.py"], file_patches={BOOT: patch}, file_status={BOOT: status}, **kw)


def run(api, path, c=None):
    c = c or cfg(**ALL)
    n = ja.start_backlog_job(api, c, item_ref="a", backlog_path=path, auto_continue=True, chain_budget=3, run_id="1", run_attempt="1",
                             fire_url="https://example.invalid/f", fire_token="T", fire=lambda *a: ("session_0001", "https://claude.ai/code/session_0001"), now=NOW)["issue"]
    assert report(api, n, c) == "accepted"
    return n, mg.run_gate(api, c, backlog_path=path, dispatch=api.dispatch_workflow)


def status(api):
    return api.comments[7][0]["body"]


# ---- freigegebene, geprueft additive Verdrahtung ---------------------------------------------------------------------------------------
def test_declared_additive_wiring_of_the_approved_step_is_merged_automatically_with_the_checked_commit():
    api = pr_api()
    n, _ = run(api, backlog())
    assert api.merged == [{"sha": HEAD, "merge_method": "squash"}] and state_of(api, n)["merged"]["pr"] == 7
    assert "Verdrahtung" in status(api) and BOOT in status(api)


def test_the_real_pr41_hunk_passes_with_the_proposed_owner_snippet():
    problems = mg.verify_protected_edits([{"filename": BOOT, "status": "modified", "patch": REAL_PATCH}], ALLOW)
    assert problems == []


def test_without_a_declaration_the_pr_stays_with_the_owner():
    api = pr_api()
    run(api, backlog(allow=None))
    assert api.merged == [] and "Besitzer" in status(api)


def test_a_declaration_on_a_step_that_is_not_approved_changes_nothing():
    api = pr_api()
    with pytest.raises(ja.AutomationError, match="nicht freigegeben"):
        run(api, backlog(approved=False))
    assert api.merged == []


def test_an_owner_review_alone_does_not_open_protected_paths():
    api = pr_api()
    api.reviews = [{"user": {"login": "DrUranus"}, "state": "APPROVED", "commit_id": HEAD, "submitted_at": "2026-10-29T10:00:00Z"}]
    n = ja.start_job(api, cfg(**ALL), task="t", base_branch="main", auto_continue=False, chain_budget=1, timeout_minutes=60, run_id="2", run_attempt="1",
                     fire_url="https://example.invalid/f", fire_token="T", fire=lambda *a: ("session_0001", "u"), now=NOW)["issue"]
    mg.run_gate(api, cfg(**ALL), backlog_path=backlog(allow=None), dispatch=api.dispatch_workflow)
    assert api.merged == [] and n == 1


# ---- was die Pruefung ablehnt ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("patch,reason", [
    (patch_with("from jarvis.history.factory import build_history", "core.history = build_history(settings, core, guard)", "core.extra = 1"), "nicht freigegeben"),
    (patch_with("from jarvis.history.factory import build_history", removed=["register_emergency_components(core)"]), "Zeilen entfernt"),
    (patch_with(*["from jarvis.history.factory import build_history"] * 7), "mehr als"),
    (patch_with("from jarvis.history.factory import build_history", 'core.history = build_history(settings, core, guard); permissions.reset()'), "nicht freigegeben"),
    (None, "kein Patch"),
    ("", "kein Patch"),
])
def test_anything_beyond_the_declared_additive_lines_is_refused(patch, reason):
    probs = mg.verify_protected_edits([{"filename": BOOT, "status": "modified", "patch": patch}], ALLOW)
    assert probs and any(reason in p for p in probs), probs
    api = pr_api(patch=patch)
    run(api, backlog())
    assert api.merged == [] and "Besitzer" in status(api)


@pytest.mark.parametrize("status_", ["added", "removed", "renamed", "copied"])
def test_only_a_plain_modification_of_the_file_qualifies(status_):
    assert mg.verify_protected_edits([{"filename": BOOT, "status": status_, "patch": REAL_PATCH}], ALLOW)


def test_denylisted_security_words_in_an_added_line_are_refused_even_if_a_pattern_would_match():
    allow = {BOOT: {"added": [r"core\.extra = .*"], "max_added": 3}}
    for line in ('core.extra = os.environ["TOKEN"]', "core.extra = permissions.budget", "core.extra = subprocess.run(x)", "core.extra = open(secret_file)",
                 "core.extra = emergency_stop", "core.extra = confirmation", "core.extra = audit_off", "core.extra = lockdown_off"):
        probs = mg.verify_protected_edits([{"filename": BOOT, "status": "modified", "patch": patch_with(line)}], allow)
        assert probs, line
    assert mg.verify_protected_edits([{"filename": BOOT, "status": "modified", "patch": patch_with("core.extra = 1", "# permissions are untouched here")}], allow) == []


@pytest.mark.parametrize("hard", ["src/jarvis/permissions/engine.py", "src/jarvis/permissions/emergency.py", "tests/test_security_x.py",
                                  "tests/test_emergency_stop.py", "tests/test_autonomy_invariants.py", "config/jarvis.toml", "CLAUDE.md",
                                  ".claude/settings.json", ".github/workflows/x.yml", ".github/automation/backlog.json"])
def test_other_protected_paths_stay_with_the_owner_even_when_bootstrap_wiring_is_declared(hard):
    api = pr_api(files=[BOOT, hard])
    api.file_patches[hard] = REAL_PATCH                              # an innocent-looking, pattern-conforming addition: only the path rule can stop it
    run(api, backlog())
    assert api.merged == [] and "Besitzer" in status(api) and "nicht freigegeben" in status(api)


def test_a_declaration_never_reaches_beyond_bootstrap_py():
    for other in ("src/jarvis/permissions/engine.py", "config/jarvis.toml", ".github/automation/backlog.json", "tests/test_security_engine.py", "src/jarvis/other.py"):
        with pytest.raises(ja.AutomationError, match="bootstrap"):
            ja.load_backlog(backlog(allow={other: {"added": ["x"], "max_added": 1}}))


@pytest.mark.parametrize("allow", [
    {BOOT: {"added": [], "max_added": 3}},                                          # nothing allowed
    {BOOT: {"added": ["("], "max_added": 3}},                                       # invalid regex
    {BOOT: {"added": ["x" * 201], "max_added": 3}},                                 # too long
    {BOOT: {"added": [".*"], "max_added": 3}},                                      # allows everything
    {BOOT: {"added": [r"import \w+"], "max_added": 3}},                             # would allow 'import subprocess'
    {BOOT: {"added": [r"core\.\w+ = .*"], "max_added": 3}},                         # would allow 'core.permissions = x'
    {BOOT: {"added": ["a"] * 6, "max_added": 3}},                                   # too many patterns
    {BOOT: {"added": ["a"], "max_added": 0}}, {BOOT: {"added": ["a"], "max_added": 21}}, {BOOT: {"added": ["a"]}},
    {BOOT: ["a"]}, "bootstrap",
])
def test_unsafe_or_malformed_declarations_are_rejected_when_the_backlog_loads(allow):
    with pytest.raises(ja.AutomationError):
        ja.load_backlog(backlog(allow=allow))


def test_the_shipped_backlog_declares_nothing_yet():
    items = ja.load_backlog(Path(__file__).resolve().parents[3] / ".github/automation/backlog.json")
    assert not [i["id"] for i in items if i.get("protected_edits")]                 # the mechanism ships, the grant is the owner's decision


# ---- Pruefbefunde bei doppelten Check-Runs ----------------------------------------------------------------------------------------------
def test_the_newest_check_run_per_name_decides_when_a_commit_has_a_pull_request_and_a_dispatch_run():
    old = {**GOOD_RUN, "id": 1, "name": "tests-linux", "conclusion": "failure", "started_at": "2026-10-29T20:00:00Z"}
    new = {**GOOD_RUN, "id": 2, "name": "tests-linux", "conclusion": "success", "started_at": "2026-10-29T20:30:00Z"}
    win = {**GOOD_RUN, "id": 3, "name": "tests-windows"}
    api = ClosingApi(reviews=[], runs=[new, old, win])
    by = mg.latest_by_name([r for r in api.runs])
    assert by["tests-linux"]["id"] == 2
    still = {**new, "id": 4, "status": "in_progress", "conclusion": None, "started_at": "2026-10-29T20:45:00Z"}
    assert mg.latest_by_name([old, new, still, win])["tests-linux"]["id"] == 4


def test_the_verifier_itself_never_covers_another_protected_path_even_if_the_allowance_bypassed_validation():
    for other in ("src/jarvis/permissions/engine.py", "src/jarvis/permissions/emergency.py", "tests/test_security_engine.py", "config/jarvis.toml", ".github/workflows/x.yml"):
        allow = {other: {"added": [r"x = 1"], "max_added": 3}}
        probs = mg.verify_protected_edits([{"filename": other, "status": "modified", "patch": "@@ -1 +1,2 @@\n context\n+x = 1\n"}], allow)
        assert probs and "nicht freigegeben" in probs[0], other
