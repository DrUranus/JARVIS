"""Errors of the business layer. Missing data is not an error (the entry is UNKNOWN); these are for malformed input."""
from __future__ import annotations

from jarvis.errors import JarvisError


class BusinessError(JarvisError):
    """Base class of the business layer."""


class InvalidBusinessInput(BusinessError):
    """A number or structure in the request is not valid."""
