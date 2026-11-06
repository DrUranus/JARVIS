"""Testhost fuer den nativen Overlay-Test (NUR Tests): Control-Center-Server mit dem deterministischen FakeUiBackend und das echte pywebview-Overlay (start_overlay).
Der Produktivstart (`jarvis-cc`) kennt das Fake-Backend nicht. `on_open_main` schreibt eine Markierungsdatei statt einen Browser zu oeffnen (JARVIS_HOST_MARKER)."""
import os
import sys
from pathlib import Path

from jarvis.control_center.overlay import start_overlay
from jarvis.control_center.server import ControlCenterServer
from jarvis.ui_contract import FakeUiBackend

marker = Path(os.environ["JARVIS_HOST_MARKER"])
srv = ControlCenterServer(FakeUiBackend(), poll_interval=0.02, on_open_main=lambda: marker.write_text("opened", encoding="utf-8"))
srv.start()
print(f"HOST {srv.url}", flush=True)
try:
    start_overlay(srv.url, on_top=True)
finally:
    srv.stop()
