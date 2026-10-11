"""Self-Improvement v1 (Phase 15): controlled, reviewable self-modification.

JARVIS may recognise recurring problems from real data (goal engine, repair engine, audit log), propose improvements, prepare a change in an ISOLATED git
branch/worktree, run it through a validation pipeline and hand it to the user. It may never overwrite the active code on its own:

  DETECTED -> PROPOSED -> PREPARED -> TESTED -> READY_FOR_APPROVAL -> APPROVED (by the USER, via ApprovalGate) -> ACTIVATED -> ROLLED_BACK

Security boundaries (permissions, policies, secrets, configuration, wiring and this layer itself) cannot be changed by it: such a change is BLOCKED and
needs a manual review. Everything is OFF by default; the Core does not import this package, `bootstrap` builds it."""
from jarvis.self_improvement.analysis import AnalysisReport, ImprovementAnalyzer, Observation
from jarvis.self_improvement.approval import ApprovalGate
from jarvis.self_improvement.errors import (ApprovalError, ChangeBlocked, ImprovementError, ImprovementStateError, InvalidProposalError, PreparationError,
                                            UnknownProposalError)
from jarvis.self_improvement.llm import LLMImprovementWriter
from jarvis.self_improvement.manager import AnalyzeReport, ImprovementManager
from jarvis.self_improvement.models import Approval, Evidence, Proposal, StageReport
from jarvis.self_improvement.pipeline import PipelineResult, ValidationPipeline
from jarvis.self_improvement.state import ProposalStatus
from jarvis.self_improvement.store import JsonProposalStore, MemoryProposalStore, ProposalStore
from jarvis.self_improvement.workspace import CommandResult, GitWorkspace, SubprocessRunner

__all__ = ["ImprovementManager", "AnalyzeReport", "ImprovementAnalyzer", "AnalysisReport", "Observation", "Proposal", "Evidence", "StageReport", "Approval",
           "ProposalStatus", "ApprovalGate", "ValidationPipeline", "PipelineResult", "GitWorkspace", "SubprocessRunner", "CommandResult", "LLMImprovementWriter",
           "ProposalStore", "MemoryProposalStore", "JsonProposalStore", "ImprovementError", "InvalidProposalError", "ImprovementStateError", "UnknownProposalError",
           "ApprovalError", "ChangeBlocked", "PreparationError"]
