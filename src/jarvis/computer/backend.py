"""Provider interfaces. The controller only ever talks to these; concrete automation libraries live in
`jarvis.computer.providers` and can be swapped one by one (e.g. replace the pyautogui input with SendInput).

All methods use *absolute virtual-desktop coordinates*; the controller translates monitor-relative ones and
validates them against the current monitor layout before calling a provider.
Providers raise ComputerError subclasses for expected failures; anything else is wrapped by the controller.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.models import LaunchResult, Monitor, RawFrame, WindowInfo


class ScreenProvider(ABC):
    @abstractmethod
    def monitors(self) -> list[Monitor]:
        """Monitors, primary first (index 0)."""

    @abstractmethod
    def capture(self, monitor: Monitor | None) -> RawFrame:
        """Capture one monitor, or the whole virtual desktop for None. RGB, 3 bytes per pixel."""


class MouseProvider(ABC):
    @abstractmethod
    def position(self) -> tuple[int, int]: ...

    @abstractmethod
    def move(self, x: int, y: int) -> None: ...

    @abstractmethod
    def click(self, x: int, y: int, button: str, clicks: int) -> None:
        """button: 'left' | 'right'; clicks: 1 or 2."""

    @abstractmethod
    def scroll(self, x: int, y: int, amount: int) -> None:
        """Positive = up/away from the user, negative = down."""


class KeyboardProvider(ABC):
    @abstractmethod
    def press(self, key: str) -> None:
        """One canonical key name (see validation.KEYS)."""

    @abstractmethod
    def hotkey(self, keys: Sequence[str]) -> None:
        """Press the keys together (modifiers first), release in reverse order."""

    @abstractmethod
    def type_text(self, text: str, interval: float) -> None: ...


class WindowProvider(ABC):
    @abstractmethod
    def list_windows(self) -> list[WindowInfo]:
        """Visible top-level windows with a title."""

    @abstractmethod
    def active_window(self) -> WindowInfo | None: ...

    def window_at(self, x: int, y: int) -> WindowInfo | None:
        """Top-level window under an absolute point, if the provider can tell."""
        raise ComputerError(ErrorCode.UNSUPPORTED, "this backend cannot tell which window is under a point")

    @abstractmethod
    def focus(self, handle: int) -> None: ...

    def minimize(self, handle: int) -> None:
        raise ComputerError(ErrorCode.UNSUPPORTED, "minimize is not supported by this backend")

    def maximize(self, handle: int) -> None:
        raise ComputerError(ErrorCode.UNSUPPORTED, "maximize is not supported by this backend")

    def restore(self, handle: int) -> None:
        raise ComputerError(ErrorCode.UNSUPPORTED, "restore is not supported by this backend")

    @abstractmethod
    def close(self, handle: int) -> None:
        """Ask the window to close (graceful, like the X button). Never kill a process."""


class AppLauncher(ABC):
    @abstractmethod
    def launch(self, executable: str, args: Sequence[str]) -> LaunchResult:
        """Start `executable` with an argument LIST. Never through a shell."""


@dataclass
class ComputerBackend:
    """A bundle of providers. Missing ones make the matching operations fail with `unsupported`."""
    name: str
    screen: ScreenProvider | None = None
    mouse: MouseProvider | None = None
    keyboard: KeyboardProvider | None = None
    windows: WindowProvider | None = None
    apps: AppLauncher | None = None

    def capabilities(self) -> list[str]:
        return [n for n in ("screen", "mouse", "keyboard", "windows", "apps") if getattr(self, n) is not None]
