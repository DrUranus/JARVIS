"""Allowlisted Premium display assets on the existing authenticated server."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from jarvis.control_center.server import ControlCenterServer

ROOT = Path(__file__).parent
PREVIEW = ROOT / "nexus_preview"
UPSTREAM = ROOT / "nexus_ultimate"
ASSETS = {
    "core.js": UPSTREAM, "core-geometry.js": UPSTREAM, "core-backends.js": UPSTREAM, "core-shaders.js": UPSTREAM,
    "styles.css": UPSTREAM, "polish.css": UPSTREAM, "space.webp": UPSTREAM, "nexus.svg": UPSTREAM,
    "preview.js": PREVIEW, "host.css": PREVIEW, "surface.css": PREVIEW,
}
MIME = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".webp": "image/webp"}

# Fixed distribution contents for the pinned 1.1.0 release. An editable
# checkout may contain unrelated files and must never add them to the download.
DEMO_FILES = (
    "index.html", "app.js", "model.js", "views.js", "icons.js", "core.js", "core-geometry.js", "core-backends.js",
    "core-shaders.js", "fonts.css", "styles.css", "polish.css", "space.webp", "nexus.svg",
    "fonts/barlow-400.ttf", "fonts/barlow-600.ttf", "fonts/barlow-700.ttf", "fonts/ibm-plex-mono-400.ttf",
    "fonts/zalando-sans-expanded-600.ttf", "fonts/LICENSE-barlow.txt", "fonts/LICENSE-ibmplexmono.txt",
    "fonts/LICENSE-zalandosansexpanded.txt",
)


@lru_cache(maxsize=1)
def standalone_archive() -> bytes:
    """Distribute the unmodified local workspace outside the authenticated UI."""
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name in DEMO_FILES:
            archive.writestr("nexus/" + name, (UPSTREAM / name).read_bytes())
        archive.writestr("STARTEN.txt", (
            "JARVIS NEXUS Ultimate 1.1.0 – eigenständiger lokaler Workspace\n"
            "Archiv entpacken und im Ordner mit STARTEN.txt ausführen:\n"
            "python -m http.server 4173 --bind 127.0.0.1 --directory nexus\n"
            "Danach http://127.0.0.1:4173 öffnen. Strg+C beendet den lokalen Dateiserver.\n"
            "Dieses Paket enthält die Offline-Demo. Es benötigt keinen JARVIS-Sitzungsschlüssel.\n"
        ).encode("utf-8"))
    return stream.getvalue()


class NexusPreviewServer(ControlCenterServer):
    def static_resource(self, path, query):
        original = super().static_resource(path, query)
        token = quote(self.token, safe="").encode("ascii")
        if original is not None:
            if path not in ("/", "/index.html") or query.get("view") != ["nexus"]:
                return original
            body, mime = original
            pages = (PREVIEW / "pages.html").read_bytes().replace(b"__TOKEN__", token)
            body = body.replace(b"</head>", b'<link rel="stylesheet" href="/nexus/host.css?t=' + token + b'"></head>')
            body = body.replace(b'</header>', b'<button id="nexus-toggle" hidden type="button" aria-controls="nexus-preview-host">NEXUS Ultimate</button></header>')
            content = (b'<div id="nexus-preview-host" hidden></div>' + pages +
                       b'<script src="/nexus/preview.js?t=' + token + b'"></script>')
            return body.replace(b'<script src="app.js?', content + b'<script src="app.js?'), mime
        if path == "/nexus/standalone.zip":
            return standalone_archive(), "application/zip"
        name = path.removeprefix("/nexus/")
        if not path.startswith("/nexus/") or name not in ASSETS:
            return None
        file = ASSETS[name] / name
        body = file.read_bytes()
        if file.suffix == ".js" and ASSETS[name] == UPSTREAM:
            # ESM resolves imported URLs independently; queries are not inherited.
            for module in ("core-shaders.js", "core-geometry.js", "core-backends.js"):
                ref = b'"./' + module.encode()
                body = body.replace(ref + b'"', ref + b"?t=" + token + b'"')
        elif name in ("styles.css", "polish.css"):
            # Shadow-scoped theme, using the upstream fallback font stacks.
            body = body.replace(b'@import url("./fonts.css");', b"").replace(b":root", b":host")
            body = body.replace(b'"./space.webp"', b'"./space.webp?t=' + token + b'"')
        return body, MIME[file.suffix]
