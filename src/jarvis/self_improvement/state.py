"""Lifecycle of an improvement proposal.

  DETECTED -> PROPOSED -> PREPARED -> TESTED -> READY_FOR_APPROVAL -> APPROVED -> ACTIVATED -> ROLLED_BACK

FAILED (preparation or tests failed; the proposal can be retried with new edits), REJECTED (user said no) and BLOCKED (a security boundary would be
touched: manual review) are the side exits. ACTIVATED can only be left by a rollback. There is deliberately no transition that skips a stage."""
from __future__ import annotations

from enum import Enum

from jarvis.self_improvement.errors import ImprovementStateError


class ProposalStatus(str, Enum):
    DETECTED = "DETECTED"                        # 1. problem recognised (evidence recorded)
    PROPOSED = "PROPOSED"                        # 2. improvement proposed
    PREPARED = "PREPARED"                        # 3. change prepared in an isolated branch / working copy
    TESTED = "TESTED"                            # 4. change tested (every required stage executed AND passed)
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"    # 5. waiting for the user
    APPROVED = "APPROVED"                        # 6. explicitly approved by the user
    ACTIVATED = "ACTIVATED"                      # 7. merged into the active branch (after approval) ...
    ROLLED_BACK = "ROLLED_BACK"                  #    ... or reverted again
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


_S = ProposalStatus
TERMINAL = frozenset({_S.ROLLED_BACK, _S.REJECTED, _S.BLOCKED})
TRANSITIONS: dict[ProposalStatus, frozenset[ProposalStatus]] = {
    _S.DETECTED: frozenset({_S.PROPOSED, _S.REJECTED, _S.BLOCKED}),
    _S.PROPOSED: frozenset({_S.PREPARED, _S.FAILED, _S.REJECTED, _S.BLOCKED}),
    _S.PREPARED: frozenset({_S.TESTED, _S.FAILED, _S.REJECTED, _S.BLOCKED}),
    _S.TESTED: frozenset({_S.READY_FOR_APPROVAL, _S.FAILED, _S.REJECTED, _S.BLOCKED}),
    _S.READY_FOR_APPROVAL: frozenset({_S.APPROVED, _S.FAILED, _S.REJECTED, _S.BLOCKED}),
    _S.APPROVED: frozenset({_S.ACTIVATED, _S.FAILED, _S.REJECTED, _S.BLOCKED}),
    _S.ACTIVATED: frozenset({_S.ROLLED_BACK}),
    _S.FAILED: frozenset({_S.PROPOSED, _S.REJECTED}),
    **{s: frozenset() for s in TERMINAL},
}


def check_transition(old: ProposalStatus, new: ProposalStatus) -> None:
    if new not in TRANSITIONS[old]:
        raise ImprovementStateError(f"illegal transition {old.value} -> {new.value}")
