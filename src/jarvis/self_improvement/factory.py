"""Builds the self-improvement subsystem (opt-in, conservative). Never raises: JARVIS starts without it."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jarvis.config import Settings
from jarvis.redaction import SecretDetector
from jarvis.self_improvement.analysis import ImprovementAnalyzer
from jarvis.self_improvement.approval import ApprovalGate
from jarvis.self_improvement.llm import LLMImprovementWriter
from jarvis.self_improvement.manager import ImprovementManager
from jarvis.self_improvement.pipeline import ValidationPipeline
from jarvis.self_improvement.store import JsonProposalStore
from jarvis.self_improvement.workspace import GitWorkspace, SubprocessRunner

log = logging.getLogger("jarvis.self_improvement")


@dataclass
class SelfImprovementSubsystem:
    status: str                                    # disabled | enabled
    reason: str = ""
    manager: ImprovementManager | None = None
    warning: str = ""

    @property
    def available(self) -> bool:
        return self.manager is not None

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason}
        if self.warning:
            info["warning"] = self.warning
        if self.manager is not None:
            info.update(self.manager.describe())
        return info


def build_self_improvement(settings: Settings, *, goals: Any = None, repairs: Any = None, audit: Any = None, llm: Any = None,
                           confirmation: Callable[[], Any] | None = None, detector: SecretDetector | None = None) -> SelfImprovementSubsystem:
    """`goals`/`repairs` are the subsystems' engines (or None), `audit` the permission engine's AuditLogger, `llm` the application's ONE provider and
    `confirmation` a getter for the CURRENT confirmation provider (so a GUI that replaces it later is respected)."""
    cfg = settings.self_improvement
    if not cfg.enabled:
        return SelfImprovementSubsystem("disabled", "self-improvement is off (self_improvement.enabled = false)")
    try:
        data = Path(cfg.data_dir).expanduser()
        store = JsonProposalStore(data / "proposals.json", cfg.max_proposals)
        analyzer = ImprovementAnalyzer(goals=goals, repairs=repairs, audit=audit, detector=detector, min_occurrences=cfg.min_occurrences)
        writer = LLMImprovementWriter(llm, detector=detector) if cfg.use_llm and llm is not None else None
        workspace = pipeline = None
        if cfg.repo_path.strip():
            runner = SubprocessRunner()
            workspace = GitWorkspace(cfg.repo_path, data, runner, timeout=cfg.prepare_timeout_seconds, max_diff_bytes=cfg.max_diff_bytes)
            pipeline = ValidationPipeline(runner, workspace.interpreter(), test_timeout=cfg.test_timeout_seconds, regression_paths=cfg.regression_paths, detector=detector)
        manager = ImprovementManager(store, analyzer=analyzer, workspace=workspace, pipeline=pipeline, gate=ApprovalGate(confirmation), audit=audit, writer=writer,
                                     allow_prepare=cfg.allow_prepare and workspace is not None, allow_activation=cfg.allow_activation and workspace is not None,
                                     max_edits=cfg.max_edits, strict_audit=settings.security.audit_strict and settings.security.audit_enabled, detector=detector)
    except Exception as exc:  # noqa: BLE001 - whatever happens here, JARVIS still starts
        log.warning("self-improvement unavailable: %s", type(exc).__name__)
        return SelfImprovementSubsystem("disabled", f"could not be built ({type(exc).__name__})")
    log.info("self-improvement enabled (prepare %s, activation %s, llm %s)", manager.allow_prepare, manager.allow_activation, bool(writer))
    return SelfImprovementSubsystem("enabled", "", manager, getattr(store, "load_warning", ""))
