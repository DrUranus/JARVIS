"""Building blocks for the self-improvement tests: a tiny REAL git repository shaped like JARVIS (src/jarvis/..., tests/...), a manager wired to it with scripted
confirmations and an in-memory audit log. Preparation and testing really run git and pytest in subprocesses."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.audit import AuditLogger, MemoryAuditSink
from jarvis.permissions.confirmation import ScriptedConfirmation
from jarvis.self_improvement import (ApprovalGate, GitWorkspace, ImprovementManager, MemoryProposalStore, SubprocessRunner, ValidationPipeline)

ONCE, NO, SESSION = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.DENY, ConfirmationChoice.ALLOW_SESSION
GOOD = {"path": "src/jarvis/goals/engine.py", "old_text": "a - b", "new_text": "a + b"}          # makes tests/test_calc.py pass
BAD = {"path": "src/jarvis/goals/engine.py", "old_text": "a - b", "new_text": "a * b"}           # compiles, imports, but the test fails
TESTS = ("tests/test_calc.py",)

FILES = {
    "src/jarvis/__init__.py": "",
    "src/jarvis/goals/__init__.py": "",
    "src/jarvis/goals/engine.py": "def add(a, b):\n    return a - b\n",
    "src/jarvis/permissions/__init__.py": "",
    "src/jarvis/permissions/engine.py": "ALLOW = False\n",
    "tests/test_calc.py": "from jarvis.goals.engine import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    "tests/test_other.py": "def test_other():\n    assert True\n",
}


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def make_repo(tmp_path: Path, files: dict[str, str] | None = None, *, crlf: bool = False) -> Path:
    """`crlf=True` reproduces a Windows checkout: core.autocrlf=true and CRLF line endings in the working tree."""
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


class Rig:
    def __init__(self, manager, repo, audit_sink, confirm, workspace):
        self.m, self.repo, self.sink, self.confirm, self.ws = manager, repo, audit_sink, confirm, workspace

    def events(self, action: str | None = None):
        return [e for e in self.sink.events if action is None or e.action == action]

    def ready(self, edits=(GOOD,), tests=TESTS):
        """PROPOSED -> READY_FOR_APPROVAL for a good change."""
        p = self.m.propose("Fix add", "add subtracts", suggested_tests=tests)
        p = self.m.prepare(p.proposal_id, list(edits))
        p = self.m.test(p.proposal_id)
        return self.m.submit_for_approval(p.proposal_id) if p.status.value == "TESTED" else p


def rig(tmp_path: Path, *, answers=(ONCE,), allow_activation=True, allow_prepare=True, files=None, test_timeout=120.0, audit=True, writer=None, analyzer=None,
        runner=None, strict_audit=True, crlf=False) -> Rig:
    repo = make_repo(tmp_path, files, crlf=crlf)
    data = tmp_path / "data"
    runner = runner or SubprocessRunner()
    ws = GitWorkspace(repo, data, runner, timeout=30)
    pipe = ValidationPipeline(runner, sys.executable, test_timeout=test_timeout)
    sink = MemoryAuditSink()
    confirm = ScriptedConfirmation(answers)
    mgr = ImprovementManager(MemoryProposalStore(), analyzer=analyzer, workspace=ws, pipeline=pipe, gate=ApprovalGate(confirm),
                             audit=AuditLogger([sink]) if audit else None, writer=writer, allow_prepare=allow_prepare, allow_activation=allow_activation,
                             strict_audit=strict_audit)
    return Rig(mgr, repo, sink, confirm, ws)
