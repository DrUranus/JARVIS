"""Browser-driven Control Center GUI checks on Windows CI.

Scope: actual Chromium DOM/canvas/interaction with local FakeUiBackend.
Not a real native pywebview overlay, physical display, or live PermissionEngine acceptance.
"""
import os
from pathlib import Path

import pytest

from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows browser GUI gate only")


def test_control_center_browser_gui():
    from playwright.sync_api import sync_playwright

    evidence = Path("reports/gui")
    evidence.mkdir(parents=True, exist_ok=True)
    srv = ControlCenterServer(FakeUiBackend(), poll_interval=0.02)
    srv.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.goto(srv.url, wait_until="domcontentloaded")
                page.locator("#mode-toggle").wait_for()
                assert page.locator("body").get_attribute("data-mode") == "orb"
                assert page.locator("#emergency").is_visible()
                page.screenshot(path=str(evidence / "orb.png"), full_page=True)
                page.locator("#mode-toggle").click()
                assert page.locator("body").get_attribute("data-mode") == "dashboard"
                assert page.locator("#dashboard-view").is_visible()
                assert page.locator("#emergency").is_visible()
                page.screenshot(path=str(evidence / "dashboard.png"), full_page=True)
                page.locator("#effects").select_option("off")
                assert page.locator("#effects").input_value() == "off"
                page.locator("#mode-toggle").click()
                assert page.locator("body").get_attribute("data-mode") == "orb"
                assert not errors, f"Browser JavaScript errors: {errors}"
            finally:
                browser.close()
    finally:
        srv.stop()
