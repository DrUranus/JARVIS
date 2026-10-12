"""Validation pipeline: scope -> static review (always) -> import -> targeted tests -> regression tests (only with PROVEN isolation, i.e. never today).

Every stage reports `executed` and `passed`; a stage that did not run is never a pass. While the ExecutionGuard is locked the three execution stages are recorded
as NOT executed, so `PipelineResult.passed` is False and no proposal can reach TESTED: a green static review alone authorises nothing.

If isolation were ever proven, the execution stages would run ONLY through a `SandboxRunner` on an exact EXPORT of the reviewed commit (no `.git`, hashes verified
before and after the run) - never through SubprocessRunner and never in a working directory."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

from jarvis.redaction import SecretDetector
from jarvis.self_improvement import policy as P
from jarvis.self_improvement.isolation import ExecutionGuard
from jarvis.self_improvement.models import StageReport
from jarvis.self_improvement.review import ReviewedChange
from jarvis.self_improvement.workspace import CommandResult, Export

STAGES = ("scope", "static_review", "import", "targeted_tests", "regression_tests")
EXECUTION_STAGES = STAGES[2:]


class SandboxRunner(Protocol):
    """A runner that executes inside a PROVEN sandbox (see isolation.REQUIRED_PROPERTIES) on a read-only export. No implementation exists."""

    def run(self, argv: Sequence[str], export_dir: Path, timeout: float, cancel: threading.Event | None = None) -> CommandResult: ...


@dataclass
class PipelineResult:
    stages: list[StageReport] = field(default_factory=list)
    blocked: str = ""                       # non-empty: a security boundary is touched -> manual review
    cancelled: bool = False
    manifest: str = ""                      # sha256 manifest of the export the execution stages ran on ("" = nothing ran)

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
    def __init__(self, guard: ExecutionGuard | None = None, sandbox: SandboxRunner | None = None, python: str = "python", *, test_timeout: float = 600.0,
                 regression_paths: Sequence[str] = ("tests",), detector: SecretDetector | None = None, verify_export: Callable[[Export], None] | None = None,
                 clock=time.monotonic) -> None:
        self._guard = guard or ExecutionGuard.locked()
        self._sandbox, self._python, self._timeout = sandbox, python, test_timeout
        self._regression = tuple(regression_paths)
        self._detector = detector or SecretDetector.from_environment()
        self._verify = verify_export
        self._clock = clock

    def _report(self, name: str, ok: bool, text: str, started: float, *, executed: bool = True, exit_status: int | None = None, timed_out: bool = False) -> StageReport:
        return StageReport(name, executed, ok and executed, self._detector.redact(text)[-P.MAX_OUTPUT:] if text else "", self._clock() - started, exit_status, timed_out)

    def run(self, change: ReviewedChange, suggested_tests: Sequence[str], export: Export | None = None, cancel: threading.Event | None = None) -> PipelineResult:
        res = PipelineResult()
        t0 = self._clock()
        bad = [f for f in change.changed_files if P.refuse_target(f)]
        if bad:
            res.blocked = f"{ascii(bad[0])}: {P.refuse_target(bad[0])}"
            res.stages.append(self._report("scope", False, res.blocked, t0))
            self._skip(res, 1, "not executed: scope did not pass")
            return res
        res.stages.append(self._report("scope", True, f"{change.stat}: {', '.join(change.changed_files)}", t0))
        t1 = self._clock()
        found = [f"{fc.path}: {x}" for fc in change.files for x in P.new_findings(fc.old_text, fc.new_text)]
        if found:
            res.blocked = f"{found[0]} (manual review required)"
            res.stages.append(self._report("static_review", False, res.blocked, t1))
            self._skip(res, 2, "not executed: static review did not pass")
            return res
        res.stages.append(self._report("static_review", True, "complete modules parsed and reviewed by AST (heuristic filter, not a proof; nothing was executed)", t1))
        if not self._guard.allowed or self._sandbox is None or export is None:
            why = self._guard.reason() if not self._guard.allowed else "no sandbox runner or export supplied"
            self._skip(res, 2, f"not executed: execution of proposed code is disabled ({why})")
            return res
        return self._execute(res, change, suggested_tests, export, cancel)

    @staticmethod
    def _skip(res: PipelineResult, start: int, why: str) -> None:
        for name in STAGES[start:]:
            res.stages.append(StageReport(name, False, False, why))

    def _execute(self, res: PipelineResult, change: ReviewedChange, tests: Sequence[str], export: Export, cancel: threading.Event | None) -> PipelineResult:
        """Only reachable with a proven-isolation attestation AND a sandbox runner (tests use a fake; production never gets here)."""
        sb, d = self._sandbox, export.path
        res.manifest = export.manifest_sha256

        def one(name: str, argv: Sequence[str], timeout: float) -> bool:
            if cancel is not None and cancel.is_set():
                res.cancelled = True
                self._skip(res, STAGES.index(name), "cancelled")
                return False
            t = self._clock()
            r = sb.run(argv, d, timeout, cancel)
            res.stages.append(self._report(name, r.ok, (r.output or "") + ("\ntimed out" if r.timed_out else "\ncancelled" if r.cancelled else ""), t,
                                           exit_status=r.exit_status, timed_out=r.timed_out))
            if r.cancelled:
                res.cancelled = True
            if not r.ok:
                self._skip(res, STAGES.index(name) + 1, f"not executed: {name} did not pass")
                return False
            return True

        mods = [f[:-3].removeprefix("src/").replace("/", ".") for f in change.changed_files]
        code = "import importlib,sys\n[importlib.import_module(m) for m in sys.argv[1:]]\nprint('imported', len(sys.argv)-1)\n"
        have = {path for path, _ in export.manifest}                       # the manifest, not the filesystem, says what exists in the exported commit
        ids = [i for i in tests if P.TEST_ID_RE.match(i) and ".." not in i and i.split("::", 1)[0] in have]
        steps = [("import", [self._python, "-c", code, *mods], min(self._timeout, 120.0))]
        if ids:
            steps.append(("targeted_tests", [self._python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *ids], self._timeout))
        else:
            steps.append(("targeted_tests", [], 0))
        reg = [p for p in self._regression if P.TEST_ID_RE.match(p + "/x.py") and any(h.startswith(p + "/") for h in have)]
        steps.append(("regression_tests", [self._python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *reg] if reg else [], self._timeout))
        for name, argv, timeout in steps:
            if not argv:
                res.stages.append(StageReport(name, False, False, "no matching test exists in the export: nothing was executed"))
                self._skip(res, STAGES.index(name) + 1, f"not executed: {name} did not pass")
                break
            if not one(name, argv, timeout):
                break
        # the tested copy must still be exactly the exported commit; without a verifier (or on any difference) the execution results are discarded
        try:
            if self._verify is None:
                raise ValueError("no export verifier configured")
            self._verify(export)
        except Exception as exc:  # noqa: BLE001
            res.stages = [s if s.name in STAGES[:2] else StageReport(s.name, s.executed, False, f"export integrity not verified after the run ({type(exc).__name__}): result discarded")
                          for s in res.stages]
        return res
