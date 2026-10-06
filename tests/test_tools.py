import pytest

from jarvis.errors import ToolError
from jarvis.permissions import PermissionLevel, is_allowed
from jarvis.tools import Tool, ToolParameter, ToolRegistry, ToolResult


class Boom(Tool):
    name = "boom"
    description = "crashes"

    def run(self, **kw):
        raise RuntimeError("kaboom")


class Spend(Tool):
    name = "spend"
    description = "spends money"
    permission = PermissionLevel.YELLOW

    def run(self, **kw):
        return ToolResult.ok("spent")


def test_register_and_execute(registry):
    assert registry.execute("echo", text="hi").output == "hi"
    assert "current_time" in registry and registry.names() == ["current_time", "echo"]


def test_duplicate_and_unknown(registry):
    from jarvis.tools.builtin import EchoTool
    with pytest.raises(ToolError):
        registry.register(EchoTool())
    registry.register(EchoTool(), replace=True)
    with pytest.raises(ToolError):
        registry.get("zzz")
    assert not registry.execute("zzz").success


def test_missing_params(registry):
    r = registry.execute("echo")
    assert not r.success and "text" in r.error


def test_crash_is_isolated(registry):
    registry.register(Boom())
    r = registry.execute("boom")
    assert not r.success and "kaboom" in r.error


def test_permissions(registry):
    registry.register(Spend())
    assert not registry.execute("spend").success
    assert registry.execute("spend", confirmed=True).output == "spent"
    assert not is_allowed(PermissionLevel.RED, confirmed=True)


def test_describe_and_unregister(registry):
    d = registry.describe_all()
    assert d[0]["name"] == "current_time"
    registry.unregister("echo")
    assert "echo" not in registry
    with pytest.raises(ToolError):
        registry.unregister("echo")
    assert ToolParameter("a", "b").required
