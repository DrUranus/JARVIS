"""Fehlerbehandlung der Agenten (agent-error-recovery): Fehler klassifizieren und eine Aufgabe hoechstens MAX_ATTEMPTS-mal ausfuehren.

Grundsaetze:
- Fail closed: nur ausdruecklich als wiederholbar gefuehrte Codes (timeout, backend_error, rate_limited, target_changed) werden wiederholt; alles andere
  (Berechtigungsablehnung, blockiertes Ziel, Notaus/failsafe, Abbruch, erschoepftes Budget, unbekannte Codes) nie.
- `target_changed` wird nur wiederholt, wenn der Aufrufer eine neu geplante Aufgabe liefert (`replan`); sonst Rueckfall auf das vorhandene
  begrenzte Replanning der Goal Engine (`fall_back_to_replanning`). Diese Grenzen (goals.policy) werden hier weder erweitert noch ersetzt.
- Notaus und Abbruch werden vor JEDEM Versuch geprueft; schlaegt die Pruefung selbst fehl, gilt das als Notaus.
- Die Aufgaben laufen weiter ueber den AgentOrchestrator (ToolRegistry -> PermissionEngine); dieses Modul fuehrt selbst nichts aus, startet nichts von
  allein und wird nur von Aufrufern benutzt, die es ausdruecklich verdrahten.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from jarvis.agents.models import AgentTask
from jarvis.agents.result import AgentResult
from jarvis.agents.state import TaskStatus

log = logging.getLogger("jarvis.agents.recovery")

MAX_ATTEMPTS = 3          # Obergrenze je Aufgabe inkl. erstem Versuch; nicht konfigurierbar hoeher

RETRY_CODES = frozenset({"timeout", "backend_error", "rate_limited"})
REPLAN_CODES = frozenset({"target_changed"})
NEVER_CODES = {
    "not_authorized": "Berechtigung abgelehnt", "permission_denied": "Berechtigung abgelehnt", "tool_access_denied": "Werkzeugzugriff nicht erlaubt",
    "blocked_target": "Ziel blockiert", "failsafe": "Notaus/Failsafe", "halted": "Notaus aktiv", "cancelled": "abgebrochen",
    "budget_exhausted": "Budget erschoepft",
}


class FailureKind(Enum):
    RETRY = "retry"                  # gleiche Aufgabe erneut
    RETRY_REPLAN = "retry_replan"    # nur mit neu geplanter Aufgabe erneut
    FATAL = "fatal"                  # nie wiederholen


@dataclass(frozen=True)
class Classification:
    kind: FailureKind
    code: str
    reason: str


def classify(status: TaskStatus, code: str | None) -> Classification:
    c = code or "unknown"
    if status in (TaskStatus.CANCELLED, TaskStatus.BLOCKED):
        return Classification(FailureKind.FATAL, c, "abgebrochen" if status is TaskStatus.CANCELLED else "blockiert")
    if status is not TaskStatus.FAILED:
        return Classification(FailureKind.FATAL, c, "kein Fehler")
    if c in NEVER_CODES:
        return Classification(FailureKind.FATAL, c, NEVER_CODES[c])
    if c in RETRY_CODES:
        return Classification(FailureKind.RETRY, c, c)
    if c in REPLAN_CODES:
        return Classification(FailureKind.RETRY_REPLAN, c, "Ziel hat sich geaendert")
    return Classification(FailureKind.FATAL, c, "Fehlerart nicht wiederholbar")


@dataclass(frozen=True)
class RecoveryOutcome:
    result: AgentResult
    attempts: int                    # tatsaechlich gestartete Versuche
    exhausted: bool                  # wiederholbarer Fehler, alle MAX_ATTEMPTS verbraucht
    fall_back_to_replanning: bool    # die Goal Engine darf (mit ihren eigenen Grenzen) neu planen
    reasons: tuple[str, ...] = ()


class RecoveryRunner:
    def __init__(self, orchestrator: Any, *, max_attempts: int = MAX_ATTEMPTS, halted: Callable[[], bool] | None = None,
                 cancelled: Callable[[], bool] | None = None, replan: Callable[[AgentTask, AgentResult, int], AgentTask | None] | None = None,
                 emit: Callable[[str, dict[str, Any]], Any] | None = None) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= MAX_ATTEMPTS:
            raise ValueError(f"max_attempts must be within 1..{MAX_ATTEMPTS}")
        self._orch, self._max = orchestrator, max_attempts
        self._halted, self._cancelled, self._replan, self._emit = halted, cancelled, replan, emit

    # ---- helpers -------------------------------------------------------------------------------------------------------------------------
    def _stop_reason(self) -> str | None:
        for fn, code in ((self._halted, "halted"), (self._cancelled, "cancelled")):
            if fn is None:
                continue
            try:
                if fn():
                    return code
            except Exception:  # noqa: BLE001 - fail closed
                return code
        return None

    def _update(self, task_id: str, status: str, detail: str) -> None:
        if self._emit is None:
            return
        try:
            self._emit("task_update", {"kind": "agent_task", "id": task_id, "status": status, "detail": detail[:200]})
        except Exception as exc:  # noqa: BLE001 - Ereignisse sind informativ
            log.warning("task_update failed (%s)", type(exc).__name__)

    @staticmethod
    def _stopped(task: AgentTask, code: str) -> AgentResult:
        status = TaskStatus.CANCELLED if code == "cancelled" else TaskStatus.BLOCKED
        return AgentResult(task.task_id, task.agent_id, status, error=code, error_code=code)

    # ---- run -----------------------------------------------------------------------------------------------------------------------------
    def run(self, task: AgentTask, timeout: float | None = None) -> RecoveryOutcome:
        base = task.task_id
        current, attempts, reasons = task, 0, []
        stop = self._stop_reason()
        if stop:
            self._update(base, "BLOCKED", f"nicht gestartet: {stop}")
            return RecoveryOutcome(self._stopped(task, stop), 0, False, False, (stop,))
        while True:
            attempts += 1
            result = self._orch.run(current, timeout)
            if result.succeeded:
                return RecoveryOutcome(result, attempts, False, False, tuple(reasons))
            c = classify(result.status, result.error_code)
            if c.kind is FailureKind.FATAL:
                return RecoveryOutcome(result, attempts, False, False, tuple(reasons))
            if attempts >= self._max:
                self._update(base, "FAILED", f"{c.code}: {attempts} Versuche ausgeschoepft, Rueckfall auf Replanning")
                return RecoveryOutcome(result, attempts, True, True, tuple(reasons))
            stop = self._stop_reason()
            if stop:
                self._update(base, "FAILED", f"keine Wiederholung: {stop}")
                return RecoveryOutcome(result, attempts, False, False, tuple(reasons))
            nxt = current
            if c.kind is FailureKind.RETRY_REPLAN:
                try:
                    nxt = self._replan(current, result, attempts + 1) if self._replan else None
                except Exception as exc:  # noqa: BLE001
                    log.warning("recovery replan failed (%s)", type(exc).__name__)
                    nxt = None
                if nxt is None:
                    self._update(base, "FAILED", f"{c.code}: keine neue Planung, Rueckfall auf Replanning")
                    return RecoveryOutcome(result, attempts, False, True, tuple(reasons))
            reasons.append(c.code)
            self._update(base, "RETRYING", f"Wiederholung {attempts + 1}/{self._max}: {c.code}")
            current = dataclasses.replace(nxt, task_id=f"{base[:56]}-r{attempts + 1}")
