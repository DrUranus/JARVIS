"""Filesystem safety foundation: normalisation, traversal and symlink protection, allowed/denied roots.

Not a filesystem tool, only the checks a future filesystem tool must pass through. Key properties:
* relative paths are resolved against a fixed base directory (never the process cwd);
* paths are resolved with os.path.realpath on the *unnormalised* input, so `link/../x` is evaluated the way the
  OS does it (symlink first, then `..`), and symlinks that point outside a root are caught;
* containment is checked component-wise (`/ws-evil` is NOT inside `/ws`);
* an empty allow-list denies everything; the filesystem root can never be an allowed root.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jarvis.errors import InvalidRequestError, PolicyError

MAX_PATH_LENGTH = 4096


@dataclass(frozen=True)
class PathCheck:
    ok: bool
    code: str                 # "ok", "outside_roots", "denied_path", "protected_path", "no_roots"
    reason: str
    resolved: str | None = None  # the real path a tool must use (symlinks resolved)
    symlinked: bool = False      # resolution changed the path through a symlink


def _norm(p: str, fold: bool) -> str:
    p = os.path.normcase(p)
    return p.casefold() if fold else p


def is_within(candidate: str, root: str, fold: bool = False) -> bool:
    """Component-wise containment of two *resolved* absolute paths (equal counts as within).
    `fold=True` compares case-insensitively: used for deny/protected checks, where over-matching is the safe
    direction (case-insensitive volumes on macOS/Windows would otherwise let 'PRIVATE' slip past 'private')."""
    c, r = _norm(candidate, fold), _norm(root, fold)
    try:
        return os.path.commonpath([c, r]) == r
    except ValueError:  # different drives / mix of absolute and relative
        return False


class PathGuard:
    def __init__(self, allowed_roots: Iterable[str | os.PathLike[str]] = (),
                 denied_paths: Iterable[str | os.PathLike[str]] = (),
                 protected_paths: Iterable[str | os.PathLike[str]] = (),
                 base_dir: str | os.PathLike[str] | None = None) -> None:
        self._allowed = [os.fspath(r) for r in allowed_roots]
        self._denied = [os.fspath(p) for p in denied_paths]
        self._protected = [os.fspath(p) for p in protected_paths]
        self._base_arg = os.fspath(base_dir) if base_dir is not None else (self._allowed[0] if self._allowed else ".")
        for root in self._allowed:
            real = self._real(self._from_cwd(root))
            if os.path.dirname(real) == real:  # '/' or 'C:\'
                raise PolicyError("the filesystem root cannot be an allowed root; name specific directories")

    # -- resolution -------------------------------------------------------------------------------
    @staticmethod
    def _real(path: str) -> str:
        try:
            return os.path.realpath(path)
        except (OSError, ValueError, RuntimeError) as exc:  # loops, NUL bytes, over-long names
            raise InvalidRequestError(f"cannot resolve path: {exc}") from exc

    @staticmethod
    def _from_cwd(raw: str) -> str:
        """Configured roots/denied/protected paths: relative ones are relative to the project (process) directory."""
        p = os.path.expanduser(raw)
        return p if os.path.isabs(p) else os.path.join(os.getcwd(), p)

    @property
    def allowed_roots(self) -> list[str]:
        return [self._real(self._from_cwd(r)) for r in self._allowed]

    @property
    def denied_paths(self) -> list[str]:
        return [self._real(self._from_cwd(d)) for d in self._denied]

    @property
    def base_dir(self) -> str:
        """Directory that relative *request* paths are resolved against (default: the first allowed root)."""
        return self._real(self._from_cwd(self._base_arg))

    def _absolute(self, raw: str) -> str:
        p = os.path.expanduser(raw) if raw.startswith("~") else raw
        return p if os.path.isabs(p) else os.path.join(self.base_dir, p)

    def resolve(self, path: str | os.PathLike[str]) -> str:
        """Absolute real path for `path` (no containment decision). Raises InvalidRequestError if malformed."""
        try:
            raw = os.fspath(path)
        except TypeError as exc:
            raise InvalidRequestError("path must be a string or path-like object") from exc
        if not isinstance(raw, str) or not raw.strip():
            raise InvalidRequestError("path must be a non-empty string")
        if len(raw) > MAX_PATH_LENGTH:
            raise InvalidRequestError("path too long")
        if any(ord(c) < 32 or ord(c) == 127 for c in raw):
            raise InvalidRequestError("path contains control characters")
        return self._real(self._absolute(raw))

    def resolve_pattern(self, pattern: str) -> str:
        """Resolve a *policy rule* path (relative to the project directory, like roots)."""
        if not isinstance(pattern, str) or not pattern.strip() or "\x00" in pattern:
            raise PolicyError("rule path must be a non-empty string")
        return self._real(self._from_cwd(pattern))

    # -- decision -----------------------------------------------------------------------------------
    def check(self, path: str | os.PathLike[str], *, modifying: bool = False) -> PathCheck:
        resolved = self.resolve(path)
        lexical = os.path.abspath(self._absolute(os.fspath(path)))
        symlinked = _norm(lexical, False) != _norm(resolved, False)
        if not self._allowed:
            return PathCheck(False, "no_roots", "no filesystem roots are allowed (default deny)", resolved, symlinked)
        for d in self._denied:
            if is_within(resolved, self._real(self._from_cwd(d)), fold=True):
                return PathCheck(False, "denied_path", "path is in a denied location", resolved, symlinked)
        if modifying:
            for p in self._protected:
                if is_within(resolved, self._real(self._from_cwd(p)), fold=True):
                    return PathCheck(False, "protected_path",
                                     "path is protected (security policy/audit files cannot be modified)",
                                     resolved, symlinked)
        if not any(is_within(resolved, self._real(self._from_cwd(r))) for r in self._allowed):
            return PathCheck(False, "outside_roots", "path is outside the allowed directories", resolved, symlinked)
        return PathCheck(True, "ok", "path is inside an allowed directory", resolved, symlinked)
