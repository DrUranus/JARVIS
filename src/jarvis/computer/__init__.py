"""Computer control: screen, mouse, keyboard, windows and applications behind provider interfaces.

The Core never imports this package or an automation library. `bootstrap` builds a ComputerSubsystem (tools in the
ToolRegistry + safety rules in the PermissionEngine); everything the PC does is a permission-checked tool call.
"""
from jarvis.computer.backend import (AppLauncher, ComputerBackend, KeyboardProvider, MouseProvider, ScreenProvider,
                                     WindowProvider)
from jarvis.computer.controller import ComputerController, Plan
from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode
from jarvis.computer.models import CursorPosition, FrameDiff, LaunchResult, Monitor, RawFrame, Screenshot, WindowInfo
from jarvis.computer.safety import ComputerSafety
from jarvis.computer.screenshots import ScreenshotStore, encode_png, frame_diff
from jarvis.computer.uia import (ControlType, UiElement, UiFindResult, UiLimits, UiQuery, UiRect, UiSnapshot, UiTreeProvider, bound_tree,
                                 find_in_tree)
from jarvis.computer.vision import ImageObserver, Observation, Verification, verify_change

__all__ = [
    "ComputerController", "Plan", "ComputerError", "ComputerUnavailableError", "ErrorCode", "ComputerBackend",
    "ScreenProvider", "MouseProvider", "KeyboardProvider", "WindowProvider", "AppLauncher", "Monitor", "WindowInfo",
    "Screenshot", "RawFrame", "FrameDiff", "LaunchResult", "CursorPosition", "ComputerSafety", "ScreenshotStore",
    "encode_png", "frame_diff", "ImageObserver", "Observation", "Verification", "verify_change",
    "ControlType", "UiElement", "UiFindResult", "UiLimits", "UiQuery", "UiRect", "UiSnapshot", "UiTreeProvider", "bound_tree", "find_in_tree",
]
