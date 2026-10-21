"""Hooks for a future vision agent (not implemented here).

A vision-capable model plugs in by implementing `ImageObserver`; it receives a `Screenshot` object from the
in-memory store (never a file path, never an automatic upload). Contract: observers must run locally unless the
user has explicitly configured an external service, and must be invoked by explicit code, never implicitly by
the controller. `verify_change` is the dependency-free verification step of action -> observe -> verify.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from jarvis.computer.models import FrameDiff, Screenshot
from jarvis.computer.screenshots import frame_diff


@dataclass(frozen=True)
class Observation:
    text: str
    confidence: float | None = None


class ImageObserver(ABC):
    @abstractmethod
    def observe(self, screenshot: Screenshot, instruction: str) -> Observation:
        """Describe / answer a question about a screenshot."""


@dataclass(frozen=True)
class Verification:
    ok: bool
    detail: str
    diff: FrameDiff


def verify_change(before: Screenshot, after: Screenshot, *, expect_change: bool = True,
                  min_changed_ratio: float = 0.0001) -> Verification:
    """Did the screen change (or stay the same) as expected between two screenshots?"""
    diff = frame_diff(before, after)
    if not diff.comparable:
        return Verification(expect_change, "frames differ in size or format (treated as changed)", diff)
    changed = diff.changed_ratio >= min_changed_ratio
    if expect_change:
        return Verification(changed, f"{diff.changed_ratio:.4%} of pixels changed" if changed
                            else "expected a screen change but the frames are (almost) identical", diff)
    return Verification(not changed, "screen unchanged as expected" if not changed
                        else f"unexpected change: {diff.changed_ratio:.4%} of pixels", diff)
