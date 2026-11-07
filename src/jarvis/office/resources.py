"""Resource name of the office tool. Every action uses the engine's PATH resource type (the real, absolute path of the file), so the PathGuard
(roots, symlinks, protected paths) is the boundary and a grant is bound to exactly one file. Document contents are never part of a resource."""
TOOL = "office"
