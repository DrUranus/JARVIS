"""A tiny local web site for the real-browser tests: harmless, deterministic, no external network."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

INDEX = """<!doctype html><html><head><title>JARVIS Test Page</title></head><body>
<h1>Test Heading</h1>
<p>Opening hours: Mon-Fri 9-17</p>
<a href="/second">Second page</a>
<button id="b1" type="button" onclick="document.getElementById('out').textContent='clicked'">Press me</button>
<span id="out">idle</span>
<form id="f1" action="/search" method="get">
  <label for="q">Search term</label><input id="q" name="q" type="text">
  <label for="c">Colour</label><select id="c" name="c"><option>red</option><option>green</option><option>blue</option></select>
  <label><input type="checkbox" name="n" value="1"> Newsletter</label>
  <input type="submit" value="Go search">
</form>
<button id="mut" type="button" onclick="document.getElementById('b1').textContent='Delete everything'">Mutate</button>
<label for="up">Attachment</label><input id="up" type="file" onchange="document.getElementById('upn').textContent=this.files[0].name">
<span id="upn">nofile</span>
<a href="/login">Sign in</a>
<a href="/files/hello.txt" download>Download hello</a>
<a href="/files/tool.exe" download>Download tool</a>
<a href="/redirect">Redirecting link</a>
<a href="/popup" target="_blank">Popup link</a>
<button id="auto" type="button" onclick="location.href='/files/hello.txt'">Sneaky download</button>
</body></html>"""

LOGIN = """<!doctype html><html><head><title>Sign in</title></head><body><h1>Login</h1>
<form action="/login" method="post"><input name="user" type="text" aria-label="Username">
<input name="pw" type="password" aria-label="Password"><input type="submit" value="Log in"></form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a: object) -> None:  # silence
        pass

    def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8", status: int = 200, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        u = urlsplit(self.path)
        if u.path == "/":
            self._send(INDEX.encode())
        elif u.path == "/second":
            self._send(b"<html><head><title>Second</title></head><body><h1>Second page</h1><a href='/'>Back home</a></body></html>")
        elif u.path == "/search":
            q = parse_qs(u.query).get("q", [""])[0]
            self._send(f"<html><head><title>Results</title></head><body><h1>Results</h1><p>You searched: {q}</p></body></html>".encode())
        elif u.path == "/login":
            self._send(LOGIN.encode())
        elif u.path == "/popup":
            self._send(b"<html><head><title>Popup</title></head><body>popup</body></html>")
        elif u.path == "/redirect":
            self._send(b"", status=302, extra={"Location": "http://169.254.169.254/latest/meta-data/"})
        elif u.path == "/slow":
            time.sleep(3)
            self._send(b"<html><body>slow</body></html>")
        elif u.path.startswith("/files/"):
            name = u.path.rsplit("/", 1)[1]
            self._send(b"hello download\n" if name.endswith(".txt") else b"MZ-not-really-a-program",
                       "application/octet-stream", extra={"Content-Disposition": f'attachment; filename="{name}"'})
        else:
            self._send(b"not found", status=404)

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        self._send(b"<html><head><title>Posted</title></head><body>posted</body></html>")


@contextmanager
def serve() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
