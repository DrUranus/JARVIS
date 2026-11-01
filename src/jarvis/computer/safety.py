"""What computer control must never touch. Conservative, hard-coded, and NOT switchable by configuration:
config can only ADD to these lists (computer.blocked_processes / blocked_titles).

Classification here only *feeds* the PermissionEngine (a request is marked RED); the engine stays the authority,
and the controller re-checks at execution time (defence in depth).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from jarvis.computer.models import WindowInfo
from jarvis.permissions import PermissionLevel

# Executables (stem, case-insensitive) that can run arbitrary commands, change security settings or administer the system.
_TERMINALS = {"cmd", "powershell", "pwsh", "powershell_ise", "windowsterminal", "wt", "conhost", "openconsole", "wsl",
              "wslhost", "bash", "sh", "zsh", "dash", "fish", "ksh", "csh", "tcsh", "mintty", "putty", "xterm", "konsole",
              "gnome-terminal", "gnome-terminal-server", "alacritty", "kitty", "tilix", "terminator", "urxvt", "st"}
_SCRIPT_HOSTS = {"wscript", "cscript", "mshta", "py", "pythonw", "node", "nodejs", "ruby", "perl", "php", "lua", "rundll32",
                 "regsvr32", "msiexec", "msbuild", "installutil", "regasm", "regsvcs", "forfiles", "pcalua", "scriptrunner"}
_SYSTEM_TOOLS = {"regedit", "reg", "mmc", "taskmgr", "msconfig", "control", "eventvwr", "gpedit", "secpol", "lusrmgr",
                 "compmgmt", "diskmgmt", "services", "perfmon", "resmon", "wmic", "wmiprvse", "dism", "sfc", "bcdedit",
                 "diskpart", "format", "vssadmin", "cipher", "icacls", "takeown", "cacls", "net", "net1", "netsh", "sc",
                 "schtasks", "taskkill", "tasklist", "shutdown", "logoff", "runas", "psexec", "psexec64", "msg", "at",
                 "certutil", "bitsadmin", "curl", "wget", "ssh", "scp", "sftp", "telnet", "ftp", "tftp", "nc", "ncat",
                 "robocopy", "xcopy", "sudo", "su", "doas", "pkexec"}
_SECURITY = {"sechealthui", "securityhealthsystray", "securityhealthservice", "msmpeng", "mpcmdrun", "mpdefendercoreservice",
             "nissrv", "smartscreen", "windefend", "wf", "firewall"}
_SHELL_ESCAPES = {"searchhost", "searchapp", "searchui", "startmenuexperiencehost", "shellexperiencehost", "runtimebroker"}
_PYTHON = re.compile(r"^python[\d.]*w?$")

BLOCKED_STEMS: frozenset[str] = frozenset(_TERMINALS | _SCRIPT_HOSTS | _SYSTEM_TOOLS | _SECURITY | _SHELL_ESCAPES)

# Title fragments (case-insensitive) of windows that must not receive input.
BLOCKED_TITLE_FRAGMENTS = ("windows security", "windows defender", "windows firewall", "task manager", "registry editor",
                           "command prompt", "powershell", "windows terminal", "user account control", "group policy",
                           "local security policy", "event viewer", "computer management", "services (local)")
BLOCKED_TITLES_EXACT = ("run", "start", "search")   # the Run dialog and the Start/Search shell surfaces
BLOCKED_WINDOW_CLASSES = ("consolewindowclass", "cascadia_hosting_window_class", "virtualconsoleclass")

# Windows whose CONTENT is never read through UI Automation, on top of everything that receives no input: password managers, credential stores and banking.
UI_READ_BLOCKED_STEMS = frozenset({"keepass", "keepassxc", "bitwarden", "1password", "lastpass", "dashlane", "enpass", "roboform", "nordpass", "keeper", "protonpass", "authy"})
UI_READ_BLOCKED_TITLE_FRAGMENTS = ("keepass", "bitwarden", "1password", "lastpass", "dashlane", "enpass", "roboform", "nordpass", "password manager", "passwort manager",
                                   "passwort-manager", "passwortmanager", "credential manager", "anmeldeinformationsverwaltung", "banking")

# Windows that may be targeted by input but never CLOSED: the desktop shell and core system processes.
PROTECTED_CLASSES = ("progman", "workerw", "shell_traywnd", "shell_secondarytraywnd")
PROTECTED_PROCESSES = {"csrss", "winlogon", "wininit", "services", "lsass", "dwm", "svchost", "smss", "system", "fontdrvhost",
                       "taskhostw", "sihost", "ctfmon", "systemd", "init", "xorg", "xwayland"}

# Keys / combinations that open command surfaces or system security screens.
RED_KEYS = frozenset({"WIN"})
RED_COMBOS = (frozenset({"CTRL", "ALT", "DELETE"}), frozenset({"CTRL", "SHIFT", "ESC"}), frozenset({"CTRL", "ESC"}),
              frozenset({"ALT", "ESC"}))


def stem_of(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/")).casefold()
    for ext in (".exe", ".com", ".bat", ".cmd", ".msc"):
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


@dataclass(frozen=True)
class Verdict:
    """Level the tool should request, and why. RED = never permitted (the engine denies it)."""
    level: PermissionLevel
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.level is PermissionLevel.RED


OK = Verdict(PermissionLevel.YELLOW)  # acting tools are YELLOW at minimum; this just means "not blocked"


class ComputerSafety:
    def __init__(self, extra_processes: Iterable[str] = (), extra_titles: Iterable[str] = (),
                 own_pids: Iterable[int] = ()) -> None:
        self._extra_stems = {stem_of(p) for p in extra_processes}
        self._extra_titles = tuple(t.casefold() for t in extra_titles)
        self._own_pids = {p for p in own_pids if p}

    # -- executables ---------------------------------------------------------------------------------------
    def is_blocked_stem(self, stem: str) -> bool:
        return stem in BLOCKED_STEMS or bool(_PYTHON.match(stem)) or stem in self._extra_stems

    def executable_verdict(self, path: str) -> Verdict:
        stem = stem_of(path)
        if self.is_blocked_stem(stem):
            return Verdict(PermissionLevel.RED, f"'{os.path.basename(path)}' can run commands or change system security "
                                                "and is never launched by computer control")
        return OK

    # -- windows ---------------------------------------------------------------------------------------------
    def window_blocked_reason(self, w: WindowInfo | None) -> str | None:
        """Why input to this window is refused, or None."""
        if w is None:
            return None
        stem = stem_of(w.process)
        if self.is_blocked_stem(stem):
            return f"window of '{w.process}' (terminal, shell, script host or security/system tool) receives no input"
        title = w.title.casefold()
        if title in BLOCKED_TITLES_EXACT or any(f in title for f in (*BLOCKED_TITLE_FRAGMENTS, *self._extra_titles)):
            return "this window is a command or security surface and receives no input"
        if w.class_name.casefold() in BLOCKED_WINDOW_CLASSES:
            return "console windows receive no input"
        return None

    def ui_read_blocked_reason(self, w: WindowInfo | None) -> str | None:
        """Why the content of this window is never read through UI Automation, or None. Stricter than input: also password managers and banking."""
        if w is None:
            return None
        if self.window_blocked_reason(w):
            return "UI Automation never reads terminals, shells, script hosts, security or system tools and other protected windows"
        title = w.title.casefold()
        if stem_of(w.process) in UI_READ_BLOCKED_STEMS or any(f in title for f in UI_READ_BLOCKED_TITLE_FRAGMENTS):
            return "UI Automation never reads password managers, credential stores or banking windows"
        return None

    def window_input_verdict(self, w: WindowInfo | None) -> Verdict:
        reason = self.window_blocked_reason(w)
        return Verdict(PermissionLevel.RED, reason) if reason else OK

    def window_close_verdict(self, w: WindowInfo) -> Verdict:
        if w.pid and w.pid in self._own_pids:
            return Verdict(PermissionLevel.RED, "this is JARVIS' own window; closing it would stop JARVIS")
        if w.class_name.casefold() in PROTECTED_CLASSES or stem_of(w.process) in PROTECTED_PROCESSES:
            return Verdict(PermissionLevel.RED, "desktop shell and system windows are never closed by computer control")
        reason = self.window_blocked_reason(w)
        if reason:  # terminals/security tools: also not ours to close (it may stop work or services running in them)
            return Verdict(PermissionLevel.RED, reason)
        return OK

    # -- keys ---------------------------------------------------------------------------------------------------
    def key_verdict(self, key: str) -> Verdict:
        if key in RED_KEYS:
            return Verdict(PermissionLevel.RED, "the Windows key opens Start/Search/Run (a command surface)")
        return OK

    def hotkey_verdict(self, keys: Sequence[str]) -> Verdict:
        ks = frozenset(keys)
        if ks & RED_KEYS:
            return Verdict(PermissionLevel.RED, "combinations with the Windows key open command surfaces (Run, Start, power menu)")
        if any(c <= ks for c in RED_COMBOS):
            return Verdict(PermissionLevel.RED, "this combination opens the system security/task screen")
        return OK
