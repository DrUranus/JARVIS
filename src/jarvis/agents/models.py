"""AgentTask and the JSON-compatibility rules of everything exchanged between agents."""
from __future__ import annotations

import copy
import json
import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from jarvis.agents import policy
from jarvis.agents.errors import InvalidTaskError


def new_task_id() -> str:
    return "at-" + uuid.uuid4().hex[:12]


def check_json(value: Any, what: str, depth: int = 0) -> None:
    """Data passed between agents is plain JSON-like data (dict/list/str/int/float/bool/None): no objects, no callables, no handles."""
    if depth > policy.MAX_INPUT_DEPTH:
        raise InvalidTaskError(f"{what} is nested too deeply")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidTaskError(f"{what} contains a non-finite number")
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            check_json(v, what, depth + 1)
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise InvalidTaskError(f"{what} keys must be text")
            check_json(v, what, depth + 1)
        return
    raise InvalidTaskError(f"{what} may only contain plain data (got {type(value).__name__})")


def clean_json(value: Any) -> Any:
    """A deep, plain copy (tuples become lists, mappings become dicts) so nobody shares mutable state with a task."""
    if isinstance(value, Mapping):
        return {k: clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    return value


@dataclass(frozen=True)
class AgentTask:
    objective: str
    agent_id: str | None = None                       # None: the orchestrator picks an agent by required_capabilities
    input: Mapping[str, Any] = field(default_factory=dict)
    required_capabilities: frozenset[str] = frozenset()
    priority: int = 5                                 # 1 (highest) .. 10 (lowest)
    parent_task_id: str | None = None
    dependencies: tuple[str, ...] = ()                # tasks that must have SUCCEEDED first (direct dependencies only)
    timeout: float | None = None                      # seconds; None = the orchestrator's default
    metadata: Mapping[str, str] = field(default_factory=dict)
    memory_query: str | None = None                   # explicit request for a few relevant memories (otherwise the agent sees none)
    task_id: str = field(default_factory=new_task_id)

    def __post_init__(self) -> None:
        if not policy.valid_id(self.task_id):
            raise InvalidTaskError("task_id must be 1..64 characters of letters, digits, _ . -")
        if self.agent_id is not None and not policy.valid_agent_id(self.agent_id):
            raise InvalidTaskError("agent_id must be a short lower-case identifier")
        if not isinstance(self.objective, str) or not self.objective.strip() or len(self.objective) > policy.MAX_OBJECTIVE \
                or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in self.objective):
            raise InvalidTaskError(f"objective must be 1..{policy.MAX_OBJECTIVE} characters of plain text")
        caps = frozenset(self.required_capabilities)
        if not all(policy.valid_capability(c) for c in caps):
            raise InvalidTaskError("capability names look like 'browser.read'")
        object.__setattr__(self, "required_capabilities", caps)
        if not isinstance(self.priority, int) or isinstance(self.priority, bool) or not 1 <= self.priority <= 10:
            raise InvalidTaskError("priority must be an integer within 1..10")
        for ref, name in ((self.parent_task_id, "parent_task_id"),):
            if ref is not None and not policy.valid_id(ref):
                raise InvalidTaskError(f"{name} is not a valid task id")
        deps = tuple(self.dependencies)
        if not all(policy.valid_id(d) for d in deps) or len(set(deps)) != len(deps) or len(deps) > 10:
            raise InvalidTaskError("dependencies must be up to 10 distinct task ids")
        if self.task_id in deps or self.task_id == self.parent_task_id:
            raise InvalidTaskError("a task cannot depend on itself")
        object.__setattr__(self, "dependencies", deps)
        if self.timeout is not None and (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                                         or not 0 < self.timeout <= policy.MAX_TIMEOUT):
            raise InvalidTaskError(f"timeout must be within 0..{policy.MAX_TIMEOUT:g} seconds")
        if not isinstance(self.input, Mapping):
            raise InvalidTaskError("input must be a mapping")
        check_json(self.input, "input")
        if len(json.dumps(clean_json(self.input))) > policy.MAX_INPUT_BYTES:
            raise InvalidTaskError("input is too large")
        object.__setattr__(self, "input", clean_json(self.input))
        if not isinstance(self.metadata, Mapping) or len(self.metadata) > policy.MAX_METADATA_ITEMS or not all(
                isinstance(k, str) and isinstance(v, str) and len(k) <= 50 and len(v) <= 500 for k, v in self.metadata.items()):
            raise InvalidTaskError("metadata must be a small mapping of short strings")
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.memory_query is not None and (not isinstance(self.memory_query, str) or not self.memory_query.strip() or len(self.memory_query) > 200):
            raise InvalidTaskError("memory_query must be a short text")

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "agent_id": self.agent_id, "objective": self.objective, "input": copy.deepcopy(dict(self.input)),
                "required_capabilities": sorted(self.required_capabilities), "priority": self.priority,
                "parent_task_id": self.parent_task_id, "dependencies": list(self.dependencies), "timeout": self.timeout,
                "metadata": dict(self.metadata), "memory_query": self.memory_query}

    def __repr__(self) -> str:  # the objective and the input can contain anything: identity and routing only
        return (f"AgentTask(task_id={self.task_id!r}, agent_id={self.agent_id!r}, priority={self.priority}, "
                f"capabilities={sorted(self.required_capabilities)})")
