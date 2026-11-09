"""FilesAgent: the `files` and `office` tools as ONE agent for file and document requests.

Every step is a call through `ctx.tools` (ToolGateway -> ToolRegistry -> PermissionEngine): reading is GREEN, every change is YELLOW with a preview and asks the person.
The agent holds no controller and no path list; the tools themselves enforce the confirmed roots, the no-delete rule, secrets protection and hash-guarded writes.
Capabilities (least privilege per task): files.read (list, read, organize plan), files.write (create, write, move, copy, mkdir, organize_step, replace), office.read, office.create.

One convenience step exists on top of the tools: `replace` (path, old_text, new_text). It is NOT a new power: it reads the file with the `files` tool (refusing truncated, redacted
or ambiguous-ending files), requires `old_text` to occur exactly once, and then calls the tool's own hash-guarded `write`. Both calls are asked/audited like any other call.
Existing Office files are never changed (the office tool has no such action)."""
from __future__ import annotations

import dataclasses
from typing import Any

from jarvis.agents import policy as P
from jarvis.agents.adapters.base import ToolSpec, ToolStepAgent
from jarvis.agents.context import AgentContext, ToolGateway
from jarvis.tools import ToolResult

_FILES_ACTIONS = {**{a: P.FILES_READ for a in ("list", "read", "organize")},
                  **{a: P.FILES_WRITE for a in ("create", "write", "move", "copy", "mkdir", "organize_step", "replace")}}
_FILES_PARAMS = frozenset({"action", "path", "destination", "content", "expected_sha256", "offset", "limit", "rules", "plan_id", "step", "old_text", "new_text"})
_OFFICE_PARAMS = frozenset({"action", "path", "content", "sheet", "limit"})
MAX_EDIT_CHARS = 20_000


def _trailing_newline(size: int, content: str, lines: int) -> bool | None:
    """Did the file end with a line break? `read` returns the lines joined without the last break; the byte size tells which variant it was (LF or CRLF files).
    None = cannot be decided (mixed endings, BOM ...): the edit is refused instead of guessing."""
    base = len(content.encode("utf-8"))
    lf_no, lf_yes = base, base + 1
    crlf_no, crlf_yes = base + max(lines - 1, 0), base + max(lines - 1, 0) + 2
    if size in (lf_no, crlf_no) and size not in (lf_yes, crlf_yes):
        return False
    if size in (lf_yes, crlf_yes) and size not in (lf_no, crlf_no):
        return True
    return None


class _ReplaceGateway:
    """The agent's gateway plus the `replace` step. Everything else is forwarded unchanged; replace is read + the tool's own hash-guarded write."""

    def __init__(self, inner: ToolGateway) -> None:
        self._g = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._g, name)

    def call(self, tool: str, **kwargs: Any) -> ToolResult:
        if tool != "files" or kwargs.get("action") != "replace":
            return self._g.call(tool, **kwargs)
        path, old, new = kwargs.get("path"), kwargs.get("old_text"), kwargs.get("new_text")
        if not isinstance(path, str) or not isinstance(old, str) or not old or not isinstance(new, str) or len(old) > MAX_EDIT_CHARS or len(new) > MAX_EDIT_CHARS:
            return ToolResult.fail("replace needs path, a non-empty old_text and new_text (each at most %d characters)" % MAX_EDIT_CHARS)
        read = self._g.call("files", action="read", path=path, limit=5000)
        if not read.success:
            return read                                                          # denied/failed: the caller sees exactly the tool's answer (BLOCKED for a denial)
        out = read.output if isinstance(read.output, dict) else {}
        content = out.get("content")
        if not isinstance(content, str) or out.get("truncated") or out.get("secrets_redacted") or not isinstance(out.get("sha256"), str):
            return ToolResult.fail("replace refused: the file is too large, contains secret-like text or could not be read completely; nothing was changed")
        if content.count(old) != 1:
            return ToolResult.fail(f"replace refused: the text to replace occurs {content.count(old)} times (it must occur exactly once); nothing was changed")
        newline = _trailing_newline(int(out.get("size", -1)), content, int(out.get("lines", 0)))
        if newline is None:
            return ToolResult.fail("replace refused: the line endings of the file are ambiguous; nothing was changed")
        updated = content.replace(old, new, 1) + ("\n" if newline else "")
        return self._g.call("files", action="write", path=path, content=updated, expected_sha256=out["sha256"])


class FilesAgent(ToolStepAgent):
    id = "files"
    name = "Files Agent"
    description = ("Reads, lists, creates, copies, moves and edits files inside the confirmed directories, and reads and creates Office files (.xlsx, .docx) in the confirmed "
                   "workspace, through the permission-checked files and office tools. Every change is asked with a preview; nothing is deleted.")
    capabilities = frozenset({P.FILES_READ, P.FILES_WRITE, P.OFFICE_READ, P.OFFICE_CREATE})
    optional_tools = frozenset({"files", "office"})       # either may be switched off; the agent needs at least one (checked when the agents are built)
    tools = {
        "files": ToolSpec(_FILES_PARAMS, _FILES_ACTIONS),
        "office": ToolSpec(_OFFICE_PARAMS, {"read": P.OFFICE_READ, "create": P.OFFICE_CREATE}),
    }

    def perform(self, task, ctx: AgentContext):
        gw = ctx.tools
        if gw is not None:
            ctx = dataclasses.replace(ctx, tools=_ReplaceGateway(gw))
        return super().perform(task, ctx)

    def _plan_list(self, steps, ctx, *, nested=False):
        planned = super()._plan_list(steps, ctx, nested=nested)
        if isinstance(planned, list):
            for tool, args, _ in planned:                                       # `replace` reads AND writes: both capabilities must be allowed for the task
                if tool == "files" and args.get("action") == "replace" and P.FILES_READ not in ctx.allowed_capabilities:
                    from jarvis.agents.result import AgentOutcome
                    return AgentOutcome.blocked("a replace step needs the capabilities 'files.read' and 'files.write'", code="capability_not_allowed")
        return planned
