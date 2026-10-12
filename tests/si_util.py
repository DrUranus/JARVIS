"""Fixtures for the self-improvement tests. NOTHING here executes proposed code: adversarial samples are plain strings that are parsed (ast) or stored, never imported,
exec'd or run. The workflow tests use an in-memory FakeWorkspace (no git, no processes) and a fake sandbox runner that only records the commands it was given.
The only real subprocesses in the suite are `git` (object-database/metadata tests on temporary repositories) and test-owned helper scripts for the process runner."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.audit import AuditLogger, MemoryAuditSink
from jarvis.permissions.confirmation import ScriptedConfirmation
from jarvis.self_improvement import (ApprovalGate, ExecutionGuard, ImprovementManager, IsolationAttestation, MemoryProposalStore, ProposalStatus, ValidationPipeline)
from jarvis.self_improvement import policy as P
from jarvis.self_improvement.errors import PreparationError
from jarvis.self_improvement.review import RawEntry, blob_sha1, review_entries
from jarvis.self_improvement.workspace import CommandResult, Export, Worktree, manifest_digest, valid_sha

ONCE, NO, SESSION = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.DENY, ConfirmationChoice.ALLOW_SESSION
PLANNER = "src/jarvis/goals/planner.py"
GOOD = {"path": PLANNER, "old_text": "return a - b", "new_text": "return a + b"}
TESTS = ("tests/test_calc.py",)
FILES = {PLANNER: "def add(a, b):\n    return a - b\n", "src/jarvis/goals/evaluator.py": "def ev():\n    return 1\n", "tests/test_calc.py": "def test_x():\n    assert True\n"}
PLATFORM = "windows" if sys.platform.startswith("win") else "linux" if sys.platform.startswith("linux") else sys.platform


def full_attestation(**override) -> IsolationAttestation:
    """A TEST DOUBLE claiming proven isolation so that the (otherwise unreachable) gate logic can be exercised. It sandboxes nothing; no production code builds one."""
    props = dict(unprivileged_user=True, no_host_credentials=True, no_network=True, no_main_repository=True, resource_limits=True, kills_all_descendants=True,
                 platform_tests_passed=True)
    props.update(override)
    return IsolationAttestation("test-double", PLATFORM, **props)


def sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


class FakeWorkspace:
    """In-memory stand-in for GitWorkspace: commits are dicts path -> text. Uses the REAL review code (allow-list, AST scan, rendering) via review_entries."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.base_files = dict(files or FILES)
        self.base = sha("base")
        self.active_head = self.base
        self.active_files = dict(self.base_files)
        self.dirty = False
        self.commits: dict[str, dict[str, str]] = {self.base: dict(self.base_files)}
        self.branches: dict[str, str] = {}
        self.worktrees: set[str] = set()
        self.blobs: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.revert_calls: list[str] = []
        for t in self.base_files.values():
            self._blob(t)

    def _blob(self, text) -> str:
        data = text if isinstance(text, bytes) else text.encode()
        s = blob_sha1(data)
        self.blobs[s] = data
        return s

    # ---- GitWorkspace surface used by the manager -----------------------------------------------------------------------------------------
    def create_worktree(self, pid, cancel=None):
        self.calls.append("create_worktree")
        self.worktrees.add(pid)
        return Worktree(pid, Path("/fake") / pid, P.BRANCH_PREFIX + pid, self.active_head)

    def read_file(self, wt, rel):
        why = P.refuse_target(rel)
        if why:
            from jarvis.self_improvement import ChangeBlocked
            raise ChangeBlocked(why)
        return self.commits[wt.base_commit][rel]

    def apply_and_commit(self, wt, edits, message, cancel=None):
        files = dict(self.commits[wt.base_commit])
        for e in edits:
            text = files.get(e["path"])
            if text is None or text.count(e["old_text"]) != 1:
                raise PreparationError("old_text must occur exactly once")
            files[e["path"]] = text.replace(e["old_text"], e["new_text"], 1)
            self._blob(files[e["path"]])
        head = sha(json.dumps(files, sort_keys=True) + wt.branch)
        self.commits[head] = files
        self.branches[wt.branch] = head
        return self.review(wt.base_commit, head)

    def review(self, base, head, cancel=None):
        valid_sha(base), valid_sha(head)
        a, b = self.commits[base], self.commits[head]
        entries = [RawEntry("M", "100644", "100644", self._blob(a[p]), self._blob(b[p]), p) for p in sorted(b) if a.get(p) != b[p]]
        return review_entries(base, head, entries, lambda s: self.blobs[s])

    def worktree_for(self, pid, branch, base):
        if pid not in self.worktrees:
            raise PreparationError("the prepared working copy no longer exists")
        return Worktree(pid, Path("/fake") / pid, branch, base)

    def branch_tip(self, branch):
        return self.branches[branch]

    def export_commit(self, commit, cancel=None):
        files = self.commits[commit]
        manifest = tuple(sorted((p, hashlib.sha256(t.encode()).hexdigest()) for p, t in files.items()))
        return Export(Path("/fake-export"), commit, manifest, manifest_digest(manifest))

    def remove_export(self, path):
        self.calls.append("remove_export")

    def discard(self, pid, branch=""):
        self.calls.append("discard")
        self.worktrees.discard(pid)
        self.branches.pop(P.BRANCH_PREFIX + pid, None)

    def fast_forward(self, branch, base, head):
        self.calls.append("fast_forward")
        if self.dirty:
            raise PreparationError("the active working tree has uncommitted changes")
        if self.active_head != base:
            raise PreparationError("the active branch moved since the change was reviewed")
        if self.branches[branch] != head:
            raise PreparationError("the improvement branch changed after it was approved")
        self.active_head, self.active_files = head, dict(self.commits[head])
        return head

    def revert(self, commit):
        self.revert_calls.append(commit)
        self.active_files = dict(self.base_files)
        self.active_head = sha("revert" + commit)
        return self.active_head

    # ---- test helpers ----------------------------------------------------------------------------------------------------------------------
    def tamper_branch(self, branch, path=PLANNER, text="def add(a, b):\n    return 42\n"):
        files = dict(self.commits[self.branches[branch]])
        files[path] = text
        self._blob(text)
        head = sha("tampered" + text)
        self.commits[head] = files
        self.branches[branch] = head

    def move_active(self):
        self.active_head = sha("someone else committed")
        self.commits[self.active_head] = dict(self.active_files)


class FakeSandbox:
    """Records the commands it is asked to run and answers from a script. It starts no process."""

    def __init__(self, *results: CommandResult) -> None:
        self.results, self.calls = list(results), []

    def run(self, argv, export_dir, timeout, cancel=None):
        self.calls.append((list(argv), export_dir))
        return self.results.pop(0) if self.results else CommandResult(0, "ok", 0.0)

    def import_check(self, modules, export_dir, timeout, cancel=None):
        self.calls.append((["import_check", *modules], export_dir))
        return self.results.pop(0) if self.results else CommandResult(0, "ok", 0.0)


class Rig:
    def __init__(self, mgr, ws, sink, confirm, sandbox, store):
        self.m, self.ws, self.sink, self.confirm, self.sandbox, self.store = mgr, ws, sink, confirm, sandbox, store

    def events(self, action=None):
        return [e for e in self.sink.events if action is None or e.action == action]

    def ready(self, edits=(GOOD,), tests=TESTS):
        p = self.m.propose("Fix add", "add subtracts", suggested_tests=tests)
        p = self.m.prepare(p.proposal_id, list(edits))
        p = self.m.test(p.proposal_id)
        return self.m.submit_for_approval(p.proposal_id) if p.status is ProposalStatus.TESTED else p


def rig(*, answers=(ONCE, ONCE), attested=True, audit=True, store=None, ws=None, sandbox=None, verify=True, files=None) -> Rig:
    ws = ws or FakeWorkspace(files)
    sandbox = sandbox or FakeSandbox()
    guard = ExecutionGuard(full_attestation()) if attested else ExecutionGuard.locked()
    pipe = ValidationPipeline(guard, sandbox, "python", verify_export=(lambda e: None) if verify else None)
    sink = MemoryAuditSink()
    confirm = ScriptedConfirmation(answers)
    store = store or MemoryProposalStore()
    mgr = ImprovementManager(store, workspace=ws, pipeline=pipe, gate=ApprovalGate(confirm), audit=AuditLogger([sink]) if audit else None, guard=guard)
    return Rig(mgr, ws, sink, confirm, sandbox, store)
