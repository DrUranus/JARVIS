"""Baseline policy rules for the browser, merged into the engine's policy at startup (visible in /permissions).

`confirm` means "ask every time and never offer a session permission"; deny > confirm > allow, so a user `allow` rule
cannot silently switch these questions off - only the explicit config flags can.
"""
from __future__ import annotations

from jarvis.browser import resources as res
from jarvis.config import BrowserSettings
from jarvis.permissions import Effect, Rule

BASELINE_PREFIX = "browser-baseline-"


def baseline_rules(settings: BrowserSettings) -> list[Rule]:
    rules: list[Rule] = []
    if settings.confirm_fill_each_time:
        rules.append(Rule(id=BASELINE_PREFIX + "fill-confirm", effect=Effect.CONFIRM, tool=res.TOOL, action="fill",
                          description="Typing into a web page is always confirmed (it can send anything to the site)"))
    if settings.confirm_file_transfer_each_time:
        for action in ("download", "upload"):
            rules.append(Rule(id=BASELINE_PREFIX + f"{action}-confirm", effect=Effect.CONFIRM, tool=res.TOOL, action=action,
                              description=f"A {action} is always confirmed"))
    return rules
