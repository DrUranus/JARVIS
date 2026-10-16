"""Windows ACL review and creation for the HMAC key file.

`os.chmod(0o600)` has no effect on a Windows ACL (it only toggles the read-only attribute), so the POSIX mode check of load_key proves nothing there. This module
works with the real security descriptor, in SDDL text form:

* parse_sddl / acl_problems are PURE functions (tested on every platform with fixture strings): they decide from the EFFECTIVE DACL - inherited entries included -
  whether anybody except the current user, SYSTEM and the Administrators group can get access, and whether the owner is one of those.
* WindowsAcl does the Windows-only work through fixed, absolute system executables (no shell, no PATH lookup): PowerShell `Get-Acl` to READ the descriptor and
  `icacls /inheritance:r /grant:r` to restrict a file WE created. It never touches a file it did not create; for an existing key it only reports.

The process execution goes through an injected `run(argv) -> (exit_status, output)`; this module imports no process API itself.

What is NOT claimed: none of the Windows calls could be executed where this was written (Linux). They are verified only by the Windows tests in
tests/test_self_improvement_keyfile.py when somebody runs them on Windows."""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Callable, Sequence

SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"

# two-letter SDDL aliases that map to a fixed SID; domain-relative aliases (DA, DU, DG, LA, ...) are intentionally absent: they stay unknown and are therefore refused
_ALIASES = {
    "SY": "S-1-5-18", "BA": "S-1-5-32-544", "WD": "S-1-1-0", "BU": "S-1-5-32-545", "AU": "S-1-5-11", "IU": "S-1-5-4", "NU": "S-1-5-2", "AN": "S-1-5-7",
    "LS": "S-1-5-19", "NS": "S-1-5-20", "BG": "S-1-5-32-546", "PU": "S-1-5-32-547", "AO": "S-1-5-32-548", "SO": "S-1-5-32-549", "PO": "S-1-5-32-550",
    "BO": "S-1-5-32-551", "RE": "S-1-5-32-552", "RC": "S-1-5-12", "ED": "S-1-5-9", "CO": "S-1-3-0", "CG": "S-1-3-1", "OW": "S-1-3-4", "SU": "S-1-5-6",
    "RD": "S-1-5-32-555", "NO": "S-1-5-32-556", "MU": "S-1-5-32-558", "LU": "S-1-5-32-559", "ER": "S-1-5-32-573", "RS": "S-1-5-32-575", "AC": "S-1-15-2-1",
}
_SID_RE = re.compile(r"S-\d+(?:-\d+)+")
_ALLOW_TYPES = {"A", "OA", "XA", "ZA"}          # grant access (object / conditional / callback variants are treated as plain grants: the conservative reading)
_DENY_TYPES = {"D", "OD", "XD"}
# inherit-only entries do not apply to the object itself
_INHERIT_ONLY = "IO"


@dataclass(frozen=True)
class Ace:
    kind: str
    flags: str
    rights: str
    sid: str                     # normalised to a SID string where the alias is fixed; otherwise the raw token


@dataclass(frozen=True)
class Acl:
    owner: str | None
    dacl_present: bool
    dacl_flags: str
    aces: tuple[Ace, ...]

    @property
    def protected(self) -> bool:
        """SDDL DACL flags are written like "PAI" / "AI" / "P": a leading P means 'protected' (does not inherit from the folder)."""
        return self.dacl_flags.startswith("P")


def _principal(token: str) -> str:
    token = token.strip()
    return _ALIASES.get(token, token)


def parse_sddl(sddl: str) -> Acl:
    """Parse the owner and the DACL of an SDDL string. Raises ValueError for text that is not SDDL (the caller fails closed)."""
    s = sddl.strip()
    if not s or not re.match(r"^[OGDS]:", s):
        raise ValueError("not an SDDL string")
    i, n = 0, len(s)
    owner: str | None = None
    dacl_present, dacl_flags = False, ""
    aces: list[Ace] = []
    while i < n:
        if s[i] not in "OGDS" or s[i + 1:i + 2] != ":":
            raise ValueError(f"unexpected SDDL text at {i}")
        section, i = s[i], i + 2
        if section in "OG":
            m = _SID_RE.match(s, i) or re.match(r"[A-Z]{2}", s[i:])
            if not m:
                raise ValueError("bad owner/group token")
            token = m.group(0)
            if section == "O":
                owner = _principal(token)
            i += len(token)
            continue
        m = re.match(r"[A-Z_]*", s[i:])             # flags such as PAI, PAR, NO_ACCESS_CONTROL
        flags, i = m.group(0), i + len(m.group(0))
        if section == "D":
            dacl_present, dacl_flags = True, flags
        while i < n and s[i] == "(":
            depth, j = 0, i
            while j < n:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if depth != 0:
                raise ValueError("unbalanced ACE parentheses")
            body = s[i + 1:j]
            i = j + 1
            if section == "D":
                f = body.split(";")
                if len(f) < 6:
                    raise ValueError("malformed ACE")
                aces.append(Ace(f[0], f[1], f[2], _principal(f[5])))
    return Acl(owner, dacl_present, dacl_flags, tuple(aces))


def acl_problems(sddl: str, user_sid: str) -> list[str]:
    """Reasons the key file is NOT acceptable (empty list = acceptable). Fail closed: anything unparsable or unknown is a problem.
    Allowed principals: the current user, SYSTEM, the Administrators group. The evaluation uses the effective DACL (explicit AND inherited entries)."""
    if not _SID_RE.fullmatch(user_sid or ""):
        return ["the current user's SID could not be determined"]
    allowed = {user_sid, SYSTEM_SID, ADMINISTRATORS_SID}
    try:
        acl = parse_sddl(sddl)
    except ValueError as exc:
        return [f"the security descriptor could not be parsed ({exc})"]
    problems: list[str] = []
    if acl.owner is None or acl.owner not in allowed:
        problems.append(f"the owner is {acl.owner or 'unknown'}, not the current user, SYSTEM or Administrators (an owner can always change the ACL)")
    if not acl.dacl_present or "NO_ACCESS_CONTROL" in acl.dacl_flags:
        problems.append("the file has no DACL (or a NULL DACL): everybody has full access")
        return problems
    effective = [a for a in acl.aces if _INHERIT_ONLY not in _chunks(a.flags)]
    granted_to_allowed = False
    for a in effective:
        if a.kind in _DENY_TYPES:
            continue
        if a.kind not in _ALLOW_TYPES:
            problems.append(f"unsupported ACE type {a.kind!r} for {a.sid}")
            continue
        if a.sid in allowed or (a.sid == "S-1-3-4" and acl.owner in allowed):       # OWNER RIGHTS only matters if the owner is acceptable
            granted_to_allowed = True
            continue
        problems.append(f"access is granted to {_describe(a.sid)} (rights {a.rights or '?'}{', inherited' if 'ID' in _chunks(a.flags) else ''})")
    if not granted_to_allowed and not problems:
        problems.append("no ACE grants access to the current user, SYSTEM or Administrators")
    return problems


def _chunks(flags: str) -> list[str]:
    return [flags[i:i + 2] for i in range(0, len(flags), 2)]


_NAMES = {"S-1-1-0": "Everyone", "S-1-5-32-545": "BUILTIN\\Users", "S-1-5-11": "Authenticated Users", "S-1-5-4": "Interactive", "S-1-5-2": "Network",
          "S-1-5-32-546": "BUILTIN\\Guests", "S-1-5-7": "Anonymous", "S-1-3-0": "Creator Owner"}


def _describe(sid: str) -> str:
    return f"{_NAMES[sid]} ({sid})" if sid in _NAMES else sid


# ---- Windows-only part ---------------------------------------------------------------------------------------------------------------------------
Run = Callable[[Sequence[str]], "tuple[int | None, str]"]


def _system32() -> str:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return os.path.join(root, "System32")


class WindowsAcl:
    """Reads (`review`) and, for files this process created, restricts (`restrict`) the ACL. `run` executes a fixed argument list and returns (exit_status, output)."""

    def __init__(self, run: Run) -> None:
        self._run = run

    @staticmethod
    def _quote(path: str) -> str:
        if any(ord(c) < 32 for c in path):
            raise ValueError("control character in path")
        return "'" + path.replace("'", "''") + "'"

    def _powershell(self, script: str) -> str:
        exe = os.path.join(_system32(), "WindowsPowerShell", "v1.0", "powershell.exe")
        # UTF-8 output, so that the runner's utf-8 decoding is exact (the default is the OEM code page). Only ASCII is ever PARSED (SID, SDDL); anything else in the output
        # is diagnostics, and a replacement character can not satisfy the strict patterns in `read`.
        script = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); " + script
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")        # -EncodedCommand: no quoting problems with any path
        status, out = self._run([exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded])
        if status != 0:
            raise OSError(f"PowerShell failed (exit {status}): {out.strip()[-200:]}")
        return out

    def read(self, path: str) -> "tuple[str, str]":
        """-> (current user SID, SDDL of the file). Raises OSError/ValueError when it can not be determined."""
        script = ("$ErrorActionPreference='Stop'; "
                  "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
                  "Write-Output ('USER_SID=' + $u); "
                  f"Write-Output ('SDDL=' + (Get-Acl -LiteralPath {self._quote(path)}).Sddl)")
        out = self._powershell(script)
        user = re.search(r"^USER_SID=(S-\d+(?:-\d+)+)\s*$", out, re.M)
        sddl = re.search(r"^SDDL=(.+?)\s*$", out, re.M)
        if not user or not sddl:
            raise ValueError("unexpected PowerShell output")
        return user.group(1), sddl.group(1)

    def review(self, path: str) -> list[str]:
        """Problems with the ACL of `path` (empty = acceptable). Any failure to read it is itself a problem (fail closed)."""
        try:
            user, sddl = self.read(path)
        except (OSError, ValueError) as exc:
            return [f"the ACL could not be read ({exc})"]
        return acl_problems(sddl, user)

    def restrict(self, path: str) -> None:
        """Remove inheritance and grant full control to the current user, SYSTEM and Administrators ONLY. For files this process just created."""
        user, _ = self.read(path)
        argv = [os.path.join(_system32(), "icacls.exe"), path, "/inheritance:r", "/grant:r", f"*{user}:(F)", f"*{SYSTEM_SID}:(F)", f"*{ADMINISTRATORS_SID}:(F)"]
        status, out = self._run(argv)
        if status != 0:
            raise OSError(f"icacls failed (exit {status}): {out.strip()[-200:]}")
