"""UI contract v1 (backlog step ui-contract-v1): versioned events and commands between a backend and a user interface. Standard library only; nothing in JARVIS uses it yet.
See docs/UI_CONTRACT.md."""
from jarvis.ui_contract.backend import UiBackend
from jarvis.ui_contract.conformance import ConformanceHooks, run_conformance
from jarvis.ui_contract.fake import FakeClock, FakeUiBackend
from jarvis.ui_contract.schema import (COMMAND_TYPES, EVENT_TYPES, MAX_TEXT, VERSION, ContractError, command_schema, event_schema, parse_command, validate_command,
                                       validate_event)

__all__ = ["UiBackend", "ConformanceHooks", "run_conformance", "FakeClock", "FakeUiBackend", "COMMAND_TYPES", "EVENT_TYPES", "MAX_TEXT", "VERSION", "ContractError",
           "command_schema", "event_schema", "parse_command", "validate_command", "validate_event"]
