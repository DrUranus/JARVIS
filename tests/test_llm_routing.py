"""Routing policy (llm-routing-policy): pure function, table tests, config and audit. No network."""
import pytest

from jarvis.config import ConfigError, RoutingSettings, Settings, load_settings
from jarvis.bootstrap import routing_audit
from jarvis.llm.routing import DataClass, LLMRouter, RouteTarget, TaskClass, route
from jarvis.permissions.audit import AuditEventType, AuditLogger, MemoryAuditSink

TASKS = list(TaskClass)
DATA = list(DataClass)


def cfg(**kw):
    base = dict(enabled=True, local_provider="loc", cloud_provider="cld", cloud_tasks=("chat", "plan", "code", "research", "vision"))
    base.update(kw)
    return RoutingSettings(**base)


# ---- defaults -------------------------------------------------------------------------------------------------------------
def test_default_is_single_provider_unchanged():
    assert Settings().llm_routing == RoutingSettings() and RoutingSettings().enabled is False
    for t in TASKS:
        for d in DATA:
            dec = route(t, d, RoutingSettings(), default_provider="mock")
            assert dec.allowed and dec.provider == "mock" and dec.target is RouteTarget.SINGLE and dec.reason == "routing_disabled"


# ---- table: cloud never for secret/never; personal needs approval ----------------------------------------------------------
@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("data", [DataClass.SECRET, DataClass.NEVER])
def test_sensitive_data_never_to_cloud(task, data):
    for approved in (False, True):
        dec = route(task, data, cfg(cloud_provider="cld", local_provider=""), default_provider="x", approved=approved)
        assert dec.target is not RouteTarget.CLOUD and not (dec.allowed and dec.provider == "cld")
        assert not dec.allowed and dec.reason in ("data_class_never_cloud", "no_local_provider")
    dec = route(task, data, cfg(), default_provider="x", approved=True)
    assert dec.provider != "cld"
    if dec.allowed:
        assert dec.target is RouteTarget.LOCAL and dec.provider == "loc"


@pytest.mark.parametrize("task,data,approved,expect", [
    ("chat", "public", False, "cld"),
    ("plan", "public", False, "cld"),
    ("code", "public", False, "cld"),
    ("research", "public", False, "cld"),
    ("chat", "personal", False, "loc"),     # personal without approval -> local, not cloud
    ("code", "personal", False, "loc"),
    ("chat", "personal", True, "cld"),
    ("research", "personal", True, "cld"),
    ("vision", "public", False, "loc"),     # vision: cloud only with explicit approval
    ("vision", "public", True, "cld"),
    ("vision", "personal", True, "loc"),
    ("speech", "public", True, "loc"),      # speech is never cloud via this policy
    ("speech", "personal", True, "loc"),
])
def test_matrix(task, data, approved, expect):
    dec = route(TaskClass(task), DataClass(data), cfg(), default_provider="x", approved=approved)
    assert dec.allowed and dec.provider == expect
    assert dec.target is (RouteTarget.CLOUD if expect == "cld" else RouteTarget.LOCAL)


def test_unknown_classes_are_rejected_fail_closed():
    for t, d in (("bogus", "public"), ("chat", "bogus"), (None, "public"), ("chat", None)):
        dec = route(t, d, cfg(), default_provider="x")
        assert not dec.allowed and dec.reason == "unknown_class"


# ---- no silent fallback ---------------------------------------------------------------------------------------------------
def test_no_cloud_fallback_without_local_provider():
    dec = route(TaskClass.CHAT, DataClass.PERSONAL, cfg(local_provider=""), default_provider="x", approved=False)
    assert not dec.allowed and dec.reason == "no_local_provider" and dec.provider == ""


def test_cloud_not_configured_means_rejection_not_bypass():
    dec = route(TaskClass.CHAT, DataClass.PUBLIC, cfg(cloud_provider=""), default_provider="x")
    assert dec.allowed and dec.provider == "loc"      # public falls to local only because local is configured (visible in reason)
    assert dec.reason == "cloud_not_configured"
    dec = route(TaskClass.CHAT, DataClass.PUBLIC, cfg(cloud_provider="", local_provider=""), default_provider="x")
    assert not dec.allowed


def test_task_not_enabled_for_cloud_goes_local_or_rejected():
    c = cfg(cloud_tasks=("chat",))
    assert route(TaskClass.PLAN, DataClass.PUBLIC, c, default_provider="x").provider == "loc"
    assert not route(TaskClass.PLAN, DataClass.PUBLIC, cfg(cloud_tasks=("chat",), local_provider=""), default_provider="x").allowed
    assert route(TaskClass.CHAT, DataClass.PUBLIC, RoutingSettings(enabled=True, local_provider="loc", cloud_provider="cld"), default_provider="x").provider == "loc"  # empty cloud_tasks = no cloud


def test_pure_function_has_no_side_effects_and_is_deterministic():
    c = cfg()
    a = route(TaskClass.CHAT, DataClass.PUBLIC, c, default_provider="x")
    assert a == route(TaskClass.CHAT, DataClass.PUBLIC, c, default_provider="x")


# ---- config ---------------------------------------------------------------------------------------------------------------
def test_unknown_config_keys_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[llm_routing]\nenabled = true\nbogus = 1\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown config key"):
        load_settings(p, env={})


def test_invalid_values_rejected(tmp_path):
    for body in ('cloud_tasks = ["nope"]', 'enabled = true\nlocal_provider = "a"\ncloud_provider = "a"', 'enabled = true'):
        p = tmp_path / "c.toml"
        p.write_text("[llm_routing]\n" + body + "\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_settings(p, env={})


def test_valid_config_loads(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[llm_routing]\nenabled = true\nlocal_provider = "openai_compatible"\ncloud_tasks = ["chat"]\n', encoding="utf-8")
    s = load_settings(p, env={})
    assert s.llm_routing.enabled and s.llm_routing.cloud_tasks == ("chat",)


def test_shipped_config_unchanged_default():
    assert load_settings("config/jarvis.toml", env={}).llm_routing.enabled is False


# ---- audit ----------------------------------------------------------------------------------------------------------------
class FailingSink(MemoryAuditSink):
    def record(self, event):
        raise OSError("disk")


def make_router(c=None, sink=None):
    sink = sink or MemoryAuditSink()
    return LLMRouter(c or cfg(), default_provider="x", audit=routing_audit(AuditLogger([sink]))), sink


def test_every_decision_is_audited_without_content():
    r, sink = make_router()
    for t, d, a in (("chat", "public", False), ("chat", "secret", False), ("vision", "personal", True), ("bogus", "x", False)):
        r.decide(t, d, approved=a, size=42)
    events = sink.tail(10)
    assert len(events) == 4 and all(e["type"] == "llm_route" for e in events)
    assert {e["status"] for e in events} == {"allowed", "denied"}
    assert events[0]["extra"]["task"] == "chat" and events[0]["extra"]["target"] == "cloud" and events[0]["extra"]["size"] == "42"
    assert AuditEventType.LLM_ROUTE.value == "llm_route"


def test_disabled_routing_is_also_audited():
    r, sink = make_router(RoutingSettings())
    assert r.decide("chat", "public").provider == "x"
    assert len(sink.tail(5)) == 1


def test_audit_failure_denies_cloud_but_allows_local():
    r, _ = make_router(sink=FailingSink())
    assert not r.decide("chat", "public").allowed          # would be cloud
    d = r.decide("chat", "personal")                        # local
    assert d.allowed and d.provider == "loc"


def test_router_no_fallback_without_config():
    r, sink = make_router(cfg(local_provider=""))
    d = r.decide("chat", "personal")
    assert not d.allowed and sink.tail(1)[0]["status"] == "denied"


def test_routing_module_is_wired_only_in_bootstrap_and_has_no_provider_or_network_code():
    import pathlib
    root = pathlib.Path("src/jarvis")
    users = sorted(str(p.relative_to(root)) for p in root.rglob("*.py") if "jarvis.llm.routing" in p.read_text(encoding="utf-8") and p.name != "routing.py")
    assert users == ["bootstrap.py"]
    src = (root / "llm" / "routing.py").read_text(encoding="utf-8")
    assert not any(w in src for w in ("socket", "urllib", "requests", "os.environ", "open(", "jarvis.permissions"))
