"""Deterministic, configurable rules.

Precedence is by *effect*, never by order: deny > confirm > allow. Every matching rule is considered, so the
outcome does not depend on how the file is arranged, and conflicts always resolve to the safer result.
Missing information resolves safely too: a deny/confirm rule whose resource constraint cannot be evaluated
because the request carries no resource is treated as matching; an allow rule never is.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from jarvis.errors import PolicyError
from jarvis.permissions.levels import PermissionLevel
from jarvis.permissions.paths import PathGuard, is_within
from jarvis.permissions.request import PermissionRequest
from jarvis.permissions.resources import ResourceType, host_matches, normalize_host

_GLOB_CHARS = set("*?[")
_KEYS = {"id", "effect", "tool", "action", "resource_type", "resources", "levels", "description"}


class Effect(str, Enum):
    DENY = "deny"
    CONFIRM = "confirm"
    ALLOW = "allow"

    @property
    def precedence(self) -> int:  # lower = wins
        return {Effect.DENY: 0, Effect.CONFIRM: 1, Effect.ALLOW: 2}[self]


def _is_glob(text: str) -> bool:
    return any(c in _GLOB_CHARS for c in text)


def _glob(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(value, pattern)


@dataclass(frozen=True)
class Rule:
    id: str
    effect: Effect
    tool: str | None = None             # exact name or glob; None = any tool (deny/confirm only)
    action: str | None = None           # exact name or glob; None = any action (deny/confirm only)
    resource_type: ResourceType | None = None
    resources: tuple[str, ...] = ()     # PATH: directories/files | DOMAIN: host or *.host | OTHER: glob
    levels: tuple[PermissionLevel, ...] = ()  # rule applies only to these (effective) levels; () = all
    description: str = ""

    @property
    def is_allow(self) -> bool:
        return self.effect is Effect.ALLOW

    def validate(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise PolicyError("every rule needs a non-empty id")
        if not isinstance(self.effect, Effect):
            raise PolicyError(f"rule {self.id!r}: invalid effect")
        if self.resources and self.resource_type in (None, ResourceType.NONE):
            raise PolicyError(f"rule {self.id!r}: 'resources' requires a resource_type")
        for r in self.resources:
            if not isinstance(r, str) or not r.strip():
                raise PolicyError(f"rule {self.id!r}: resources must be non-empty strings")
            if r.strip() in ("*", "**", "/", "*.*"):
                raise PolicyError(f"rule {self.id!r}: unrestricted resource pattern {r!r} is not allowed")
        if self.is_allow:
            if not self.tool or _is_glob(self.tool):
                raise PolicyError(f"rule {self.id!r}: allow rules must name an exact tool (no wildcards)")
            if not self.action or self.action.strip() == "*":
                raise PolicyError(f"rule {self.id!r}: allow rules must name an action (no bare '*')")
            if PermissionLevel.RED in self.levels:
                raise PolicyError(f"rule {self.id!r}: RED actions can never be allowed")
            if self.resource_type is ResourceType.DOMAIN:
                for r in self.resources:
                    if r.startswith("*.") and "." not in r[2:]:
                        raise PolicyError(f"rule {self.id!r}: allow rule too broad: {r!r}")

    # -- matching -----------------------------------------------------------------------------------
    def matches(self, req: PermissionRequest, level: PermissionLevel, resource: str | None, guard: PathGuard) -> bool:
        """`resource` is the engine-normalised resource (real path / host / raw string) or None."""
        if self.tool is not None and not _glob(self.tool, req.tool):
            return False
        if self.action is not None and not _glob(self.action, req.action):
            return False
        if self.levels and level not in self.levels:
            return False
        if self.resource_type is None:
            return True
        if req.resource_type is not self.resource_type:
            # a request without any resource info cannot be ruled out: deny/confirm rules still apply
            return req.resource_type is ResourceType.NONE and not self.is_allow
        if not self.resources:
            return True
        if resource is None:
            return not self.is_allow
        return any(self._resource_matches(p, resource, guard) for p in self.resources)

    def _resource_matches(self, pattern: str, resource: str, guard: PathGuard) -> bool:
        if self.resource_type is ResourceType.PATH:
            return is_within(resource, guard.resolve_pattern(pattern), fold=not self.is_allow)  # deny/confirm over-match
        if self.resource_type is ResourceType.DOMAIN:
            return host_matches(pattern, resource)
        return _glob(pattern, resource)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "effect": self.effect.value, "tool": self.tool, "action": self.action,
                "resource_type": self.resource_type.value if self.resource_type else None,
                "resources": list(self.resources), "levels": [lv.value for lv in self.levels],
                "description": self.description}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Rule":
        if not isinstance(data, Mapping):
            raise PolicyError("each rule must be a table")
        unknown = set(data) - _KEYS
        if unknown:
            raise PolicyError(f"rule {data.get('id', '?')!r}: unknown keys {sorted(unknown)}")
        try:
            effect = Effect(str(data.get("effect", "")).lower())
        except ValueError:
            raise PolicyError(f"rule {data.get('id', '?')!r}: effect must be allow, confirm or deny") from None
        try:
            rtype = ResourceType(str(data["resource_type"]).lower()) if data.get("resource_type") else None
            levels = tuple(PermissionLevel(str(x).lower()) for x in data.get("levels", ()))
        except ValueError as exc:
            raise PolicyError(f"rule {data.get('id', '?')!r}: {exc}") from None
        resources = data.get("resources", ())
        if isinstance(resources, str) or not isinstance(resources, (list, tuple)):
            raise PolicyError(f"rule {data.get('id', '?')!r}: resources must be a list")
        for key in ("tool", "action", "description"):
            if data.get(key) is not None and not isinstance(data[key], str):
                raise PolicyError(f"rule {data.get('id', '?')!r}: {key} must be a string")
        rule = cls(id=data.get("id", ""), effect=effect, tool=data.get("tool"), action=data.get("action"),
                   resource_type=rtype, resources=tuple(resources), levels=levels,
                   description=data.get("description", ""))
        rule.validate()
        return rule


@dataclass(frozen=True)
class Verdict:
    effect: Effect | None = None       # None = no rule matched
    rule: str | None = None            # id of the deciding rule
    considered: tuple[str, ...] = ()   # ids of all matching rules, in deterministic order


@dataclass(frozen=True)
class Policy:
    rules: tuple[Rule, ...] = ()

    def __post_init__(self) -> None:
        ids = [r.id for r in self.rules]
        if len(set(ids)) != len(ids):
            raise PolicyError("duplicate rule ids")
        for r in self.rules:
            r.validate()

    @property
    def fingerprint(self) -> str:
        canon = json.dumps([r.to_dict() for r in sorted(self.rules, key=lambda r: r.id)], sort_keys=True)
        return hashlib.sha256(canon.encode()).hexdigest()[:16]

    def verdict(self, req: PermissionRequest, level: PermissionLevel, resource: str | None, guard: PathGuard) -> Verdict:
        matching = [r for r in self.rules if r.matches(req, level, resource, guard)]
        if not matching:
            return Verdict()
        matching.sort(key=lambda r: (r.effect.precedence, r.id))  # safest effect first, ties by id: deterministic
        return Verdict(matching[0].effect, matching[0].id, tuple(r.id for r in matching))

    def validate_paths(self, guard: PathGuard) -> None:
        """Fail early on unusable path patterns."""
        for r in self.rules:
            if r.resource_type is ResourceType.PATH:
                for p in r.resources:
                    guard.resolve_pattern(p)

    @classmethod
    def from_rules(cls, rules: Iterable[Mapping[str, Any] | Rule]) -> "Policy":
        return cls(tuple(r if isinstance(r, Rule) else Rule.from_dict(r) for r in rules))

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> "Policy":
        p = Path(path).expanduser()
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise PolicyError(f"policy file not found: {p}") from None
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
            raise PolicyError(f"cannot read policy file {p}: {exc}") from exc
        unknown = set(data) - {"rule"}
        if unknown:
            raise PolicyError(f"unknown top-level keys in policy file: {sorted(unknown)}")
        rules = data.get("rule", [])
        if not isinstance(rules, list):
            raise PolicyError("policy file: [[rule]] entries expected")
        return cls.from_rules(rules)
