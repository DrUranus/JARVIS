"""Application launcher on plain subprocess: argument LIST, no shell, scrubbed environment, detached."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Sequence

from jarvis.computer.backend import AppLauncher
from jarvis.computer.errors import ComputerError, ErrorCode
from jarvis.computer.models import LaunchResult

_SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)


def scrubbed_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for launched programs: JARVIS' API keys/tokens/passwords are not handed on to other applications."""
    src = os.environ if env is None else env
    return {k: v for k, v in src.items() if not _SECRET_NAME.search(k)}


class SubprocessLauncher(AppLauncher):
    MAX_TRACKED = 64

    def __init__(self) -> None:
        self._children: list[subprocess.Popen] = []  # kept only so finished programs can be reaped (no zombies)

    def _reap(self) -> None:
        self._children = [p for p in self._children if p.poll() is None]

    def launch(self, executable: str, args: Sequence[str]) -> LaunchResult:
        self._reap()
        argv = [executable, *args]
        kwargs: dict = dict(shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            close_fds=True, env=scrubbed_environment())
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(argv, **kwargs)  # noqa: S603 - list argv, shell=False, target vetted by the controller
        except FileNotFoundError:
            raise ComputerError(ErrorCode.LAUNCH_FAILED, "executable not found") from None
        except PermissionError:
            raise ComputerError(ErrorCode.LAUNCH_FAILED, "permission denied when starting the executable") from None
        except OSError as exc:
            raise ComputerError(ErrorCode.LAUNCH_FAILED, f"could not start the executable ({type(exc).__name__})") from None
        self._children.append(proc)
        del self._children[:-self.MAX_TRACKED]
        return LaunchResult(proc.pid, executable)
