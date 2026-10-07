"""[computer] configuration, factory, bootstrap, Core and CLI: JARVIS starts and stays usable whatever the backend does."""
import dataclasses
import sys
from pathlib import Path

import pytest

from computer_util import NO, ONCE, make_executable, make_rig
from jarvis.bootstrap import build_core
from jarvis.computer import ComputerBackend, ComputerError, ComputerUnavailableError, ErrorCode
from jarvis.computer import factory as cf
from jarvis.computer.factory import ComputerSubsystem, build_computer, create_backend, register_backend
from jarvis.computer.policy import BASELINE_PREFIX, baseline_rules
from jarvis.computer.providers import pyautogui_input as pgi
from jarvis.config import ComputerSettings, Settings, load_settings
from jarvis.errors import ConfigError, PolicyError
from jarvis.interface.cli import repl, run_command
from jarvis.permissions import ScriptedConfirmation, Policy
from jarvis.core import JarvisCore
from jarvis.llm.mock import MockProvider
from jarvis.tools import ToolRegistry
from secutil import make_engine, types

REPO = Path(__file__).resolve().parent.parent


def env_for(tmp_path, **extra):
    (tmp_path / "ws").mkdir(exist_ok=True)
    base = {"JARVIS_WORKSPACE": str(tmp_path / "ws"), "JARVIS_LOG_DIR": str(tmp_path / "logs"),
            "JARVIS_MEMORY_PATH": str(tmp_path / "m.db")}
    return {**base, **{k: str(v) for k, v in extra.items()}}


# ---- configuration -------------------------------------------------------------------------------------------------------------
def test_defaults_are_safe_and_off():
    c = load_settings(env={}).computer
    assert c == ComputerSettings() and c.enabled is False and c.backend == "auto" and c.allow_unlisted_apps is False
    assert c.confirm_keyboard_each_time and c.confirm_window_close_each_time and c.show_text_preview
    assert (c.default_monitor, c.screenshot_max_items, c.max_text_length, c.max_scroll) == (0, 3, 500, 20)
    assert c.apps == {} and c.blocked_processes == ("explorer.exe",) and c.max_actions_per_minute == 120


def test_repo_config_matches_the_defaults():
    assert load_settings(REPO / "config" / "jarvis.toml", env={}).computer == ComputerSettings()


def test_file_env_and_application_table(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[computer]\nenabled = true\nbackend = "fake"\ndefault_monitor = 1\nmax_text_length = 80\n'
                 'blocked_processes = ["a.exe", "b.exe"]\nblocked_titles = ["secret doc"]\n'
                 '[computer.apps]\nnotepad = "C:\\\\Windows\\\\notepad.exe"\nmy-tool = "/opt/tool"\n')
    c = load_settings(f, env={"JARVIS_COMPUTER_MAX_SCROLL": "5", "JARVIS_COMPUTER_SHOW_TEXT_PREVIEW": "false"}).computer
    assert c.enabled and c.backend == "fake" and c.default_monitor == 1 and c.max_text_length == 80 and c.max_scroll == 5
    assert c.show_text_preview is False and c.blocked_processes == ("a.exe", "b.exe") and c.blocked_titles == ("secret doc",)
    assert c.apps == {"notepad": "C:\\Windows\\notepad.exe", "my-tool": "/opt/tool"}
    assert load_settings(env={"JARVIS_COMPUTER_BLOCKED_PROCESSES": "x.exe" + __import__("os").pathsep + "y.exe"}).computer.blocked_processes == ("x.exe", "y.exe")


@pytest.mark.parametrize("env", [{"JARVIS_COMPUTER_BACKEND": "pyxel"}, {"JARVIS_COMPUTER_DEFAULT_MONITOR": "-1"},
                                 {"JARVIS_COMPUTER_SCREENSHOT_MAX_ITEMS": "0"}, {"JARVIS_COMPUTER_MAX_TEXT_LENGTH": "0"},
                                 {"JARVIS_COMPUTER_MAX_TEXT_LENGTH": "99999"}, {"JARVIS_COMPUTER_MAX_SCROLL": "0"},
                                 {"JARVIS_COMPUTER_TYPE_INTERVAL": "-1"}, {"JARVIS_COMPUTER_MAX_ACTIONS_PER_MINUTE": "-3"},
                                 {"JARVIS_COMPUTER_MAX_SCROLL": "x"},
                                 {"JARVIS_COMPUTER_APPS": "notepad=/x"}])  # tables only via the TOML file
def test_invalid_computer_config(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


@pytest.mark.parametrize("toml", ['[computer.apps]\n"bad alias!" = "/x"\n', '[computer.apps]\nok = ""\n', '[computer.apps]\nok = 5\n',
                                  '[computer]\nblocked_titles = [""]\n', '[computer]\nbogus = 1\n', '[computer]\nallow_everything = true\n',
                                  '[computer]\nskip_permissions = true\n', '[computer]\nhotkey_blocklist = []\n'])
def test_invalid_computer_file_and_no_bypass_switches(tmp_path, toml):
    f = tmp_path / "c.toml"
    f.write_text(toml)
    with pytest.raises(ConfigError):
        load_settings(f, env={})


def test_baseline_rules_follow_the_config():
    ids = lambda **kw: sorted(r.id for r in baseline_rules(ComputerSettings(**kw)))  # noqa: E731
    assert ids() == [BASELINE_PREFIX + "keyboard-confirm", BASELINE_PREFIX + "window-close-confirm"]
    assert ids(confirm_keyboard_each_time=False) == [BASELINE_PREFIX + "window-close-confirm"]
    assert ids(confirm_keyboard_each_time=False, confirm_window_close_each_time=False) == []


# ---- backend factory ------------------------------------------------------------------------------------------------------------------
def test_fake_backend_is_selectable_and_probed():
    b = create_backend(ComputerSettings(backend="fake"))
    assert b.name == "fake" and b.capabilities() == ["screen", "mouse", "keyboard", "windows", "apps"]


def test_unknown_backend_is_unavailable_with_a_reason():
    with pytest.raises(ComputerUnavailableError, match="unknown computer backend"):
        create_backend(_settings("pyxel"))


def test_auto_picks_the_platform_backend(monkeypatch):
    seen = []
    for name in ("windows", "x11"):
        monkeypatch.setitem(cf._BUILDERS, name, lambda s, n=name: (seen.append(n), cf._build_fake(s))[1])
    create_backend(ComputerSettings(backend="auto"), platform="win32")
    create_backend(ComputerSettings(backend="auto"), platform="linux")
    create_backend(ComputerSettings(backend="auto"), platform="darwin")
    assert seen == ["windows", "x11", "x11"]


def test_a_backend_whose_display_probe_fails_is_unavailable(monkeypatch):
    from jarvis.computer.providers.fake import FakeBackend

    def builder(settings):
        fb = FakeBackend()
        fb.fail_next("screen.monitors", ComputerError(ErrorCode.NO_DISPLAY, "cannot open display :0"))
        return fb.bundle()

    monkeypatch.setitem(cf._BUILDERS, "probe-fail", builder)
    with pytest.raises(ComputerUnavailableError) as exc:
        create_backend(_settings("probe-fail"))
    assert exc.value.code is ErrorCode.NO_DISPLAY and "cannot open display" in str(exc.value)

    def raising(settings):
        fb = FakeBackend()
        fb.fail_next("screen.monitors", RuntimeError("segfault-ish"))
        return fb.bundle()

    monkeypatch.setitem(cf._BUILDERS, "probe-crash", raising)
    with pytest.raises(ComputerUnavailableError) as exc:
        create_backend(_settings("probe-crash"))
    assert exc.value.code is ErrorCode.NO_DISPLAY and "segfault-ish" not in str(exc.value)


def _settings(backend):
    """ComputerSettings with an arbitrary (registered) backend name, bypassing the config validation list."""
    return dataclasses.replace(ComputerSettings(), backend=backend)


def test_custom_backends_can_be_registered(monkeypatch):
    monkeypatch.setitem(cf._BUILDERS, "custom", lambda s: ComputerBackend("custom-backend"))
    assert create_backend(_settings("custom")).name == "custom-backend"
    register_backend("another", cf._build_fake)
    assert "another" in cf._BUILDERS
    cf._BUILDERS.pop("another")


def test_real_backend_without_a_display_is_a_clean_unavailable(monkeypatch):
    """The real providers on this machine: no DISPLAY (or no libraries) must give a reason, not a crash or SystemExit."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delitem(sys.modules, "pyautogui", raising=False)
    monkeypatch.setattr(pgi, "_module", None)
    if sys.platform == "win32":
        pytest.skip("no X11 on Windows")
    with pytest.raises(ComputerUnavailableError) as exc:
        create_backend(ComputerSettings(backend="x11"))
    assert exc.value.code in (ErrorCode.NO_DISPLAY, ErrorCode.BACKEND_UNAVAILABLE) and str(exc.value)


# ---- build_computer ------------------------------------------------------------------------------------------------------------------------
def build_env(tmp_path, **cs):
    engine, sink, ws = make_engine(tmp_path, confirmation=ScriptedConfirmation([ONCE] * 5))
    registry = ToolRegistry(engine)
    settings = dataclasses.replace(Settings(), computer=ComputerSettings(**cs))
    return settings, registry, engine, sink


def test_disabled_registers_nothing(tmp_path):
    settings, registry, engine, sink = build_env(tmp_path)
    sub = build_computer(settings, registry, engine)
    assert sub.status == "disabled" and not sub.available and registry.names() == [] and "policy_changed" not in types(sink)
    assert "computer.enabled = false" in sub.reason and sub.halt() is False and sub.resume() is False


def test_enabled_with_the_fake_backend(tmp_path):
    settings, registry, engine, sink = build_env(tmp_path, enabled=True, backend="fake")
    sub = build_computer(settings, registry, engine)
    assert sub.status == "enabled" and sub.available and sub.reason == "backend fake"
    assert sub.tool_names == ["screen", "screen_save", "mouse", "keyboard", "window", "app"] and registry.names() == sorted(sub.tool_names)
    assert {r.id for r in engine.policy.rules} == {BASELINE_PREFIX + "keyboard-confirm", BASELINE_PREFIX + "window-close-confirm"}
    changed = [e for e in sink.events if e.type.value == "policy_changed"][-1]
    assert "computer baseline" in changed.detail and BASELINE_PREFIX + "keyboard-confirm" in changed.extra["added"]
    d = sub.describe()
    assert d["status"] == "enabled" and d["backend"] == "fake" and d["tools"] == sub.tool_names
    sub.halt("test")
    assert sub.describe()["status"] == "halted" and sub.controller.halted == "test"
    sub.resume()
    assert sub.describe()["status"] == "enabled"


def test_user_policy_rules_are_kept_when_the_baseline_is_added(tmp_path):
    settings, registry, engine, _ = build_env(tmp_path, enabled=True, backend="fake")
    engine.update_policy(Policy.from_rules([{"id": "mine", "effect": "deny", "tool": "x"}]))
    build_computer(settings, registry, engine)
    assert "mine" in {r.id for r in engine.policy.rules} and BASELINE_PREFIX + "keyboard-confirm" in {r.id for r in engine.policy.rules}


@pytest.mark.parametrize("make_error", [lambda s: (_ for _ in ()).throw(ComputerUnavailableError("no library", ErrorCode.BACKEND_UNAVAILABLE)),
                                        lambda s: (_ for _ in ()).throw(RuntimeError("driver crash")),
                                        lambda s: (_ for _ in ()).throw(ImportError("x")),
                                        lambda s: (_ for _ in ()).throw(ComputerError(ErrorCode.NO_DISPLAY, "no display"))])
def test_an_unusable_backend_never_stops_startup(tmp_path, monkeypatch, make_error):
    monkeypatch.setitem(cf._BUILDERS, "broken", make_error)
    settings, registry, engine, _ = build_env(tmp_path)
    settings = dataclasses.replace(settings, computer=dataclasses.replace(_settings("broken"), enabled=True))
    sub = build_computer(settings, registry, engine)
    assert sub.status == "unavailable" and not sub.available and sub.reason and registry.names() == []
    assert engine.policy.rules == ()  # no half-installed state


def test_failing_to_install_the_safety_rules_means_no_tools(tmp_path, monkeypatch):
    settings, registry, engine, _ = build_env(tmp_path, enabled=True, backend="fake")
    monkeypatch.setattr(type(engine), "update_policy", lambda self, p, source="api": (_ for _ in ()).throw(PolicyError("duplicate rule ids")))
    sub = build_computer(settings, registry, engine)
    assert sub.status == "unavailable" and "safety rules" in sub.reason and registry.names() == []  # fail closed


def test_a_tool_name_conflict_rolls_everything_back(tmp_path):
    from jarvis.computer.tools import MouseTool
    from jarvis.computer.providers.fake import FakeBackend
    from jarvis.computer import ComputerController
    settings, registry, engine, sink = build_env(tmp_path, enabled=True, backend="fake")
    registry.register(MouseTool(ComputerController(FakeBackend().bundle(), settings.computer)))  # someone already owns "mouse"
    sub = build_computer(settings, registry, engine)
    assert sub.status == "unavailable" and "ToolError" in sub.reason
    assert registry.names() == ["mouse"]  # the partially registered computer tools were removed again
    assert engine.policy.rules == ()  # ... and so were the baseline rules (restored to the previous policy)
    assert "computer rollback" in [e.detail for e in sink.events if e.type.value == "policy_changed"][-1]


def test_building_twice_is_refused_cleanly_and_changes_nothing(tmp_path):
    settings, registry, engine, _ = build_env(tmp_path, enabled=True, backend="fake")
    assert build_computer(settings, registry, engine).status == "enabled"
    names, rules = registry.names(), engine.policy.rules
    again = build_computer(settings, registry, engine)
    assert again.status == "unavailable" and "PolicyError" in again.reason
    assert registry.names() == names and engine.policy.rules == rules


# ---- bootstrap / Core -----------------------------------------------------------------------------------------------------------------------
def test_default_startup_has_no_computer_tools(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    sub = core.subsystems["computer"]
    assert sub.status == "disabled" and "mouse" not in core.tools and "screen" not in core.tools
    assert core.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit."


def test_enabled_startup_wires_tools_into_the_permission_engine(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_COMPUTER_ENABLED="true", JARVIS_COMPUTER_BACKEND="fake")))
    sub = core.subsystems["computer"]
    assert sub.status == "enabled" and {"screen", "mouse", "keyboard", "window", "app", "screen_save"} <= set(core.tools.names())
    assert core.permissions.require_protected_tools and not core.permissions.trust_caller_confirmation
    out = core.tools.execute("screen", action="monitors")
    assert out.success and out.output[0]["primary"]
    core.permissions.set_confirmation_provider(ScriptedConfirmation([NO]))
    out = core.tools.execute("mouse", action="click", x="1", y="1")
    assert not out.success and "declined" in out.error
    log = (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert "computer baseline" in log and '"tool": "mouse"' in log


def test_production_mode_still_gets_computer_tools_but_no_demo_tool(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_MODE="production", JARVIS_COMPUTER_ENABLED="true",
                                                JARVIS_COMPUTER_BACKEND="fake")))
    assert "permission_demo" not in core.tools and "mouse" in core.tools


def test_unavailable_backend_leaves_jarvis_fully_usable(tmp_path, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delitem(sys.modules, "pyautogui", raising=False)
    monkeypatch.setattr(pgi, "_module", None)
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_COMPUTER_ENABLED="true", JARVIS_COMPUTER_BACKEND="x11")))
    sub = core.subsystems["computer"]
    assert sub.status == "unavailable" and sub.reason and "mouse" not in core.tools
    assert core.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit." and core.tools.execute("echo", text="ok").success
    assert "nicht verfügbar" in run_command(core, "/computer")


def test_core_without_subsystems(tmp_path):
    core = JarvisCore(MockProvider())
    assert core.subsystems == {} and run_command(core, "/computer") == "Computersteuerung: nicht konfiguriert."
    assert run_command(core, "/computer stop") == "Computersteuerung: nicht konfiguriert."


# ---- CLI --------------------------------------------------------------------------------------------------------------------------------------
def cli_core(tmp_path, **extra):
    return build_core(load_settings(env=env_for(tmp_path, JARVIS_COMPUTER_ENABLED="true", JARVIS_COMPUTER_BACKEND="fake", JARVIS_COMPUTER_USE_DEFAULT_APPS="false", **extra)))


def run_repl(core, lines):
    it, out = iter(lines), []

    def fake_input(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    repl(core, fake_input, out.append)
    return "\n".join(out)


def test_cli_status_stop_and_resume(tmp_path):
    core = cli_core(tmp_path)
    status = run_command(core, "/computer")
    assert "Computersteuerung: aktiv" in status and "Backend: fake" in status and "Werkzeuge: screen" in status
    assert "notepad" not in status and "keine konfiguriert" in status
    assert "angehalten" in run_command(core, "/computer stop") and "ANGEHALTEN" in run_command(core, "/computer")
    out = run_repl(core, ["/run screen action=monitors", "/computer resume", "/run screen action=monitors", "/exit"])
    assert "Nicht ausgeführt: [failsafe]" in out and "Computersteuerung fortgesetzt." in out and "OK: [{'index': 0" in out


def test_cli_disabled_status_explains_how_to_enable(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    s = run_command(core, "/computer")
    assert "deaktiviert" in s and "JARVIS_COMPUTER_ENABLED=true" in s and "pip install" in s
    assert run_command(core, "/computer stop") == "Computersteuerung ist nicht aktiv."


def test_cli_asks_before_acting_and_refuses_bad_input(tmp_path):
    core = cli_core(tmp_path)
    out = run_repl(core, ["/run mouse action=click x=10 y=10", "n", "/run mouse action=click x=9999 y=1",
                          "/run mouse action=click x=2 y=2", "j", "/run keyboard action=hotkey keys=win+r", "/exit"])
    assert "Aktion: click" in out and "Ziel: screen://monitor/0/10/10" in out and "Risiko: YELLOW" in out
    assert "the user declined" in out and "[invalid_coordinates]" in out and "OK: {'action': 'click'" in out
    assert "RED actions are never permitted: combinations with the Windows key" in out  # denied even without any window
    assert out.count("Erlauben?") == 2  # only the two valid clicks were put to the user


def test_cli_screenshot_prints_metadata_never_pixels(tmp_path):
    core = cli_core(tmp_path)
    out = run_repl(core, ["/run screen action=screenshot", "/computer", "/exit"])
    assert "'width': 64" in out and "shot-" in out and "bytes" in out and "\\x" not in out
    assert "Gespeicherte Screenshots: shot-" in out
