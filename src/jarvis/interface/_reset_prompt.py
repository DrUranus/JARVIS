"""Bind one synchronous GUI/CLI engine reset to the UI provider that receives its question."""
from __future__ import annotations

import threading
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any, Iterator


class ResetPromptOrigin:
    def __init__(self) -> None:
        self._busy = threading.Lock()
        self._caller = threading.local()

    @contextmanager
    def enter(self) -> Iterator[bool]:
        if not self._busy.acquire(blocking=False):
            yield False
            return
        try:
            self._caller.expected = True
            yield True
        finally:
            del self._caller.expected
            self._busy.release()

    def claim(self, request: Any) -> bool:
        if not getattr(self._caller, "expected", False):
            return False
        if (request.request_id != "emergency-reset" or request.tool != "jarvis"
                or request.action != "emergency_reset" or request.session_allowed is not False):
            return False
        self._caller.expected = False
        return True


def reset_prompt_from(engine: Any) -> AbstractContextManager[bool]:
    provider = getattr(engine, "confirmation", None)
    origin = getattr(provider, "reset_prompt_origin", None)
    return origin.enter() if isinstance(origin, ResetPromptOrigin) else nullcontext(True)
