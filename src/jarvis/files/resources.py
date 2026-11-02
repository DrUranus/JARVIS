"""Resource names of the file tools. Every file action uses the engine's PATH resource type (the real, absolute path of the TARGET: the
destination for move/copy/organize_step), so the PathGuard (roots, symlinks, protected paths) is the boundary. File contents are never part of a resource."""
TOOL = "files"
