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
from typing import Any, Callable, Sequence

from jarvis.bootstrap import build_core
from jarvis.config import Settings, load_settings
from jarvis.control_center.overlay import OverlayUnavailable, start_overlay, webview_available
from jarvis.control_center.server import ControlCenterServer
from jarvis.control_center.views import ReadViews
from jarvis.errors import JarvisError


class LauncherError(JarvisError):
    """The control center must not be started (disabled, or no real backend)."""


def open_main_window(main_url: str) -> None:
    """Klick im Mini-Overlay: das Hauptfenster ist die Control-Center-Seite im Systembrowser (dieselbe Loopback-URL, ohne Overlay-Ansicht)."""
    webbrowser.open(main_url)


def build_server(settings: Settings, core: Any, on_open_main: Callable[[], None] | None = None) -> ControlCenterServer:
    """The server for the real backend of `core`. Listens on nothing until `.start()`. Raises LauncherError instead of falling back to anything else."""
    if not settings.control_center.enabled:
        raise LauncherError("Das Control Center ist aus (control_center.enabled = false). Aktivieren: control_center.enabled = true "
                            "(bzw. JARVIS_CONTROL_CENTER_ENABLED=true) – zusammen mit assistant.enabled und agents.enabled.")
    assistant = core.subsystems.get("assistant")
    ui = getattr(assistant, "ui", None)
    if ui is None:
        reason = getattr(assistant, "reason", "") or "kein Assistent"
        raise LauncherError(f"Kein echtes Backend: der Assistent ist nicht aktiv ({reason}). Nötig: assistant.enabled = true und agents.enabled = true.")
    return ControlCenterServer(ui, views=build_views(core, assistant, settings), on_open_main=on_open_main)


def build_views(core: Any, assistant: Any, settings: Settings | None = None) -> ReadViews:
    """Nur lesende Ansichten: Journal-Speicher des Assistenten (falls aktiv) und die `tail`-Funktion des Audit-Protokolls. Fehlt eines, meldet die Ansicht das leer."""
    store = getattr(getattr(assistant, "journal", None), "store", None)
    audit = getattr(getattr(core, "permissions", None), "audit", None)
    doctor = None
    if settings is not None:
        from jarvis.control_center.setup_view import build_report
        doctor = lambda: build_report(core, settings)                                  # noqa: E731 - nur lesend, bei jedem Abruf frisch
    return ReadViews(journal=store, audit_tail=getattr(audit, "tail", None), doctor=doctor)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jarvis-cc", description="JARVIS Control Center (lokale Weboberfläche, nur 127.0.0.1)")
    ap.add_argument("-c", "--config", help="Pfad zu einer TOML-Konfiguration")
    ap.add_argument("--open", action="store_true", help="URL im Systembrowser öffnen (sonst nur ausgeben)")
    ap.add_argument("--overlay", action="store_true", help="optionales Mini-Overlay (140x140, verschiebbar) öffnen; braucht pywebview (.[ui]), Standard aus")
    ap.add_argument("--overlay-on-top", action="store_true", help="Overlay immer im Vordergrund (nur mit --overlay)")
    args = ap.parse_args(argv)
    if args.overlay_on_top and not args.overlay:
        print("Startfehler: --overlay-on-top gilt nur zusammen mit --overlay.", file=sys.stderr)
        return 2
    if args.overlay and not webview_available():                # vor jedem Aufbau: ohne pywebview startet nichts
        print('Startfehler: pywebview ist nicht installiert (nur für das optionale Mini-Overlay nötig): pip install -e ".[ui]"', file=sys.stderr)
        return 2
    main_url: list[str] = []
    try:
        settings = load_settings(args.config or _default_config())
        if not settings.control_center.enabled:               # vor jedem Aufbau: ein ausgeschaltetes Control Center baut nichts
            build_server(settings, None)
        core = build_core(settings)
        server = build_server(settings, core, (lambda: open_main_window(main_url[0])) if args.overlay else None)
    except JarvisError as exc:
        print(f"Startfehler: {exc}", file=sys.stderr)
        return 2
    server.start()
    print(f"Control Center (echtes Backend, nur Loopback): {server.url}\nBeenden mit Strg+C.")
    main_url.append(server.url)
    if args.open:
        webbrowser.open(server.url)
    try:
        if args.overlay:
            try:
                start_overlay(server.url, on_top=args.overlay_on_top)   # blockiert bis das Overlay geschlossen wird; Server, Notaus (CLI/GUI) laufen unabhaengig
            except OverlayUnavailable as exc:
                print(f"Overlay nicht gestartet: {exc}", file=sys.stderr)
            print("Overlay beendet. Das Control Center läuft weiter (Strg+C beendet es).")
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
