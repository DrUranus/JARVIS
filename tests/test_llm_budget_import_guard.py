"""E6: semantic import guard. The older structure tests look at spellings (`module.endswith("budget")`, the text "from jarvis.llm import cost_budget"); an import can be spelled in many
ways. This file resolves every import to the fully qualified module it really pulls in and checks THAT, so neither the session budget of the permission engine nor the LLM cost model
can be reached by a different spelling (`from pkg import mod as alias`, `import a.b.c`, parenthesised lists, relative imports). It adds checks; it relaxes none."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
SESSION_BUDGET = "jarvis.permissions.budget"                 # the permission engine's session budget (tool calls / run time)
COST_MODEL = "jarvis.llm.cost_budget"                        # E6: the LLM cost / token model
SESSION_BUDGET_PACKAGES = ("tools", "agents", "goals", "self_repair", "self_improvement", "computer", "browser", "coding", "research", "business", "finance", "llm", "planning")
COST_MODEL_IMPORTERS = {"llm/cost_budget.py", "llm/budgeted.py", "config.py", "bootstrap.py"}
BUDGETED_PROVIDER_IMPORTERS = {"llm/budgeted.py", "bootstrap.py"}


def _package_of(path: Path) -> str:
    rel = path.relative_to(SRC).with_suffix("")
    parts = ["jarvis", *rel.parts]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts[:-1])


def resolved_imports(source: str, package: str = "jarvis.x") -> set[str]:
    """Every module name an import statement may really load: `import a.b` -> a.b; `from m import n` -> m AND m.n (n may be a submodule); relative imports are made absolute."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.split(".")
                parent = parent[: len(parent) - (node.level - 1)]
                base = ".".join(parent + ([base] if base else []))
            out.add(base)
            out.update(f"{base}.{a.name}" for a in node.names if a.name != "*")
    return out


def _hits(target: str, imports: set[str]) -> bool:
    return any(m == target or m.startswith(target + ".") for m in imports)


# ---- the checker itself (it must see through every spelling) ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("snippet", [
    "from jarvis.permissions.budget import SessionBudget",
    "from jarvis.permissions import budget",
    "from jarvis.permissions import budget as b",
    "from jarvis.permissions import (engine,\n    budget as b)",
    "import jarvis.permissions.budget",
    "import jarvis.permissions.budget as pb",
    "from jarvis import permissions\nfrom jarvis.permissions.budget import *",
])
def test_the_checker_finds_every_spelling_of_the_session_budget(snippet):
    assert _hits(SESSION_BUDGET, resolved_imports(snippet))


@pytest.mark.parametrize("snippet", [
    "from jarvis.llm import cost_budget as cb",
    "from jarvis.llm.cost_budget import CostBudget",
    "import jarvis.llm.cost_budget as c",
    "from jarvis.llm import (base,\n  cost_budget)",
])
def test_the_checker_finds_every_spelling_of_the_cost_model(snippet):
    assert _hits(COST_MODEL, resolved_imports(snippet))


def test_the_checker_resolves_relative_imports():
    assert _hits(COST_MODEL, resolved_imports("from . import cost_budget", package="jarvis.llm"))
    assert _hits(COST_MODEL, resolved_imports("from .cost_budget import CostBudget", package="jarvis.llm"))
    assert _hits(SESSION_BUDGET, resolved_imports("from ..permissions import budget", package="jarvis.llm"))
    assert not _hits(SESSION_BUDGET, resolved_imports("from jarvis.llm import cost_budget as cb"))      # two different things: the cost model is NOT the session budget


# ---- the real tree -----------------------------------------------------------------------------------------------------------------------------
def test_no_tool_agent_goal_or_llm_module_reaches_the_session_budget_in_any_spelling():
    for pkg in SESSION_BUDGET_PACKAGES:
        for f in (SRC / pkg).rglob("*.py"):
            imports = resolved_imports(f.read_text(encoding="utf-8"), _package_of(f))
            assert not _hits(SESSION_BUDGET, imports), f"{pkg}/{f.name} imports the session budget"


def test_the_wrapper_never_touches_the_permission_engine_or_the_emergency_module_by_import():
    imports = resolved_imports((SRC / "llm" / "budgeted.py").read_text(encoding="utf-8"), "jarvis.llm")
    assert not any(m == "jarvis.permissions" or m.startswith("jarvis.permissions.") for m in imports), sorted(imports)
    assert not _hits("jarvis.tools", imports) and not _hits("jarvis.agents", imports)


def test_only_the_approved_modules_import_the_cost_model_in_any_spelling():
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).as_posix()
        if rel in COST_MODEL_IMPORTERS:
            continue
        assert not _hits(COST_MODEL, resolved_imports(f.read_text(encoding="utf-8"), _package_of(f))), rel


def test_only_the_composition_root_imports_the_enforcing_wrapper():
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).as_posix()
        if rel in BUDGETED_PROVIDER_IMPORTERS:
            continue
        assert not _hits("jarvis.llm.budgeted", resolved_imports(f.read_text(encoding="utf-8"), _package_of(f))), rel


def test_the_wrapper_reads_the_emergency_stop_only_through_an_injected_object():
    tree = ast.parse((SRC / "llm" / "budgeted.py").read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "engage" not in attrs and "reset" not in attrs and "trigger" not in attrs and "run_stoppers" not in attrs      # the latch is only read (`engaged`), never changed
    assert "engaged" in {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} or "engaged" in (SRC / "llm" / "budgeted.py").read_text(encoding="utf-8")


def test_the_older_spelling_based_check_has_a_gap_that_this_file_closes():
    """Documents the finding: `tests/test_session_budget.py` flags `ImportFrom` nodes whose MODULE ends with "budget". `from jarvis.permissions import budget` has the module
    `jarvis.permissions`, so that older predicate does not see it - the resolved check above does."""
    node = ast.parse("from jarvis.permissions import budget").body[0]
    old_predicate = isinstance(node, ast.ImportFrom) and (node.module or "").endswith("budget")
    assert old_predicate is False and _hits(SESSION_BUDGET, resolved_imports("from jarvis.permissions import budget"))
