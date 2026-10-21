"""In-memory screenshot store, PNG encoding (stdlib only) and frame comparison.

Nothing here writes to disk or sends anything anywhere; persisting is a separate, explicitly confirmed tool."""
from __future__ import annotations

import struct
import threading
import zlib
from collections import OrderedDict

from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.models import FrameDiff, Screenshot


class ScreenshotStore:
    """Bounded store (count and bytes). The oldest screenshots are dropped first."""

    def __init__(self, max_items: int = 3, max_bytes: int = 256 * 1024 * 1024) -> None:
        self._max_items, self._max_bytes = max(1, max_items), max_bytes
        self._items: "OrderedDict[str, Screenshot]" = OrderedDict()
        self._lock = threading.Lock()

    def add(self, shot: Screenshot) -> Screenshot:
        with self._lock:
            self._items[shot.id] = shot
            while len(self._items) > self._max_items or (len(self._items) > 1 and self._total() > self._max_bytes):
                self._items.popitem(last=False)
        return shot

    def _total(self) -> int:
        return sum(s.size_bytes for s in self._items.values())

    def get(self, shot_id: str) -> Screenshot:
        with self._lock:
            try:
                return self._items[shot_id]
            except KeyError:
                raise ComputerError(ErrorCode.INVALID_INPUT, f"no stored screenshot {str(shot_id)[:30]!r} "
                                    f"(kept: {list(self._items)})") from None

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._items)

    def latest(self) -> Screenshot | None:
        with self._lock:
            return next(reversed(self._items.values()), None)

    def clear(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items.clear()
            return n


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """Minimal PNG writer (8-bit RGB, no filtering), so no imaging library is needed to save a screenshot."""
    if width < 1 or height < 1 or len(rgb) != width * height * 3:
        raise ComputerError(ErrorCode.INVALID_INPUT, "pixel data does not match the image size")
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def frame_diff(a: Screenshot, b: Screenshot) -> FrameDiff:
    """Pixel comparison of two screenshots (the 'verify' step of action -> observe -> verify)."""
    if (a.width, a.height, a.format) != (b.width, b.height, b.format) or len(a.data) != len(b.data):
        return FrameDiff(False, False, 1.0, 0, None)
    if a.data == b.data:
        return FrameDiff(True, True, 0.0, 0, None)
    w, h = a.width, a.height
    stride = w * 3
    changed = 0
    left, top, right, bottom = w, h, -1, -1
    for y in range(h):
        ra, rb = a.data[y * stride:(y + 1) * stride], b.data[y * stride:(y + 1) * stride]
        if ra == rb:
            continue
        row_cols = [x for x in range(w) if ra[x * 3:x * 3 + 3] != rb[x * 3:x * 3 + 3]]
        changed += len(row_cols)
        top, bottom = min(top, y), max(bottom, y)
        left, right = min(left, row_cols[0]), max(right, row_cols[-1])
    return FrameDiff(True, False, changed / (w * h), changed, (left, top, right, bottom))
