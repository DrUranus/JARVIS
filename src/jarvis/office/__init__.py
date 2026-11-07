"""Office files (office-docs, O1): read `.xlsx`/`.docx` and create NEW ones inside the confirmed workspace.

One ProtectedTool `office` in the ordinary ToolRegistry: every call goes through ToolRegistry.execute -> PermissionEngine. Macros, VBA, active content,
external links and OLE objects are never loaded, run or resolved (the package is checked BEFORE a library sees it); no program is started, nothing is
overwritten or deleted. The libraries come from the optional extra `office` and are imported lazily. The Core never imports this package; `bootstrap`
wires it (opt-in, office.enabled = false by default). Design: docs/OFFICE_DESIGN.md.
"""
from jarvis.office.controller import OfficeController

__all__ = ["OfficeController"]
