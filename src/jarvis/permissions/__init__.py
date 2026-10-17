"""Permissions & security: the layer between JARVIS and every powerful tool.

Independent of Voice, Memory, LLM providers and any concrete tool: tools describe their calls
(PermissionRequest / ActionSpec); the PermissionEngine decides; a ConfirmationProvider asks the user;
an AuditLogger records. Depends only on `jarvis.errors` and the neutral `jarvis.redaction`
(plus `jarvis.config` in factory.py).
"""
from jarvis.permissions.emergency import (ComponentStop, EmergencyStop, ReportStatus, ResetResult, StopOutcome, StopReport,
                                          StopResult)
from jarvis.permissions.audit import (AuditEvent, AuditEventType, AuditLogger, AuditSink, JsonlAuditSink,
                                      LoggingAuditSink, MemoryAuditSink, NullAuditSink)
from jarvis.permissions.confirmation import (CliConfirmation, ConfirmationChoice, ConfirmationProvider,
                                             ConfirmationRequest, DenyAllConfirmation, ScriptedConfirmation)
from jarvis.permissions.decision import DecisionStatus, GrantScope, PermissionDecision
from jarvis.permissions.engine import PermissionEngine, PermissionMode, action_floor
from jarvis.permissions.grants import ExecutionGrant, args_fingerprint, current_grant, verify_execution
from jarvis.permissions.levels import PermissionLevel, is_allowed, max_level
from jarvis.permissions.paths import PathCheck, PathGuard
from jarvis.permissions.policy import Effect, Policy, Rule
from jarvis.permissions.request import ActionSpec, PermissionRequest
from jarvis.permissions.resources import ResourceType

__all__ = [
    "ComponentStop", "EmergencyStop", "ReportStatus", "ResetResult", "StopOutcome", "StopReport", "StopResult",
    "PermissionLevel", "is_allowed", "max_level", "PermissionRequest", "ActionSpec", "ResourceType",
    "PermissionDecision", "DecisionStatus", "GrantScope", "PermissionEngine", "PermissionMode", "action_floor",
    "Policy", "Rule", "Effect", "PathGuard", "PathCheck",
    "ConfirmationProvider", "ConfirmationRequest", "ConfirmationChoice", "CliConfirmation", "DenyAllConfirmation",
    "ScriptedConfirmation", "AuditEvent", "AuditEventType", "AuditLogger", "AuditSink", "JsonlAuditSink",
    "MemoryAuditSink", "NullAuditSink", "LoggingAuditSink", "ExecutionGrant", "args_fingerprint", "current_grant",
    "verify_execution",
]
