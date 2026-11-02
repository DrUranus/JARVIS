"""Which file NAMES the file tools never touch: key/credential/.env files, secret directories, `.git` internals, executable file types, device names.

A deliberate, small copy of the lists of the coding agent (the packages must not import each other: tests/test_coding_security.py). A test in
tests/test_files_tools.py checks that these lists never fall behind the coding agent's.
"""
from __future__ import annotations

import fnmatch
import posixpath
from dataclasses import dataclass

SECRET_NAMES = frozenset({".env", ".netrc", ".npmrc", ".pypirc", ".git-credentials", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
                          "known_hosts", "authorized_keys", "secrets", "secret", "wallet.dat", "cookies", "login data", "shadow",
                          "htpasswd", ".htpasswd"})
SECRET_PATTERNS = (".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", "*.jks", "*.keystore", "*.ppk", "*.gpg", "*.asc",
                   "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "credentials*", "secrets.*", "secret.*", "*.token", "*.ovpn",
                   "service-account*.json", "*_rsa", "*_ed25519")
SECRET_DIRS = frozenset({".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure"})
EXAMPLE_SUFFIXES = (".example", ".sample", ".template", ".dist")   # `.env.example` documents a layout, it holds no secrets
BLOCKED_EXTENSIONS = frozenset({".exe", ".dll", ".sys", ".msi", ".scr", ".com", ".lnk", ".pif", ".cpl", ".msc", ".reg", ".hta",
                                ".so", ".dylib", ".apk", ".app", ".dmg", ".pkg", ".jar", ".class", ".pyc", ".pyd", ".bin",
                                ".bat", ".cmd", ".ps1", ".vbs", ".wsf", ".sh"})
RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))})


@dataclass(frozen=True)
class PathInfo:
    secret: bool = False
    protected: bool = False     # .git internals
    blocked_extension: bool = False


def classify(parts: list[str]) -> PathInfo:
    low = [c.casefold() for c in parts]
    name = low[-1]
    secret = any(c in SECRET_DIRS for c in low[:-1]) or name in SECRET_DIRS
    if not name.endswith(EXAMPLE_SUFFIXES) and (name in SECRET_NAMES or any(fnmatch.fnmatchcase(name, pat) for pat in SECRET_PATTERNS)):
        secret = True
    return PathInfo(secret=secret, protected=".git" in low, blocked_extension=posixpath.splitext(name)[1] in BLOCKED_EXTENSIONS)
