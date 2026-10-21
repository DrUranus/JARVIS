"""Immutable snapshots: Evidence, StageReport, Approval, Transition and Proposal. Everything stored is bounded and plain text; free text never
appears in a repr. Proposals serialise to JSON (to_dict/from_dict) and are validated again when loaded."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from jarvis.self_improvement import policy as P
from jarvis.self_improvement.errors import InvalidProposalError
from jarvis.self_improvement.state import ProposalStatus, check_transition

SOURCES = ("analysis", "llm", "user")


_SHA_OR_EMPTY = re.compile(r"^([0-9a-f]{40})?\Z")
_HEX_OR_EMPTY = re.compile(r"^([0-9a-f]{16,64})?\Z")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_proposal_id() -> str:
    return "imp-" + uuid.uuid4().hex[:12]


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _parse_dt(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        raise InvalidProposalError("bad timestamp") from None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _texts(values: Any, limit: int, each: int) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise InvalidProposalError("expected a list of texts")
    return tuple(P.clean_text(v, each) for v in list(values)[:limit] if isinstance(v, str) and v.strip())


@dataclass(frozen=True)
class Evidence:
    """One observation the proposal rests on. `source` names where the data came from (goal engine, repair engine, audit log); `refs` are the
    ids of the records that were actually counted. `count` is a count of those records - never an estimate."""
    source: str
    description: str = field(repr=False)
    count: int = 1
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise InvalidProposalError("evidence needs a source")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            raise InvalidProposalError("evidence count must be a positive integer")
        object.__setattr__(self, "source", P.clean_text(self.source, 60))
        object.__setattr__(self, "description", P.clean_text(self.description, 400))
        object.__setattr__(self, "refs", tuple(P.clean_text(r, 80) for r in list(self.refs)[:20]))

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "description": self.description, "count": self.count, "refs": list(self.refs)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Evidence":
        return cls(d.get("source", ""), d.get("description", ""), d.get("count", 1), tuple(d.get("refs", ())))


@dataclass(frozen=True)
class StageReport:
    """Result of one validation stage. `executed=False` means it did NOT run - it never counts as passed."""
    name: str
    executed: bool
    passed: bool
    summary: str = field(default="", repr=False)
    duration: float = 0.0
    exit_status: int | None = None
    timed_out: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", P.clip(self.summary, P.MAX_OUTPUT))
        if self.passed and not self.executed:
            raise InvalidProposalError("a stage that did not run cannot have passed")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "executed": self.executed, "passed": self.passed, "summary": self.summary,
                "duration": round(float(self.duration), 3), "exit_status": self.exit_status, "timed_out": self.timed_out}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StageReport":
        return cls(str(d.get("name", "")), bool(d.get("executed")), bool(d.get("passed")), str(d.get("summary", "")),
                   float(d.get("duration", 0.0)), d.get("exit_status"), bool(d.get("timed_out")))


@dataclass(frozen=True)
class Approval:
    """The user's explicit approval, bound to the exact change that was shown: branch head and digest of the diff."""
    at: datetime
    channel: str
    head_commit: str
    diff_digest: str
    view_digest: str = ""            # digest of the exact review text that was shown to the user

    def to_dict(self) -> dict[str, Any]:
        return {"at": _iso(self.at), "channel": self.channel, "head_commit": self.head_commit, "diff_digest": self.diff_digest, "view_digest": self.view_digest}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Approval":
        at = _parse_dt(d.get("at"))
        if at is None:
            raise InvalidProposalError("approval without timestamp")
        return cls(at, P.clip(d.get("channel", ""), 60), str(d.get("head_commit", "")), str(d.get("diff_digest", "")),
                   str(d.get("view_digest", "")))


@dataclass(frozen=True)
class Transition:
    old: ProposalStatus | None
    new: ProposalStatus
    at: datetime
    actor: str                       # analysis | llm | user | system
    note: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"old": self.old.value if self.old else None, "new": self.new.value, "at": _iso(self.at), "actor": self.actor, "note": self.note}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Transition":
        at = _parse_dt(d.get("at"))
        if at is None:
            raise InvalidProposalError("transition without timestamp")
        old = d.get("old")
        return cls(ProposalStatus(old) if old else None, ProposalStatus(d.get("new")), at, P.clip(d.get("actor", ""), 20), P.clip(d.get("note", ""), 300))


@dataclass(frozen=True)
class Proposal:
    title: str
    problem: str = field(repr=False)
    evidence: tuple[Evidence, ...] = ()
    change: str = field(default="", repr=False)                 # the proposed change, in words
    benefit: str = field(default="", repr=False)
    risks: tuple[str, ...] = field(default=(), repr=False)
    affected: tuple[str, ...] = ()                              # files or components, as far as known
    suggested_tests: tuple[str, ...] = ()
    proposal_id: str = field(default_factory=new_proposal_id)
    fingerprint: str = ""
    source: str = "analysis"
    status: ProposalStatus = ProposalStatus.DETECTED
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    history: tuple[Transition, ...] = ()
    # ---- filled by preparation / validation / approval / activation --------------------------------------------------------------------------
    edits: tuple[Mapping[str, str], ...] = field(default=(), repr=False)
    branch: str = ""
    base_commit: str = ""
    head_commit: str = ""
    diff_digest: str = ""
    diff_stat: str = field(default="", repr=False)
    changed_files: tuple[str, ...] = ()
    stages: tuple[StageReport, ...] = ()
    approval: Approval | None = None
    reason: str = field(default="", repr=False)                 # why FAILED / BLOCKED / REJECTED
    tested_manifest: str = ""                                   # sha256 of the file manifest of the exact exported commit that was reviewed/tested
    rev: int = 0                                                # compare-and-swap counter of the store (incremented by every save)

    def __post_init__(self) -> None:
        if not P.ID_RE.match(self.proposal_id):
            raise InvalidProposalError("bad proposal id")
        if isinstance(self.rev, bool) or not isinstance(self.rev, int) or self.rev < 0:
            raise InvalidProposalError("bad revision counter")
        for name, rx in (("base_commit", _SHA_OR_EMPTY), ("head_commit", _SHA_OR_EMPTY), ("diff_digest", _HEX_OR_EMPTY), ("tested_manifest", _HEX_OR_EMPTY)):
            if not rx.match(getattr(self, name)):
                raise InvalidProposalError(f"{name} is not a valid hash")
        if self.branch and self.branch != P.BRANCH_PREFIX + self.proposal_id:
            raise InvalidProposalError("bad branch name")
        if len(self.changed_files) > P.MAX_FILES or any(not isinstance(f, str) or P.refuse_target(f) for f in self.changed_files):
            raise InvalidProposalError("changed file outside the allow-list")
        if not isinstance(self.status, ProposalStatus):
            raise InvalidProposalError("status must be a ProposalStatus")
        if self.source not in SOURCES:
            raise InvalidProposalError(f"source must be one of {SOURCES}")
        if not isinstance(self.title, str) or not self.title.strip() or not isinstance(self.problem, str) or not self.problem.strip():
            raise InvalidProposalError("a proposal needs a title and a problem description")
        if len(self.evidence) > P.MAX_EVIDENCE:
            raise InvalidProposalError("too much evidence")
        if self.source == "analysis" and not self.evidence:
            raise InvalidProposalError("an analysed proposal needs evidence from real data")
        sset = object.__setattr__
        sset(self, "title", P.clean_text(self.title, P.MAX_TITLE))
        sset(self, "problem", P.clean_text(self.problem, P.MAX_TEXT))
        sset(self, "change", P.clean_text(self.change, P.MAX_TEXT))
        sset(self, "benefit", P.clean_text(self.benefit, P.MAX_TEXT))
        sset(self, "risks", tuple(P.clean_text(r, 300) for r in list(self.risks)[:P.MAX_LIST]))
        sset(self, "affected", tuple(P.clean_text(a, 200) for a in list(self.affected)[:P.MAX_FILES]))
        sset(self, "suggested_tests", tuple(self.suggested_tests)[:P.MAX_TESTS])
        for t in self.suggested_tests:
            if not isinstance(t, str) or not P.TEST_ID_RE.match(t) or ".." in t:
                raise InvalidProposalError(f"suggested test refused: {P.clip(t, 60)!r} (expected tests/<file>.py[::name])")
        sset(self, "reason", P.clean_text(self.reason, 500))
        sset(self, "history", tuple(self.history)[-P.MAX_HISTORY:])
        sset(self, "edits", tuple(dict(e) for e in self.edits))

    @property
    def is_terminal(self) -> bool:
        from jarvis.self_improvement.state import TERMINAL
        return self.status in TERMINAL

    @property
    def tests_passed(self) -> bool:
        """True only when stages were really executed and every one of them passed."""
        return bool(self.stages) and all(s.executed and s.passed for s in self.stages)

    def moved(self, new: ProposalStatus, actor: str, note: str = "", **changes: Any) -> "Proposal":
        """The only way a status changes: validated against the lifecycle and recorded in the history."""
        check_transition(self.status, new)
        now = utcnow()
        tr = Transition(self.status, new, now, actor, P.clip(note, 300))
        return replace(self, status=new, updated_at=now, history=(*self.history, tr)[-P.MAX_HISTORY:], **changes)

    def evolve(self, **changes: Any) -> "Proposal":
        return replace(self, updated_at=utcnow(), **changes)

    def to_dict(self, *, with_edits: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "proposal_id": self.proposal_id, "fingerprint": self.fingerprint, "title": self.title, "problem": self.problem,
            "evidence": [e.to_dict() for e in self.evidence], "change": self.change, "benefit": self.benefit, "risks": list(self.risks),
            "affected": list(self.affected), "suggested_tests": list(self.suggested_tests), "source": self.source, "status": self.status.value,
            "created_at": _iso(self.created_at), "updated_at": _iso(self.updated_at), "history": [t.to_dict() for t in self.history],
            "branch": self.branch, "base_commit": self.base_commit, "head_commit": self.head_commit, "diff_digest": self.diff_digest,
            "diff_stat": self.diff_stat, "changed_files": list(self.changed_files), "stages": [s.to_dict() for s in self.stages],
            "approval": self.approval.to_dict() if self.approval else None, "reason": self.reason, "edit_count": len(self.edits),
            "tested_manifest": self.tested_manifest, "rev": self.rev}
        if with_edits:
            d["edits"] = [dict(e) for e in self.edits]
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Proposal":
        try:
            return cls(
                title=d["title"], problem=d["problem"], evidence=tuple(Evidence.from_dict(e) for e in d.get("evidence", ())), change=d.get("change", ""),
                benefit=d.get("benefit", ""), risks=_texts(d.get("risks", ()), P.MAX_LIST, 300), affected=_texts(d.get("affected", ()), P.MAX_FILES, 200),
                suggested_tests=tuple(d.get("suggested_tests", ())), proposal_id=d["proposal_id"], fingerprint=str(d.get("fingerprint", "")),
                source=d.get("source", "analysis"), status=ProposalStatus(d["status"]), created_at=_parse_dt(d["created_at"]) or utcnow(),
                updated_at=_parse_dt(d["updated_at"]) or utcnow(), history=tuple(Transition.from_dict(t) for t in d.get("history", ())),
                edits=tuple(dict(e) for e in d.get("edits", ())), branch=str(d.get("branch", "")), base_commit=str(d.get("base_commit", "")),
                head_commit=str(d.get("head_commit", "")), diff_digest=str(d.get("diff_digest", "")), diff_stat=str(d.get("diff_stat", "")),
                changed_files=tuple(str(f) for f in d.get("changed_files", ())), stages=tuple(StageReport.from_dict(s) for s in d.get("stages", ())),
                approval=Approval.from_dict(d["approval"]) if d.get("approval") else None, reason=str(d.get("reason", "")),
                tested_manifest=str(d.get("tested_manifest", "")), rev=int(d.get("rev", 0)))
        except InvalidProposalError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise InvalidProposalError(f"stored proposal is malformed ({type(exc).__name__})") from None
