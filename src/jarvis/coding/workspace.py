"""Workspace handling: confining every path to one directory, and recognising what kind of project it is.

All file system facts come from the provider (so a fake provider exercises exactly the same rules). The confinement is
checked on the REAL path (symlinks resolved), component-wise (so '/ws-evil' is not inside '/ws'), and - on Windows -
case-insensitively. On top of that the permission engine's PathGuard checks the same resolved path.
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass

from jarvis.coding.backend import CodingProvider
from jarvis.coding.errors import CodingError, CodingErrorCode as EC
from jarvis.coding.models import ProjectInfo
from jarvis.coding.policy import PathInfo, classify, split_relative


def norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def within(path: str, root: str) -> bool:
    """Component-wise containment of two real absolute paths (equal counts as within)."""
    p, r = norm(path), norm(root)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # different drives, relative/absolute mix
        return False


def same_path(a: str, b: str) -> bool:
    return norm(a) == norm(b)


@dataclass(frozen=True)
class ResolvedPath:
    rel: str            # '/'-separated, relative to the workspace root
    abs: str            # real absolute path (symlinks resolved)
    parts: tuple[str, ...]
    info: PathInfo

    @property
    def name(self) -> str:
        return self.parts[-1]


def resolve_in_workspace(provider: CodingProvider, root: str, rel: object) -> ResolvedPath:
    """Turn a user/LLM supplied relative path into a real path inside `root`, or raise PATH_DENIED."""
    parts = split_relative(rel)
    candidate = os.path.join(root, *parts)
    real = provider.realpath(candidate)
    if not within(real, root):
        raise CodingError(EC.PATH_DENIED, "that path leads outside the workspace")
    # the part below the root must also be what we asked for (a symlink to a sibling inside the workspace is fine, but
    # a protected name must not be reachable through an innocent-looking link)
    real_rel = os.path.relpath(real, root).replace("\\", "/")
    real_parts = tuple(p for p in real_rel.split("/") if p and p != ".")
    info = classify(list(parts))
    if real_parts:
        deep = classify(list(real_parts))
        info = PathInfo(secret=info.secret or deep.secret, protected=info.protected or deep.protected, deps=info.deps or deep.deps,
                        blocked_extension=info.blocked_extension or deep.blocked_extension)
    return ResolvedPath("/".join(parts), real, tuple(parts), info)


def resolve_directory(provider: CodingProvider, root: str, rel: object | None) -> ResolvedPath | None:
    """Like resolve_in_workspace, but None / '.' means the root itself."""
    if rel in (None, "", ".", "./"):
        return None
    return resolve_in_workspace(provider, root, rel)


# ---- project analysis ---------------------------------------------------------------------------------------------------------
IMPORTANT = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pytest.ini", "tox.ini", "Pipfile", "package.json",
             "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "tsconfig.json", "jest.config.js", "jest.config.ts", "vitest.config.ts",
             "README.md", "README.rst", "Makefile", ".gitignore", "conftest.py")
PY_FRAMEWORKS = ("django", "flask", "fastapi", "starlette", "pyramid", "tornado", "aiohttp", "sanic", "streamlit", "pydantic")
JS_FRAMEWORKS = ("next", "react", "vue", "svelte", "@angular/core", "express", "nestjs", "@nestjs/core", "koa", "fastify", "nuxt")
JS_TEST = ("jest", "vitest", "mocha", "jasmine", "ava", "playwright", "cypress")
MAX_CONFIG = 200_000


def _text(provider: CodingProvider, path: str) -> str:
    try:
        return provider.read_file(path, MAX_CONFIG).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - analysis is best effort
        return ""


def is_jarvis_repo(provider: CodingProvider, root: str) -> bool:
    """The JARVIS repository itself: gets the strict rules that later self-improvement will build on."""
    pyproject = _text(provider, os.path.join(root, "pyproject.toml"))
    named = False
    try:
        named = tomllib.loads(pyproject).get("project", {}).get("name") == "jarvis-ai"
    except tomllib.TOMLDecodeError:
        pass
    pkg = provider.stat(os.path.join(root, "src", "jarvis", "permissions"))
    return bool(named or (pkg and pkg.is_dir and provider.stat(os.path.join(root, "src", "jarvis", "__init__.py"))))


def analyze_project(provider: CodingProvider, root: str) -> ProjectInfo:
    names = {e.name: e for e in provider.scandir(root)}
    lower = {n.casefold(): n for n in names}
    important = tuple(n for n in IMPORTANT if n.casefold() in lower)
    languages: list[str] = []
    framework, test_fw = "", ""

    py = any(k in lower for k in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pipfile", "pytest.ini", "tox.ini"))
    if py:
        languages.append("Python")
        deps = (_text(provider, os.path.join(root, "pyproject.toml")) + "\n" + _text(provider, os.path.join(root, "requirements.txt"))
                + "\n" + _text(provider, os.path.join(root, "setup.cfg"))).casefold()
        framework = next((f for f in PY_FRAMEWORKS if f in deps), "")
        if "pytest.ini" in lower or "[tool.pytest" in deps or "pytest" in deps or "conftest.py" in lower:
            test_fw = "pytest"
        elif "tests" in lower or "test" in lower:
            test_fw = "unittest"

    js_test = ""
    if "package.json" in lower:
        try:
            pkg = json.loads(_text(provider, os.path.join(root, names[lower["package.json"]].name)) or "{}")
        except ValueError:
            pkg = {}
        all_deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})} if isinstance(pkg, dict) else {}
        ts = "tsconfig.json" in lower or "typescript" in all_deps
        languages.append("TypeScript" if ts else "JavaScript")
        js_framework = next((f for f in JS_FRAMEWORKS if f in all_deps), "")
        framework = framework or js_framework or "Node.js"
        js_test = next((t for t in JS_TEST if t in all_deps), "")
        scripts = pkg.get("scripts") if isinstance(pkg, dict) else None
        if not js_test and isinstance(scripts, dict) and scripts.get("test"):
            js_test = "npm test"
    elif "tsconfig.json" in lower:
        languages.append("TypeScript")
    test_fw = test_fw or js_test

    language = languages[0] if languages else "unknown"
    return ProjectInfo(root, language, framework, test_fw, important, tuple(languages), is_jarvis_repo(provider, root))
