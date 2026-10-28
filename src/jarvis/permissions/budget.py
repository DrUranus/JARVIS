"""Session budget (Phase 14, sub-goal 4): a total cap on tool calls and run time for the whole process, over all goals and agents.

Owned by the PermissionEngine (the one control point). There is deliberately no way to reset or raise it while the process runs, and it is not a tool:
no tool, agent or goal code may reference it (structure test). Exhaustion only denies further actions; nothing is cancelled automatically. The run time starts
with the first booked action. Booking is atomic, so concurrent callers can never book more than the limit."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


class SessionBudget:
    __slots__ = ("_max_calls", "_max_seconds", "_clock", "_lock", "_calls", "_started", "_reported")

    def __init__(self, max_calls: int, max_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        if int(max_calls) < 1 or float(max_seconds) <= 0:
            raise ValueError("budget limits must be positive")
        self._max_calls, self._max_seconds, self._clock = int(max_calls), float(max_seconds), clock
        self._lock = threading.Lock()
        self._calls = 0
        self._started: float | None = None
        self._reported = False

    max_calls = property(lambda self: self._max_calls)
    max_seconds = property(lambda self: self._max_seconds)

    def _elapsed(self) -> float:
        return 0.0 if self._started is None else self._clock() - self._started

    def _time_denial(self) -> str | None:
        used = self._elapsed()
        if self._started is not None and used >= self._max_seconds:
            return f"session budget exhausted: run time {used:.0f}s/{self._max_seconds:.0f}s"
        return None

    def _denial(self) -> str | None:
        if self._calls >= self._max_calls:
            return f"session budget exhausted: tool calls {self._calls}/{self._max_calls}"
        return self._time_denial()

    def denial(self) -> str | None:
        """Why a NEW action would be refused now, or None. Books nothing."""
        with self._lock:
            return self._denial()

    def time_denial(self) -> str | None:
        """Only the run-time part (for an already booked call that is about to execute). Books nothing."""
        with self._lock:
            return self._time_denial()

    def book(self) -> str | None:
        """Book one tool call atomically. Returns the refusal reason (nothing is consumed) or None when booked."""
        with self._lock:
            why = self._denial()
            if why:
                return why
            if self._started is None:
                self._started = self._clock()
            self._calls += 1
            return None

    def take_exhaustion_notice(self) -> bool:
        """True exactly once, when the budget is exhausted (for a single audit entry)."""
        with self._lock:
            if self._reported or self._denial() is None:
                return False
            self._reported = True
            return True

    def usage(self) -> dict[str, Any]:
        with self._lock:
            return {"calls": self._calls, "max_calls": self._max_calls, "elapsed_seconds": round(self._elapsed(), 1),
                    "max_seconds": self._max_seconds, "exhausted": self._denial() is not None}
