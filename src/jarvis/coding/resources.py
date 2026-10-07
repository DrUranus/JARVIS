"""Resource names of the coding agent.

    coding://workspace/<wid>              a workspace            (shown in prompts)
    coding://file/<wid>/<relative path>   one file of a workspace (shown in prompts)
    coding://session/<sid>                a coding session        (engine resource of session actions)
    coding://test/<sid>/<runner>#<state>  running tests on exactly this state of the code (engine resource of `test`)
    <real path>                           engine resource (type PATH) of every file/directory action: the PathGuard
                                          checks allowed roots, denied and protected paths on it

File and directory actions use the engine's PATH resource type so the existing PathGuard (roots, symlinks, case folding,
protected paths) is the boundary, and ordinary path rules apply. The `coding://` names identify the target for people.
Nothing a file contains is ever part of a resource.
"""
from __future__ import annotations

import re

TOOL = "coding"
_UNSAFE = re.compile(r"[^\w.\-:/ ]")


def _clean(text: str, limit: int = 200) -> str:
    return _UNSAFE.sub("_", text.strip())[:limit] or "unknown"


def workspace_resource(wid: str) -> str:
    return f"coding://workspace/{_clean(wid, 40)}"


def file_resource(wid: str, rel: str) -> str:
    return f"coding://file/{_clean(wid, 40)}/{_clean(rel, 300)}"


def session_resource(sid: str) -> str:
    return f"coding://session/{_clean(sid, 40)}"


def test_resource(sid: str, runner: str, state: str) -> str:
    return f"coding://test/{_clean(sid, 40)}/{_clean(runner, 40).replace(' ', '-')}#{_clean(state, 16)}"


def llm_resource(sid: str) -> str:
    return f"coding://llm/{_clean(sid, 40)}"
