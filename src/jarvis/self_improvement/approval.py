"""ApprovalGate: the ONE way a change gets approved. It asks the user through the application's confirmation provider (the same channel the permission
engine uses: terminal, GUI, ...) and treats anything but an explicit single "yes" as a refusal - no session grants, no default, no timeout-yes.

It is not reachable from any model-facing component: the analyzer, the writer and the pipeline never receive it; the manager calls it only from `approve`,
which only the user interface calls. A headless deployment (confirmation = deny) can therefore never approve a change."""
from __future__ import annotations

import logging
import uuid
from typing import Callable, Mapping

from jarvis.permissions.confirmation import ConfirmationChoice, ConfirmationProvider, ConfirmationRequest
from jarvis.permissions.levels import PermissionLevel

log = logging.getLogger("jarvis.self_improvement")


class ApprovalGate:
    def __init__(self, provider: ConfirmationProvider | Callable[[], ConfirmationProvider | None] | None) -> None:
        self._provider = provider

    def _current(self) -> ConfirmationProvider | None:
        p = self._provider
        if p is None or isinstance(p, ConfirmationProvider):
            return p
        try:
            return p()
        except Exception:  # noqa: BLE001
            return None

    @property
    def channel(self) -> str:
        p = self._current()
        return type(p).__name__ if p else "none"

    def ask(self, action: str, proposal_id: str, reason: str, context: Mapping[str, str]) -> bool:
        provider = self._current()
        if provider is None:
            return False
        req = ConfirmationRequest(request_id=uuid.uuid4().hex[:12], tool="self_improvement", action=action, level=PermissionLevel.YELLOW,
                                  resource=proposal_id, reason=reason, context=dict(context), session_allowed=False)
        try:
            return provider.confirm(req) is ConfirmationChoice.ALLOW_ONCE
        except BaseException as exc:  # noqa: BLE001 - Ctrl-C, closed input, a broken UI: all of these are "no"
            log.warning("approval prompt failed (%s): treated as refusal", type(exc).__name__)
            return False
