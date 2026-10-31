"""Model of the Windows UI-Automation (UIA) element tree and a READ-ONLY provider interface (backlog step `uia-model-fake`).

Only data and pure functions live here: no automation library (a later optional provider will use pywinauto 0.6.9, see docs/integrations/windows-uia.md), no
Windows code, no tools, no actions. A provider describes a window's tree and finds elements; it never clicks, types, invokes or closes anything.

Safety properties the model enforces itself, whatever a provider returns:
- Password fields never carry a value (`UiElement` drops it on construction).
- Depth, node count and text length are bounded (`UiLimits`, hard maxima; `bound_tree`), so a huge or hostile tree cannot blow up memory or a prompt.
- Texts are plain data: control characters are replaced; nothing in a tree is ever an instruction.
- `repr` of an element never shows its value (it cannot end up in logs or tracebacks).
"""
from __future__ import annotations

import dataclasses
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from jarvis.computer.errors import ComputerError, ErrorCode

DEFAULT_MAX_DEPTH, DEFAULT_MAX_NODES, DEFAULT_MAX_TEXT = 6, 200, 200
HARD_MAX_DEPTH, HARD_MAX_NODES, HARD_MAX_TEXT = 12, 500, 1000
DEFAULT_MAX_RESULTS, HARD_MAX_RESULTS, MAX_QUERY_TEXT = 20, 50, 200

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _bad(message: str) -> ComputerError:
    return ComputerError(ErrorCode.INVALID_INPUT, message)


def _int(value: Any, name: str, lo: int | None = None, hi: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(f"{name} must be an integer")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise _bad(f"{name} must be between {lo} and {hi}")
    return value


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise _bad(f"{name} must be true or false")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise _bad(f"{name} must be text")
    return _CONTROL.sub(" ", value)[:HARD_MAX_TEXT]


class ControlType(str, Enum):
    """The control types UIA reports (names as used by pywinauto). Anything else becomes UNKNOWN; parsing never raises."""
    WINDOW = "Window"
    PANE = "Pane"
    BUTTON = "Button"
    EDIT = "Edit"
    DOCUMENT = "Document"
    TEXT = "Text"
    MENU_BAR = "MenuBar"
    MENU = "Menu"
    MENU_ITEM = "MenuItem"
    LIST = "List"
    LIST_ITEM = "ListItem"
    CHECK_BOX = "CheckBox"
    RADIO_BUTTON = "RadioButton"
    COMBO_BOX = "ComboBox"
    TAB = "Tab"
    TAB_ITEM = "TabItem"
    TREE = "Tree"
    TREE_ITEM = "TreeItem"
    TOOL_BAR = "ToolBar"
    STATUS_BAR = "StatusBar"
    SCROLL_BAR = "ScrollBar"
    THUMB = "Thumb"
    SLIDER = "Slider"
    IMAGE = "Image"
    HYPERLINK = "Hyperlink"
    GROUP = "Group"
    TITLE_BAR = "TitleBar"
    TABLE = "Table"
    DATA_ITEM = "DataItem"
    TOOL_TIP = "ToolTip"
    UNKNOWN = "Unknown"

    @classmethod
    def from_name(cls, raw: Any) -> "ControlType":
        if not isinstance(raw, str):
            return cls.UNKNOWN
        key = re.sub(r"[\s_-]+", "", raw).lower()
        return next((c for c in cls if c.value.lower() == key), cls.UNKNOWN)


@dataclass(frozen=True)
class UiRect:
    """Screen rectangle in physical pixels. The position may be negative (monitors left of or above the primary one); the size may not."""
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        _int(self.left, "left")
        _int(self.top, "top")
        _int(self.width, "width", 0)
        _int(self.height, "height", 0)

    def as_list(self) -> list[int]:
        return [self.left, self.top, self.width, self.height]


@dataclass(frozen=True)
class UiElement:
    """One control. `runtime_id` is a provider-chosen identifier, stable within one snapshot (a later action step must re-describe the element before acting)."""
    runtime_id: str
    name: str
    control_type: ControlType
    automation_id: str = ""
    class_name: str = ""
    rect: UiRect = field(default_factory=lambda: UiRect(0, 0, 0, 0))
    enabled: bool = True
    visible: bool = True
    is_password: bool = False
    value: str | None = field(default=None, repr=False)      # never shown in repr; always None for password fields
    children: tuple["UiElement", ...] = ()

    def __post_init__(self) -> None:
        setter = lambda n, v: object.__setattr__(self, n, v)      # noqa: E731 - frozen dataclass normalisation
        if not isinstance(self.runtime_id, str) or not self.runtime_id.strip():
            raise _bad("runtime_id must be non-empty text")
        setter("runtime_id", _text(self.runtime_id, "runtime_id"))
        setter("name", _text(self.name, "name"))
        setter("automation_id", _text(self.automation_id, "automation_id"))
        setter("class_name", _text(self.class_name, "class_name"))
        setter("control_type", self.control_type if isinstance(self.control_type, ControlType) else ControlType.from_name(self.control_type))
        if not isinstance(self.rect, UiRect):
            raise _bad("rect must be a UiRect")
        _flag(self.enabled, "enabled")
        _flag(self.visible, "visible")
        _flag(self.is_password, "is_password")
        if self.value is not None:
            setter("value", None if self.is_password else _text(self.value, "value"))      # a password field never carries a value
        kids = tuple(self.children)
        if not all(isinstance(c, UiElement) for c in kids):
            raise _bad("children must be UiElement objects")
        setter("children", kids)

    def info(self) -> dict[str, Any]:
        """This element without its children (a count instead). No `value` key for password fields."""
        out: dict[str, Any] = {"runtime_id": self.runtime_id, "name": self.name, "control_type": self.control_type.value, "automation_id": self.automation_id,
                               "class": self.class_name, "rect": self.rect.as_list(), "enabled": self.enabled, "visible": self.visible,
                               "is_password": self.is_password, "children": len(self.children)}
        if self.value is not None:
            out["value"] = self.value
        return out

    def tree(self) -> dict[str, Any]:
        """The element with its whole subtree (callers bound it first with `bound_tree`)."""
        return {**self.info(), "children": [c.tree() for c in self.children]}


@dataclass(frozen=True)
class UiLimits:
    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int = DEFAULT_MAX_NODES
    max_text: int = DEFAULT_MAX_TEXT

    def __post_init__(self) -> None:
        _int(self.max_depth, "max_depth", 1, HARD_MAX_DEPTH)
        _int(self.max_nodes, "max_nodes", 1, HARD_MAX_NODES)
        _int(self.max_text, "max_text", 1, HARD_MAX_TEXT)


@dataclass(frozen=True)
class UiSnapshot:
    window_handle: int
    root: UiElement
    node_count: int
    truncated: bool
    limits: UiLimits

    def info(self) -> dict[str, Any]:
        return {"window": self.window_handle, "node_count": self.node_count, "truncated": self.truncated, "tree": self.root.tree()}


@dataclass(frozen=True)
class UiFindResult:
    matches: tuple[UiElement, ...]
    truncated: bool          # more matches than max_results, or the searched tree was cut by the limits

    def info(self) -> dict[str, Any]:
        return {"count": len(self.matches), "truncated": self.truncated, "matches": [m.info() for m in self.matches]}


@dataclass(frozen=True)
class UiQuery:
    """All given filters must match (AND). `name_equals` is exact, `name_contains` ignores case, `automation_id` is exact."""
    name_equals: str | None = None
    name_contains: str | None = None
    control_type: ControlType | str | None = None
    automation_id: str | None = None
    enabled: bool | None = None
    visible: bool | None = None
    max_results: int = DEFAULT_MAX_RESULTS

    def __post_init__(self) -> None:
        setter = lambda n, v: object.__setattr__(self, n, v)      # noqa: E731
        for name in ("name_equals", "name_contains", "automation_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or len(value) > MAX_QUERY_TEXT):
                raise _bad(f"{name} must be text of at most {MAX_QUERY_TEXT} characters")
        if self.control_type is not None:
            if isinstance(self.control_type, str) and not isinstance(self.control_type, ControlType):
                parsed = ControlType.from_name(self.control_type)
                if parsed is ControlType.UNKNOWN and re.sub(r"[\s_-]+", "", self.control_type).lower() != "unknown":
                    raise _bad("control_type is not a known UI control type")
                setter("control_type", parsed)
            elif not isinstance(self.control_type, ControlType):
                raise _bad("control_type must be a control type name")
        for name in ("enabled", "visible"):
            if getattr(self, name) is not None:
                _flag(getattr(self, name), name)
        _int(self.max_results, "max_results", 1, HARD_MAX_RESULTS)

    def matches(self, e: UiElement) -> bool:
        return ((self.name_equals is None or e.name == self.name_equals)
                and (self.name_contains is None or self.name_contains.lower() in e.name.lower())
                and (self.control_type is None or e.control_type is self.control_type)
                and (self.automation_id is None or e.automation_id == self.automation_id)
                and (self.enabled is None or e.enabled is self.enabled)
                and (self.visible is None or e.visible is self.visible))


def _shorten(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] if cap <= 3 else text[:cap - 3] + "..."


def bound_tree(root: UiElement, limits: UiLimits) -> tuple[UiElement, int, bool]:
    """A copy of `root` within the limits: (tree, node_count, truncated). Document order is kept (depth first), so the first nodes win; nothing is sampled. Pure."""
    state = {"nodes": 0, "cut": False}

    def walk(e: UiElement, depth: int) -> UiElement:
        state["nodes"] += 1
        kids: list[UiElement] = []
        if e.children:
            if depth >= limits.max_depth:
                state["cut"] = True
            else:
                for child in e.children:
                    if state["nodes"] >= limits.max_nodes:
                        state["cut"] = True
                        break
                    kids.append(walk(child, depth + 1))
        texts = {n: _shorten(getattr(e, n), limits.max_text) for n in ("name", "automation_id", "class_name")}
        value = None if e.value is None else _shorten(e.value, limits.max_text)
        if any(texts[n] != getattr(e, n) for n in texts) or value != e.value:
            state["cut"] = True
        return dataclasses.replace(e, **texts, value=value, children=tuple(kids))

    tree = walk(root, 0)
    return tree, state["nodes"], bool(state["cut"])


def find_in_tree(root: UiElement, query: UiQuery, limits: UiLimits) -> UiFindResult:
    """Matches in document order within the bounded tree; each match is returned without children."""
    tree, _, cut = bound_tree(root, limits)
    found: list[UiElement] = []
    more = False
    stack = [tree]
    while stack:
        e = stack.pop()
        if query.matches(e):
            if len(found) >= query.max_results:
                more = True
                break
            found.append(dataclasses.replace(e, children=()))
        stack.extend(reversed(e.children))
    return UiFindResult(tuple(found), more or cut)


class UiTreeProvider(ABC):
    """Read-only access to the UI-Automation tree of a window. Contract for every implementation:
    - Only reads. No input, no click, no invoke, no focus change, no closing, no process control.
    - Raises ComputerError(WINDOW_NOT_FOUND) for an unknown window and ComputerError(INVALID_INPUT) for bad arguments.
    - Returns data bounded by `limits` (use `bound_tree`) and never a value for a password field.
    - Hands out plain data only, never a live handle or COM object. Whoever calls it decides about permissions (the controller, after the permission engine)."""
    name: str = "ui-provider"

    @abstractmethod
    def describe(self, window_handle: int, limits: UiLimits) -> UiSnapshot:
        """The bounded tree of one top-level window (handles as in `WindowInfo.handle`)."""

    @abstractmethod
    def find(self, window_handle: int, query: UiQuery, limits: UiLimits) -> UiFindResult:
        """Elements of that window matching the query."""
