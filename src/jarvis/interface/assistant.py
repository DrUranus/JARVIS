"""End-to-end assistant wiring (backlog step assistant-e2e, Strang A / A9).

Connects what already exists - the goal/agent layers, the task journal, the agent router and the UI-contract adapter (`ControllerUiBackend`) - without adding any
power: this module executes no tool, grants nothing, starts nothing by itself (no thread, no timer; it works on a pull model driven by the adapter's pump) and does
not import the permission package. The flow stays: text -> goal planning -> router (per step) -> agents -> ToolRegistry.execute -> PermissionEngine -> confirmation
(the engine's provider; with the UI adapter a `confirmation_request` event) -> result -> journal -> contract events. Off by default (assistant.enabled = false)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("jarvis.assistant")

_MAX_PUBLISHED = 2000


class RoutingSink:
    """Late-bound target of the router's `routing` events: the router is built before the UI adapter exists. Until an adapter is attached, events are dropped."""

    def __init__(self) -> None:
        self._ui: Any = None

    def attach(self, ui: Any) -> None:
        self._ui = ui

    def __call__(self, type_: str, data: dict[str, Any]) -> None:
        ui = self._ui
        if ui is not None:
            ui.publish(type_, data)


@dataclass
class AssistantSubsystem:
    status: str                                    # disabled | enabled
    reason: str = ""
    ui: Any = None                                 # ControllerUiBackend
    journal: Any = None                            # JournalRecorder | None
    router: Any = None                             # AgentRouter | None
    goals: Any = None                              # GoalEngine | None (read only here)
    _published: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def available(self) -> bool:
        return self.ui is not None

    # ---- journal + result events (pull model; read only) -----------------------------------------------------------------------------
    def sync(self) -> int:
        """Store finished work in the journal and publish `task_update` + `result` once per finished goal. Never raises; starts, resumes and cancels nothing."""
        if not self.available:
            return 0
        try:
            if self.journal is not None:
                self.journal.sync()
        except Exception:                                                                 # noqa: BLE001 - the journal must never break the flow
            log.warning("journal sync failed", exc_info=True)
        return self._publish_finished_goals()

    def _publish_finished_goals(self) -> int:
        engine = self.goals
        if engine is None:
            return 0
        from jarvis.goals.state import GOAL_TERMINAL
        count = 0
        with self._lock:
            for g in list(engine.list()):
                if g.status not in GOAL_TERMINAL or g.goal_id in self._published or len(self._published) >= _MAX_PUBLISHED:
                    continue
                try:
                    res = engine.result(g.goal_id)
                except Exception:                                                         # noqa: BLE001
                    continue
                self._published.add(g.goal_id)
                status = str(getattr(g.status, "value", g.status)).upper()
                try:
                    from jarvis.interface.goal_text import event_summary
                    summary = event_summary(status, res)
                except Exception:                                                         # noqa: BLE001 - the explanation is a courtesy, never a failure
                    summary = f"{status}: {res.summary}" if getattr(res, "summary", "") else status
                self.ui.publish_finished("goal", g.goal_id, status, summary)
                count += 1
        return count

    # ---- read only status ---------------------------------------------------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"status": self.status, "reason": self.reason}
        if self.available:
            info.update(journal=self.journal is not None, router=self.router is not None, goals=self.goals is not None, events=self.ui.last_seq,
                        results_published=len(self._published))
        return info

    def status_text(self) -> str:
        if not self.available:
            return (f"Assistent: deaktiviert – {self.reason}\nAktivieren: assistant.enabled = true und agents.enabled = true "
                    "(bzw. JARVIS_ASSISTANT_ENABLED=true); Journal (journal.enabled) und Router (agents.router.enabled) sind eigene, optionale Schalter.")
        d = self.describe()
        yes = lambda v: "an" if v else "aus"                                             # noqa: E731
        return "\n".join(["Assistent: aktiviert (nur Anzeige; startet nichts von selbst)",
                          f"  Journal: {yes(d['journal'])}   Router: {yes(d['router'])}   Ziel-Engine: {yes(d['goals'])}",
                          f"  Vertragsereignisse: {d['events']}   veröffentlichte Ergebnisse: {d['results_published']}"])


def _enable_resume_planner(core: Any, journal: Any) -> None:
    """With a journal, the goal planner is wrapped once by the pass-through `ResumeAwarePlanner` so that an explicit `/resume` can leave out finished steps. Goals that are
    not registered by that command are planned exactly as before. Never raises."""
    goals = core.subsystems.get("goals")
    engine = getattr(goals, "engine", None)
    if journal is None or engine is None or not hasattr(engine, "wrap_planner"):
        return
    try:
        from jarvis.journal.resume import ResumeAwarePlanner
        goals.planner = engine.wrap_planner(ResumeAwarePlanner) if not isinstance(getattr(engine, "_planner", None), ResumeAwarePlanner) else engine._planner
    except Exception:                                                                     # noqa: BLE001 - JARVIS starts without it
        log.warning("resume planner unavailable", exc_info=True)


def build_assistant(settings: Any, core: Any, *, ui_factory: Any, journal: Any = None, router: Any = None, sink: RoutingSink | None = None) -> AssistantSubsystem:
    """Never raises: JARVIS starts without it. `ui_factory(controller)` builds the adapter (bootstrap passes it so that this module needs no permission import)."""
    cfg = settings.assistant
    if not cfg.enabled:
        return AssistantSubsystem("disabled", "the assistant is off (assistant.enabled = false)")
    agents = core.subsystems.get("agents")
    if getattr(agents, "orchestrator", None) is None:
        return AssistantSubsystem("disabled", "the assistant needs the multi-agent layer (agents.enabled = true)")
    try:
        from jarvis.interface.gui_model import GuiController
        ui = ui_factory(GuiController(core, settings))
        sub = AssistantSubsystem("enabled", "", ui, journal, router, getattr(core.subsystems.get("goals"), "engine", None))
        _enable_resume_planner(core, journal)
        ui.add_pump_hook(sub.sync)
        if sink is not None:
            sink.attach(ui)
    except Exception as exc:                                                              # noqa: BLE001 - whatever happens here, JARVIS still starts
        log.warning("assistant unavailable: %s", type(exc).__name__)
        return AssistantSubsystem("disabled", f"could not be built ({type(exc).__name__})")
    return sub
