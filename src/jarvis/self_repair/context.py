"""RepairContext: what the user explicitly releases for ONE repair run. Only known keys, plain data, bounded, no bypass-style keys."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from jarvis.self_repair import policy as P
from jarvis.self_repair.errors import InvalidRepairError


@dataclass(frozen=True)
class RepairContext:
    workspace: str = field(repr=False)
    tests: tuple[str, ...] = ()
    runner: str | None = None
    candidates: tuple[Mapping[str, Any], ...] = field(default=(), repr=False)     # proposed repairs, one per attempt (v1 writes no fix by itself)
    repair: bool = False                                                          # fix requested (otherwise: self-test only)


def check_context(workspace: str, objective: str, ctx: Mapping[str, Any] | None) -> RepairContext:
    ctx = {} if ctx is None else ctx
    if not isinstance(ctx, Mapping):
        raise InvalidRepairError("context must be a mapping")
    unknown = sorted(str(k)[:30] for k in ctx if k not in P.CONTEXT_KEYS)
    if unknown:
        raise InvalidRepairError(f"unknown context keys {unknown}; allowed: {sorted(P.CONTEXT_KEYS)}")
    try:
        P.check_plain(ctx, "context")
    except ValueError as exc:
        raise InvalidRepairError(str(exc)) from None
    bad = P.find_reserved(ctx)
    if bad:
        raise InvalidRepairError(f"the context key {bad!r} is not allowed")
    if P.json_size(P.plain_copy(ctx)) > P.MAX_CONTEXT_BYTES:
        raise InvalidRepairError("the context is too large")
    tests = ctx.get("tests") or ()
    if isinstance(tests, str):
        tests = (tests,)
    if not isinstance(tests, (list, tuple)) or len(tests) > P.MAX_TESTS or not all(isinstance(t, str) and t.strip() and len(t) <= 200 for t in tests):
        raise InvalidRepairError(f"tests must be up to {P.MAX_TESTS} test paths or ids")
    runner = ctx.get("runner")
    if runner is not None and runner not in P.RUNNERS:
        raise InvalidRepairError(f"unknown test runner; known: {', '.join(P.RUNNERS)}")
    cands = ctx.get("candidates") or ()
    if not isinstance(cands, (list, tuple)) or len(cands) > P.MAX_CANDIDATES or not all(isinstance(c, Mapping) for c in cands):
        raise InvalidRepairError(f"candidates must be up to {P.MAX_CANDIDATES} objects")
    wants = ctx.get("repair")
    if wants is not None and not isinstance(wants, bool):
        raise InvalidRepairError("repair must be true or false")
    repair = wants if wants is not None else (bool(cands) or bool(P.FIX_WORDS.search(objective)))
    return RepairContext(workspace, tuple(t.strip() for t in tests), runner, tuple(P.plain_copy(c) for c in cands), repair)
