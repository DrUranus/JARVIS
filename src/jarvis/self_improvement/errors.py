"""Errors of the self-improvement layer. Runtime conditions (a change fails its tests, a path is refused) are states of a proposal; these
exceptions are for programmer errors and for operations that are refused (unknown proposal, wrong state, missing approval)."""
from __future__ import annotations

from jarvis.errors import JarvisError


class ImprovementError(JarvisError):
    """Base class of the self-improvement layer."""


class InvalidProposalError(ImprovementError):
    """A proposal, edit or stored record is malformed."""


class ImprovementStateError(ImprovementError):
    """Illegal status transition or an operation that does not fit the proposal's current status."""


class UnknownProposalError(ImprovementError):
    pass


class ApprovalError(ImprovementError):
    """The explicit user approval is missing, was declined or no longer matches the prepared change."""


class ChangeBlocked(ImprovementError):
    """The change touches a security boundary or breaks a rule; it needs a manual review and is never prepared/activated automatically."""


class PreparationError(ImprovementError):
    """The isolated copy could not be prepared (git missing, repository unusable, edit does not apply, timeout, cancelled)."""
