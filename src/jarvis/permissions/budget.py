"""Session budget (Phase 14, sub-goal 4): one cap on tool calls and on run time for the whole process, across all goals and agents.

The budget belongs to the permission engine, the single control point; it is checked in `PermissionEngine._evaluate` right after the emergency stop and
booked only when a call is approved. It has no reset and no way to raise a limit: a restart of the process starts a new session. Exhaustion only refuses
further actions; nothing running is cancelled (that is what the emergency stop is for).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class BudgetUsage:
    calls: int
    max_calls: int
    elapsed: float          # seconds since the first booked action; 0.0 before it
    max_seconds: float
    started: bool
    exhausted: str | None   # why the next action would be refused, else None


class SessionBudget:
    def __init__(self, max_tool_calls: int, max_runtime_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        if max_tool_calls < 1 or max_runtime_seconds <= 0:
            raise ValueError("session budget limits must be positive")
        self._max_calls, self._max_seconds, self._clock = int(max_tool_calls), float(max_runtime_seconds), clock
        self._lock = threading.Lock()          # guards the fields below; held only for field access
        self._calls = 0
        self._start: float | None = None       # the clock at the first booked action
        self._reported = False

    max_tool_calls = property(lambda self: self._max_calls)
    max_runtime_seconds = property(lambda self: self._max_seconds)

    # -- all callers hold self._lock ----------------------------------------------------------------------------
    def _elapsed(self) -> float:
        return 0.0 if self._start is None else max(0.0, self._clock() - self._start)

    def _time_reason(self) -> str | None:
        if self._start is not None and self._elapsed() >= self._max_seconds:
            return f"Laufzeit {self._elapsed():.0f}/{self._max_seconds:g} s"
        return None

    def _refusal(self) -> str | None:
        time_reason = self._time_reason()
        if self._calls >= self._max_calls:
            reason = f"Tool-Aufrufe {self._calls}/{self._max_calls}"
            reason += f", {time_reason}" if time_reason else ""
        elif time_reason:
            reason = f"{time_reason}, Tool-Aufrufe {self._calls}/{self._max_calls}"
        else:
            return None
        return f"Sitzungsbudget erschöpft ({reason}); weitere Aktionen sind erst nach einem Neustart möglich"

    # -- public --------------------------------------------------------------------------------------------------
    def refusal(self) -> str | None:
        """Why the next action would be refused, or None. Books nothing."""
        with self._lock:
            return self._refusal()

    def try_book(self) -> str | None:
        """Atomically book one tool call: None when booked, else the refusal (nothing booked). Only the permission engine calls this."""
        with self._lock:
            reason = self._refusal()
            if reason is not None:
                return reason
            if self._start is None:
                self._start = self._clock()
            self._calls += 1
            return None

    def overrun(self) -> str | None:
        """For an already booked call about to run: the refusal only if the time ran out meanwhile (the count was booked, so it cannot be 'too many')."""
        with self._lock:
            return self._refusal() if self._time_reason() else None

    def claim_report(self) -> bool:
        """True exactly once, when the budget is exhausted: the caller writes the one audit event."""
        with self._lock:
            if self._reported or self._refusal() is None:
                return False
            self._reported = True
            return True

    def usage(self) -> BudgetUsage:
        with self._lock:
            return BudgetUsage(self._calls, self._max_calls, self._elapsed(), self._max_seconds, self._start is not None, self._refusal())

    def summary(self) -> str:
        u = self.usage()
        state = f"ERSCHÖPFT: {u.exhausted}" if u.exhausted else "aktiv"
        return f"Sitzungsbudget {state}\n  Tool-Aufrufe: {u.calls}/{u.max_calls}\n  Laufzeit: {u.elapsed:.0f}/{u.max_seconds:g} s" + ("" if u.started else " (beginnt mit der ersten Aktion)")
