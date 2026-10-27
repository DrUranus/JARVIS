"""GitWorkspace and SubprocessRunner against REAL git on temporary repositories. Only `git` runs (plus test-owned helper scripts for the runner); no proposed code is
imported or executed. Covers V3 (exact export, manifest, hashes), V7 (metadata review that .gitattributes cannot hide), validated git arguments, process limits.
These tests show the behaviour of the helpers; they do not prove isolation."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

from jarvis.self_improvement import ChangeBlocked, ExecutionDisabled, ExecutionGuard, GitWorkspace, PreparationError, SubprocessRunner, policy as P
from jarvis.self_improvement.isolation import REQUIRED_PROPERTIES
from jarvis.self_improvement.workspace import Export, manifest_digest, scrubbed_env, valid_sha
from si_util import full_attestation

PLANNER = "src/jarvis/goals/planner.py"
FILES = {"src/jarvis/__init__.py": "", PLANNER: "def add(a, b):\n    return a - b\n", "src/jarvis/goals/evaluator.py": "X = 1\n", "tests/test_x.py": "def test_x():\n    assert True\n"}


def git(repo: Path, *args: str, check=True) -> str:
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(r.stderr)
    return r.stdout.strip()


def make_repo(tmp_path: Path, files=None, *, crlf=False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    if crlf:
        git(repo, "config", "core.autocrlf", "true")
    for rel, text in {**FILES, **(files or {})}.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as fh:
            fh.write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def commit_change(repo: Path, changes: dict[str, str | None]) -> tuple[str, str]:
    base = git(repo, "rev-parse", "HEAD")
    for rel, text in changes.items():
        f = repo / rel
        if text is None:
            f.unlink()
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return base, git(repo, "rev-parse", "HEAD")


def commit_with_entries(repo: Path, entries: dict[str, tuple[str, str, str]], parent: str | None = None) -> str:
    """Build a commit from (mode, type, sha) entries with git PLUMBING (mktree + commit-tree). No working tree, index, OS symlink, file mode or case-sensitivity of the host
    file system is involved, so the same fixture is valid on Linux and Windows (where core.fileMode=false and symlinks need a privilege).
    The input is passed as BYTES with NUL-terminated records (`mktree -z`): text mode would make Windows write '\\n' as '\\r\\n', which turned every name into 'name\\r' and
    made the fixtures wrong there (first real Windows run); `-z` also avoids any C-style quoting of unusual names."""
    def tree_of(items: dict[str, tuple[str, str, str]]) -> str:
        rows: list[bytes] = []
        subdirs: dict[str, dict[str, tuple[str, str, str]]] = {}
        for path, (mode, kind, sha) in items.items():
            head, _, rest = path.partition("/")
            if rest:
                subdirs.setdefault(head, {})[rest] = (mode, kind, sha)
            else:
                rows.append(f"{mode} {kind} {sha}\t{head}".encode("utf-8") + b"\0")
        rows += [f"040000 tree {tree_of(sub)}\t{name}".encode("utf-8") + b"\0" for name, sub in subdirs.items()]
        return subprocess.run(["git", "mktree", "-z"], cwd=repo, input=b"".join(rows), capture_output=True, check=True).stdout.decode("ascii").strip()
    args = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree_of(entries), "-m", "fixture"] + (["-p", parent] if parent else [])
    return subprocess.run(args, cwd=repo, capture_output=True, check=True).stdout.decode("ascii").strip()


def tree_entries(repo: Path, commit: str) -> dict[str, tuple[str, str, str]]:
    """The complete tree of a commit as {path: (mode, type, sha)}; raw bytes with -z, so no quoting and no newline translation."""
    raw = subprocess.run(["git", "ls-tree", "-r", "-z", commit], cwd=repo, capture_output=True, check=True).stdout
    out = {}
    for rec in filter(None, raw.split(b"\0")):
        meta, path = rec.decode("utf-8").split("\t", 1)
        mode, kind, sha = meta.split(" ")
        out[path] = (mode, kind, sha)
    return out


def blob(repo: Path, content: str) -> str:
    """Write exactly these bytes as a blob (UTF-8, no newline translation, no filters)."""
    return subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input=content.encode("utf-8"), capture_output=True, check=True).stdout.decode("ascii").strip()


def assert_clean_names(entries: dict[str, tuple[str, str, str]]) -> None:
    """Fixture guard: no name may contain a control character (a stray '\\r' once hid behind a wrong error message)."""
    assert all(ch.isprintable() for path in entries for ch in path), [p for p in entries if not p.isprintable()]


def ws(tmp_path, repo) -> GitWorkspace:
    return GitWorkspace(repo, tmp_path / "data", timeout=30)


def ws_unlocked(tmp_path, repo) -> GitWorkspace:
    """A workspace whose guard is a TEST DOUBLE claiming proven isolation. It sandboxes nothing; it only lets the git-only primitives run in a temporary repository."""
    return GitWorkspace(repo, tmp_path / "data", timeout=30, guard=ExecutionGuard(full_attestation()))


# ---- valid git arguments ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["--output=/tmp/x", "HEAD", "main", "g" * 40, "a" * 39, "a" * 41, "A" * 40, "", None, 5, "a" * 40 + " --stat", "a" * 40 + "\n"])
def test_only_full_hex_object_ids_reach_git(tmp_path, bad):
    with pytest.raises(PreparationError):
        valid_sha(bad)
    w = ws_unlocked(tmp_path, make_repo(tmp_path))                       # unlocked only so that the argument check behind the guard is reached
    with pytest.raises(PreparationError):
        w.changed_entries(bad, "a" * 40)
    with pytest.raises(PreparationError):
        w.worktree_for("imp-000000000001", P.BRANCH_PREFIX + "imp-000000000001", bad)
    with pytest.raises(PreparationError):
        w.revert(bad)


def test_a_stored_option_like_base_cannot_write_files(tmp_path):
    w = ws(tmp_path, make_repo(tmp_path))
    target = tmp_path / "pwned"
    with pytest.raises(PreparationError):
        w.review(f"--output={target}", "a" * 40)
    assert not target.exists()


# ---- V7: review from metadata and blobs --------------------------------------------------------------------------------------------------------
def test_a_clean_change_is_reviewed_from_git_objects(tmp_path):
    repo = make_repo(tmp_path)
    base, head = commit_change(repo, {PLANNER: "def add(a, b):\n    return a + b\n"})
    r = ws(tmp_path, repo).review(base, head)
    assert r.changed_files == (PLANNER,) and any("a + b" in ln for ln in r.view) and len(r.diff_digest) == 32


def test_gitattributes_minus_diff_and_binary_cannot_hide_a_change(tmp_path):
    repo = make_repo(tmp_path)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.py -diff\n*.py binary\n")
    base, head = commit_change(repo, {PLANNER: "import socket\n"})
    assert "Binary files" in git(repo, "diff", base, head)               # the TEXT diff is blinded ...
    with pytest.raises(ChangeBlocked, match="socket"):                   # ... the metadata + blob review is not
        ws(tmp_path, repo).review(base, head)


def test_plus_plus_prefixed_added_lines_are_scanned(tmp_path):
    repo = make_repo(tmp_path)
    base, head = commit_change(repo, {PLANNER: "x = 1\n++__import__('os')\n"})
    with pytest.raises(ChangeBlocked, match="manual review"):
        ws(tmp_path, repo).review(base, head)


@pytest.mark.parametrize("changes, text", [
    ({"src/jarvis/goals/new.py": "x = 1\n"}, "only modifications"), ({PLANNER: None}, "only modifications"),
    ({"src/jarvis/permissions/engine.py": "x = 2\n"}, "manual review"), ({"src/jarvis/goals/evaluator.py": "X = 2\n", "tests/test_x.py": "def test_x():\n    pass\n"}, "manual review"),
    ({PLANNER: "x = 'é'\n".encode("latin-1").decode("latin-1")}, None)])
def test_added_deleted_and_unlisted_files_block(tmp_path, changes, text):
    repo = make_repo(tmp_path, {"src/jarvis/permissions/engine.py": "x = 1\n"})
    base, head = commit_change(repo, changes)
    if text is None:
        ws(tmp_path, repo).review(base, head)               # a plain unicode change in an allowed file is fine
        return
    with pytest.raises(ChangeBlocked, match=text):
        ws(tmp_path, repo).review(base, head)


def test_mode_changes_symlinks_renames_and_binary_files_block(tmp_path):
    """Mode and type changes are built as git objects (plumbing), so this runs unchanged on Windows: there `os.chmod` is invisible to git (core.fileMode=false) and
    `os.symlink` needs a privilege, which made the old file-system based fixture fail with 'nothing to commit'."""
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    entries = tree_entries(repo, base)
    assert_clean_names(entries)
    assert set(entries) == set(FILES) and entries[PLANNER][0] == "100644"
    mode, kind, sha = entries[PLANNER]
    head = commit_with_entries(repo, {**entries, PLANNER: ("100755", kind, sha)}, base)                       # executable bit set
    built = tree_entries(repo, head)
    assert set(built) == set(entries) and built[PLANNER] == ("100755", kind, sha)                              # precondition: the COMPLETE tree is there and only the mode differs
    assert {p: v for p, v in built.items() if p != PLANNER} == {p: v for p, v in entries.items() if p != PLANNER}
    with pytest.raises(ChangeBlocked, match="mode"):
        ws(tmp_path, repo).review(base, head)
    link = blob(repo, "planner.py")
    head2 = commit_with_entries(repo, {**entries, "src/jarvis/goals/evaluator.py": ("120000", "blob", link)}, base)   # regular file replaced by a symlink
    built2 = tree_entries(repo, head2)
    assert set(built2) == set(entries) and built2["src/jarvis/goals/evaluator.py"] == ("120000", "blob", link)
    with pytest.raises(ChangeBlocked):
        ws(tmp_path, repo).review(base, head2)
    # a content change in an allowed file is accepted when the mode is unchanged (the check is not simply refusing everything)
    head3 = commit_with_entries(repo, {**entries, PLANNER: ("100644", "blob", blob(repo, "def add(a, b):\n    return a + b\n"))}, base)
    assert set(tree_entries(repo, head3)) == set(entries)
    assert ws(tmp_path, repo).review(base, head3).changed_files == (PLANNER,)
    repo2 = make_repo(tmp_path / "b")
    b0, h0 = commit_change(repo2, {PLANNER: "x = 1\n\x00\x01"})
    with pytest.raises(ChangeBlocked, match="binary"):
        ws(tmp_path / "b", repo2).review(b0, h0)


# ---- V3: export of the exact commit ------------------------------------------------------------------------------------------------------------
def test_export_contains_exactly_the_files_of_the_commit_and_no_git(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "untracked.txt").write_text("not versioned")
    (repo / PLANNER).write_text("def add(a, b):\n    return 'UNCOMMITTED'\n")           # working-tree state must not leak into the export
    w = ws(tmp_path, repo)
    exp = w.export_commit(git(repo, "rev-parse", "HEAD"))
    try:
        listed = sorted(p.relative_to(exp.path).as_posix() for p in exp.path.rglob("*") if p.is_file())
        assert listed == sorted(FILES) and not (exp.path / ".git").exists() and not (exp.path / "untracked.txt").exists()
        assert (exp.path / PLANNER).read_text() == FILES[PLANNER] and "UNCOMMITTED" not in (exp.path / PLANNER).read_text()
        assert dict(exp.manifest)[PLANNER] == hashlib.sha256(FILES[PLANNER].encode()).hexdigest()
        assert exp.manifest_sha256 == manifest_digest(list(exp.manifest)) and exp.commit == git(repo, "rev-parse", "HEAD")
        w.verify_export(exp)
        assert (exp.path / PLANNER).stat().st_mode & 0o222 == 0           # exported files are made read-only (advisory: the owner/root can still change them -
        #                                                                   which is why the manifest is verified again after any run)
    finally:
        w.remove_export(exp.path)
    assert not exp.path.exists()


def test_any_difference_between_export_and_manifest_is_detected(tmp_path):
    repo = make_repo(tmp_path)
    w = ws(tmp_path, repo)
    exp = w.export_commit(git(repo, "rev-parse", "HEAD"))
    try:
        for mutate in (lambda: (exp.path / "extra.py").write_text("x"), lambda: os.chmod(exp.path / PLANNER, 0o600) or (exp.path / PLANNER).write_text("changed"),
                       lambda: (exp.path / "src").joinpath(".git").mkdir()):
            for p in [exp.path, *exp.path.rglob("*")]:
                os.chmod(p, 0o700)
            mutate()
            with pytest.raises(PreparationError, match="differs"):
                w.verify_export(exp)
            for q in list(exp.path.rglob("extra.py")) + list(exp.path.rglob(".git")):
                (q.rmdir() if q.is_dir() else q.unlink())
            (exp.path / PLANNER).write_bytes(FILES[PLANNER].encode())      # bytes, not write_text(): on Windows text mode would write CRLF and the (correct) hash check would fail
            w.verify_export(exp)
        # a missing file
        os.chmod(exp.path / "src/jarvis/goals", 0o700)
        (exp.path / "src/jarvis/goals/evaluator.py").unlink()
        with pytest.raises(PreparationError):
            w.verify_export(exp)
    finally:
        w.remove_export(exp.path)


EXPORT_REFUSALS = {
    # case: (extra entries, regex the error must match, regex it must NOT match)
    "symlink": ({"src/jarvis/link.py": ("120000", "blob", "@/etc/passwd")}, r"not a regular file", r"file name"),
    "submodule": ({"src/jarvis/sub": ("160000", "commit", "@base")}, r"not a regular file", r"file name"),
    "non-ascii-name": ({"src/jarvis/we ird\u00e9.py": ("100644", "blob", "@x1")}, r"unusual file name", r"collision|regular file"),
    "case-collision": ({"src/jarvis/A.py": ("100644", "blob", "@x1"), "src/jarvis/a.py": ("100644", "blob", "@x2")}, r"differ only in case", r"unusual|regular file"),
    "backslash-name": ({"src/jarvis/a\\b.py": ("100644", "blob", "@x1")}, r"unusual file name", r"collision|regular file"),
    "drive-colon-name": ({"src/jarvis/c:x.py": ("100644", "blob", "@x1")}, r"unusual file name", r"collision|regular file"),
    "trailing-dot-name": ({"src/jarvis/x.py.": ("100644", "blob", "@x1")}, r"unusual file name", r"collision|regular file"),
}


@pytest.mark.parametrize("case", list(EXPORT_REFUSALS))
def test_export_refuses_symlinks_submodule_entries_and_unusual_names(tmp_path, case):
    """One case per run, each must reach ITS validation and say so (the old combined message hid which rule fired). Fixtures are commits built with git plumbing (see
    commit_with_entries): no OS symlink, no case-sensitive file system and no non-ASCII file name on disk needed."""
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    entries = tree_entries(repo, base)
    assert_clean_names(entries)
    extra, expected, forbidden = EXPORT_REFUSALS[case]
    contents = {"@x1": blob(repo, "x = 1\n"), "@x2": blob(repo, "x = 2\n"), "@base": base}
    extra = {path: (mode, kind, contents.get(sha, blob(repo, sha[1:]) if sha.startswith("@/") else sha)) for path, (mode, kind, sha) in extra.items()}
    commit = commit_with_entries(repo, {**entries, **extra}, base)
    built = tree_entries(repo, commit)
    assert set(built) == set(entries) | set(extra) and all(built[p] == v for p, v in extra.items())      # the complete tree, including the offending entry, is in the commit
    def leftovers() -> set[Path]:
        return set(Path(tempfile.gettempdir()).glob("jarvis-export-*"))
    before = leftovers()
    with pytest.raises(PreparationError) as exc:
        ws(tmp_path, repo).export_commit(commit)
    assert re.search(expected, str(exc.value)), str(exc.value)
    assert not re.search(forbidden, str(exc.value)), f"wrong rule fired: {exc.value}"
    assert leftovers() == before                                                             # a refused export leaves no directory behind


def test_export_accepts_an_executable_regular_file_as_a_regular_file(tmp_path):
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    entries = tree_entries(repo, base)
    w = ws(tmp_path, repo)
    ok = w.export_commit(commit_with_entries(repo, {**entries, "src/jarvis/ok.py": ("100755", "blob", blob(repo, "x = 1\n"))}, base))
    try:
        assert "src/jarvis/ok.py" in dict(ok.manifest)
    finally:
        w.remove_export(ok.path)


def test_export_survives_clean_smudge_filters_and_crlf_settings(tmp_path):
    """The export reads blobs from the object database: no filter and no autocrlf setting can alter what is tested."""
    repo = make_repo(tmp_path, crlf=True)
    git(repo, "config", "filter.evil.smudge", "echo SMUDGED")
    (repo / ".gitattributes").write_text("*.py filter=evil\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "attrs")
    w = ws(tmp_path, repo)
    exp = w.export_commit(git(repo, "rev-parse", "HEAD"))
    try:
        assert b"SMUDGED" not in (exp.path / PLANNER).read_bytes() and (exp.path / PLANNER).read_bytes() == FILES[PLANNER].encode()
    finally:
        w.remove_export(exp.path)


def test_export_removal_only_touches_export_directories(tmp_path):
    victim = tmp_path / "important"
    victim.mkdir()
    (victim / "f").write_text("keep")
    GitWorkspace.remove_export(victim)
    assert (victim / "f").exists()


# ---- the workspace refuses to change the repository on its own (direct calls cannot bypass the manager's lock) ------------------------------------------------
MUTATORS = {
    "create_worktree": lambda w: w.create_worktree("imp-000000000001"),
    "apply_and_commit": lambda w: w.apply_and_commit(None, [{"path": PLANNER, "old_text": "a", "new_text": "b"}], "m"),
    "discard": lambda w: w.discard("imp-000000000001", P.BRANCH_PREFIX + "imp-000000000001"),
    "fast_forward": lambda w: w.fast_forward(P.BRANCH_PREFIX + "imp-000000000001", "a" * 40, "b" * 40),
    "revert": lambda w: w.revert("a" * 40),
}


@pytest.mark.parametrize("name", list(MUTATORS))
def test_direct_calls_to_mutating_methods_are_refused_by_default(tmp_path, monkeypatch, name):
    repo = make_repo(tmp_path)
    head, branches = git(repo, "rev-parse", "HEAD"), git(repo, "branch", "--list")
    def boom(*a, **k):
        raise AssertionError("a process was started")
    monkeypatch.setattr(subprocess, "Popen", boom)
    with pytest.raises(ExecutionDisabled, match="isolation"):
        MUTATORS[name](ws(tmp_path, repo))                                  # the guard is asked BEFORE any validation, path work or process
    monkeypatch.undo()
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "branch", "--list") == branches and not (tmp_path / "data").exists()


@pytest.mark.parametrize("missing", REQUIRED_PROPERTIES)
def test_a_partial_attestation_does_not_unlock_the_workspace(tmp_path, missing):
    w = GitWorkspace(make_repo(tmp_path), tmp_path / "data", timeout=30, guard=ExecutionGuard(full_attestation(**{missing: False})))
    for call in MUTATORS.values():
        with pytest.raises(ExecutionDisabled, match=missing):
            call(w)


def test_the_guard_is_the_only_barrier_and_read_only_methods_stay_available(tmp_path):
    """With the test-double attestation the git-only primitives run; locked, review/export/status still work (they cannot change the repository)."""
    repo = make_repo(tmp_path)
    locked, base = ws(tmp_path, repo), git(repo, "rev-parse", "HEAD")
    assert locked.tracked_changes() == "" and locked.head() == base and locked.changed_entries(base, base) == []
    exp = locked.export_commit(base)
    locked.remove_export(exp.path)
    opened = ws_unlocked(tmp_path, repo)
    wt = opened.create_worktree("imp-000000000001")
    assert wt.path.is_dir() and "jarvis/improve-imp-000000000001" in git(repo, "branch", "--list")
    opened.discard("imp-000000000001", wt.branch)
    assert not wt.path.exists() and "jarvis/improve" not in git(repo, "branch", "--list")


# ---- GIT_CONFIG_NOSYSTEM must not be set (Windows: system-level core.autocrlf=true) --------------------------------------------------------------
class SystemConfigRunner(SubprocessRunner):
    """Simulates a machine whose SYSTEM git config sets core.autocrlf=true (the Git for Windows default): the file is handed to git exactly like a real system config
    would be found, i.e. outside the scrubbed environment's control, while GIT_CONFIG_NOSYSTEM stays whatever the code under test decides."""

    def __init__(self, sysfile: Path) -> None:
        super().__init__()
        self._sys = str(sysfile)

    def _spawn(self, argv, cwd, env_extra, out, err):
        return super()._spawn(argv, cwd, {**(env_extra or {}), "GIT_CONFIG_SYSTEM": self._sys, "GIT_CONFIG_GLOBAL": os.devnull}, out, err)


def _git_supports_system_override() -> bool:
    out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.split()[-1].split(".")
    return tuple(int(x) for x in out[:2] if x.isdigit()) >= (2, 32)


def test_the_scrubbed_environment_does_not_hide_the_system_git_config():
    assert "GIT_CONFIG_NOSYSTEM" not in scrubbed_env() and scrubbed_env({"X": "1"})["X"] == "1"


@pytest.mark.skipif(not _git_supports_system_override(), reason="needs git >= 2.32 (GIT_CONFIG_SYSTEM) to simulate a system-level autocrlf setting")
def test_crlf_working_tree_is_clean_under_a_system_level_autocrlf_config(tmp_path, monkeypatch):
    sysfile = tmp_path / "system.gitconfig"
    sysfile.write_text("[core]\n\tautocrlf = true\n")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(sysfile))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for rel, text in FILES.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "w", encoding="utf-8", newline="\r\n") as fh:                  # a Windows checkout: CRLF in the working tree ...
            fh.write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")                                            # ... LF in the blobs (autocrlf=true)
    assert b"\r\n" not in subprocess.run(["git", "cat-file", "blob", "HEAD:" + PLANNER], cwd=repo, capture_output=True).stdout
    w = GitWorkspace(repo, tmp_path / "data", SystemConfigRunner(sysfile), timeout=30)
    assert w.tracked_changes() == ""                                                     # clean: the system config is honoured
    (repo / PLANNER).write_bytes(b"def add(a, b):\r\n    return 'really changed'\r\n")
    assert PLANNER in w.tracked_changes()                                                # a real change is still detected
    # control: this is what GIT_CONFIG_NOSYSTEM=1 did - the same CRLF file is reported as modified, so the assertion above is not vacuous
    (repo / PLANNER).write_bytes(FILES[PLANNER].replace("\n", "\r\n").encode())
    env = {**os.environ, "GIT_CONFIG_SYSTEM": str(sysfile), "GIT_CONFIG_GLOBAL": os.devnull}
    assert subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, env=env, capture_output=True, text=True).stdout.strip() == ""
    # The status above refreshed the index's stat cache for this file. Without a different stat the next git call would not read the content at all and could report
    # "clean" whatever the config says (seen once on a Windows runner, timing dependent) - so make the control compare content: same bytes, but a new mtime.
    st = (repo / PLANNER).stat()
    os.utime(repo / PLANNER, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert PLANNER in subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, env={**env, "GIT_CONFIG_NOSYSTEM": "1"}, capture_output=True, text=True).stdout


# ---- active tree checks (git primitive used by a future activation; fixtures only) -------------------------------------------------------------
@pytest.mark.parametrize("crlf", [False, True], ids=["lf", "windows-crlf-autocrlf"])
def test_dirty_tree_is_detected_with_and_without_autocrlf(tmp_path, crlf):
    repo = make_repo(tmp_path, crlf=crlf)
    w = ws(tmp_path, repo)
    assert w.tracked_changes() == ""
    (repo / PLANNER).write_text("changed\n")
    assert PLANNER in w.tracked_changes()


# ---- process runner: limits ---------------------------------------------------------------------------------------------------------------
def test_runner_timeout_cancel_and_output_cap(tmp_path):
    import threading
    r = SubprocessRunner(max_output=1000, max_total=200_000)
    t0 = time.monotonic()
    res = r.run([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 0.5)
    assert res.timed_out and not res.ok and time.monotonic() - t0 < 15
    flag = threading.Event()
    flag.set()
    assert r.run([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 30, flag).cancelled
    big = r.run([sys.executable, "-c", "import sys\nwhile True:\n    sys.stdout.write('x' * 1000)"], tmp_path, 30)
    assert big.output_limit and not big.ok and len(big.output) <= 1000
    with pytest.raises(PreparationError):
        r.capture([sys.executable, "-c", "import sys; sys.stdout.write('x' * 5000)"], tmp_path, 10, 1000)
    assert r.capture([sys.executable, "-c", "import sys; sys.stdout.write('abc')"], tmp_path, 10, 1000) == b"abc"
    with pytest.raises(PreparationError):
        r.capture([sys.executable, "-c", "raise SystemExit(3)"], tmp_path, 10, 1000)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="descendant discovery uses /proc (Linux only; Windows is untested)")
def test_detached_child_processes_are_killed_with_their_parent(tmp_path):
    """Helper scripts are written by this test (they are not proposed code)."""
    pidfile = tmp_path / "child.pid"
    (tmp_path / "child.py").write_text("import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(60)\n")
    (tmp_path / "parent.py").write_text(textwrap.dedent("""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]], start_new_session=True)
        time.sleep(60)
    """))
    res = SubprocessRunner().run([sys.executable, str(tmp_path / "parent.py"), str(tmp_path / "child.py"), str(pidfile)], tmp_path, 3.0)
    assert res.timed_out
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    alive = True
    while alive and time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except OSError:
            alive = False
    if alive:
        os.kill(pid, 9)
    assert not alive, "the detached grandchild survived the timeout"


def test_runner_environment_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-supersecretvalue1234567890")
    monkeypatch.setenv("MY_PASSWORD", "hunter2hunter2")
    res = SubprocessRunner().run([sys.executable, "-c", "import os; print(sorted(k for k in os.environ if k.upper() in ('OPENAI_API_KEY', 'MY_PASSWORD')))"], tmp_path, 20)
    assert res.ok and "OPENAI" not in res.output and "MY_PASSWORD" not in res.output
