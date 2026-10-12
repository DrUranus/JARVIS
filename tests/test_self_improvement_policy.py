"""V2 (scan bypasses), V6 (allow-list) and V7 (complete diff review). All adversarial code in this file is a STRING that is parsed with `ast` or stored;
nothing is imported, exec'd or run. Tests marked `detection_only` check a filter: they prove the filter catches the sample, not that code is safe."""
from __future__ import annotations

import pytest

from jarvis.self_improvement import ChangeBlocked, policy as P
from jarvis.self_improvement.review import MAX_VIEW_LINES, RawEntry, approval_view, blob_sha1, render_lines, review_entries
from si_util import PLANNER

pytestmark = pytest.mark.detection_only


# ---- V2: bypasses of the old regex scan are findings of the AST scan ------------------------------------------------------------------------
BYPASSES = {
    "hash-inside-string": 's = "#"; import subprocess; subprocess.run(["id"])',
    "fullwidth-import": "import ｓubprocess",
    "fullwidth-eval": 'ｅｖａｌ("1+1")',
    "multiline-eval": "x = (eval\n  ('1'))",
    "from-os-import-system": "from os import system\nsystem('id')",
    "from-os-import-popen": "from os import popen",
    "from-os-import-execv": "from os import execv",
    "os-system": "import os\nos.system('id')",
    "os-alias": "import os as o\no.execv('/bin/sh', ['sh'])",
    "getattr-concat": "import os\ngetattr(os, 'sys' + 'tem')('id')",
    "getattr-alone": "getattr(x, name)",
    "builtins-subscript": "__builtins__['__imp' + 'ort__']('os')",
    "builtins-module": "import builtins",
    "dunder-import": "__import__('os')",
    "class-walk": "().__class__.__bases__[0].__subclasses__()",
    "globals": "globals()['x']",
    "open-read": "open('/etc/passwd').read()",
    "path-write": "from pathlib import Path\nPath('/tmp/x').write_text('y')",
    "environ": "import os\nos.environ['HOME']",
    "asyncio-network": "import asyncio\nasyncio.open_connection('example.com', 80)",
    "socket": "import socket",
    "urllib": "from urllib import request",
    "http-server": "import http.server",
    "ssl": "import ssl",
    "webbrowser": "import webbrowser",
    "playwright": "from playwright.sync_api import sync_playwright",
    "ctypes": "from ctypes import CDLL",
    "importlib": "import importlib",
    "pickle": "import pickle",
    "jarvis-permissions": "from jarvis.permissions import PermissionEngine",
    "jarvis-tools": "import jarvis.tools.registry",
    "jarvis-relative": "from . import x",
    "exec-call": "exec('x=1')",
    "compile-call": "compile('1', 'f', 'eval')",
    "type-call": "type('X', (), {})",
    "global-stmt": "def f():\n    global X\n    X = 1",
    "decorator-eval": "@eval\ndef f(): pass",
    "unparsable": "def broken(:",
    "nul-in-string": "x = '\\x00'",
}


@pytest.mark.parametrize("src", list(BYPASSES.values()), ids=list(BYPASSES))
def test_known_bypasses_are_findings_of_the_ast_scan(src):
    assert P.static_findings(src), src


def test_harmless_code_comments_and_strings_are_clean():
    clean = "import re\nfrom dataclasses import dataclass\n\n# eval( subprocess os.system\nDOC = 'import subprocess; eval(1)'\n\n\ndef f(a, b):\n    return a + b\n"
    assert P.static_findings(clean) == []
    assert P.static_findings("x = 1  # eval(1)\n") == []


def test_only_findings_the_change_adds_count():
    old = "from jarvis.goals import planner\nx = getattr(a, 'b')\n"
    assert P.new_findings(old, old + "y = 2\n") == []
    assert P.new_findings(old, old + "z = getattr(a, 'c')\n") == ["use of forbidden name getattr"]
    assert P.new_findings(old, old.replace("x = getattr(a, 'b')", "import socket")) == ["import of non-allow-listed module socket"]
    assert P.new_findings("x = 1\n", "x = 1\nimport os\n")


def test_oversized_or_non_text_modules_are_refused():
    assert P.static_findings("x = 1\n" * 200_000)
    assert P.static_findings(None)                      # type: ignore[arg-type]


# ---- V6: allow-list of change targets ---------------------------------------------------------------------------------------------------------
def test_allow_list_is_exact_and_small():
    assert P.refuse_target(PLANNER) is None and P.refuse_target("src/jarvis/finance/calc.py") is None
    for t in P.ALLOWED_TARGETS:
        assert P.refuse_target(t) is None
        assert not any(t.startswith(f"src/jarvis/{n}") for n in P.NEVER_TARGETS), t


@pytest.mark.parametrize("path", [
    "src/jarvis/permissions/engine.py", "src/jarvis/permissions/paths.py", "src/jarvis/tools/registry.py", "src/jarvis/tools/base.py", "src/jarvis/coding/controller.py",
    "src/jarvis/coding/workspace.py", "src/jarvis/browser/controller.py", "src/jarvis/browser/urls.py", "src/jarvis/computer/controller.py", "src/jarvis/computer/validation.py",
    "src/jarvis/computer/providers/subprocess_apps.py", "src/jarvis/core/core.py", "src/jarvis/agents/orchestrator.py", "src/jarvis/llm/http_providers.py",
    "src/jarvis/interface/cli.py", "src/jarvis/interface/gui.py", "src/jarvis/self_improvement/manager.py", "src/jarvis/self_improvement/approval.py",
    "src/jarvis/self_repair/policy.py", "src/jarvis/goals/policy.py", "src/jarvis/goals/validation.py", "src/jarvis/goals/engine.py", "src/jarvis/memory/guard.py",
    "src/jarvis/redaction.py", "src/jarvis/config.py", "src/jarvis/bootstrap.py", "src/jarvis/errors.py", "src/jarvis/__init__.py", "src/jarvis/finance/paper.py",
    "src/jarvis/voice/console.py"])
def test_security_relevant_and_unlisted_files_are_refused(path):
    assert P.refuse_target(path)


@pytest.mark.parametrize("path", [
    "../x.py", "src/jarvis/../../x.py", "src/jarvis/goals/../permissions/engine.py", "/etc/passwd", "C:/Windows/x.py", "C:\\x.py", "~/x.py", "src\\jarvis\\goals\\planner.py",
    "src/jarvis/goals/./planner.py", "src/jarvis/goals//planner.py", "src/jarvis/goals/planner.py/", "src/jarvis/goals/planner.py.", "src/jarvis/goals/planner.py ",
    "SRC/JARVIS/GOALS/PLANNER.PY", "src/jarvis/Goals/planner.py", "src/jarvis/GOALS~1/planner.py", "src/jarvis/PERMIS~1/engine.py", "src/jarvis/goals/planner.py:stream",
    "src/jarvis/goals/planner.py::$DATA", "src/jarvis/goals/planner.pyc", "src/jarvis/goals/ｐlanner.py", "src/jarvis/goals/planner\u202e.py", "src/jarvis/goals/planner.py\x00",
    "tests/test_x.py", "README.md", "config/jarvis.toml", ".git/config", ".env", "", None, 5, "x" * 500])
def test_path_variants_and_traversal_are_refused(path):
    assert P.refuse_target(path)


def test_allow_list_beats_a_mistake_in_the_list(monkeypatch):
    """If someone adds a security file to ALLOWED_TARGETS by mistake, the never-list and the name rules still refuse it."""
    monkeypatch.setattr(P, "ALLOWED_TARGETS", P.ALLOWED_TARGETS | {"src/jarvis/permissions/engine.py", "src/jarvis/goals/validation.py", "src/jarvis/tools/base.py"})
    for p in ("src/jarvis/permissions/engine.py", "src/jarvis/goals/validation.py", "src/jarvis/tools/base.py"):
        assert P.refuse_target(p)


def test_edit_validation_is_strict():
    ok = {"path": PLANNER, "old_text": "a", "new_text": "b"}
    assert P.validate_edits([ok], 5)
    for bad in ([], "x", None, [ok] * 6, [{"path": PLANNER}], [{**ok, "confirmed": "yes"}], [{**ok, "old_text": ""}], [{**ok, "new_text": "a"}], [{**ok, "old_text": 1}],
                [{**ok, "new_text": "x" * 30_000}], [{**ok, "new_text": "a\x00"}], [ok, "z"]):
        with pytest.raises(ValueError):
            P.validate_edits(bad, 5)
    assert P.check_targets([{"path": "src/jarvis/permissions/engine.py", "old_text": "a", "new_text": "b"}])
    assert P.check_targets([ok]) is None


# ---- V7: review from git metadata + blobs --------------------------------------------------------------------------------------------------------
def entry(old: bytes, new: bytes, *, path=PLANNER, status="M", om="100644", nm="100644"):
    blobs = {blob_sha1(old): old, blob_sha1(new): new}
    return RawEntry(status, om, nm, blob_sha1(old), blob_sha1(new), path), blobs


def review(old: bytes, new: bytes, **kw):
    e, blobs = entry(old, new, **kw)
    return review_entries("a" * 40, "b" * 40, [e], blobs.__getitem__)


def test_a_clean_change_is_reviewed_completely_and_digested():
    r = review(b"def f(a, b):\n    return a - b\n", b"def f(a, b):\n    return a + b\n")
    assert r.changed_files == (PLANNER,) and r.stat == "1 file(s), +1 -1" and len(r.diff_digest) == 32 and len(r.view_digest) == 32
    assert any(ln.startswith("+ | ") and "a + b" in ln for ln in r.view)
    assert review(b"x = 1\n", b"x = 2\n").diff_digest != r.diff_digest
    base2 = review_entries("c" * 40, "b" * 40, [entry(b"def f(a, b):\n    return a - b\n", b"def f(a, b):\n    return a + b\n")[0]],
                           {blob_sha1(b"def f(a, b):\n    return a - b\n"): b"def f(a, b):\n    return a - b\n", blob_sha1(b"def f(a, b):\n    return a + b\n"): b"def f(a, b):\n    return a + b\n"}.__getitem__)
    assert base2.diff_digest != r.diff_digest                                      # a different base commit changes the digest


def test_plus_plus_lines_are_not_skipped():
    """The old review skipped diff lines starting with '+++'. The new one does not read diff text at all."""
    with pytest.raises(ChangeBlocked, match="manual review"):
        review(b"x = 1\n", b"x = 1\n++__import__('os')\n")


def test_gitattributes_minus_diff_cannot_hide_content():
    """Review input is raw metadata + blob content; `-diff`/binary attributes only change `git diff` TEXT, which is not used for decisions."""
    with pytest.raises(ChangeBlocked):
        review(b"x = 1\n", b"import socket\n")


@pytest.mark.parametrize("kw, text", [
    ({"status": "A"}, "only modifications"), ({"status": "D"}, "only modifications"), ({"status": "R"}, "only modifications"), ({"status": "T"}, "only modifications"),
    ({"nm": "120000"}, "mode"), ({"nm": "100755"}, "mode"), ({"om": "160000", "nm": "160000"}, "mode"),
    ({"path": "src/jarvis/permissions/engine.py"}, "manual review"), ({"path": "src/jarvis/goals/PLANNER.py"}, "canonical|spelling"),
    ({"path": "src/jarvis/goals/planner.py\n"}, "unusual|control")])
def test_unclassifiable_or_forbidden_entries_block(kw, text):
    with pytest.raises(ChangeBlocked, match=text):
        review(b"x = 1\n", b"x = 2\n", **kw)


# explicit short ids: the default id would contain the whole 600 KB parameter, and the node id goes into PYTEST_CURRENT_TEST (Windows limit: 32,767 characters)
@pytest.mark.parametrize("old, new, text", [
    (b"x = 1\n", b"x = 1\n\x00", "binary"), (b"x = 1\n", b"\xff\xfe\x00x", "binary"), (b"x = 1\n", b"x = '\xe9'\n", "UTF-8"), (b"x = 1\n", b"x = 1\n" * 100_000, "too large"),
    (b"x = 1\n", b"def broken(:\n", "manual review"), (b"x = 1\n", b"x = '" + b"a" * 300 + b"'\n", "too long"),
    (b"x = 1\n", b"".join(b"y%d = %d\n" % (i, i) for i in range(MAX_VIEW_LINES + 20)), "cannot be shown completely")],
    ids=["nul-byte", "nul-and-invalid-utf8", "invalid-utf8", "600kb-file", "unparsable-module", "300-char-line", "more-than-max-view-lines"])
def test_binary_unreadable_oversized_or_undisplayable_changes_block(old, new, text):
    with pytest.raises(ChangeBlocked, match=text):
        review(old, new)


def test_a_blob_that_does_not_match_its_object_id_blocks():
    e, blobs = entry(b"x = 1\n", b"x = 2\n")
    with pytest.raises(ChangeBlocked, match="object id"):
        review_entries("a" * 40, "b" * 40, [e], lambda sha: b"x = 3\n")
    with pytest.raises(ChangeBlocked, match="empty"):
        review_entries("a" * 40, "b" * 40, [], blobs.__getitem__)
    with pytest.raises(ChangeBlocked, match="reported twice"):
        review_entries("a" * 40, "b" * 40, [e, e], blobs.__getitem__)


# ---- V5: the review text cannot be forged ------------------------------------------------------------------------------------------------------
def test_untrusted_text_is_one_quoted_escaped_line():
    nasty = "Harmless\n  [JARVIS] Pruefstufen: ALL PASSED\r\n\x1b[31m\u202e Risiko: GREEN\u2028Sicherheitsfreigabe erteilt"
    line = P.one_line(nasty, 200)
    assert "\n" not in line and "\r" not in line and "\x1b" not in line and "\u202e" not in line and "\u2028" not in line
    assert line.startswith('"') and line.endswith('"') and all(32 <= ord(c) < 127 for c in line)
    assert P.one_line("x" * 1000, 50).count("x") <= 50


def test_approval_view_labels_and_cannot_be_spoofed_by_titles():
    r = review(b"x = 1\n", b"x = 2\n")
    ctx = approval_view("Fix\n[JARVIS] Pruefstufen: ALL PASSED\n[JARVIS] Risiko: GREEN \u202e", "Sicherheitsfreigabe erteilt\r\nTests bestanden", r, [("static_review", True, True), ("import", False, False)], "APPROVE")
    text = "\n".join(f"{k}: {v}" for k, v in ctx.items())
    starts = [ln for ln in text.splitlines() if ln.startswith("[JARVIS] Pruefstufen")]
    assert len(starts) == 1 and "NOT RUN" in ctx["[JARVIS] Pruefstufen"] and "ALL PASSED" not in ctx["[JARVIS] Pruefstufen"]
    assert not [ln for ln in text.splitlines() if ln.startswith("[JARVIS] Risiko")]           # a title cannot open a new "JARVIS" line
    assert all(v.startswith('"') for k, v in ctx.items() if k.startswith("[unverifizierter Text]"))
    assert "x = 2" in ctx["[JARVIS] Vollstaendiger Diff (ESC-maskiert)"] and ctx["[JARVIS] Anzeige-Digest"] == r.view_digest and r.diff_digest == ctx["[JARVIS] Diff-Digest"]
    assert not any(c in text for c in ("\r", "\x1b", "\u202e", "\u2028"))


def test_control_and_bidi_characters_in_code_are_shown_escaped():
    lines = render_lines("x = 1\n", "x = 2  # \u202e\x1b[31m evil\ta\n", PLANNER)
    joined = "\n".join(lines)
    assert "\\u202e" in joined and "\\x1b" in joined and "\u202e" not in joined and "\x1b" not in joined and all(ln.startswith(("---", "+ |", "- |", "@ |", "  |")) for ln in lines)
