"""Shared helpers for the security tests."""
from __future__ import annotations

from pathlib import Path

from jarvis.permissions import (AuditLogger, MemoryAuditSink, PathGuard, PermissionEngine, PermissionLevel,
                                PermissionRequest, Policy, ResourceType)
from jarvis.redaction import SecretDetector

G, Y, R = PermissionLevel.GREEN, PermissionLevel.YELLOW, PermissionLevel.RED


def make_engine(tmp_path: Path, *, rules=(), confirmation=None, redactor=None, denied=(), protected=(), **kw):
    """Strict engine with a temporary workspace `tmp_path/ws` as the only allowed root."""
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    sink = MemoryAuditSink()
    red = redactor or SecretDetector()
    engine = PermissionEngine(
        policy=Policy.from_rules(rules), path_guard=PathGuard([ws], denied, protected, base_dir=ws),
        confirmation=confirmation, audit=AuditLogger([sink], red), redactor=red, **kw)
    return engine, sink, ws


def req(tool="t", action="read", level=G, **kw) -> PermissionRequest:
    return PermissionRequest(tool=tool, action=action, level=level, **kw)


def path_req(path, action="write", level=Y, tool="filesystem", **kw) -> PermissionRequest:
    return PermissionRequest(tool=tool, action=action, level=level, resource=str(path),
                             resource_type=ResourceType.PATH, **kw)


def types(sink):
    return [e.type.value for e in sink.events]
