"""User confirmation abstraction. Interfaces (CLI, voice, GUI, mobile) implement ConfirmationProvider; the
engine only sees ConfirmationRequest -> ConfirmationChoice."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Mapping

from jarvis.permissions.levels import PermissionLevel

log = logging.getLogger("jarvis.security")


class ConfirmationChoice(str, Enum):
    DENY = "deny"
    ALLOW_ONCE = "allow_once"        # exactly this call
    ALLOW_SESSION = "allow_session"  # this action on this resource until the session ends / expires


@dataclass(frozen=True)
class ConfirmationRequest:
    """Everything a UI needs, already redacted. Plain data, so it can be rendered or spoken anywhere."""
    request_id: str
    tool: str
    action: str
    level: PermissionLevel
    resource: str | None = None
    reason: str = ""
    context: Mapping[str, str] = field(default_factory=dict)
    session_allowed: bool = True   # may the provider offer "allow for this session"?

    @property
    def summary(self) -> str:
        """One sentence (suitable for speech)."""
        target = f" auf {self.resource}" if self.resource else ""
        return f"JARVIS möchte die Aktion „{self.action}“ mit „{self.tool}“{target} ausführen."

    def to_text(self) -> str:
        lines = [self.summary, f"  Aktion: {self.action}", f"  Werkzeug: {self.tool}"]
        if self.resource:
            lines.append(f"  Ziel: {self.resource}")
        lines.append(f"  Risiko: {self.level.value.upper()}")
        if self.reason:
            lines.append(f"  Grund: {self.reason}")
        for k, v in self.context.items():
            lines.append(f"  {k}: {v}")
        lines.append("Erlauben?")
        return "\n".join(lines)


class ConfirmationProvider(ABC):
    @abstractmethod
    def confirm(self, request: ConfirmationRequest) -> ConfirmationChoice:
        """Ask the user. Any failure/ambiguity must be answered with DENY (the engine also fails closed)."""


class DenyAllConfirmation(ConfirmationProvider):
    """Used when nobody can be asked (headless): every confirmation is declined."""

    def confirm(self, request: ConfirmationRequest) -> ConfirmationChoice:
        return ConfirmationChoice.DENY


class ScriptedConfirmation(ConfirmationProvider):
    """Plays back prepared answers (tests, demos). Runs out -> DENY. Records every request it saw."""

    def __init__(self, choices: Iterable[ConfirmationChoice | str] = ()) -> None:
        self._choices = [ConfirmationChoice(c) for c in choices]
        self.requests: list[ConfirmationRequest] = []

    def confirm(self, request: ConfirmationRequest) -> ConfirmationChoice:
        self.requests.append(request)
        return self._choices.pop(0) if self._choices else ConfirmationChoice.DENY


class CliConfirmation(ConfirmationProvider):
    """Terminal prompt. Only an explicit 'j'/'ja'/'y'/'yes' (once) or 's'/'sitzung'/'session' is a yes;
    empty input, anything unknown, EOF and Ctrl-C all mean no."""

    ONCE = {"j", "ja", "y", "yes"}
    SESSION = {"s", "sitzung", "session"}

    def __init__(self, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print) -> None:
        self._input, self._output = input_fn, output_fn

    def bind_io(self, input_fn: Callable[[str], str], output_fn: Callable[[str], None]) -> None:
        self._input, self._output = input_fn, output_fn

    def confirm(self, request: ConfirmationRequest) -> ConfirmationChoice:
        self._output(request.to_text())
        options = "[j]a, einmal / [s]itzung / [N]ein: " if request.session_allowed else "[j]a, einmal / [N]ein: "
        try:
            answer = self._input(options).strip().casefold()
        except (EOFError, KeyboardInterrupt):
            self._output("Keine Antwort – abgelehnt.")
            return ConfirmationChoice.DENY
        if answer in self.ONCE:
            return ConfirmationChoice.ALLOW_ONCE
        if answer in self.SESSION and request.session_allowed:
            return ConfirmationChoice.ALLOW_SESSION
        if answer not in ("", "n", "nein", "no"):
            self._output("Nicht verstanden – abgelehnt.")
        return ConfirmationChoice.DENY
