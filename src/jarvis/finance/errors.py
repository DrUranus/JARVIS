"""Errors of the finance layer. Missing data is NOT an error (the metric is UNKNOWN); these are for malformed input and forbidden operations."""
from __future__ import annotations

from jarvis.errors import JarvisError


class FinanceError(JarvisError):
    """Base class of the finance layer."""


class InvalidFinanceInput(FinanceError):
    """A number, symbol or structure in the request is not valid."""


class LiveTradingNotSupported(FinanceError):
    """Orders, transfers, withdrawals and broker access do not exist in this version."""
