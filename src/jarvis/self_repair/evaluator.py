"""RepairEvaluator: the golden rule, deterministic. A repair counts as successful ONLY IF the targeted test passed AND the regression passed
AND every changed file is one the plan allowed. Anything else is never reported as success."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from jarvis.self_repair import policy as P
from jarvis.self_repair.models import TestResult


class Verdict(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Evaluation:
    verdict: Verdict
    reason: str = ""


class RepairEvaluator:
    def unexpected_files(self, changed: Iterable[str], allowed: Iterable[str]) -> tuple[str, ...]:
        ok = {P.norm_path(a) for a in allowed}
        return tuple(c for c in changed if P.norm_path(c) not in ok)

    def golden(self, targeted: TestResult | None, regression: TestResult | None, changed: Iterable[str], allowed: Iterable[str]) -> Evaluation:
        stray = self.unexpected_files(changed, allowed)
        if stray:
            return Evaluation(Verdict.BLOCKED, f"files outside the repair plan were changed: {', '.join(stray[:3])}")
        if targeted is None or not targeted.passed:
            return Evaluation(Verdict.FAILED, "the targeted test did not pass")
        if regression is None:
            return Evaluation(Verdict.FAILED, "no regression run")
        if not regression.passed:
            return Evaluation(Verdict.FAILED, f"the regression run failed ({len(regression.failed_tests)} test(s))")
        return Evaluation(Verdict.SUCCESS, "targeted test and regression passed; only planned files changed")

    def preexisting(self, baseline: TestResult | None, regression: TestResult) -> tuple[int, int]:
        """(failures of the regression run that ALREADY failed in the baseline, all failures of the regression run)."""
        before = set(baseline.failed_tests) if baseline else set()
        return len([t for t in regression.failed_tests if t in before]), len(regression.failed_tests)
