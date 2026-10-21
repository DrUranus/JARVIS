"""Builds the self-improvement subsystem (opt-in, conservative). Never raises: JARVIS starts without it."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any, Callable, Mapping, Sequence

from jarvis.config import Settings
from jarvis.redaction import SecretDetector
from jarvis.self_improvement.analysis import ImprovementAnalyzer
from jarvis.self_improvement.approval import ApprovalGate
from jarvis.self_improvement.llm import LLMImprovementWriter
from jarvis.self_improvement.manager import ImprovementManager
from jarvis.self_improvement.isolation import ExecutionGuard
from jarvis.self_improvement.store import JsonProposalStore, load_key

log = logging.getLogger("jarvis.self_improvement")


@dataclass
class SelfImprovementSubsystem:
    status: str                                    # disabled | enabled
    reason: str = ""
    manager: ImprovementManager | None = None
    warning: str = ""
    data_dir: str = ""                             # the ABSOLUTE directory actually used (a relative config value is resolved against the working directory)

    @property
    def available(self) -> bool:
        return self.manager is not None

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason}
        if self.data_dir:
            info["data_dir"] = self.data_dir
        if self.warning:
            info["warning"] = self.warning
        if self.manager is not None:
            info.update(self.manager.describe())
        return info


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def cloud_sync_warning(path: Path, env: Mapping[str, str]) -> str:
    """A note (never an error) when `path` lies in a folder that a sync client such as OneDrive watches: the client can hold files open (a refused replace of
    proposals.json) and uploads their content (proposals, and the key if it lives there)."""
    try:
        real = path.resolve()
    except OSError:
        return ""
    roots = [Path(v) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial") if (v := env.get(k))]
    for r in roots:
        if _inside(real, r):
            return f"{real} is inside the OneDrive folder {r}: sync can lock the file and uploads it; prefer a folder outside OneDrive"
    if any(part.casefold().startswith("onedrive") for part in real.parts):
        return f"{real} looks like it is inside a OneDrive folder: sync can lock the file and uploads it; prefer a folder outside OneDrive"
    return ""


def _forbidden_zone(path: Path, roots: Sequence[str]) -> str:
    """Why `path` may not be used for the proposal store / key (empty = fine): it must be neither inside nor an ancestor of a directory that tools may write to."""
    for r in roots:
        if not r:
            continue
        root = Path(r).expanduser()
        if _inside(path, root) or _inside(root, path):
            return f"{path} overlaps {root}"
    return ""


def build_self_improvement(settings: Settings, *, goals: Any = None, repairs: Any = None, audit: Any = None, llm: Any = None,
                           confirmation: Callable[[], Any] | None = None, detector: SecretDetector | None = None, env: Mapping[str, str] | None = None) -> SelfImprovementSubsystem:
    """Builds ONLY the proposal workflow: no workspace, no pipeline execution, a locked ExecutionGuard. `goals`/`repairs` are the engines (or None), `audit` the
    permission engine's AuditLogger, `llm` the application's ONE provider and `confirmation` a getter for the CURRENT confirmation provider. Fails closed: if the
    data directory or the key lies where the coding tools may write, or the key cannot be loaded, the subsystem stays disabled."""
    cfg = settings.self_improvement
    if not cfg.enabled:
        return SelfImprovementSubsystem("disabled", "self-improvement is off (self_improvement.enabled = false)")
    try:
        env = os.environ if env is None else env
        data = Path(cfg.data_dir).expanduser()
        key_path = Path(cfg.key_path).expanduser() if cfg.key_path.strip() else Path.home() / ".jarvis" / "self_improvement.store.key"
        zones = [*settings.effective_fs_roots, settings.workspace, *settings.coding.workspace_roots, str(Path(settings.log_dir))]
        for what, path in (("data_dir", data), ("store key", key_path)):
            bad = _forbidden_zone(path, zones)
            if bad:
                return SelfImprovementSubsystem("disabled", f"the {what} must lie outside every directory the tools may write to ({bad})")
        if _inside(key_path, data) or _inside(data, key_path):
            return SelfImprovementSubsystem("disabled", "the store key must not lie inside the data directory")
        key = load_key(env, key_path)
        store = JsonProposalStore(data / "proposals.json", key, cfg.max_proposals)
        analyzer = ImprovementAnalyzer(goals=goals, repairs=repairs, audit=audit, detector=detector, min_occurrences=cfg.min_occurrences)
        writer = LLMImprovementWriter(llm, detector=detector) if cfg.use_llm and llm is not None else None
        manager = ImprovementManager(store, analyzer=analyzer, workspace=None, pipeline=None, gate=ApprovalGate(confirmation), audit=audit, writer=writer,
                                     guard=ExecutionGuard.locked(), max_edits=cfg.max_edits, detector=detector)
    except Exception as exc:  # noqa: BLE001 - whatever happens here, JARVIS still starts (without this feature)
        log.warning("self-improvement unavailable: %s", type(exc).__name__)
        return SelfImprovementSubsystem("disabled", f"could not be built ({type(exc).__name__}: {str(exc)[:120]})")
    log.info("self-improvement enabled as PROPOSAL WORKFLOW only (no code preparation, test or activation)")
    notes = [w for w in (store.load_warning, cloud_sync_warning(data, env), cloud_sync_warning(key_path, env)) if w]
    if not Path(cfg.data_dir).expanduser().is_absolute():
        notes.append(f"data_dir is relative and was resolved against the working directory: {data.resolve()}")
    return SelfImprovementSubsystem("enabled", "", manager, "; ".join(notes), str(data.resolve()))
