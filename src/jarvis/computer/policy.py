"""Baseline policy rules for computer control, merged into the engine's policy at startup.

These are ordinary engine rules (visible in /permissions, audited as a policy change). `confirm` means "ask every
time and never offer a session permission"; because deny > confirm > allow, a user `allow` rule cannot silently
switch these questions off - only the explicit config flags can.
"""
from __future__ import annotations

from jarvis.computer import resources as res
from jarvis.config import ComputerSettings
from jarvis.permissions import Effect, Rule

BASELINE_PREFIX = "computer-baseline-"


def baseline_rules(settings: ComputerSettings) -> list[Rule]:
    rules: list[Rule] = []
    if settings.confirm_keyboard_each_time:
        rules.append(Rule(id=BASELINE_PREFIX + "keyboard-confirm", effect=Effect.CONFIRM, tool=res.TOOL_KEYBOARD,
                          description="Keyboard input is always confirmed (it can type anything into the active window)"))
    if settings.confirm_window_close_each_time:
        rules.append(Rule(id=BASELINE_PREFIX + "window-close-confirm", effect=Effect.CONFIRM, tool=res.TOOL_WINDOW,
                          action="close", description="Closing a window is always confirmed (unsaved work may be lost)"))
    return rules
