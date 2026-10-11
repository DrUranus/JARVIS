"""Validation pipeline for a prepared change: scope -> diff review -> syntax -> import -> targeted tests -> regression tests.

Every stage reports whether it was EXECUTED and whether it PASSED; a stage that did not run (an earlier stage failed, no test exists, cancelled) is recorded
as not executed and never counts as passed. The result is `passed` only if every stage ran and passed. A diff that touches a security boundary ends the
pipeline with `blocked=True` before any code of the change is executed. Test commands are fixed argument lists built here; the test ids come from
validated proposal fields, never from model text."""
from __future__ import annotations

import ast
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from jarvis.redaction import SecretDetector
from jarvis.self_improvement import policy as P
from jarvis.self_improvement.models import StageReport
from jarvis.self_improvement.workspace import CommandRunner, PreparedChange, scrubbed_env  # noqa: F401

STAGES = ("scope", "diff_review", "syntax", "import", "targeted_tests", "regression_tests")


@dataclass
class PipelineResult:
    stages: list[StageReport] = field(default_factory=list)
    blocked: str = ""                       # non-empty: a security boundary is touched -> manual review
    cancelled: bool = False

    @property
    def passed(self) -> bool:
        return not self.blocked and not self.cancelled and len(self.stages) == len(STAGES) and all(s.executed and s.passed for s in self.stages)

    @property
    def failure(self) -> str:
        for s in self.stages:
            if not (s.executed and s.passed):
                return f"{s.name}: {s.summary.splitlines()[0] if s.summary else ('not executed' if not s.executed else 'failed')}"[:300]
        return ""


class ValidationPipeline:
    def __init__(self, runner: CommandRunner, python: str, *, test_timeout: float = 600.0, regression_paths: Sequence[str] = ("tests",),
                 detector: SecretDetector | None = None, clock=time.monotonic) -> None:
        self._runner, self._python, self._timeout = runner, python, test_timeout
        self._regression = tuple(regression_paths)
        self._detector = detector or SecretDetector.from_environment()
        self._clock = clock

    def _report(self, name: str, ok: bool, text: str, started: float, *, executed: bool = True, exit_status: int | None = None, timed_out: bool = False) -> StageReport:
        return StageReport(name, executed, ok and executed, self._detector.redact(text)[-P.MAX_OUTPUT:] if text else "", self._clock() - started, exit_status, timed_out)

    def run(self, change: PreparedChange, suggested_tests: Sequence[str], cancel: threading.Event | None = None) -> PipelineResult:
        res = PipelineResult()
        wt = change.worktree.path

        def skip_rest(from_index: int, why: str) -> None:
            for name in STAGES[from_index:]:
                res.stages.append(StageReport(name, False, False, why))

        def stage(i: int, fn) -> bool:
            if cancel is not None and cancel.is_set():
                res.cancelled = True
                skip_rest(i, "cancelled")
                return False
            started = self._clock()
            rep = fn(started)
            res.stages.append(rep)
            if rep.timed_out and cancel is not None and cancel.is_set():
                res.cancelled = True
            if not (rep.executed and rep.passed):
                skip_rest(i + 1, f"not executed: {STAGES[i]} did not pass")
                return False
            return True

        # 1. scope - what exactly changed
        def scope(t: float) -> StageReport:
            bad = [f for f in change.changed_files if P.refuse_target(f)]
            if bad:
                res.blocked = f"{bad[0]}: {P.refuse_target(bad[0])}"
                return self._report("scope", False, res.blocked, t)
            return self._report("scope", True, f"{len(change.changed_files)} file(s) changed:\n{change.stat}", t)

        if not stage(0, scope):
            return res

        # 2. diff review - added lines must not touch the sandbox or the security machinery
        def review(t: float) -> StageReport:
            added = "\n".join(ln[1:] for ln in change.diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
            why = P.scan_added(added)
            if why:
                res.blocked = why
                return self._report("diff_review", False, why, t)
            return self._report("diff_review", True, f"{len(added.splitlines())} added line(s) reviewed", t)

        if not stage(1, review):
            return res

        # 3. syntax - parsed, never executed
        def syntax(t: float) -> StageReport:
            for rel in change.changed_files:
                try:
                    ast.parse((wt / rel).read_text(encoding="utf-8"), filename=rel)
                except (SyntaxError, ValueError, OSError) as exc:
                    return self._report("syntax", False, f"{rel}: {type(exc).__name__}: {exc}", t)
            return self._report("syntax", True, f"{len(change.changed_files)} file(s) parse", t)

        if not stage(2, syntax):
            return res

        # 4. import - the worktree's code (not the installed copy) must import
        def imports(t: float) -> StageReport:
            mods = [Path(f).relative_to("src").with_suffix("").as_posix().replace("/", ".").removesuffix(".__init__") for f in change.changed_files]
            code = ("import importlib,sys,os\nimport jarvis\nroot=os.path.realpath(sys.argv[1])\n"
                    "assert os.path.realpath(jarvis.__file__).startswith(root), 'jarvis is not imported from the prepared copy'\n"
                    "[importlib.import_module(m) for m in sys.argv[2:]]\nprint('imported', len(sys.argv)-2)\n")
            r = self._runner.run([self._python, "-c", code, str(wt), *mods], wt, min(self._timeout, 120.0), cancel, {"PYTHONPATH": str(wt / "src")})
            return self._report("import", r.ok, r.output or ("timed out" if r.timed_out else "cancelled" if r.cancelled else ""), t,
                                exit_status=r.exit_status, timed_out=r.timed_out)

        if not stage(3, imports):
            return res

        # 5. targeted tests - only validated ids that exist in the prepared copy
        def targeted(t: float) -> StageReport:
            ids = [i for i in suggested_tests if P.TEST_ID_RE.match(i) and ".." not in i and (wt / i.split("::", 1)[0]).is_file()]
            if not ids:
                return self._report("targeted_tests", False, "no suggested test exists in the prepared copy: nothing was executed", t, executed=False)
            return self._pytest("targeted_tests", ids, wt, cancel, t)

        if not stage(4, targeted):
            return res

        # 6. regression tests
        def regression(t: float) -> StageReport:
            paths = [p for p in self._regression if P.TEST_ID_RE.match(p + "/x.py") and (wt / p).exists()]
            if not paths:
                return self._report("regression_tests", False, "no regression test path exists in the prepared copy: nothing was executed", t, executed=False)
            return self._pytest("regression_tests", paths, wt, cancel, t)

        stage(5, regression)
        return res

    def _pytest(self, name: str, targets: list[str], wt: Path, cancel, started: float) -> StageReport:
        r = self._runner.run([self._python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *targets], wt, self._timeout, cancel,
                             {"PYTHONPATH": str(wt / "src")})
        tail = r.output[-P.MAX_OUTPUT:]
        if r.timed_out:
            tail = f"timed out after {self._timeout:g}s\n{tail}"
        elif r.cancelled:
            tail = f"cancelled\n{tail}"
        # exit status 0 = all passed; 5 = nothing collected (not a pass)
        return self._report(name, r.ok, tail, started, exit_status=r.exit_status, timed_out=r.timed_out)
