"""Builds the coding-tool steps for baseline/targeted/regression runs and turns the tool's structured answer into a TestResult.
It only describes steps (plain data); the Coding Agent runs them through the permission-checked tool."""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from jarvis.self_repair import policy as P
from jarvis.self_repair.errors import InvalidRepairError
from jarvis.self_repair.models import ErrorCategory, TestResult


def start_steps(workspace: str) -> list[dict[str, Any]]:
    return [{"action": "start", "workspace": workspace}, {"action": "info"}]


def test_step(runner: str | None, args: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    step: dict[str, Any] = {"action": "test"}
    if runner:
        step["runner"] = runner
    if args:
        step["args"] = " ".join(args)
    return step


test_step.__test__ = False  # type: ignore[attr-defined]


def last_step(output: Any, action: str) -> Mapping[str, Any] | None:
    steps = output.get("steps") if isinstance(output, Mapping) else None
    for st in reversed(steps if isinstance(steps, list) else []):
        if isinstance(st, Mapping) and st.get("action") == action:
            return st
    return None


def parse_test_result(output: Any, redact: Callable[[str], str] = lambda s: s) -> TestResult | None:
    """The TestResult of the last `test` step of an agent task, or None when there is none (the step never ran)."""
    st = last_step(output, "test")
    if st is None or st.get("ok") is not True or not isinstance(st.get("output"), Mapping):
        return None
    out = st["output"]
    failed = out.get("failures")
    failed = tuple(str(f) for f in failed) if isinstance(failed, list) else ()
    code = out.get("exit_code")
    passed = out.get("passed") is True and not out.get("timed_out") and not out.get("aborted")
    try:
        return TestResult(passed, redact(str(out.get("summary") or "")), code if isinstance(code, int) and not isinstance(code, bool) else None, failed,
                          ErrorCategory.NONE if passed else ErrorCategory.UNKNOWN, redact(str(out.get("stdout") or "")), redact(str(out.get("stderr") or "")),
                          float(out.get("duration") or 0.0), bool(out.get("timed_out")))
    except (InvalidRepairError, TypeError, ValueError):
        return None


def changed_paths(output: Any) -> tuple[str, ...] | None:
    """File paths of the session's `changes` list ('path: modify +1/-1'), or None when the step did not run."""
    st = last_step(output, "changes")
    if st is None or st.get("ok") is not True or not isinstance(st.get("output"), Mapping):
        return None
    items = st["output"].get("changes")
    if not isinstance(items, list):
        return None
    return tuple(re.split(r": (?:create|modify|delete|add|replace|overwrite|\w+) \+", str(i), maxsplit=1)[0].replace("\\", "/") for i in items)


def change_summaries(output: Any) -> tuple[str, ...] | None:
    st = last_step(output, "changes")
    if st is None or st.get("ok") is not True or not isinstance(st.get("output"), Mapping):
        return None
    items = st["output"].get("changes")
    return tuple(str(i) for i in items) if isinstance(items, list) else None
