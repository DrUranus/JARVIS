import json

import pytest

from jarvis.core import JarvisCore
from jarvis.llm.mock import MockProvider
from jarvis.tools.builtin import register_builtin_tools
from jarvis.tools.registry import ToolRegistry

PLAN_JSON = json.dumps({"steps": [
    {"description": "Anforderungen analysieren", "tools": [], "agents": ["research"]},
    {"description": "Code schreiben", "tools": ["echo", "nonexistent"], "agents": ["coding"]},
    {"description": "Test ausführen", "tools": [], "agents": ["testing"]},
]})


def plan_responder(request):
    """Returns a JSON plan for planner prompts, plain text otherwise."""
    if "planning module" in request.messages[0].content:
        return PLAN_JSON
    return "ok"


@pytest.fixture
def provider():
    return MockProvider(responder=plan_responder)


@pytest.fixture
def registry():
    return register_builtin_tools(ToolRegistry())


@pytest.fixture
def core(provider, registry):
    return JarvisCore(provider=provider, tools=registry)
