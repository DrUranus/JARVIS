"""Real Windows tests of the mss screen provider (monitor list + capture). Skipped everywhere else.

Read-only: only the monitor geometry is queried and pixels are grabbed - no mouse, no keyboard, no foreign program
is started, nothing leaves the machine. Without an interactive desktop (or without the optional `mss`) the tests
skip with an explicit reason instead of passing silently.
"""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="real Windows desktop capture (mss/GDI)")

from jarvis.computer.errors import ComputerError, ComputerUnavailableError, ErrorCode  # noqa: E402
from jarvis.computer.models import Monitor  # noqa: E402


@pytest.fixture(scope="module")
def screen():
    pytest.importorskip("mss", reason="optional library 'mss' not installed (pip install '.[computer]')")
    from jarvis.computer.providers.mss_screen import MssScreen
    provider = MssScreen()
    try:
        provider.monitors()
    except ComputerUnavailableError as exc:
        pytest.skip(f"no interactive desktop: {exc}")
    return provider


def test_monitors_are_listed_with_one_primary_first(screen):
    mons = screen.monitors()
    assert mons and [m.index for m in mons] == list(range(len(mons)))
    assert mons[0].primary and not any(m.primary for m in mons[1:])
    assert all(m.width > 0 and m.height > 0 for m in mons)


def test_screenshot_of_a_monitor_matches_its_size(screen):
    mon = screen.monitors()[0]
    frame = screen.capture(mon)
    assert (frame.left, frame.top) == (mon.left, mon.top)
    assert (frame.width, frame.height) == (mon.width, mon.height)
    assert len(frame.rgb) == frame.width * frame.height * 3


def test_every_monitor_can_be_captured(screen):
    for mon in screen.monitors():
        frame = screen.capture(mon)
        assert (frame.width, frame.height) == (mon.width, mon.height)


def test_full_virtual_screen_covers_all_monitors(screen):
    frame = screen.capture(None)
    mons = screen.monitors()
    assert frame.width >= max(m.width for m in mons) and frame.height >= max(m.height for m in mons)
    assert len(frame.rgb) == frame.width * frame.height * 3


def test_without_a_desktop_the_error_is_clean(screen, monkeypatch):
    def broken():
        raise OSError("no desktop")
    monkeypatch.setattr(screen, "_factory", broken)
    with pytest.raises(ComputerUnavailableError) as info:
        screen.monitors()
    assert info.value.code == ErrorCode.NO_DISPLAY


def test_capture_failure_is_a_computer_error_not_a_crash(screen, monkeypatch):
    class Broken:
        monitors = [{"left": 0, "top": 0, "width": 1, "height": 1}] * 2

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def grab(self, area):
            raise OSError("grab failed")
    monkeypatch.setattr(screen, "_factory", Broken)
    with pytest.raises(ComputerError) as info:
        screen.capture(Monitor(0, 0, 0, 1, 1, True, "m"))
    assert info.value.code == ErrorCode.BACKEND_ERROR
