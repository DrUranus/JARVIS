"""Errors of the research layer. Runtime conditions (a source is unreachable, a URL is refused) are part of the RESULT; these are for malformed requests."""
from __future__ import annotations

from jarvis.errors import JarvisError


class ResearchError(JarvisError):
    """Base class of the research layer."""


class InvalidResearchRequest(ResearchError):
    """The task input is not a valid research request."""
