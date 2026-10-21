"""Interfaces, URL policy, resources, configuration, factory/bootstrap and CLI of the browser agent."""
import importlib.util
import inspect

import pytest

from browser_util import HOME, ONCE, make_rig
from jarvis.bootstrap import build_core
from jarvis.browser import (BrowserController, BrowserPage, BrowserProvider, BrowserSession, ElementInfo, LaunchOptions, UrlPolicy,
                            safe_url)
from jarvis.browser import resources as res
from jarvis.browser.factory import BrowserSubsystem, build_browser, register_provider
from jarvis.browser.providers.fake import FakeBrowserProvider, FakeSession
from jarvis.browser.urls import is_private_host, url_key
from jarvis.config import BrowserSettings, load_settings
from jarvis.errors import ConfigError
from jarvis.interface.cli import repl, run_command
from jarvis.permissions import PermissionLevel as L
from test_computer_integration import env_for, run_repl


# ---- provider interfaces ----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("abc", [BrowserProvider, BrowserSession, BrowserPage])
def test_interfaces_are_abstract(abc):
    with pytest.raises(TypeError):
        abc()


def test_fake_provider_implements_every_abstract_method():
    for impl, abc in ((FakeBrowserProvider, BrowserProvider), (FakeSession, BrowserSession),
                      (inspect.getmodule(FakeSession).FakePage, BrowserPage)):
        assert not getattr(impl, "__abstractmethods__", frozenset()), impl
        assert {n for n, f in inspect.getmembers(abc, inspect.isfunction) if not n.startswith("_")} <= set(dir(impl))


def test_playwright_provider_implements_the_same_interfaces():
    pytest.importorskip("playwright")
    from jarvis.browser.providers import playwright_provider as pp
    for impl in (pp.PlaywrightProvider, pp.PlaywrightSession, pp.PlaywrightPage):
        assert not impl.__abstractmethods__


def test_fake_provider_lifecycle_and_guard_are_part_of_the_contract():
    p = FakeBrowserProvider()
    seen = []
    s = p.start(LaunchOptions(), lambda url, nav: seen.append((url, nav)) or True)
    assert s.is_alive()
    page = s.new_page()
    page.goto("https://example.com/", 1)
    assert seen == [("https://example.com/", True)] and page.info().url == "https://example.com/"
    s.close()
    assert not s.is_alive() and page.is_closed()


# ---- URL policy -------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("host,private", [("localhost", True), ("127.0.0.1", True), ("10.1.2.3", True), ("192.168.0.9", True), ("172.16.0.1", True),
                                          ("169.254.1.1", True), ("::1", True), ("fe80::1", True), ("intranet", True), ("nas.local", True),
                                          ("db.internal", True), ("8.8.8.8", False), ("example.com", False), ("2001:4860:4860::8888", False)])
def test_private_host_detection(host, private):
    assert is_private_host(host) is private


def test_url_policy_levels():
    p = UrlPolicy(trusted_hosts=("docs.python.org", "*.wikipedia.org"), blocked_hosts=("bad.com",), private_hosts_allowed=("127.0.0.1",))
    assert p.classify("https://docs.python.org/3/").level is L.GREEN
    assert p.classify("https://de.wikipedia.org/wiki/X").level is L.GREEN
    assert p.classify("https://wikipedia.org/").level is L.YELLOW
    assert p.classify("https://example.com/").level is L.YELLOW
    assert p.classify("http://127.0.0.1:8000/x").level is L.YELLOW
    assert p.classify("http://127.0.0.2/").level is L.RED
    assert p.classify("https://sub.bad.com").level is L.YELLOW  # exact entry: subdomains need '*.bad.com'
    assert p.classify("https://bad.com/").level is L.RED
    assert p.classify("about:blank").level is L.GREEN
    for bad in (None, 5, "", "   ", "http://", "https:///x", "http://exa mple.com", "http://a.com/\x00", "x" * 3000, "//example.com"):
        assert p.classify(bad).level is L.RED, bad


def test_idn_and_odd_hosts_are_normalised_not_trusted_blindly():
    p = UrlPolicy(trusted_hosts=("example.com",))
    assert p.classify("https://EXAMPLE.com./").level is L.GREEN
    assert p.classify("https://example.com.evil.net/").level is L.YELLOW
    assert p.classify("https://example.com@evil.net/").level is L.RED  # credentials syntax, never a trusted-host trick
    assert p.classify("https://exämple.com/").host == "xn--exmple-cua.com"


def test_safe_url_hides_credentials_query_values_and_fragments():
    assert safe_url("https://u:p@example.com:8443/a/b?token=SECRET&x=1#frag") == "https://example.com:8443/a/b?token=…&x=…"
    assert safe_url("about:blank") == "about:blank" and safe_url("file:///etc/passwd").startswith("(")
    assert len(safe_url("https://example.com/" + "a" * 500)) <= 160
    assert url_key("https://Example.com:443/p?q=1#f") == "https://example.com:443/p"


# ---- resources ------------------------------------------------------------------------------------------------------------------------------
def test_resource_uris_are_fixed_and_cleaned():
    assert res.session_resource("s1-ab") == "browser://session/s1-ab"
    assert res.page_resource("s1", "p2", "example.com") == "browser://page/s1/p2@example.com"
    assert res.element_resource("s1", "p2", "e7", "example.com") == "browser://element/s1/p2/e7@example.com"
    evil = res.element_resource("s1/../x", "p 2", "e7\nRisiko: GREEN", "ex ample.com/?a")
    assert "\n" not in evil and " " not in evil and "//" not in evil.split("://", 1)[1] and "?" not in evil


def test_resources_seen_by_the_engine_are_those_uris(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6)
    r.open()
    ids = r.find()
    out = r.run(action="click", element=ids["Go"])
    sid, = {r.controller.overview()["session"]}
    assert out.permission.resolved_resource == f"browser://element/{sid}/p1/{ids['Go']}@example.com"
    assert r.run(action="goto", url="https://other.org/x").permission.resolved_resource == "other.org"  # engine host resource
    assert r.run(action="info").permission.resolved_resource.startswith("browser://page/")


def test_element_fingerprint_depends_on_identity_not_on_state():
    a = ElementInfo("1", "input", "textbox", "Search", "text", dom_name="q")
    assert a.fingerprint() == ElementInfo("9", "input", "textbox", "Search", "text", dom_name="q", has_value=True).fingerprint()
    assert a.fingerprint() != ElementInfo("1", "input", "textbox", "Search", "text", dom_name="x").fingerprint()
    assert a.fingerprint() != ElementInfo("1", "button", "button", "Search", "text", dom_name="q").fingerprint()
    link = ElementInfo("1", "a", "link", "More", href="https://e.com/a?x=1")
    assert link.fingerprint() == ElementInfo("1", "a", "link", "More", href="https://e.com/a?x=2#f").fingerprint()
    assert link.fingerprint() != ElementInfo("1", "a", "link", "More", href="https://e.com/b").fingerprint()


# ---- configuration -------------------------------------------------------------------------------------------------------------------------------
def test_defaults_are_off_and_safe():
    s = load_settings(env={}).browser
    assert s == BrowserSettings() and s.enabled is False and s.trusted_hosts == () and s.private_hosts_allowed == ()
    assert s.confirm_fill_each_time and s.confirm_file_transfer_each_time and s.max_actions_per_session > 0


def test_file_and_env_configuration(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[browser]\nenabled = true\nprovider = "fake"\nbrowser = "msedge"\ntrusted_hosts = ["docs.python.org"]\nmax_pages = 3\n',
                 encoding="utf-8")
    import os
    b = load_settings(f, env={"JARVIS_BROWSER_HEADLESS": "true", "JARVIS_BROWSER_BLOCKED_HOSTS": os.pathsep.join(["a.com", "b.com"])}).browser
    assert (b.enabled, b.provider, b.browser, b.max_pages, b.headless) == (True, "fake", "msedge", 3, True)
    assert b.trusted_hosts == ("docs.python.org",) and b.blocked_hosts == ("a.com", "b.com")


@pytest.mark.parametrize("toml", ['[browser]\nprovider = "selenium"\n', '[browser]\nbrowser = "firefox"\n', '[browser]\nmax_pages = 0\n',
                                  '[browser]\nnavigation_timeout = 0\n', '[browser]\ntrusted_hosts = ["*"]\n', '[browser]\ntrusted_hosts = ["*.*"]\n',
                                  '[browser]\ntrusted_hosts = ["a*.com"]\n', '[browser]\nprivate_hosts_allowed = ["*.local"]\n',
                                  '[browser]\nblocked_hosts = [""]\n', '[browser]\nbogus = 1\n', '[browser]\nallow_file_urls = true\n',
                                  '[browser]\nskip_permissions = true\n', '[browser]\nallow_red = true\n', '[browser]\nmax_elements = 0\n'])
def test_invalid_browser_config_and_no_bypass_switches(tmp_path, toml):
    f = tmp_path / "c.toml"
    f.write_text(toml, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(f, env={})


# ---- factory / bootstrap ----------------------------------------------------------------------------------------------------------------------
def test_disabled_by_default_registers_nothing(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    sub = core.subsystems["browser"]
    assert sub.status == "disabled" and "browser" not in core.tools and not sub.available and sub.halt() is False
    assert "deaktiviert" in run_command(core, "/browser") and "JARVIS_BROWSER_ENABLED" in run_command(core, "/browser")


def test_enabled_fake_registers_one_protected_tool_and_baseline_rules(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake")))
    sub = core.subsystems["browser"]
    assert sub.status == "enabled" and sub.tool_names == ["browser"] and "browser" in core.tools
    rules = {r.id for r in core.permissions.policy.rules}
    assert {"browser-baseline-fill-confirm", "browser-baseline-download-confirm", "browser-baseline-upload-confirm"} <= rules
    assert core.tools.describe_all() and next(t for t in core.tools.describe_all() if t["name"] == "browser")["permission"] == "green"


def test_baseline_rules_can_be_switched_off_only_by_config(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake",
                                               JARVIS_BROWSER_CONFIRM_FILL_EACH_TIME="false")))
    rules = {r.id for r in core.permissions.policy.rules}
    assert "browser-baseline-fill-confirm" not in rules and "browser-baseline-upload-confirm" in rules


def test_missing_library_leaves_jarvis_fully_usable(tmp_path, monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: None if name == "playwright" else real(name, *a, **k))
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="playwright")))
    sub = core.subsystems["browser"]
    assert sub.status == "unavailable" and "playwright" in sub.reason and "browser" not in core.tools
    assert core.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit." and core.tools.execute("echo", text="ok").success
    out = run_command(core, "/browser")
    assert "nicht verfügbar" in out and "playwright" in out


def test_unknown_or_failing_providers_do_not_break_startup(tmp_path):
    def boom(settings):
        raise RuntimeError("provider exploded with secret=abc12345")
    register_provider("exploding", boom)
    from jarvis.permissions import PermissionEngine
    from jarvis.tools import ToolRegistry
    settings = load_settings(env=env_for(tmp_path)).__class__()
    from dataclasses import replace
    for provider in ("exploding", "nope"):
        s = replace(settings, browser=replace(settings.browser, enabled=True, provider=provider))
        engine = PermissionEngine()
        sub = build_browser(s, ToolRegistry(engine), engine)
        assert sub.status == "unavailable" and "abc12345" not in sub.reason


def test_a_failure_while_installing_rolls_the_policy_back(tmp_path, monkeypatch):
    from dataclasses import replace
    from jarvis.permissions import PermissionEngine, Policy
    from jarvis.tools import ToolRegistry
    from jarvis.errors import ToolError
    import jarvis.browser.factory as fac

    def broken(registry, controller):
        raise ToolError("cannot register")
    monkeypatch.setattr(fac, "register_browser_tools", broken)
    s = load_settings(env={})
    s = replace(s, browser=replace(s.browser, enabled=True, provider="fake"))
    engine = PermissionEngine(policy=Policy())
    before = engine.policy
    sub = build_browser(s, ToolRegistry(engine), engine)
    assert sub.status == "unavailable" and engine.policy.rules == before.rules  # no half-installed safety rules


def test_real_provider_construction_needs_no_browser_binary(tmp_path):
    pytest.importorskip("playwright")
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_BROWSER_ENABLED="true")))
    assert core.subsystems["browser"].status == "enabled"  # the browser itself is only launched by an approved `start`


# ---- CLI ------------------------------------------------------------------------------------------------------------------------------------------
def cli_core(tmp_path, **extra):
    return build_core(load_settings(env=env_for(tmp_path, JARVIS_BROWSER_ENABLED="true", JARVIS_BROWSER_PROVIDER="fake", **extra)))


def test_cli_status_halt_and_resume(tmp_path):
    core = cli_core(tmp_path)
    status = run_command(core, "/browser")
    assert "Browser-Agent: aktiv" in status and "Provider: fake" in status and "/run browser action=" in status
    assert "angehalten" in run_command(core, "/browser halt") and "ANGEHALTEN" in run_command(core, "/browser")
    out = run_repl(core, ["/run browser action=status", "/browser resume", "/run browser action=status", "/exit"])
    assert "[failsafe]" in out and "Browser-Agent fortgesetzt." in out and "OK: {'running': False" in out


def test_cli_uses_the_ordinary_run_and_permission_path(tmp_path):
    core = cli_core(tmp_path)
    out = run_repl(core, ["/browser start", "n", "/browser start", "j", "/run browser action=pages", "/run browser action=goto url=file:///etc/passwd",
                          "/browser", "/exit"])
    assert out.count("Erlauben?") == 1 + 1  # declined once, accepted once; GREEN and RED never ask
    assert "the user declined" in out and "OK: {'session'" in out and "RED actions are never permitted" in out
    assert "Sitzung: s1-" in out


def test_cli_help_lists_the_browser_command(tmp_path):
    assert "/browser" in run_command(cli_core(tmp_path), "/help")
