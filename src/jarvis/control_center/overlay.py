"""Optionales Windows-Mini-Overlay des Control Centers (cc-mini-overlay, Option A, Standard aus).

Ein kleines (ca. 140x140), rechteckiges, per Ziehen verschiebbares Fenster, das die bestehende Loopback-Seite mit `?view=overlay` zeigt. Start nur durch
den ausdruecklichen Aufruf `jarvis-cc --overlay` (optional `--overlay-on-top`). Grenzen: nie klickdurchlaessig, nicht transparent (unter Windows von pywebview
nicht unterstuetzt), keine JS-Python-Bruecke (`js_api`), kein Debug, nur die Loopback-URL mit Token. pywebview ist ein optionales Extra (`.[ui]`) und wird erst
in `start_overlay` importiert. Dieses Modul kennt weder Berechtigungen noch Notaus: das Overlay ist nur ein weiterer Client des Vertrags."""
from __future__ import annotations

import importlib.util
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jarvis.errors import JarvisError

OVERLAY_SIZE = (140, 140)
TITLE = "JARVIS"
LOOPBACK = "127.0.0.1"


class OverlayUnavailable(JarvisError):
    """Das Overlay kann nicht gestartet werden (pywebview fehlt oder die URL ist nicht die lokale Loopback-URL)."""


def webview_available(find_spec: Callable[[str], Any] = importlib.util.find_spec) -> bool:
    """Nur `find_spec`, kein Import (nichts wird geladen oder gestartet)."""
    try:
        return find_spec("webview") is not None
    except (ImportError, ValueError):
        return False


def overlay_options(on_top: bool = False) -> dict[str, Any]:
    """Fensteroptionen. Absichtlich ohne `js_api`, `transparent`, `debug`: keine Bruecke, kein Click-through, keine Entwicklerwerkzeuge."""
    width, height = OVERLAY_SIZE
    return {"width": width, "height": height, "frameless": True, "easy_drag": True, "resizable": False,
            "on_top": bool(on_top), "transparent": False}


def overlay_url(base_url: str) -> str:
    """Die Overlay-Ansicht der Loopback-URL (Token bleibt erhalten). Alles ausser `http://127.0.0.1:<port>` wird abgelehnt."""
    parts = urlsplit(base_url)
    if parts.scheme != "http" or parts.hostname != LOOPBACK or parts.port is None:
        raise OverlayUnavailable("Das Overlay zeigt nur die lokale Control-Center-Adresse (http://127.0.0.1:<Port>).")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "view"] + [("view", "overlay")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), ""))


def start_overlay(base_url: str, *, on_top: bool = False, webview_module: Any = None,
                  find_spec: Callable[[str], Any] = importlib.util.find_spec) -> None:
    """Oeffnet das Overlay und blockiert, bis es geschlossen wird. Ohne pywebview: OverlayUnavailable (deutsche Meldung), kein Rueckfall auf etwas anderes."""
    url = overlay_url(base_url)
    wv = webview_module
    if wv is None:
        if not webview_available(find_spec):
            raise OverlayUnavailable('pywebview ist nicht installiert (nur für das optionale Mini-Overlay nötig): pip install -e ".[ui]"')
        import webview as wv  # noqa: PLC0415 - bewusst erst hier
    wv.create_window(TITLE, url, **overlay_options(on_top))
    wv.start(debug=False)
