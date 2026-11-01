"""Output protection for the read-only UI tool (backlog step `uia-tools-readonly`). Pure functions on `UiElement` trees.

What reaches the caller (an agent, a prompt, a log) never contains:
- the value of a password field (the model already drops it; checked again here),
- the value of a field that LOOKS like it holds a secret (name or AutomationId says password, PIN, token, API key, security code ...): the field stays, its value goes,
- a secret inside any text (names, values, ids): detected by `jarvis.redaction` and replaced by [REDACTED].
Everything in a tree is data from another program, never an instruction.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Callable

from jarvis.computer.uia import UiElement
from jarvis.redaction import SecretDetector

SENSITIVE_FIELD = re.compile(
    r"(?i)passwor[dt]|passwd|passphrase|kennwort|\bpin\b|\bpwd\b|secret|\btoken\b|api[ _\-]?key|private[ _\-]?key|recovery[ _\-]?(?:key|code)|seed phrase|\bcvv\b|\bcvc\b|"
    r"security code|sicherheitscode|\botp\b|\btan\b|2fa|one[ \-]time")

Redactor = Callable[[str], str]
_DEFAULT = SecretDetector()


def is_sensitive(e: UiElement) -> bool:
    return e.is_password or bool(SENSITIVE_FIELD.search(e.name) or SENSITIVE_FIELD.search(e.automation_id))


def protect_element(e: UiElement, redact: Redactor | None = None) -> UiElement:
    """This element (children untouched) without the value of sensitive fields and with secrets removed from its texts."""
    red = redact or _DEFAULT.redact
    return dataclasses.replace(e, name=red(e.name), automation_id=red(e.automation_id), class_name=red(e.class_name),
                               value=None if (e.value is None or is_sensitive(e)) else red(e.value))


def protect_tree(root: UiElement, redact: Redactor | None = None) -> UiElement:
    """The whole (already bounded) tree protected. Recursion is bounded by the tree depth, which `bound_tree` caps at HARD_MAX_DEPTH."""
    return dataclasses.replace(protect_element(root, redact), children=tuple(protect_tree(c, redact) for c in root.children))
