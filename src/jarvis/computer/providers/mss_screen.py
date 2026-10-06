"""Screen provider on `mss` (monitors + capture). Imported lazily; a missing library or display is a clean
ComputerUnavailableError, never an import-time crash."""
from __future__ import annotations

from typing import Any

from jarvis.computer.backend import ScreenProvider
from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode
from jarvis.computer.models import Monitor, RawFrame


def _import_mss() -> Any:
    try:
        import mss
    except ImportError:
        raise ComputerUnavailableError("the 'mss' library is not installed (pip install 'jarvis-ai[computer]')") from None
    except (Exception, SystemExit) as exc:
        raise ComputerUnavailableError(f"'mss' could not be loaded ({type(exc).__name__})") from None
    return mss


class MssScreen(ScreenProvider):
    def __init__(self) -> None:
        self._mss = _import_mss()
        self._factory = getattr(self._mss, "MSS", None) or self._mss.mss  # mss >= 10 renamed mss.mss -> mss.MSS

    def _open(self) -> Any:
        try:
            return self._factory()
        except Exception as exc:  # X server unreachable, no desktop session...
            raise ComputerUnavailableError(f"cannot open the display ({type(exc).__name__})", ErrorCode.NO_DISPLAY) from None

    def monitors(self) -> list[Monitor]:
        with self._open() as sct:
            raw = [dict(m) for m in sct.monitors[1:]]  # [0] is the combined virtual screen
        if not raw:
            raise ComputerError(ErrorCode.NO_DISPLAY, "no monitors found")
        primary = next((i for i, m in enumerate(raw) if m.get("is_primary")), None)
        if primary is None:  # older mss: the primary monitor sits at the origin
            primary = next((i for i, m in enumerate(raw) if m["left"] == 0 and m["top"] == 0), 0)
        order = [primary, *[i for i in range(len(raw)) if i != primary]]
        return [Monitor(n, raw[i]["left"], raw[i]["top"], raw[i]["width"], raw[i]["height"], n == 0,
                        str(raw[i].get("output") or f"monitor-{n}")) for n, i in enumerate(order)]

    def capture(self, monitor: Monitor | None) -> RawFrame:
        with self._open() as sct:
            area = sct.monitors[0] if monitor is None else {
                "left": monitor.left, "top": monitor.top, "width": monitor.width, "height": monitor.height}
            try:
                shot = sct.grab(area)
            except Exception as exc:
                raise ComputerError(ErrorCode.BACKEND_ERROR, f"screen capture failed ({type(exc).__name__})") from None
            return RawFrame(area["left"], area["top"], shot.width, shot.height, bytes(shot.rgb))
