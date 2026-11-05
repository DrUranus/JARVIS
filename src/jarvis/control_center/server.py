"""Lokaler Control-Center-Server (cc-shell): `ThreadingHTTPServer` ausschliesslich auf 127.0.0.1, Zufalls-Token, Pruefung von Host und Origin, Ereignisse per Server-Sent
Events, Befehle per POST (Groessenlimit vor dem Parsen, `parse_command`). Er reicht nur Vertragsbefehle an ein `UiBackend` weiter; er kennt weder Werkzeuge noch Rechte."""
from __future__ import annotations

import hmac
import json
import secrets
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from jarvis.control_center.views import ReadViews, ViewError
from jarvis.ui_contract.backend import UiBackend
from jarvis.ui_contract.schema import MAX_COMMAND_BYTES, VERSION, ContractError, parse_command

LOOPBACK = "127.0.0.1"
WEB_DIR = Path(__file__).parent / "web"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/core_states.json": ("core_states.json", "application/json; charset=utf-8")}
VIEW_PATHS = {"/view/history": "history", "/view/audit": "audit"}   # nur GET, nur lesend
MIN_TOKEN_LEN = 16
MAX_SEQ = 2**53


class _Httpd(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class ControlCenterServer:
    def __init__(self, backend: UiBackend, *, host: str = LOOPBACK, port: int = 0, token: str | None = None, poll_interval: float = 0.25,
                 heartbeat_s: float = 15.0, max_clients: int = 4, views: ReadViews | None = None) -> None:
        if host != LOOPBACK:
            raise ValueError("the control center listens on 127.0.0.1 only")
        if token is not None and len(token) < MIN_TOKEN_LEN:
            raise ValueError("token too short")
        self.backend, self.host, self._want_port = backend, host, port
        self.views = views                                            # nur lesende Ansichten (cc-results-audit); ohne sie gibt es keine /view-Pfade
        self.token = token or secrets.token_urlsafe(32)
        self.poll_interval, self.heartbeat_s, self.max_clients = poll_interval, heartbeat_s, max_clients
        self.port: int | None = None
        self._httpd: _Httpd | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._backend_lock = threading.Lock()
        self._clients = 0
        self._clients_lock = threading.Lock()

    # ---- Lebenszyklus (nur auf ausdruecklichen Aufruf) ------------------------------------------------------------------------------------
    @property
    def url(self) -> str:
        if self.port is None:
            raise RuntimeError("server not started")
        return f"http://{self.host}:{self.port}/?t={self.token}"

    def start(self) -> None:
        if self._httpd is not None:
            raise RuntimeError("already started")
        self._stop.clear()
        httpd = _Httpd((self.host, self._want_port), _make_handler(self))
        self._httpd, self.port = httpd, httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, name="jarvis-control-center", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        httpd, thread = self._httpd, self._thread
        if httpd is None:
            return
        self._stop.set()
        httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(timeout=5)
        self._httpd = self._thread = None

    # ---- Hilfen ---------------------------------------------------------------------------------------------------------------------------
    def _allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def _allowed_origins(self) -> set[str]:
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def _token_ok(self, supplied: str | None) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8", "replace"), self.token.encode())

    def _call(self, fn, *args):
        with self._backend_lock:
            return fn(*args)

    def _client_joined(self) -> bool:
        with self._clients_lock:
            if self._clients >= self.max_clients:
                return False
            self._clients += 1
            return True

    def _client_left(self) -> None:
        with self._clients_lock:
            self._clients -= 1
            last = self._clients == 0
        if last and not self._stop.is_set():
            try:
                self._call(self.backend.detach)  # Oberflaeche weg -> offene Rueckfragen gelten als abgelehnt
            except Exception:
                pass


def _make_handler(srv: ControlCenterServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "JarvisControlCenter"
        sys_version = ""
        protocol_version = "HTTP/1.0"

        def log_message(self, format: str, *args: Any) -> None:  # keine Zugriffsprotokolle (die URL enthaelt das Token)
            pass

        # ---- gemeinsame Antworten --------------------------------------------------------------------------------------------------------
        def _headers(self, status: int, ctype: str, length: int | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Permissions-Policy", "microphone=(), camera=(), geolocation=()")  # die Seite selbst bekommt nie Mikrofon oder Kamera

        def _reply(self, status: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8") -> None:
            self._headers(status, ctype, len(body))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, obj: Any) -> None:
            self._reply(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        # ---- Pruefungen: Host -> Origin -> Token -----------------------------------------------------------------------------------------
        def _guard(self, *, need_origin: bool) -> tuple[str, dict[str, list[str]]] | None:
            if (self.headers.get("Host") or "").lower() not in srv._allowed_hosts():
                self._reply(403, b"forbidden")
                return None
            origin = self.headers.get("Origin")
            if origin is None and need_origin:
                self._reply(403, b"forbidden")
                return None
            if origin is not None and origin not in srv._allowed_origins():
                self._reply(403, b"forbidden")
                return None
            parts = urlsplit(self.path)
            query = parse_qs(parts.query, keep_blank_values=True)
            supplied = self.headers.get("X-JARVIS-Token") or (query.get("t") or [""])[0]
            if not srv._token_ok(supplied):
                self._reply(401, b"unauthorized")
                return None
            return parts.path, query

        # ---- Methoden ----------------------------------------------------------------------------------------------------------------------
        def do_GET(self) -> None:
            checked = self._guard(need_origin=False)
            if checked is None:
                return
            path, query = checked
            if path == "/events":
                self._events(query)
            elif path in VIEW_PATHS and srv.views is not None:
                self._view(path, query)
            elif path in STATIC:
                name, ctype = STATIC[path]
                try:
                    body = (WEB_DIR / name).read_bytes()
                except OSError:
                    self._reply(404, b"not found")
                    return
                if name == "index.html":
                    body = body.replace(b"__TOKEN__", srv.token.encode())
                self._reply(200, body, ctype)
            else:
                self._reply(404, b"not found")

        def _view(self, path: str, query: dict[str, list[str]]) -> None:
            """Lesende Ansicht (GET): Filter aus der Query, Antwort als JSON. Keine Wirkung ausser dem Lesen."""
            params = {k: v[0] for k, v in query.items() if k != "t"}
            if any(len(v) != 1 for k, v in query.items() if k != "t"):
                self._json(400, {"error": "each parameter may be given once"})
                return
            try:
                self._json(200, getattr(srv.views, VIEW_PATHS[path])(params))
            except ViewError as exc:
                self._json(400, {"error": str(exc)})
            except Exception:                                                      # noqa: BLE001 - keine Interna nach aussen
                self._json(500, {"error": "view unavailable"})

        def do_POST(self) -> None:
            checked = self._guard(need_origin=True)
            if checked is None:
                return
            path, _ = checked
            if path != "/command":
                self._reply(404, b"not found")
                return
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                self._reply(415, b"json required")
                return
            raw_len = self.headers.get("Content-Length")
            if raw_len is None or not raw_len.isascii() or not raw_len.isdigit():
                self._reply(411 if raw_len is None else 400, b"bad length")
                return
            length = int(raw_len)
            if length > MAX_COMMAND_BYTES:
                self._reply(413, b"too large")
                return
            body = self.rfile.read(length)
            try:
                command = parse_command(body)
            except ContractError:
                raw_id = _safe_id(body)
                self._json(400, _reject_ack(raw_id))
                return
            self._json(200, srv._call(srv.backend.send, command))

        def _method_not_allowed(self) -> None:
            if self._guard(need_origin=False) is not None:
                self._reply(405, b"method not allowed")

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _method_not_allowed

        # ---- Server-Sent Events ----------------------------------------------------------------------------------------------------------
        def _events(self, query: dict[str, list[str]]) -> None:
            raw = (query.get("since") or [self.headers.get("Last-Event-ID") or ""])[0]
            since: int | None = None
            if raw != "":
                if not raw.isascii() or not raw.isdigit() or int(raw) > MAX_SEQ:
                    self._reply(400, b"bad since")
                    return
                since = int(raw)
            if not srv._client_joined():
                self._reply(503, b"too many clients")
                return
            try:
                self._headers(200, "text/event-stream; charset=utf-8")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                first = srv._call(srv.backend.snapshot) if since is None else srv._call(srv.backend.events_since, since, 1000)
                last = since or 0
                self._write(first)
                last = max([last] + [e["seq"] for e in first])
                idle = 0.0
                while not srv._stop.wait(srv.poll_interval):
                    if self._peer_gone():
                        break
                    batch = srv._call(srv.backend.events_since, last, 200)
                    if batch:
                        self._write(batch)
                        last = batch[-1]["seq"]
                        idle = 0.0
                    else:
                        idle += srv.poll_interval
                        if idle >= srv.heartbeat_s:
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                            idle = 0.0
            except OSError:
                pass  # Client weg
            finally:
                srv._client_left()

        def _peer_gone(self) -> bool:
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                return True

        def _write(self, events: list[dict[str, Any]]) -> None:
            if not events:
                return
            out = b"".join(f"id: {e['seq']}\nevent: message\ndata: {json.dumps(e, ensure_ascii=False)}\n\n".encode("utf-8") for e in events)
            self.wfile.write(out)
            self.wfile.flush()

    return Handler


def _safe_id(body: bytes) -> str:
    try:
        obj = json.loads(body.decode("utf-8"))
        cid = obj.get("id") if isinstance(obj, dict) else None
        if isinstance(cid, str) and 0 < len(cid) <= 64 and all(c.isalnum() or c in "_.:-" for c in cid) and cid.isascii():
            return cid
    except (ValueError, UnicodeDecodeError):
        pass
    return "invalid"


def _reject_ack(cid: str) -> dict[str, Any]:
    """Ack fuer einen Befehl, der den Vertrag verletzt (kommt nie beim Backend an)."""
    import datetime as dt
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"v": VERSION, "seq": 0, "ts": ts, "type": "ack", "data": {"id": cid, "ok": False, "code": "invalid_command", "message": "the command does not follow the contract"}}
