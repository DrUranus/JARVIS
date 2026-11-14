"""V2.1 M7 as a quality GATE (adapter around `quality.engine.evaluate`, imports nothing else). OFF by default (agents.quality_gate); the orchestrator only holds the object and asks it.

For an agent the gate is switched on for, a SUCCEEDED result counts only if it carries structured evidence (`output["quality_report"]`) that the engine ACCEPTS. The agent's own
statement decides nothing: the status given to the engine is the real outcome status, anything the report claims about itself (status, accepted, verdict ...) is ignored. No report,
an unreadable one or a failing engine/source = not accepted (fail closed). The decision carries codes only - never statements, values or file contents."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from jarvis.quality.engine import evaluate
from jarvis.quality.reports import TYPED_AGENTS, build_report

log = logging.getLogger("jarvis.quality")


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    code: str                          # quality_accepted | quality_rejected | quality_unverified | quality_unavailable | quality_audit_unavailable | quality_audit_inconsistent
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

    def check(self, agent_id: str | None, status: str, output: Any, context: Mapping[str, Any] | None = None) -> GateDecision:
        """`context` = {"task_id", "parents": [{"task_id", "agent_id", "status", "output"}]} from the orchestrator's own records (independent of the agent)."""
        typed = agent_id in TYPED_AGENTS
        try:
            report = build_report(agent_id, output, context) if typed else (output.get("quality_report") if isinstance(output, Mapping) else None)
            if not isinstance(report, Mapping):
                return GateDecision(False, "quality_unverified", unknown=("no_quality_report",), self_reported=status)
            events: tuple[Any, ...] = ()
            if typed or self._audit is not None:
                found = self._read_audit()
                if isinstance(found, GateDecision):
                    return GateDecision(found.accepted, found.code, found.failed, found.unknown, status)
                events = found
            doc = {**report, "status": status}
            task_id = context.get("task_id") if isinstance(context, Mapping) else None
            if typed and isinstance(task_id, str) and any(e.get("type") == "budget_exhausted" and isinstance(e.get("extra"), Mapping) and e["extra"].get("task_id") == task_id for e in events):
                doc["budgets"] = [{"name": "agent_budget", "limit": 1, "used": 2, "binding": True}]      # the audit records that THIS task used its budget up
            verdict = evaluate(doc, file_exists=self._file_exists, audit_events=events, calculators=self._calculators)
        except Exception:  # noqa: BLE001 - a failing engine or source never means "accepted"; internals stay in the log
            log.warning("quality gate failed for agent %s", str(agent_id)[:40], exc_info=True)
            return GateDecision(False, "quality_unavailable", unknown=("gate_error",), self_reported=status)
        if verdict.accepted:
            return GateDecision(True, "quality_accepted", self_reported=verdict.self_reported)
        return GateDecision(False, "quality_rejected" if verdict.failed else "quality_unverified", verdict.failed, verdict.unknown, verdict.self_reported)

    def _read_audit(self) -> "tuple[dict[str, Any], ...] | GateDecision":
        """The audit events, or a closed decision: no source / unreadable source = unavailable; malformed or contradicting data = inconsistent."""
        if self._audit is None:
            return GateDecision(False, "quality_audit_unavailable", unknown=("no_audit_source",))
        try:
            raw = self._audit()
        except Exception:  # noqa: BLE001 - internals stay in the log
            log.warning("quality gate: the audit source failed", exc_info=True)
            return GateDecision(False, "quality_audit_unavailable", unknown=("audit_unreadable",))
        if not isinstance(raw, (list, tuple)) or not all(isinstance(e, dict) for e in raw):
            return GateDecision(False, "quality_audit_inconsistent", unknown=("audit_malformed",))
        if not raw:                                                 # a working audit always holds events (every tool registration is logged): none = not readable / not running
            return GateDecision(False, "quality_audit_unavailable", unknown=("audit_empty",))
        if any(e.get("type") == "unreadable_line" for e in raw):    # the JSONL tail marks a damaged line this way: the log cannot be trusted as evidence
            return GateDecision(False, "quality_audit_inconsistent", unknown=("audit_line_unreadable",))
        accepted: dict[str, int] = {}
        rejected: set[str] = set()
        for e in raw:
            if e.get("type") in ("confirmation_accepted", "confirmation_rejected"):
                rid = e.get("request_id")
                if not isinstance(rid, str) or not rid:
                    return GateDecision(False, "quality_audit_inconsistent", unknown=("confirmation_without_request_id",))
                if e["type"] == "confirmation_accepted":
                    accepted[rid] = accepted.get(rid, 0) + 1
                else:
                    rejected.add(rid)
        if any(n > 1 for n in accepted.values()) or set(accepted) & rejected:
            return GateDecision(False, "quality_audit_inconsistent", unknown=("contradicting_confirmations",))
        return tuple(raw)
