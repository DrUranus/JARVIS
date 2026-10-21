"""Coding agent v1: controlled software-development steps behind a provider interface, every action a permission-checked tool call.

The Core never imports this package. `bootstrap` builds a CodingSubsystem (one tool in the ToolRegistry + baseline rules in the
PermissionEngine). Independent of Computer Control and the Browser Agent: it has its own controller and never drives either.
"""
from jarvis.coding.backend import CodingProvider
from jarvis.coding.controller import CodingController, Plan
from jarvis.coding.errors import CodingError, CodingErrorCode
from jarvis.coding.models import (CommandResult, CommandSpec, DirEntry, FileChange, FileStat, ProjectInfo, SearchHit, SessionStatus,
                                  TestResult, Workspace)

__all__ = ["CodingController", "Plan", "CodingProvider", "CodingError", "CodingErrorCode", "CommandSpec", "CommandResult", "DirEntry",
           "FileChange", "FileStat", "ProjectInfo", "SearchHit", "SessionStatus", "TestResult", "Workspace"]
