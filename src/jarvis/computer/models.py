"""Plain data types of the computer-control layer. No automation library appears here."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Monitor:
    index: int            # 0 = primary
    left: int             # position in the virtual desktop
    top: int
    width: int
    height: int
    primary: bool = False
    name: str = ""

    def contains(self, x: int, y: int) -> bool:
        """Monitor-relative point inside the monitor?"""
        return 0 <= x < self.width and 0 <= y < self.height


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    process: str          # executable name, e.g. "notepad.exe"
    pid: int = 0
    class_name: str = ""
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    minimized: bool = False
    maximized: bool = False
    active: bool = False

    def describe(self) -> dict[str, Any]:
        return {"handle": self.handle, "title": self.title, "process": self.process, "pid": self.pid,
                "class": self.class_name, "rect": [self.left, self.top, self.width, self.height],
                "minimized": self.minimized, "maximized": self.maximized, "active": self.active}


@dataclass(frozen=True)
class LaunchResult:
    pid: int | None
    executable: str


@dataclass(frozen=True)
class RawFrame:
    """What a screen provider returns: tightly packed RGB bytes (3 per pixel)."""
    left: int
    top: int
    width: int
    height: int
    rgb: bytes = field(repr=False)


@dataclass(frozen=True)
class Screenshot:
    """A captured frame. Lives in memory only; `data` is excluded from repr so it cannot end up in logs."""
    id: str
    monitor: int | None   # None = the whole virtual desktop
    left: int
    top: int
    width: int
    height: int
    sha256: str = field(repr=False)  # content hash: kept out of reprs (logs/tracebacks) like the pixels
    captured_at: datetime
    format: str = "rgb"
    data: bytes = field(default=b"", repr=False)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @classmethod
    def from_frame(cls, frame: RawFrame, monitor: int | None) -> "Screenshot":
        return cls(id="shot-" + uuid.uuid4().hex[:8], monitor=monitor, left=frame.left, top=frame.top,
                   width=frame.width, height=frame.height, sha256=hashlib.sha256(frame.rgb).hexdigest(),
                   captured_at=datetime.now(timezone.utc), data=frame.rgb)

    def info(self) -> dict[str, Any]:
        """Metadata for callers, tool results and logs. Never the pixels."""
        return {"id": self.id, "monitor": "all" if self.monitor is None else self.monitor, "width": self.width,
                "height": self.height, "format": self.format, "bytes": self.size_bytes, "sha256": self.sha256[:16],
                "captured_at": self.captured_at.isoformat(timespec="seconds"),
                "note": "kept in memory only; saving to disk needs the confirmed 'screen_save' tool"}


@dataclass(frozen=True)
class FrameDiff:
    comparable: bool      # same size and format
    identical: bool
    changed_ratio: float  # share of differing pixels, 0..1
    changed_pixels: int = 0
    bbox: tuple[int, int, int, int] | None = None  # (left, top, right, bottom) of the changed region

    def info(self) -> dict[str, Any]:
        return {"comparable": self.comparable, "identical": self.identical,
                "changed_ratio": round(self.changed_ratio, 6), "changed_pixels": self.changed_pixels,
                "bbox": list(self.bbox) if self.bbox else None}


@dataclass(frozen=True)
class CursorPosition:
    monitor: int | None   # None if outside every monitor
    x: int                # monitor-relative
    y: int
