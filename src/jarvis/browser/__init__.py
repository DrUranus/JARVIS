"""Browser agent v1: a browser behind provider interfaces, every action a permission-checked tool call.

The Core never imports this package or an automation library. `bootstrap` builds a BrowserSubsystem (one tool in the
ToolRegistry + baseline rules in the PermissionEngine). Independent of Computer Control: it has its own controller and
never drives the mouse or keyboard of the PC.
"""
from jarvis.browser.backend import BrowserPage, BrowserProvider, BrowserSession, UrlGuard
from jarvis.browser.controller import BrowserController, Plan
from jarvis.browser.errors import BrowserError, BrowserErrorCode, BrowserUnavailableError
from jarvis.browser.models import ElementInfo, ElementRef, LaunchOptions, PageInfo, PageSnapshot
from jarvis.browser.urls import UrlPolicy, UrlVerdict, safe_url

__all__ = [
    "BrowserController", "Plan", "BrowserProvider", "BrowserSession", "BrowserPage", "UrlGuard", "BrowserError",
    "BrowserErrorCode", "BrowserUnavailableError", "ElementInfo", "ElementRef", "LaunchOptions", "PageInfo",
    "PageSnapshot", "UrlPolicy", "UrlVerdict", "safe_url",
]
