"""E6: the enforcing wrapper around an LLM provider (token / call / optional cost budget). OFF unless `llm_budget.enabled`; wired only in `bootstrap.build_core`.

What it does, for EVERY call (complete and complete_text share one path):
  1. Not-Aus engaged -> refuse (the latch is only READ here; nothing is reset or engaged).
  2. Plan the call: output tokens = request.max_tokens, else the configured `llm.max_tokens` (the value the provider will really use); input tokens = ESTIMATE of
     characters / 3, rounded up. The estimate is only ever used for refusing and for booking when real usage is missing - it is never shown as consumption.
  3. `CostBudget.check` (calls, per-call and session tokens, estimated session input, optional cost limit; fail-closed on unknown price / earlier unknown cost).
  4. Refusal = `LLMError("LLM-Budget: ...")` with numbers only (never prompt, answer or key), one `budget_exhausted` audit event for the first refusal, no retry and no
     fallback to another model or provider.
  5. Allowed -> the request is passed on UNCHANGED and the call is booked: measured usage if the provider reported both counts, otherwise the planned maxima as an
     ESTIMATE. A failed provider call is booked as an estimate too (it may have been sent and billed) and the error is re-raised.
The calls are serialised by one lock so concurrent callers cannot slip past a limit between check and booking. The budget has no setter, reset or raise function.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Callable, Sequence

from jarvis.errors import LLMError
from jarvis.llm.base import LLMProvider, LLMRequest, LLMResponse, Message
from jarvis.llm import cost_budget as cb

CHARS_PER_TOKEN = 3


def estimate_input_tokens(messages: Sequence[Message]) -> int:
    """ESTIMATE only: ceil(characters / 3) over all message contents."""
    chars = sum(len(m.content) for m in messages if isinstance(getattr(m, "content", None), str))
    return math.ceil(chars / CHARS_PER_TOKEN)


class BudgetedProvider(LLMProvider):
    def __init__(self, inner: LLMProvider, budget: cb.CostBudget, *, default_model: str, default_max_tokens: int,
                 emergency: Any = None, audit: Callable[[dict], Any] | None = None) -> None:
        self._inner = inner
        self._budget = budget
        self._model = default_model
        self._default_max = default_max_tokens
        self._emergency = emergency
        self._audit = audit
        self._lock = threading.Lock()
        self._refused = 0
        self._audited = False
        self.name = inner.name

    # -- state -----------------------------------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        s = self._budget.snapshot()
        return {"enabled": True, "calls": s.calls, "input_tokens": s.input_tokens, "output_tokens": s.output_tokens, "tokens": s.tokens, "refused": self._refused,
                "cost": format(s.cost.normalize(), "f") if s.cost_complete else cb.UNKNOWN, "cost_complete": s.cost_complete,
                "limits": {"max_calls": self._budget.limits.max_calls, "max_tokens_session": self._budget.limits.max_tokens_session}}

    # -- the one call path -----------------------------------------------------------------------------------------
    def complete(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            model = request.model or self._model
            planned_out = request.max_tokens if request.max_tokens is not None else self._default_max
            planned_in = estimate_input_tokens(request.messages)
            if getattr(self._emergency, "engaged", False):
                self._refuse("LLM-Budget: Not-Aus aktiv, keine LLM-Aufrufe", planned_in, planned_out)
            decision = self._budget.check(model, input_tokens=planned_in, max_output_tokens=planned_out)
            if not decision.allowed:
                self._refuse(decision.reason, planned_in, planned_out)
            try:
                response = self._inner.complete(request)
            except BaseException:
                self._budget.record_estimated(model, planned_in, planned_out)       # may have been sent and billed: count the worst plan, then re-raise
                raise
            usage = cb.parse_usage(getattr(response, "usage", None))
            if usage.known:
                self._budget.record(model, usage)
            else:
                self._budget.record_estimated(model, planned_in, planned_out)
            return response

    def _refuse(self, reason: str, planned_in: int, planned_out: int) -> None:
        self._refused += 1
        if not self._audited and self._audit is not None:
            self._audited = True
            s = self._budget.snapshot()
            try:
                self._audit({"reason": reason, "calls": s.calls, "tokens": s.tokens, "planned_input_tokens": planned_in, "planned_output_tokens": planned_out})
            except Exception:                        # a broken audit sink must not turn a refusal into a call
                pass
        raise LLMError(reason if reason.startswith("LLM-Budget") else f"LLM-Budget: {reason}")
