"""RepairRun, RepairAttempt, TestResult, Diagnosis, RepairPlan: immutable snapshots with validated construction and status changes.
Free text never appears in a repr; everything stored is bounded (no unbounded logs in memory) and redacted by the engine before it gets here."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from jarvis.agents import policy as AP
from jarvis.self_repair import policy as P
from jarvis.self_repair.errors import InvalidRepairError
from jarvis.self_repair.state import AttemptStatus, RepairStatus, check_attempt_transition, check_run_transition, RUN_TERMINAL


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_run_id() -> str:
    return "r-" + uuid.uuid4().hex[:12]


class ErrorCategory(str, Enum):
    TEST_FAILURE = "TEST_FAILURE"
    IMPORT_ERROR = "IMPORT_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    ASSERTION_FAILURE = "ASSERTION_FAILURE"
    TIMEOUT = "TIMEOUT"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    MISSING_FILE = "MISSING_FILE"
    UNKNOWN = "UNKNOWN"
    NONE = "NONE"                    # the tests passed


@dataclass(frozen=True)
class TestResult:
    __test__ = False                 # not a pytest test class

    passed: bool
    summary: str = field(default="", repr=False)
    exit_status: int | None = None
    failed_tests: tuple[str, ...] = ()
    error_category: ErrorCategory = ErrorCategory.NONE
    stdout_summary: str = field(default="", repr=False)
    stderr_summary: str = field(default="", repr=False)
    duration: float = 0.0
    timed_out: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise InvalidRepairError("passed must be a bool")
        object.__setattr__(self, "summary", P.clip(self.summary, P.MAX_SUMMARY))
        object.__setattr__(self, "stdout_summary", P.tail(str(self.stdout_summary), P.MAX_STDOUT))
        object.__setattr__(self, "stderr_summary", P.tail(str(self.stderr_summary), P.MAX_STDERR))
        object.__setattr__(self, "failed_tests", tuple(P.clip(t, 200) for t in list(self.failed_tests)[: P.MAX_FAILED_TESTS]))
        if not isinstance(self.error_category, ErrorCategory):
            raise InvalidRepairError("error_category must be an ErrorCategory")
        if not isinstance(self.duration, (int, float)) or isinstance(self.duration, bool) or self.duration < 0 or self.duration != self.duration:
            object.__setattr__(self, "duration", 0.0)

    def fingerprint(self) -> tuple[Any, ...]:
        return (self.passed, self.error_category.value, tuple(sorted(self.failed_tests)))

    def to_dict(self) -> dict[str, Any]:
        """Bounded and without the raw logs: what a status view may show."""
        return {"passed": self.passed, "summary": self.summary, "exit_status": self.exit_status, "failed_tests": list(self.failed_tests),
                "error_category": self.error_category.value, "duration": round(float(self.duration), 3), "timed_out": self.timed_out}


@dataclass(frozen=True)
class Diagnosis:
    category: ErrorCategory
    summary: str = field(default="", repr=False)
    failed_tests: tuple[str, ...] = ()
    suspect_files: tuple[str, ...] = ()        # files named in the output (hints, never trusted as targets)
    repairable: bool = False
    evidence: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", P.clip(self.summary, P.MAX_SUMMARY))
        object.__setattr__(self, "evidence", P.clip(self.evidence, 300))
        object.__setattr__(self, "failed_tests", tuple(self.failed_tests)[: P.MAX_FAILED_TESTS])
        object.__setattr__(self, "suspect_files", tuple(P.clip(f, 200) for f in list(self.suspect_files)[:10]))

    def fingerprint(self) -> tuple[Any, ...]:
        return (self.category.value, tuple(sorted(self.failed_tests)))

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category.value, "summary": self.summary, "failed_tests": list(self.failed_tests),
                "suspect_files": list(self.suspect_files), "repairable": self.repairable}


@dataclass(frozen=True)
class RepairPlan:
    objective: str = field(repr=False)
    target_files: tuple[str, ...]
    target_tests: tuple[str, ...] = ()
    allowed_capabilities: frozenset[str] = frozenset({AP.CODING_READ, AP.CODING_WRITE, AP.CODING_TEST})
    reason: str = field(default="", repr=False)
    edits: tuple[Mapping[str, Any], ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip() or len(self.objective) > P.MAX_OBJECTIVE:
            raise InvalidRepairError("a repair plan needs an objective")
        if not self.target_files or len(self.target_files) > P.MAX_EDITS:
            raise InvalidRepairError("a repair plan names 1..%d target files" % P.MAX_EDITS)
        for f in self.target_files:
            why = P.refuse_target(f)
            if why:
                raise InvalidRepairError(f"target file refused: {why}")
        caps = frozenset(self.allowed_capabilities)
        if not caps <= {AP.CODING_READ, AP.CODING_WRITE, AP.CODING_TEST}:
            raise InvalidRepairError("a repair plan may only use coding.read, coding.write and coding.test")
        object.__setattr__(self, "allowed_capabilities", caps)
        object.__setattr__(self, "reason", P.clip(self.reason, 300))
        object.__setattr__(self, "edits", tuple(P.plain_copy(e) for e in self.edits))

    def digest(self) -> str:
        import hashlib
        import json
        return hashlib.sha256(json.dumps(P.plain_copy(list(self.edits)), sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {"objective": P.clip(self.objective, 300), "target_files": list(self.target_files), "target_tests": list(self.target_tests),
                "allowed_capabilities": sorted(self.allowed_capabilities), "reason": self.reason, "edit_count": len(self.edits)}


@dataclass(frozen=True)
class RepairAttempt:
    attempt_id: str
    run_id: str
    number: int
    diagnosis: Diagnosis | None = None
    repair_objective: str = field(default="", repr=False)
    changed_files: tuple[str, ...] = ()
    targeted_test_result: TestResult | None = None
    regression_result: TestResult | None = None
    status: AttemptStatus = AttemptStatus.PENDING
    failure_reason: str = field(default="", repr=False)
    plan: RepairPlan | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not AP.valid_id(self.attempt_id) or not AP.valid_id(self.run_id):
            raise InvalidRepairError("attempt_id and run_id must be valid ids")
        if not isinstance(self.number, int) or isinstance(self.number, bool) or not 1 <= self.number <= P.MAX_ATTEMPTS_HARD:
            raise InvalidRepairError("attempt number out of range")
        object.__setattr__(self, "failure_reason", P.clip(self.failure_reason, P.MAX_SUMMARY))
        object.__setattr__(self, "repair_objective", P.clip(self.repair_objective, P.MAX_OBJECTIVE))

    def with_status(self, new: AttemptStatus, reason: str = "") -> "RepairAttempt":
        check_attempt_transition(self.status, new)
        return replace(self, status=new, failure_reason=P.clip(reason, P.MAX_SUMMARY) if reason else self.failure_reason)

    def evolve(self, **kw: Any) -> "RepairAttempt":
        return replace(self, **kw)

    def to_dict(self) -> dict[str, Any]:
        return {"attempt_id": self.attempt_id, "run_id": self.run_id, "number": self.number, "status": self.status.value,
                "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None, "repair_objective": P.clip(self.repair_objective, 300),
                "changed_files": list(self.changed_files),
                "targeted_test_result": self.targeted_test_result.to_dict() if self.targeted_test_result else None,
                "regression_result": self.regression_result.to_dict() if self.regression_result else None,
                "failure_reason": self.failure_reason, "plan": self.plan.to_dict() if self.plan else None}


@dataclass(frozen=True)
class RepairRun:
    objective: str = field(repr=False)
    workspace: str = field(repr=False)
    run_id: str = field(default_factory=new_run_id)
    status: RepairStatus = RepairStatus.PENDING
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    max_attempts: int = P.MAX_ATTEMPTS_DEFAULT
    attempt_count: int = 0
    current_phase: str = "pending"
    failure_summary: str = field(default="", repr=False)
    final_summary: str = field(default="", repr=False)
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip() or len(self.objective) > P.MAX_OBJECTIVE or any(
                ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in self.objective):
            raise InvalidRepairError(f"objective must be 1..{P.MAX_OBJECTIVE} characters of plain text")
        if not isinstance(self.workspace, str) or not self.workspace.strip() or len(self.workspace) > 1000 or "\x00" in self.workspace:
            raise InvalidRepairError("an explicit workspace is required")
        if not AP.valid_id(self.run_id):
            raise InvalidRepairError("run_id must be 1..64 characters of letters, digits, _ . -")
        if not isinstance(self.status, RepairStatus):
            raise InvalidRepairError("status must be a RepairStatus")
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= P.MAX_ATTEMPTS_HARD:
            raise InvalidRepairError(f"max_attempts must be within 1..{P.MAX_ATTEMPTS_HARD}")
        if not isinstance(self.attempt_count, int) or not 0 <= self.attempt_count <= self.max_attempts:
            raise InvalidRepairError("attempt_count must be within 0..max_attempts")
        if self.timeout is not None and (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)) or not 0 < self.timeout <= P.MAX_TIMEOUT):
            raise InvalidRepairError(f"timeout must be within 0..{P.MAX_TIMEOUT:g} seconds")
        object.__setattr__(self, "failure_summary", P.clip(self.failure_summary, P.MAX_SUMMARY))
        object.__setattr__(self, "final_summary", P.clip(self.final_summary, P.MAX_SUMMARY))

    @property
    def is_terminal(self) -> bool:
        return self.status in RUN_TERMINAL

    def with_status(self, new: RepairStatus, now: datetime | None = None) -> "RepairRun":
        check_run_transition(self.status, new)
        now = now or utcnow()
        kw: dict[str, Any] = {"status": new}
        if self.started_at is None and new is not RepairStatus.CANCELLED and new is not RepairStatus.TIMEOUT:
            kw["started_at"] = now
        if new in RUN_TERMINAL:
            kw["finished_at"] = now
        return replace(self, **kw)

    def evolve(self, **kw: Any) -> "RepairRun":
        return replace(self, **kw)

    def to_dict(self) -> dict[str, Any]:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"run_id": self.run_id, "objective": P.clip(self.objective, 300), "workspace": P.clip(self.workspace, 300), "status": self.status.value,
                "created_at": iso(self.created_at), "started_at": iso(self.started_at), "finished_at": iso(self.finished_at),
                "max_attempts": self.max_attempts, "attempt_count": self.attempt_count, "current_phase": self.current_phase,
                "failure_summary": self.failure_summary, "final_summary": self.final_summary, "timeout": self.timeout}


@dataclass(frozen=True)
class RepairResult:
    run: RepairRun
    attempts: tuple[RepairAttempt, ...] = ()
    baseline: TestResult | None = None
    changed_files: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=(), repr=False)
    reason_code: str | None = None

    @property
    def status(self) -> RepairStatus:
        return self.run.status

    @property
    def succeeded(self) -> bool:
        return self.run.status is RepairStatus.SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {"run": self.run.to_dict(), "attempts": [a.to_dict() for a in self.attempts], "baseline": self.baseline.to_dict() if self.baseline else None,
                "changed_files": list(self.changed_files), "warnings": list(self.warnings), "reason_code": self.reason_code}
