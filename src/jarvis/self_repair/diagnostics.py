"""DiagnosisEngine: deterministic classification of a failed test run. It names a category only when the output PROVES it; otherwise UNKNOWN.
No LLM, no guessing - and it never claims to know a cause it cannot show."""
from __future__ import annotations

import re

from jarvis.self_repair import policy as P
from jarvis.self_repair.models import Diagnosis, ErrorCategory, TestResult

_C = ErrorCategory
_RULES: tuple[tuple[ErrorCategory, re.Pattern[str], str], ...] = (
    (_C.ENVIRONMENT_ERROR, re.compile(r"No module named '?(pytest|_pytest)\b|PermissionError|Permission denied|command not found|RUNNER_UNAVAILABLE|runner is unavailable|"
                                      r"could not be started", re.I), "the test environment itself is broken"),
    (_C.SYNTAX_ERROR, re.compile(r"\b(SyntaxError|IndentationError|TabError)\b"), "a Python syntax error"),
    (_C.IMPORT_ERROR, re.compile(r"\b(ModuleNotFoundError|ImportError)\b|cannot import name"), "a module or name cannot be imported"),
    (_C.MISSING_FILE, re.compile(r"FileNotFoundError|No such file or directory|file or directory not found|ERROR: not found", re.I), "a file the code needs is missing"),
    (_C.ASSERTION_FAILURE, re.compile(r"\bAssertionError\b|^E\s+assert\b|^\s*assert .+", re.M), "an assertion failed"),
)
_FILE_REF = re.compile(r"(?:^|[\s\"'(])((?:[\w.\-]+[/\\])*[\w.\-]+\.py)[:\", ]")
_PREFIX = re.compile(r"^(?:[A-Za-z]:)?[/\\].*?[/\\](?=(?:src|tests?|lib|app|[\w\-]+)[/\\])")


class DiagnosisEngine:
    def diagnose(self, result: TestResult) -> Diagnosis:
        if result.passed:
            return Diagnosis(_C.NONE, "the tests pass", (), (), False)
        text = result.stdout_summary + "\n" + result.stderr_summary
        files = tuple(dict.fromkeys(self._files(text)))
        if result.timed_out:
            return Diagnosis(_C.TIMEOUT, "the test run did not finish in time", result.failed_tests, files, False, "timed_out")
        for cat, rx, what in _RULES:
            m = rx.search(text)
            if m:
                repairable = cat not in (_C.ENVIRONMENT_ERROR,)
                return Diagnosis(cat, f"{what} ({len(result.failed_tests)} failed test(s))", result.failed_tests, files, repairable, P.clip(m.group(0), 120))
        if result.failed_tests:
            return Diagnosis(_C.TEST_FAILURE, f"{len(result.failed_tests)} test(s) failed; the output names no more specific cause",
                             result.failed_tests, files, True, result.failed_tests[0])
        return Diagnosis(_C.UNKNOWN, "the run failed but the output does not show why", (), files, False, "")

    @staticmethod
    def _files(text: str) -> list[str]:
        out = []
        for m in _FILE_REF.finditer(text):
            f = m.group(1).replace("\\", "/")
            if P.split_path(f) is not None and "site-packages" not in f:
                out.append(f)
        return out[:10]
