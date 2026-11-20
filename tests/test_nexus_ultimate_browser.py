"""Premium preview on a real loopback server and ControllerUiBackend, headless only."""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from jarvis.bootstrap import build_core
from jarvis.permissions.confirmation import ConfirmationChoice, ConfirmationRequest
from jarvis.permissions.levels import PermissionLevel
from jarvis.control_center.launcher import build_server
from jarvis.config import load_settings
from test_control_center_binding import real_core, real_env


@pytest.fixture(scope="module")
def chromium_browser():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as api:
        try:
            browser = api.chromium.launch(executable_path=os.getenv("JARVIS_CHROMIUM_PATH") or None,
                                          args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        except sync.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Chromium fehlt: Browserprüfung nicht ausgeführt")
            raise
        yield browser
        browser.close()


def test_preview_in_existing_v1_session(tmp_path, monkeypatch, chromium_browser):
    sync = pytest.importorskip("playwright.sync_api")
    settings = load_settings(env=real_env(tmp_path))
    core = real_core(tmp_path)
    server = build_server(settings, core, nexus_preview=True)
    server.start()
    try:
        page = chromium_browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        posts, streams, errors, violations = [], [], [], []
        def request(req):
            if req.method == "POST":
                posts.append(urlsplit(req.url).path)
            if urlsplit(req.url).path == "/events":
                streams.append(req.method)
        page.on("request", request)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.expose_function("reportPolicy", lambda directive: violations.append(directive))
        page.add_init_script("addEventListener('securitypolicyviolation', e => reportPolicy(e.violatedDirective));")
        page.goto(server.url + "&view=nexus", wait_until="domcontentloaded")
        host = page.locator("#nexus-preview-host")
        sync.expect(host.get_by_role("heading", name="JARVIS", exact=True)).to_be_visible()
        banner = host.locator(".preview-status")
        sync.expect(banner).to_contain_text("Not-Aus inaktiv")
        # Data comes from the isolated controller adapter; no audio, user task or external provider.
        server.backend.publish("state", {"state":"listening"})
        sync.expect(host.locator("[data-current-state]")).to_have_text("Listening")
        sync.expect(host.locator("[data-backend]")).to_have_text(re.compile(r"^(WebGPU|WebGL 2|Canvas 2D)$"))
        if evidence := os.getenv("JARVIS_NEXUS_EVIDENCE"):
            Path(evidence).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(evidence) / "core.png"))
        for key in ("overview", "ai-core", "live-workspace", "agent-center", "creative-studio", "coding-studio",
                    "business-center", "trading-center", "automations", "memory-settings"):
            host.locator(f'a[href="#/{key}"]').first.click()
            sync.expect(host.locator("main")).to_have_class(re.compile(key))
            assert host.locator("canvas").count() == 1
            if evidence:
                page.screenshot(path=str(Path(evidence) / (key + ".png")))
        page.get_by_role("button", name="V1-Oberfläche").click()
        sync.expect(page.locator("#orb-view")).to_be_visible()
        page.get_by_role("button", name="NEXUS Ultimate · Leseansicht").click()
        assert streams == ["GET"] and not posts
        assert server._clients == 1
        # Existing V1 control reaches the real permission engine.
        page.locator("#emergency").click()
        sync.expect(banner).to_contain_text("Not-Aus aktiv")
        assert core.permissions.emergency.engaged
        assert posts == ["/command"]
        # Interrupt the real event stream once on the server side, without
        # making timing assumptions about port reuse after a process restart.
        original = server.backend.events_since
        def interrupt_once(*args):
            monkeypatch.setattr(server.backend, "events_since", original)
            raise OSError("controlled end of SSE stream")
        monkeypatch.setattr(server.backend, "events_since", interrupt_once)
        sync.expect(banner).to_contain_text("Not-Aus unbekannt", timeout=10000)
        sync.expect(banner).to_contain_text("Not-Aus aktiv", timeout=15000)
        assert server._clients == 1
        assert not errors and not violations, (errors, violations)
        page.close()
    finally:
        server.stop()


def test_two_windows_share_backend_decisions_and_deny_on_last_disconnect(tmp_path, chromium_browser):
    sync = pytest.importorskip("playwright.sync_api")
    settings = load_settings(env={**real_env(tmp_path), "JARVIS_ASSISTANT_CONFIRMATION_TIMEOUT_SECONDS": "5"})
    core = build_core(settings)
    server = build_server(settings, core, nexus_preview=True)
    server.start()
    context = chromium_browser.new_context(reduced_motion="reduce")
    try:
        preview = context.new_page()
        preview.goto(server.url + "&view=nexus", wait_until="domcontentloaded")
        fallback = context.new_page()
        fallback.goto(server.url, wait_until="domcontentloaded")
        sync.expect(preview.locator(".preview-status")).to_contain_text("verbunden")
        sync.expect(fallback.locator("#conn")).to_have_text("verbunden")
        assert server._clients == 2
        # Exercise only the real confirmation provider. No tool is called.
        req = ConfirmationRequest("preview-test", "display", "check", PermissionLevel.YELLOW,
                                  resource="local-test", session_allowed=False)
        provider = server.backend.confirmation_provider
        with ThreadPoolExecutor(max_workers=1) as pool:
            for choice in (ConfirmationChoice.DENY, ConfirmationChoice.ALLOW_ONCE):
                result = pool.submit(provider.confirm, req)
                for page in (preview, fallback):
                    sync.expect(page.locator("#confirm-dialog")).to_be_visible()
                    sync.expect(page.locator('[data-choice="deny"]')).to_be_focused()
                sync.expect(preview.locator("#nexus-toggle")).to_be_disabled()
                sync.expect(preview.locator("[data-current-state]")).to_have_text("Awaiting Approval")
                assert preview.locator("#nexus-preview-host").evaluate("(el) => el.inert")
                preview.locator(f'[data-choice="{choice.value}"]').click()
                assert result.result(timeout=8) == choice
                for page in (preview, fallback):
                    sync.expect(page.locator("#confirm-dialog")).to_be_hidden()
            timed = pool.submit(provider.confirm, req)
            sync.expect(preview.locator("#confirm-dialog")).to_be_visible()
            assert timed.result(timeout=9) == ConfirmationChoice.DENY
            sync.expect(preview.locator("#confirm-dialog")).to_be_hidden()
            disconnected = pool.submit(provider.confirm, req)
            sync.expect(preview.locator("#confirm-dialog")).to_be_visible()
            fallback.close()
            assert not disconnected.done()
            preview.close()
            assert disconnected.result(timeout=3) == ConfirmationChoice.DENY
            events = server.backend.events_since(0, 1000)
            assert [e["data"]["outcome"] for e in events if e["type"] == "confirmation_closed"][-4:] == [
                "denied", "allow_once", "timeout", "cancelled"]
    finally:
        context.close()
        server.stop()
