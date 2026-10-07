"""Self-Testing / Self-Repair v1: run the tests of an explicitly given workspace, recognise a failure, diagnose it deterministically, apply a
LIMITED repair through the existing Coding Agent, re-test (targeted, then regression) and report success only when the golden rule holds:
targeted PASS and regression PASS and only planned files changed.

Chain: Core -> RepairEngine -> DiagnosisEngine/RepairPlanner -> AgentPlanner -> AgentOrchestrator -> Coding Agent -> ToolGateway -> ToolRegistry ->
PermissionEngine -> CodingController. This layer touches no file, runs no command and decides no permission; it is no self-modification: it
repairs only inside the workspace the user names, never JARVIS itself. The Core does not import it; `bootstrap` builds it (opt-in)."""
from jarvis.self_repair.context import RepairContext, check_context
from jarvis.self_repair.diagnostics import DiagnosisEngine
from jarvis.self_repair.engine import RepairCancelReport, RepairEngine
from jarvis.self_repair.errors import InvalidRepairError, PlanBlocked, RepairError, RepairStateError, UnknownRepairError
from jarvis.self_repair.evaluator import Evaluation, RepairEvaluator, Verdict
from jarvis.self_repair.models import (Diagnosis, ErrorCategory, RepairAttempt, RepairPlan, RepairResult, RepairRun, TestResult)
from jarvis.self_repair.planner import RepairPlanner, SuppliedProposer
from jarvis.self_repair.state import AttemptStatus, RepairStatus

__all__ = ["RepairRun", "RepairAttempt", "RepairPlan", "RepairResult", "TestResult", "Diagnosis", "ErrorCategory", "RepairStatus", "AttemptStatus",
           "RepairContext", "check_context", "RepairEngine", "RepairCancelReport", "DiagnosisEngine", "RepairPlanner", "SuppliedProposer",
           "RepairEvaluator", "Evaluation", "Verdict", "RepairError", "InvalidRepairError", "PlanBlocked", "RepairStateError", "UnknownRepairError"]
