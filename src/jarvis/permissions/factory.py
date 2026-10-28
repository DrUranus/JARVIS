"""Builds the engine from configuration. Restrictive by default; a broken policy file is a startup error
(PolicyError), never silently replaced by something more permissive."""
from __future__ import annotations

from jarvis.config import Settings
from jarvis.permissions.audit import AuditLogger, JsonlAuditSink
from jarvis.permissions.budget import SessionBudget
from jarvis.permissions.confirmation import CliConfirmation, ConfirmationProvider, DenyAllConfirmation
from jarvis.permissions.engine import PermissionEngine, PermissionMode
from jarvis.permissions.levels import PermissionLevel
from jarvis.permissions.paths import PathGuard
from jarvis.permissions.policy import Policy
from jarvis.redaction import SecretDetector


def build_permission_engine(settings: Settings, *, redactor: SecretDetector | None = None,
                            confirmation: ConfirmationProvider | None = None) -> PermissionEngine:
    sec = settings.security
    redactor = redactor or SecretDetector.from_environment(extra=[settings.llm.api_key, settings.voice.api_key])
    roots = settings.effective_fs_roots
    audit_path = settings.effective_audit_path
    # the policy file and the audit log must not be modifiable through the tools they govern
    protected = [audit_path, *([sec.policy_file] if sec.policy_file else [])]
    guard = PathGuard(roots, sec.denied_paths, protected, base_dir=roots[0])
    policy = Policy.from_file(sec.policy_file) if sec.policy_file else Policy()
    if confirmation is None:
        confirmation = DenyAllConfirmation() if sec.confirmation == "deny" else CliConfirmation()
    sinks = [JsonlAuditSink(audit_path)] if sec.audit_enabled else []
    engine = PermissionEngine(
        policy=policy, path_guard=guard, confirmation=confirmation, audit=AuditLogger(sinks, redactor),
        redactor=redactor, mode=PermissionMode(sec.mode), allow_session_grants=sec.allow_session_grants,
        session_ttl=float(sec.session_ttl_seconds), trust_caller_confirmation=False, undeclared_level=PermissionLevel.YELLOW,
        require_protected_tools=True, audit_strict=sec.audit_strict and sec.audit_enabled, audit_green=sec.audit_green,
        budget=SessionBudget(settings.budget.max_tool_calls, settings.budget.max_runtime_seconds) if settings.budget.enabled else None)
    if sec.policy_file:
        engine.note_policy_loaded(sec.policy_file)
    return engine
