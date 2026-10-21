"""Central emergency stop ("Notaus"): one thread-safe latch plus a registry of component stoppers.

Design (Phase 14, sub-goal 1):
* The latch lives in the PermissionEngine (`engine.emergency`), the one place every tool call already passes. While it is engaged the engine denies EVERY request
  (GREEN included) and refuses to open an execution scope; `JarvisCore.handle` and the goal/repair entry points refuse new work. Nothing but `reset` clears it, and a
  new request never does.
* `engage()` only flips the latch (a tiny lock, no I/O, no waiting), so it works even while a normal request hangs. `run_stoppers()` then asks every registered
  component to stop, each in its own daemon thread with a hard deadline, so one stuck component can neither block the others nor the caller.
* The result is reported per component and never rounded up: STOPPED (effective now), REQUESTED (cooperative, may still run), NOTHING (had nothing running),
  FAILED (the stopper raised or refused), TIMEOUT (no answer in time: state unknown). Only "all STOPPED/NOTHING" is reported as complete.
* What the stop can NOT do: it does not undo anything that was already executed outside JARVIS (a click, a typed text, a started external program, a sent
  request) and it cannot interrupt a call that does not cooperate. It is not a sandbox.
* `reset` is the only way back and needs an authoriser callback (the engine asks the user through its ConfirmationProvider). It is not a tool: no model or tool can call it.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

log = logging.getLogger("jarvis.security")

DEFAULT_TIMEOUT = 5.0


class StopOutcome(str, Enum):
    STOPPED = "stopped"        # effective immediately for this component
    REQUESTED = "requested"    # cooperative: the stop was requested and may still be running
    NOTHING = "nothing"        # the component had nothing to stop (off, idle)
    FAILED = "failed"          # the stopper raised, or the component could not be stopped
    TIMEOUT = "timeout"        # no answer within the deadline: the state is unknown


_DONE = frozenset({StopOutcome.STOPPED, StopOutcome.NOTHING})


@dataclass(frozen=True)
class StopResult:
    """What a stopper returns (returning None means STOPPED)."""
    outcome: StopOutcome
    detail: str = ""


@dataclass(frozen=True)
class ComponentStop:
    name: str
    outcome: StopOutcome
    detail: str = ""


class ReportStatus(str, Enum):
    COMPLETE = "complete"        # every component stopped (or had nothing to stop)
    REQUESTED = "requested"      # nothing failed, but at least one component only got a cooperative request
    INCOMPLETE = "incomplete"    # at least one component failed, timed out or was never asked


@dataclass(frozen=True)
class StopReport:
    engaged: bool
    reason: str
    source: str
    components: tuple[ComponentStop, ...] = ()
    in_progress: bool = False

    @property
    def status(self) -> ReportStatus:
        if self.in_progress or any(c.outcome in (StopOutcome.FAILED, StopOutcome.TIMEOUT) for c in self.components):
            return ReportStatus.INCOMPLETE
        if any(c.outcome is StopOutcome.REQUESTED for c in self.components):
            return ReportStatus.REQUESTED
        return ReportStatus.COMPLETE

    @property
    def complete(self) -> bool:
        return self.status is ReportStatus.COMPLETE

    def summary(self) -> str:
        head = {ReportStatus.COMPLETE: "NOTAUS aktiv – alle Komponenten gestoppt.",
                ReportStatus.REQUESTED: "NOTAUS aktiv – Abbruch angefordert; kooperative Komponenten können noch laufen.",
                ReportStatus.INCOMPLETE: "NOTAUS aktiv – UNVOLLSTÄNDIG gestoppt (siehe Komponenten)."}[self.status]
        if self.in_progress:
            head += " (Stopp läuft noch)"
        lines = [head, "Neue Aktionen, Ziele und Tool-Aufrufe sind gesperrt, bis der Notaus ausdrücklich zurückgesetzt wird.",
                 "Bereits ausgeführte externe Aktionen werden weder rückgängig gemacht noch garantiert beendet."]
        lines += [f"  {c.name}: {c.outcome.value}" + (f" – {c.detail}" if c.detail else "") for c in self.components]
        return "\n".join(lines)


@dataclass(frozen=True)
class ResetResult:
    ok: bool
    detail: str = ""
    problems: tuple[str, ...] = ()


Stopper = Callable[[str], "StopResult | None"]
Resumer = Callable[[], None]
Listener = Callable[[bool, "StopReport | None"], None]


@dataclass
class _Component:
    name: str
    stopper: Stopper
    resumer: Resumer | None


class EmergencyStop:
    def __init__(self, *, on_event: Callable[[str, str], None] | None = None, default_timeout: float = DEFAULT_TIMEOUT) -> None:
        self._lock = threading.Lock()                     # guards the fields below; held only for field access, never while a stopper runs
        self._run_lock = threading.Lock()                 # one run_stoppers at a time
        self._engaged = False
        self._epoch = 0                                   # +1 on every engage and reset: a stop run that outlives its epoch must not report anything
        self._reason = ""
        self._source = ""
        self._components: dict[str, _Component] = {}
        self._results: dict[str, ComponentStop] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._listeners: list[Listener] = []
        self._on_event = on_event
        self._default_timeout = default_timeout

    # -- state ---------------------------------------------------------------------------------------------------------
    @property
    def engaged(self) -> bool:
        return self._engaged

    @property
    def reason(self) -> str:
        return self._reason

    def report(self, in_progress: bool = False) -> StopReport:
        with self._lock:
            order = [n for n in self._components]
            comps = tuple(self._results[n] for n in order if n in self._results)
            return StopReport(self._engaged, self._reason, self._source, comps, in_progress)

    # -- registry ----------------------------------------------------------------------------------------------------------
    def register(self, name: str, stopper: Stopper, resumer: Resumer | None = None) -> None:
        """A component that can be stopped. `stopper(reason)` must return quickly (it runs under a deadline) and may return a StopResult.
        `resumer()` is called by an authorised reset for components that were stopped."""
        with self._lock:
            self._components[name] = _Component(name, stopper, resumer)
            self._results.pop(name, None)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._components.pop(name, None)
            self._results.pop(name, None)

    def names(self) -> list[str]:
        with self._lock:
            return list(self._components)

    def add_listener(self, listener: Listener) -> None:
        """`listener(engaged, report)` is called from the thread that changed the state (engage / report update / reset): it must not touch GUI widgets."""
        with self._lock:
            self._listeners.append(listener)

    def _notify(self, engaged: bool, report: StopReport | None) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(engaged, report)
            except Exception:
                log.exception("emergency listener failed")

    def _event(self, kind: str, detail: str) -> None:
        if self._on_event is not None:
            try:
                self._on_event(kind, detail)
            except Exception:                              # auditing must never prevent or delay the stop
                log.exception("emergency event hook failed")

    # -- engage ------------------------------------------------------------------------------------------------------------
    def engage(self, reason: str = "emergency stop", source: str = "api") -> bool:
        """Flip the latch. Immediate, never blocks on a component. Returns True when this call engaged it (False: it already was)."""
        with self._lock:
            newly = not self._engaged
            if newly:
                self._engaged, self._reason, self._source = True, (reason or "emergency stop")[:200], (source or "api")[:50]
                self._epoch += 1
                self._results.clear()
        if newly:
            log.warning("EMERGENCY STOP engaged by %s: %s", source, reason)
            self._event("engage", f"{source}: {reason}"[:300])
            self._notify(True, self.report(in_progress=True))
        return newly

    def trigger(self, reason: str = "emergency stop", source: str = "api", timeout: float | None = None) -> StopReport:
        self.engage(reason, source)
        return self.run_stoppers(timeout)

    # -- stopping the components -----------------------------------------------------------------------------------------------
    def run_stoppers(self, timeout: float | None = None) -> StopReport:
        """Ask every component that is not yet stopped to stop, concurrently, within `timeout` seconds in total (default 5 s). Calling it again retries the
        components that failed, timed out or only got a request. If another run is in progress, its (partial) report is returned at once."""
        if not self._engaged:
            return self.report()
        if not self._run_lock.acquire(blocking=False):
            return self.report(in_progress=True)
        try:
            with self._lock:
                epoch = self._epoch
            budget = self._default_timeout if timeout is None else max(0.0, float(timeout))
            deadline = time.monotonic() + budget
            reason = self._reason
            with self._lock:
                todo = [c for c in self._components.values()
                        if c.name not in self._results or self._results[c.name].outcome not in _DONE]
            slots: dict[str, list[ComponentStop]] = {}
            started: list[tuple[_Component, threading.Thread]] = []
            for comp in todo:
                old = self._threads.get(comp.name)
                if old is not None and old.is_alive():       # a previous attempt is still stuck: do not pile up threads
                    self._set_result(ComponentStop(comp.name, StopOutcome.TIMEOUT, "an earlier stop attempt has not returned yet"), epoch)
                    continue
                box: list[ComponentStop] = []
                slots[comp.name] = box
                t = threading.Thread(target=self._call, args=(comp, reason, box), name=f"jarvis-stop-{comp.name}"[:60], daemon=True)
                self._threads[comp.name] = t
                started.append((comp, t))
                t.start()
            for comp, t in started:
                t.join(max(0.0, deadline - time.monotonic()))
                box = slots[comp.name]
                if box:
                    self._set_result(box[0], epoch)
                else:
                    self._set_result(ComponentStop(comp.name, StopOutcome.TIMEOUT, f"no answer within {budget:g} s; the state is unknown"), epoch)
            rep = self.report()
            current = self._engaged and epoch == self._epoch
        finally:
            self._run_lock.release()
        if current:                                              # a reset (or a new engage) during the run makes this report stale: say nothing
            self._event("stop_report", f"{rep.status.value}: " + ", ".join(f"{c.name}={c.outcome.value}" for c in rep.components))
            self._notify(True, rep)
        return rep

    @staticmethod
    def _call(comp: _Component, reason: str, box: list[ComponentStop]) -> None:
        try:
            res = comp.stopper(reason)
            if res is None:
                box.append(ComponentStop(comp.name, StopOutcome.STOPPED))
            elif isinstance(res, StopResult):
                box.append(ComponentStop(comp.name, res.outcome, res.detail[:300]))
            else:
                box.append(ComponentStop(comp.name, StopOutcome.FAILED, "the stopper returned an invalid result"))
        except Exception as exc:                              # the failure is REPORTED, never swallowed
            log.warning("emergency stop of %s failed: %s", comp.name, type(exc).__name__)
            box.append(ComponentStop(comp.name, StopOutcome.FAILED, f"{type(exc).__name__}: {str(exc)[:200]}"))

    def _set_result(self, result: ComponentStop, epoch: int | None = None) -> None:
        with self._lock:
            if result.name in self._components and (epoch is None or epoch == self._epoch):
                self._results[result.name] = result

    # -- reset ----------------------------------------------------------------------------------------------------------------------
    def reset(self, authorize: Callable[[], bool], source: str = "user") -> ResetResult:
        """The only way to clear the latch. `authorize()` must obtain an explicit human decision (the engine asks its ConfirmationProvider); anything but a
        True result keeps the stop engaged. Components that were stopped are resumed afterwards; a component that cannot be resumed stays halted and is listed."""
        if not self._engaged:
            return ResetResult(False, "the emergency stop is not engaged")
        self._event("reset_requested", source)
        try:
            allowed = bool(authorize())
        except Exception as exc:
            log.warning("emergency reset authorisation failed: %s", type(exc).__name__)
            allowed = False
        if not allowed:
            self._event("reset_denied", source)
            return ResetResult(False, "reset not authorised; the emergency stop stays engaged")
        with self._lock:
            resumers = [(c.name, c.resumer) for c in self._components.values()
                        if c.resumer is not None and c.name in self._results
                        and self._results[c.name].outcome in (StopOutcome.STOPPED, StopOutcome.REQUESTED, StopOutcome.TIMEOUT, StopOutcome.FAILED)]
            stuck = [n for n, t in self._threads.items() if t.is_alive()]
        problems: list[str] = [f"{n}: an earlier stop call has still not returned" for n in stuck]
        for name, resume in resumers:
            try:
                resume()
            except Exception as exc:
                problems.append(f"{name}: could not be resumed ({type(exc).__name__}); it stays halted")
        with self._lock:
            self._engaged, self._reason, self._source = False, "", ""
            self._epoch += 1
            self._results.clear()
        log.warning("EMERGENCY STOP reset by %s", source)
        self._event("reset_ok", source + (f" (problems: {len(problems)})" if problems else ""))
        self._notify(False, None)
        return ResetResult(True, "the emergency stop was reset", tuple(problems))
