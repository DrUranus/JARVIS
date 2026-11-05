"""Startbefehl des Control Centers (`jarvis-cc`, cc-backend-binding): verbindet die lokale Weboberflaeche mit dem ECHTEN `UiBackend` des Assistenten.

Nichts startet von selbst: nur der ausdrueckliche Aufruf von `main()`, nur mit `control_center.enabled = true` (Standard aus) und nur mit aktivem Assistenten
(`assistant.enabled`, dessen Adapter ist das Backend). Der Server lauscht ausschliesslich auf 127.0.0.1. Dieses Modul fuehrt kein Werkzeug aus, kennt weder
Berechtigungen noch Notaus-Zustand und hat keinen eigenen Freigabeweg: Befehle gehen als Vertragsbefehle an den Adapter, der sie an den Controller und damit an
die PermissionEngine weitergibt (`ToolRegistry.execute -> PermissionEngine`). Das Fake-Backend gibt es hier nicht (es dient nur Tests)."""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from typing import Any, Sequence

from jarvis.bootstrap import build_core
from jarvis.config import Settings, load_settings
from jarvis.control_center.server import ControlCenterServer
from jarvis.control_center.views import ReadViews
from jarvis.errors import JarvisError


class LauncherError(JarvisError):
    """The control center must not be started (disabled, or no real backend)."""


def build_server(settings: Settings, core: Any) -> ControlCenterServer:
    """The server for the real backend of `core`. Listens on nothing until `.start()`. Raises LauncherError instead of falling back to anything else."""
    if not settings.control_center.enabled:
        raise LauncherError("Das Control Center ist aus (control_center.enabled = false). Aktivieren: control_center.enabled = true "
                            "(bzw. JARVIS_CONTROL_CENTER_ENABLED=true) – zusammen mit assistant.enabled und agents.enabled.")
    assistant = core.subsystems.get("assistant")
    ui = getattr(assistant, "ui", None)
    if ui is None:
        reason = getattr(assistant, "reason", "") or "kein Assistent"
        raise LauncherError(f"Kein echtes Backend: der Assistent ist nicht aktiv ({reason}). Nötig: assistant.enabled = true und agents.enabled = true.")
    return ControlCenterServer(ui, views=build_views(core, assistant))


def build_views(core: Any, assistant: Any) -> ReadViews:
    """Nur lesende Ansichten: Journal-Speicher des Assistenten (falls aktiv) und die `tail`-Funktion des Audit-Protokolls. Fehlt eines, meldet die Ansicht das leer."""
    store = getattr(getattr(assistant, "journal", None), "store", None)
    audit = getattr(getattr(core, "permissions", None), "audit", None)
    return ReadViews(journal=store, audit_tail=getattr(audit, "tail", None))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jarvis-cc", description="JARVIS Control Center (lokale Weboberfläche, nur 127.0.0.1)")
    ap.add_argument("-c", "--config", help="Pfad zu einer TOML-Konfiguration")
    ap.add_argument("--open", action="store_true", help="URL im Systembrowser öffnen (sonst nur ausgeben)")
    args = ap.parse_args(argv)
    try:
        settings = load_settings(args.config or _default_config())
        if not settings.control_center.enabled:               # vor jedem Aufbau: ein ausgeschaltetes Control Center baut nichts
            build_server(settings, None)
        core = build_core(settings)
        server = build_server(settings, core)
    except JarvisError as exc:
        print(f"Startfehler: {exc}", file=sys.stderr)
        return 2
    server.start()
    print(f"Control Center (echtes Backend, nur Loopback): {server.url}\nBeenden mit Strg+C.")
    if args.open:
        webbrowser.open(server.url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def _default_config() -> str | None:
    from jarvis.interface.cli import _default_config as default
    return default()


if __name__ == "__main__":
    raise SystemExit(main())
