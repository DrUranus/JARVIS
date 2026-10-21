"""Mouse and keyboard on `pyautogui`. The library is imported lazily and fully contained here.

Hazards handled (all observed on a headless Linux box): importing pyautogui without DISPLAY raises KeyError, and
without tkinter its MouseInfo helper calls sys.exit() - so the import is guarded against SystemExit too.
pyautogui's fail-safe stays ON: slamming the pointer into a screen corner aborts the action (emergency stop).
"""
from __future__ import annotations

from typing import Any, Sequence

from jarvis.computer.backend import KeyboardProvider, MouseProvider
from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode

_module: Any = None


def load_pyautogui() -> Any:
    global _module
    if _module is not None:
        return _module
    try:
        import pyautogui
    except ImportError:
        raise ComputerUnavailableError("the 'pyautogui' library is not installed (pip install 'jarvis-ai[computer]')") from None
    except SystemExit:  # MouseInfo helper exits when tkinter is missing (Linux)
        raise ComputerUnavailableError("pyautogui could not initialise (on Linux it needs python3-tk)") from None
    except Exception as exc:
        code = ErrorCode.NO_DISPLAY if "DISPLAY" in repr(exc) or "display" in str(exc).lower() else ErrorCode.BACKEND_UNAVAILABLE
        raise ComputerUnavailableError(f"pyautogui could not initialise ({type(exc).__name__}): "
                                       "no usable display?" if code is ErrorCode.NO_DISPLAY else
                                       f"pyautogui could not initialise ({type(exc).__name__})", code) from None
    pyautogui.PAUSE = 0          # the controller does its own settling
    pyautogui.FAILSAFE = True    # emergency stop: pointer in a corner aborts input
    _module = pyautogui
    return pyautogui


def _call(pg: Any, fn: Any, *args: Any, kwargs: dict[str, Any] | None = None) -> None:
    """Run a pyautogui function; never echo exception text (it may contain typed characters)."""
    try:
        fn(*args, **(kwargs or {}))
    except pg.FailSafeException:
        raise ComputerError(ErrorCode.FAILSAFE, "emergency stop: the pointer is in a screen corner (pyautogui fail-safe)") from None
    except ComputerError:
        raise
    except Exception as exc:
        raise ComputerError(ErrorCode.BACKEND_ERROR, f"input backend error ({type(exc).__name__})") from None


class PyAutoGuiMouse(MouseProvider):
    def __init__(self) -> None:
        self._pg = load_pyautogui()

    def position(self) -> tuple[int, int]:
        p = self._pg.position()
        return int(p.x), int(p.y)

    def move(self, x: int, y: int) -> None:
        _call(self._pg, self._pg.moveTo, x, y, kwargs={"duration": 0})

    def click(self, x: int, y: int, button: str, clicks: int) -> None:
        _call(self._pg, self._pg.click, kwargs={"x": x, "y": y, "button": button, "clicks": clicks, "interval": 0.05})

    def scroll(self, x: int, y: int, amount: int) -> None:
        _call(self._pg, self._pg.scroll, amount, kwargs={"x": x, "y": y})


class PyAutoGuiKeyboard(KeyboardProvider):
    def __init__(self) -> None:
        self._pg = load_pyautogui()

    @staticmethod
    def _name(key: str) -> str:
        return key.lower()  # canonical CTRL/ENTER/PAGEUP/F5/A ... are pyautogui's lower-case names

    def press(self, key: str) -> None:
        _call(self._pg, self._pg.press, self._name(key))

    def hotkey(self, keys: Sequence[str]) -> None:
        names = [self._name(k) for k in keys]
        try:
            _call(self._pg, self._pg.hotkey, *names)
        except ComputerError:
            for name in reversed(names):  # an aborted combination must not leave CTRL/ALT/SHIFT held down
                try:
                    self._pg.keyUp(name)
                except Exception:
                    pass
            raise

    def type_text(self, text: str, interval: float) -> None:
        if any(ord(c) > 126 or (ord(c) < 32 and c not in "\n\t") for c in text):
            raise ComputerError(ErrorCode.UNSUPPORTED, "this backend can only type ASCII characters, newline and tab")
        _call(self._pg, self._pg.write, text, kwargs={"interval": interval})
