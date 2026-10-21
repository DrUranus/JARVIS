"""Goal Engine v1: the user states a goal; JARVIS makes a short, validated sequence of steps, lets the EXISTING agents do them through the
AgentOrchestrator, evaluates the results and ends the goal SUCCEEDED / FAILED / BLOCKED / CANCELLED / TIMEOUT - within hard limits.

Chain: Core -> GoalEngine -> GoalPlanner/AgentPlanner -> AgentOrchestrator -> Agent -> ToolGateway -> ToolRegistry -> PermissionEngine -> ...
This layer adds no capability and no permission; it never touches tools, providers or the operating system. The Core does not import it;
`bootstrap` builds it (opt-in)."""
from jarvis.goals.context import GoalContext, check_user_context
from jarvis.goals.engine import GoalCancelReport, GoalEngine
from jarvis.goals.errors import (GoalError, GoalStateError, InvalidGoalError, InvalidPlanError, PlanningError, UnknownGoalError)
from jarvis.goals.evaluator import Decision, GoalDecision, GoalEvaluator, StepVerdict, Verdict
from jarvis.goals.models import Goal, GoalResult, GoalStep, GoalStepResult
from jarvis.goals.planner import GoalPlanner
from jarvis.goals.state import GoalStatus, StepStatus
from jarvis.goals.validation import validate_plan

__all__ = ["Goal", "GoalStep", "GoalStepResult", "GoalResult", "GoalStatus", "StepStatus", "GoalContext", "check_user_context", "GoalEngine",
           "GoalCancelReport", "GoalPlanner", "GoalEvaluator", "GoalDecision", "Decision", "StepVerdict", "Verdict", "validate_plan",
           "GoalError", "GoalStateError", "InvalidGoalError", "InvalidPlanError", "PlanningError", "UnknownGoalError"]
