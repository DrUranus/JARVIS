"""Ausdruecklicher Start: `python -m jarvis.control_center [--open]`. Zeigt den Vertrag gegen das Fake-Backend (keine echte Aktion); der Browser oeffnet nur mit --open."""
from __future__ import annotations

import argparse
import threading
import webbrowser

from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.control_center", description="Control Center (Demo gegen FakeUiBackend, nur 127.0.0.1)")
    ap.add_argument("--open", action="store_true", help="URL im Systembrowser oeffnen (sonst nur ausgeben)")
    args = ap.parse_args(argv)
    server = ControlCenterServer(FakeUiBackend(name="fake-demo"))
    server.start()
    print(f"Control Center (Demo, Fake-Backend): {server.url}\nBeenden mit Strg+C.")
    if args.open:
        webbrowser.open(server.url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
