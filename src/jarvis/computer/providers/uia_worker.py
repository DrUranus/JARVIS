"""Worker process of the read-only UI-Automation provider (backlog step `uia-provider-readonly`).

Runs as `python -m jarvis.computer.providers.uia_worker`, started and stopped only by `PywinautoUiaProvider`. The MAIN thread of this process is the one and only
owner of the UIA connection (docs/uia-compat-results.md: a connection used from another thread hangs). It reads JSON lines from stdin and answers on stdout.

Only reading: window list and element tree (name, type, ids, rectangle, flags, password flag). Values of controls are never read. No input, no click, no
process control. pywinauto is imported lazily inside `PywinautoReader`, so importing this module needs no library.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any, TextIO

MAX_WINDOWS = 200
MAX_REQUEST_BYTES = 4096


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


class PywinautoReader:
    """The only code that touches pywinauto (UIA backend)."""

    def __init__(self) -> None:
        from pywinauto.uia_element_info import UIAElementInfo      # lazy: a missing library is reported by the provider factory
        self._info = UIAElementInfo

    # -- helpers ---------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _rect(info: Any) -> list[int]:
        r = info.rectangle
        return [int(r.left), int(r.top), max(0, int(r.right - r.left)), max(0, int(r.bottom - r.top))]

    @staticmethod
    def _password(info: Any) -> bool:
        try:
            return bool(info.element.CurrentIsPassword)
        except Exception:      # noqa: BLE001 - unknown means: treat as protected
            return True

    def windows(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for child in self._info().children():
            try:
                handle, title = int(child.handle or 0), str(child.name or "")
                if handle and title and child.visible:
                    out.append({"handle": handle, "title": title, "class_name": str(child.class_name or ""), "pid": int(child.process_id or 0)})
            except Exception:      # noqa: BLE001 - a window that vanished while reading
                continue
            if len(out) >= MAX_WINDOWS:
                break
        return out

    def tree(self, handle: int, max_depth: int, max_nodes: int, max_text: int, deadline: float) -> dict[str, Any]:
        try:
            root = self._info(handle)
            str(root.name)
        except Exception:      # noqa: BLE001
            raise LookupError("no such window") from None
        budget = {"nodes": 0}

        def cut(text: Any) -> str:
            return str(text or "")[:max_text]

        def walk(info: Any, path: str, depth: int) -> dict[str, Any]:
            budget["nodes"] += 1
            node: dict[str, Any] = {"runtime_id": path, "name": cut(info.name), "control_type": str(info.control_type or "Unknown"),
                                    "automation_id": cut(info.automation_id), "class_name": cut(info.class_name), "rect": self._rect(info),
                                    "enabled": bool(info.enabled), "visible": bool(info.visible), "is_password": self._password(info), "children": []}
            if depth < max_depth:
                try:
                    kids = info.children()
                except Exception:      # noqa: BLE001
                    kids = []
                for index, kid in enumerate(kids):
                    if budget["nodes"] >= max_nodes or time.monotonic() > deadline:
                        break
                    try:
                        node["children"].append(walk(kid, f"{path}.{index}", depth + 1))
                    except Exception:      # noqa: BLE001 - an element that vanished while reading is skipped
                        continue
            return node

        return walk(root, "0", 0)


def _answer(reader: Any, request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "windows":
        return {"ok": True, "windows": reader.windows()}
    if op == "tree":
        handle, depth, nodes, text = (_int(request.get(k)) for k in ("handle", "max_depth", "max_nodes", "max_text"))
        if min(handle, depth, nodes, text) < 0:
            return {"ok": False, "code": "invalid_input", "message": "bad request"}
        deadline = time.monotonic() + 600.0
        try:
            return {"ok": True, "tree": reader.tree(handle, depth, nodes, text, deadline)}
        except LookupError:
            return {"ok": False, "code": "window_not_found", "message": "no such window"}
    return {"ok": False, "code": "invalid_input", "message": "unknown operation"}


def serve(reader: Any, stdin: TextIO, stdout: TextIO) -> None:
    """Protocol loop: one JSON request per line, one JSON answer per line. Errors never carry exception text (it could contain window content)."""
    for line in stdin:
        if len(line) > MAX_REQUEST_BYTES:
            break
        try:
            request = json.loads(line)
            answer = _answer(reader, request) if isinstance(request, dict) else {"ok": False, "code": "invalid_input", "message": "bad request"}
            answer["id"] = request.get("id") if isinstance(request, dict) else None
        except Exception as exc:      # noqa: BLE001 - never leak the message
            answer = {"ok": False, "code": "backend_error", "message": f"worker failed ({type(exc).__name__})", "id": None}
            try:
                answer["id"] = request.get("id")
            except Exception:      # noqa: BLE001
                pass
        stdout.write(json.dumps(answer, ensure_ascii=True) + "\n")
        stdout.flush()


def main() -> int:
    channel, sys.stdout = sys.stdout, sys.stderr      # library output must never corrupt the protocol channel
    try:
        reader = PywinautoReader()
    except Exception as exc:      # noqa: BLE001
        channel.write(json.dumps({"ok": False, "code": "backend_unavailable", "message": f"pywinauto cannot be loaded ({type(exc).__name__})", "id": None}) + "\n")
        channel.flush()
        return 2
    serve(reader, sys.stdin, channel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
