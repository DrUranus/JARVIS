"""V2.1 M7 as a quality GATE (adapter around `quality.engine.evaluate`, imports nothing else). OFF by default (agents.quality_gate); the orchestrator only holds the object and asks it.

For an agent the gate is switched on for, a SUCCEEDED result counts only if it carries structured evidence (`output["quality_report"]`) that the engine ACCEPTS. The agent's own
statement decides nothing: the status given to the engine is the real outcome status, anything the report claims about itself (status, accepted, verdict ...) is ignored. No report,
an unreadable one or a failing engine/source = not accepted (fail closed). The decision carries codes only - never statements, values or file contents."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from jarvis.quality.engine import evaluate

log = logging.getLogger("jarvis.quality")


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    code: str                          # quality_accepted | quality_rejected | quality_unverified | quality_unavailable
    failed: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    self_reported: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "code": self.code, "failed": list(self.failed), "unknown": list(self.unknown), "self_reported": self.self_reported}


class QualityGate:
    def __init__(self, agents: Iterable[str], *, calculators: Mapping[str, Callable[[Any], Any]] | None = None, file_exists: Callable[[str], bool] | None = None,
                 audit_events: Callable[[], Sequence[Any]] | None = None) -> None:
        self._agents = frozenset(agents)
        self._calculators, self._file_exists, self._audit = calculators, file_exists, audit_events

    @property
    def agents(self) -> frozenset[str]:
        return self._agents

    def applies(self, agent_id: str | None) -> bool:
        return agent_id in self._agents

    def check(self, agent_id: str | None, status: str, output: Any) -> GateDecision:
        report = output.get("quality_report") if isinstance(output, Mapping) else None
        if not isinstance(report, Mapping):
            return GateDecision(False, "quality_unverified", unknown=("no_quality_report",), self_reported=status)
        try:
            events = tuple(self._audit()) if self._audit is not None else ()
            verdict = evaluate({**report, "status": status}, file_exists=self._file_exists, audit_events=events, calculators=self._calculators)
        except Exception:  # noqa: BLE001 - a failing engine or source never means "accepted"; internals stay in the log
            log.warning("quality gate failed for agent %s", str(agent_id)[:40], exc_info=True)
            return GateDecision(False, "quality_unavailable", unknown=("gate_error",), self_reported=status)
        if verdict.accepted:
            return GateDecision(True, "quality_accepted", self_reported=verdict.self_reported)
        return GateDecision(False, "quality_rejected" if verdict.failed else "quality_unverified", verdict.failed, verdict.unknown, verdict.self_reported)
