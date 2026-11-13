"""V2.1 (Mission 1): analysis of a plan as a dependency graph - pure logic, nothing is executed and nothing is granted.

It answers, deterministically and before anything runs: is the plan valid (ids, dependencies, cycles, the hard step/depth limits of the goal layer)? Which steps can run in parallel
(waves, bounded by `max_parallel`, the most valuable / least risky first)? Which steps can NOT run because information, a tool or a capability is missing, and is the goal itself still
reachable? What is the longest chain (only if every duration is known - nothing is guessed)? `replan` swaps a failed step for a prepared alternative (never for fatal codes, never beyond
the attempt limit, never with a capability the plan did not already use); `resume` returns what is left after an interruption and names interrupted steps with side effects, which need
a new confirmation. The existing GoalEngine / AgentOrchestrator stay the only executors; `from_steps` adapts their GoalStep objects."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from jarvis.goals import policy as GP

MAX_REPLANS = 2
NEVER_REPLAN = frozenset(GP.FATAL_CODES | {"agent_budget_exceeded", "agent_budget_unavailable", "budget_exhausted", "cancelled", "failsafe", "not_authorized", "blocked_target",
                                           "external_action_not_supported", "emergency_stop", "quality_rejected", "quality_unverified",
                                           "quality_unavailable"})


@dataclass(frozen=True)
class Node:
    id: str
    deps: tuple[str, ...] = ()
    capability: str | None = None
    tool: str | None = None
    needs: tuple[str, ...] = ()          # information keys that must be known or provided by an ANCESTOR
    provides: tuple[str, ...] = ()
    value: int = 3                       # 1..5, higher = more useful
    risk: int = 3                        # 1..5, higher = riskier
    cost: int = 3                        # 1..5, higher = more expensive
    est_seconds: float | None = None     # None = unknown (never guessed)
    side_effect: bool = False
    verify: bool = False                 # a quality gate (checks results, produces nothing new)
    capabilities: tuple[str, ...] = ()   # further required capabilities (GoalStep adapter)

    @property
    def required(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(([self.capability] if self.capability else []) + list(self.capabilities)))


@dataclass(frozen=True)
class Analysis:
    ok: bool
    error: str = ""
    cycle: tuple[str, ...] = ()
    waves: tuple[tuple[str, ...], ...] = ()
    runnable: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    missing_info: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    missing_tools: Mapping[str, str] = field(default_factory=dict)
    missing_capabilities: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    questions: tuple[str, ...] = ()
    unsolvable: bool = False
    critical_path: tuple[str, ...] = ()
    critical_seconds: float | None = None
    unknown_durations: tuple[str, ...] = ()
    verify_nodes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Replan:
    action: str                          # replaced | degraded | abort
    reason: str
    replacement: str | None
    analysis: Analysis | None


@dataclass(frozen=True)
class Resume:
    analysis: Analysis
    needs_confirmation: tuple[str, ...]


def from_steps(steps: Iterable[Any]) -> list[Node]:
    """GoalStep objects -> nodes (ids, dependencies, required capabilities; an evaluation step is a quality gate)."""
    return [Node(s.step_id, tuple(s.dependencies), capabilities=tuple(sorted(s.required_capabilities)), est_seconds=None, verify=bool(getattr(s, "is_evaluation", False)))
            for s in steps]


def _invalid(nodes: list[Node]) -> tuple[str, tuple[str, ...]]:
    if not nodes:
        return "empty", ()
    if len(nodes) > GP.MAX_STEPS_HARD:
        return "too_many_steps", ()
    if any(not isinstance(n, Node) or not GP.valid_id(n.id) or " " in n.id for n in nodes):
        return "invalid_id", ()
    ids = [n.id for n in nodes]
    if len(set(ids)) != len(ids):
        return "duplicate_id", ()
    reserved = {k.lower() for k in GP.RESERVED_KEYS}
    for n in nodes:
        if any(str(x).lower() in reserved for x in (n.id, *n.needs, *n.provides, *n.deps)):
            return "reserved_key", ()
        if not all(isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= 5 for r in (n.value, n.risk, n.cost)):
            return "invalid_rating", ()
    known = set(ids)
    if any(d not in known for n in nodes for d in n.deps):
        return "unknown_dependency", ()
    return "", ()


def _order(nodes: list[Node]) -> tuple[list[str], tuple[str, ...]]:
    """Topological order (Kahn, by id) or the ids on cycles."""
    by = {n.id: n for n in nodes}
    left = {n.id: set(n.deps) for n in nodes}
    order: list[str] = []
    while True:
        ready = sorted(i for i, d in left.items() if not d)
        if not ready:
            break
        for i in ready:
            order.append(i)
            del left[i]
        for d in left.values():
            d.difference_update(ready)
    if not left:
        return order, ()
    cyc = set(left)
    changed = True
    while changed:                                           # drop nodes that only hang BEHIND a cycle
        changed = False
        for i in list(cyc):
            if not any(i in by[j].deps for j in cyc):
                cyc.discard(i)
                changed = True
    return order, tuple(sorted(cyc or left))


def analyse(nodes: Iterable[Node], *, capabilities: Iterable[str], available_tools: Iterable[str], known_info: Iterable[str], max_parallel: int = 3, goals: Iterable[str] | None = None,
            done: Iterable[str] = (), failed: Iterable[str] = ()) -> Analysis:
    nodes = list(nodes)
    error, _ = _invalid(nodes)
    if error:
        return Analysis(False, error)
    order, cycle = _order(nodes)
    if cycle:
        return Analysis(False, "cycle", cycle)
    by = {n.id: n for n in nodes}
    depth: dict[str, int] = {}
    ancestors: dict[str, set[str]] = {}
    for i in order:
        depth[i] = 1 + max((depth[d] for d in by[i].deps), default=0)
        ancestors[i] = set().union(*({d} | ancestors[d] for d in by[i].deps)) if by[i].deps else set()
    if max(depth.values()) > GP.MAX_DEPTH_HARD:
        return Analysis(False, "too_deep")
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) or max_parallel < 1:
        return Analysis(False, "invalid_parallel_limit")
    caps, tls, known, done_set, failed_set = set(capabilities), set(available_tools), set(known_info), set(done) & set(by), set(failed) & set(by)
    missing_info: dict[str, tuple[str, ...]] = {}
    missing_tools: dict[str, str] = {}
    missing_caps: dict[str, tuple[str, ...]] = {}
    direct: set[str] = set(failed_set)
    for i in order:
        n = by[i]
        if i in done_set:
            continue
        have = known | {p for a in ancestors[i] for p in by[a].provides}
        lack = tuple(k for k in n.needs if k not in have)
        if lack:
            missing_info[i] = lack
        if n.tool is not None and n.tool not in tls:
            missing_tools[i] = n.tool
        lack_caps = tuple(c for c in n.required if c not in caps)
        if lack_caps:
            missing_caps[i] = lack_caps
        if lack or i in missing_tools or lack_caps:
            direct.add(i)
    blocked = {i for i in order if i not in done_set and (i in direct or ancestors[i] & direct)}
    runnable = [i for i in order if i not in blocked and i not in done_set]
    # waves: ready = every dependency finished earlier (or done); the best `max_parallel` first
    finished, waves, left = set(done_set), [], set(runnable)
    while left:
        ready = sorted((i for i in left if set(by[i].deps) <= finished), key=lambda i: (-by[i].value, by[i].risk, by[i].cost, i))[:max_parallel]
        if not ready:                                            # cannot happen for a valid graph; never loop forever
            break
        waves.append(tuple(ready))
        finished.update(ready)
        left.difference_update(ready)
    sinks = [i for i in order if not any(i in n.deps for n in nodes)]
    targets = [g for g in (goals if goals is not None else sinks) if g in by]
    unknown = tuple(i for i in runnable if by[i].est_seconds is None)
    path: tuple[str, ...] = ()
    seconds: float | None = None
    if runnable and not unknown:
        best: dict[str, tuple[float, tuple[str, ...]]] = {}
        for i in runnable:
            prev = max((best[d] for d in by[i].deps if d in best), key=lambda t: (t[0], tuple(reversed(t[1]))), default=(0.0, ()))
            best[i] = (prev[0] + float(by[i].est_seconds or 0), prev[1] + (i,))
        seconds, path = max(best.values(), key=lambda t: (t[0], t[1]))
    verify = tuple(i for i in order if by[i].verify)
    warnings = () if verify else ("no_quality_gate",)
    return Analysis(ok=not blocked, waves=tuple(waves), runnable=tuple(runnable), blocked=tuple(i for i in order if i in blocked), missing_info=missing_info,
                    missing_tools=missing_tools, missing_capabilities=missing_caps, questions=tuple(sorted({k for v in missing_info.values() for k in v})),
                    unsolvable=any(t in blocked for t in targets), critical_path=path, critical_seconds=seconds, unknown_durations=unknown, verify_nodes=verify, warnings=warnings)


def replan(nodes: Iterable[Node], *, failed: str, code: str, done: Iterable[str], alternatives: Mapping[str, Iterable[Node]], capabilities: Iterable[str], available_tools: Iterable[str],
           known_info: Iterable[str], attempts_used: int = 0, max_parallel: int = 3) -> Replan:
    """What to do after `failed` ended with `code`. Finished work (`done`) is kept; a fatal code or a used-up attempt limit aborts; without a usable alternative the plan is
    degraded (the failed step and everything behind it is blocked, the rest goes on) and `analysis.unsolvable` says whether the goal is still reachable."""
    nodes = list(nodes)
    kw = dict(capabilities=capabilities, available_tools=available_tools, known_info=known_info, max_parallel=max_parallel)
    if code in NEVER_REPLAN:
        return Replan("abort", f"code {code!r} is never replanned", None, None)
    if attempts_used >= MAX_REPLANS:
        return Replan("abort", f"replan attempt limit {MAX_REPLANS} reached", None, None)
    used_caps = {c for n in nodes for c in n.required}
    reason = "no alternative prepared"
    for alt in alternatives.get(failed, ()):
        if any(c not in used_caps for c in alt.required):
            reason = "alternative needs a capability the plan did not use"
            continue
        swapped = [alt if n.id == failed else replace(n, deps=tuple(alt.id if d == failed else d for d in n.deps)) for n in nodes]
        a = analyse(swapped, done=done, **kw)
        if a.error or alt.id in a.blocked:
            reason = f"alternative {alt.id!r} is not runnable ({a.error or 'blocked'})"
            continue
        return Replan("replaced", f"{failed!r} replaced after {code!r}", alt.id, a)
    return Replan("degraded", reason, None, analyse(nodes, done=done, failed=(failed,), **kw))


def resume(nodes: Iterable[Node], *, done: Iterable[str], interrupted: Iterable[str], capabilities: Iterable[str], available_tools: Iterable[str], known_info: Iterable[str],
           max_parallel: int = 3) -> Resume:
    """The remaining plan after an interruption. Interrupted steps WITH side effects are listed: they may have happened and must be confirmed again before they run."""
    nodes = list(nodes)
    by = {n.id: n for n in nodes}
    again = tuple(sorted(i for i in set(interrupted) if i in by and by[i].side_effect and i not in set(done)))
    return Resume(analyse(nodes, done=done, capabilities=capabilities, available_tools=available_tools, known_info=known_info, max_parallel=max_parallel), again)
