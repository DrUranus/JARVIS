"""Opt-in and packaging boundaries for the read-only Premium view."""
import http.client
from io import BytesIO
from zipfile import ZipFile
from pathlib import Path

from jarvis.control_center.server import ControlCenterServer, CSP
from jarvis.ui_contract.fake import FakeUiBackend


def get(server, path, token=True):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", path, headers={"X-JARVIS-Token": server.token} if token else {})
    response = conn.getresponse()
    result = response.status, response.getheader("Content-Security-Policy"), response.read()
    conn.close()
    return result


def test_preview_mount_and_dependencies_stay_authenticated_and_opt_in():
    from jarvis.control_center.nexus_assets import NexusPreviewServer
    for enabled in (False, True):
        server = (NexusPreviewServer if enabled else ControlCenterServer)(FakeUiBackend())
        server.start()
        try:
            assert b'nexus-preview-host' not in get(server, "/")[2]
            for path in ("/nexus/core.js", "/nexus/preview.js", "/?view=nexus"):
                assert get(server, path, token=False)[0] == 401
            if enabled:
                status, policy, html = get(server, "/?view=nexus")
                assert status == 200 and policy == CSP
                assert html.count(b'data-nexus-page=') == 11
                assert b'id="confirm-dialog"' in html and b'id="emergency"' in html
                assert b'nexus-preview-host' in html
                assert b'__TOKEN__' not in html
                for asset in ("core.js", "core-shaders.js", "core-geometry.js", "core-backends.js", "preview.js", "styles.css", "polish.css", "space.webp", "nexus.svg"):
                    status, policy, content = get(server, "/nexus/" + asset)
                    assert status == 200 and policy == CSP and content
                status, policy, archive = get(server, "/nexus/standalone.zip")
                assert status == 200 and policy == CSP
                with ZipFile(BytesIO(archive)) as zipped:
                    assert zipped.testzip() is None
                    assert "nexus/app.js" in zipped.namelist()
                    assert "nexus/fonts/barlow-400.ttf" in zipped.namelist()
                    assert all(server.token.encode() not in zipped.read(n) for n in zipped.namelist())
                assert server.token.encode() in get(server, "/nexus/core.js")[2]
            else:
                assert b'nexus-preview-host' not in get(server, "/?view=nexus")[2]
                assert get(server, "/nexus/core.js")[0] == 404
            for name in ("app.js", "views.js", "../bootstrap.py", "index.html"):
                assert get(server, "/nexus/" + name)[0] == 404
        finally:
            server.stop()


def test_display_module_has_no_command_or_second_stream():
    root = Path(__file__).resolve().parents[1] / "src/jarvis/control_center"
    source = (root / "nexus_preview/preview.js").read_text()
    for forbidden in ("EventSource(", "fetch(", "XMLHttpRequest", "sendBeacon", "innerHTML", "srcdoc", "/command"):
        assert forbidden not in source
