"""File tools (A8): list, read (bounded), create, write (hash-guarded), move, copy, mkdir and organize (plan first, every step confirmed).

One ProtectedTool `files` in the ordinary ToolRegistry: every call goes through ToolRegistry.execute -> PermissionEngine. There is NO delete,
no overwrite by move/copy/create, no shell, and nothing outside the confirmed roots (the engine's PathGuard plus the controller's own checks).
The Core never imports this package; `bootstrap` wires it (opt-in, files.enabled = false by default).
"""
from jarvis.files.controller import FilesController, Plan
from jarvis.files.errors import FilesError

__all__ = ["FilesController", "FilesError", "Plan"]
