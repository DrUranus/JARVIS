"""Lesende UIA-Tools (Backlog-Schritt uia-tools-readonly): ein Tool `ui` (windows | tree | find) hinter ToolRegistry und PermissionEngine.

Nur Lesen: keine Klicks, keine Eingaben, keine Aktionen. Passwortfelder und als sensibel erkannte Felder liefern nie einen Wert, Ausgaben laufen durch die Redaktion, gesperrte
Fenster (Terminals, Sicherheitswerkzeuge, Passwortmanager, Banking, eigene Sperren) werden nie gelesen, Notaus und Sitzungsbudget wirken, standardmaessig ist alles aus.
Fake-Backend und Fake-UIA-Provider: kein Netzwerk, kein Windows, keine Bibliothek. Laeuft unter Linux und Windows gleich."""
from __future__ import annotations

import ast
import dataclasses
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from computer_util import ONCE, SESSION, approved
from jarvis.computer import ComputerBackend, ComputerController, ComputerError, ErrorCode
from jarvis.computer import resources as res
from jarvis.computer.policy import baseline_rules
from jarvis.computer.providers.fake import FakeBackend
from jarvis.computer.providers.fake_uia import FAKE_SECRET, FakeUiaProvider, login_tree, notepad_tree
from jarvis.computer.tools import TOOL_CLASSES, UiTool, register_computer_tools
from jarvis.computer.uia import UiElement, UiRect
from jarvis.config import ComputerSettings
from jarvis.permissions import PermissionLevel, Policy, ScriptedConfirmation
from jarvis.permissions.budget import SessionBudget
from jarvis.tools import ToolRegistry
from jarvis.tools.base import ProtectedTool
from secutil import make_engine

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "src" / "jarvis" / "computer"
SK = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"           # sieht wie ein API-Schluessel aus (nur Testdaten)


def el(rid, name, ctype="Pane", children=(), **kw):
    return UiElement(runtime_id=rid, name=name, control_type=ctype, children=tuple(children), **kw)


def secrets_tree():
    return el("0", "Einstellungen", "Window", children=[
        el("0.0", "API key", "Edit", value="geheimer-wert-123456"),
        el("0.1", "Kennwort", "Edit", value="noch-ein-geheimnis"),
        el("0.2", "Notizen", "Edit", value=f"merke: key {SK} und token=abcdef123456"),
        el("0.3", "Name", "Edit", value="Alice"),
        el("0.4", "Passwort speichern", "CheckBox"),
        el("0.5", "Weiter", "Button", automation_id="ok", rect=UiRect(1, 2, 3, 4)),
    ], rect=UiRect(0, 0, 100, 100))


@dataclass
class Rig:
    engine: Any
    sink: Any
    prompts: ScriptedConfirmation
    registry: ToolRegistry
    fb: FakeBackend
    provider: FakeUiaProvider
    controller: ComputerController
    handles: dict[str, int]

    def run(self, **kw):
        return self.registry.execute("ui", **kw)

    def blob(self) -> str:
        return json.dumps([e.to_dict() for e in self.sink.events]) + "\n".join(r.to_text() + json.dumps(dict(r.context)) for r in self.prompts.requests)


def make_ui_rig(tmp_path, answers=(), *, budget=None, with_ui=True, extra_windows=(), **settings_kw) -> Rig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = ScriptedConfirmation(answers or [ONCE] * 40)
    kw = {"budget": budget} if budget else {}
    engine, sink, _ws = make_engine(tmp_path, confirmation=prompts, **kw)
    fb = FakeBackend()
    handles, trees = {}, {}
    windows = [("notepad", "Untitled - Notepad", "notepad.exe", notepad_tree()), ("login", "Sign in - Example", "example.exe", login_tree()),
               ("settings", "Einstellungen", "settings.exe", secrets_tree()), *extra_windows]
    for key, title, process, tree in windows:
        w = fb.add_window(title, process, width=40, height=30, active=(key == "notepad"))
        handles[key], trees[w.handle] = w.handle, tree
    provider = FakeUiaProvider(trees)
    bundle = fb.bundle()
    if with_ui:
        bundle.ui = provider
    settings = ComputerSettings(enabled=True, apps={}, use_default_apps=False, action_delay=0.0, uia_enabled=with_ui, **settings_kw)
    controller = ComputerController(bundle, settings, sleep=lambda s: None, own_pids=())
    engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
    registry = ToolRegistry(engine)
    register_computer_tools(registry, controller)
    return Rig(engine, sink, prompts, registry, fb, provider, controller, handles)


@pytest.fixture
def rig(tmp_path):
    return make_ui_rig(tmp_path)


def dump(x) -> str:
    return json.dumps(x, default=str, ensure_ascii=False)


def walk(tree: dict):
    yield tree
    for c in tree.get("children", []):
        yield from walk(c)


# ---- Registrierung: standardmaessig aus --------------------------------------------------------------------------------------------------
def test_the_ui_tool_exists_only_when_the_backend_has_a_ui_provider(tmp_path):
    with_ui, without = make_ui_rig(tmp_path / "a"), make_ui_rig(tmp_path / "b", with_ui=False)
    assert "ui" in with_ui.registry.names() and "ui" not in without.registry.names()
    assert without.registry.names() == ["app", "keyboard", "mouse", "screen", "screen_save", "window"]            # unveraendert


def test_the_ui_tool_is_a_protected_tool_declared_yellow_and_not_part_of_the_default_tool_set():
    assert issubclass(UiTool, ProtectedTool) and UiTool.permission is PermissionLevel.YELLOW and UiTool.name == res.TOOL_UI == "ui"
    assert UiTool not in TOOL_CLASSES and "ui" not in res.ALL_TOOLS
    assert {p.name for p in UiTool.parameters} == {"action", "window", "name_equals", "name_contains", "control_type", "automation_id", "enabled", "visible",
                                                   "max_results", "max_depth", "max_nodes"}


def test_register_returns_the_ui_tool_last_and_a_lenient_engine_is_still_refused(tmp_path):
    r = make_ui_rig(tmp_path)
    assert r.registry.names() == ["app", "keyboard", "mouse", "screen", "screen_save", "ui", "window"]
    from jarvis.errors import ToolError
    from jarvis.permissions import PermissionEngine
    for lenient in (PermissionEngine(trust_caller_confirmation=True), PermissionEngine(require_protected_tools=False)):
        with pytest.raises(ToolError):
            register_computer_tools(ToolRegistry(lenient), r.controller)


def test_the_shipped_defaults_keep_ui_automation_off():
    assert ComputerSettings().uia_enabled is False
    import tomllib
    assert tomllib.loads((ROOT / "config" / "jarvis.toml").read_text(encoding="utf-8"))["computer"]["uia_enabled"] is False


def test_building_the_subsystem_registers_the_ui_tool_only_with_uia_enabled(tmp_path):
    from jarvis.computer import factory
    from jarvis.config import Settings
    for enabled, expected in ((False, False), (True, True)):
        (tmp_path / str(enabled)).mkdir(parents=True, exist_ok=True)
        engine, _s, _w = make_engine(tmp_path / str(enabled), confirmation=ScriptedConfirmation([ONCE] * 5))
        registry = ToolRegistry(engine)
        settings = dataclasses.replace(Settings(), computer=ComputerSettings(enabled=True, backend="fake", uia_enabled=enabled))
        sub = factory.build_computer(settings, registry, engine)
        assert sub.status == "enabled" and ("ui" in registry.names()) is expected and ("ui" in sub.tool_names) is expected


# ---- Rechte: jeder Zugriff ueber die Engine -----------------------------------------------------------------------------------------------
def test_calling_the_tool_without_the_engine_is_refused(rig):
    from jarvis.errors import PermissionDeniedError
    tool = rig.registry.get("ui")
    with pytest.raises(PermissionDeniedError):
        tool.run(action="windows")
    plan = rig.controller.plan_ui("windows")
    with pytest.raises(ComputerError) as exc:
        rig.controller.execute(plan)
    assert exc.value.code is ErrorCode.NOT_AUTHORIZED and rig.provider.calls == []


def test_every_read_is_confirmed_and_the_prompt_names_window_and_process(rig):
    out = rig.run(action="tree", window=rig.handles["notepad"])
    assert out.success and len(rig.prompts.requests) == 1
    req = rig.prompts.requests[0]
    assert req.tool == "ui" and req.action == "tree" and req.level is PermissionLevel.YELLOW
    assert req.resource == f"ui://tree/{rig.handles['notepad']}/notepad.exe" and "Notepad" in dump(dict(req.context))


def test_a_denied_confirmation_reads_nothing(tmp_path):
    from computer_util import NO
    r = make_ui_rig(tmp_path, [NO])
    out = r.run(action="tree", window=r.handles["notepad"])
    assert not out.success and r.provider.calls == []


def test_a_session_permission_covers_the_same_window_only(tmp_path):
    r = make_ui_rig(tmp_path, [SESSION])
    assert r.run(action="tree", window=r.handles["notepad"]).success and r.run(action="tree", window=r.handles["notepad"]).success
    assert len(r.prompts.requests) == 1                                          # die zweite Anfrage ist gedeckt
    other = r.run(action="tree", window=r.handles["login"])
    assert len(r.prompts.requests) == 2 or not other.success                     # ein anderes Fenster braucht eine neue Entscheidung


# ---- Fensterliste, Baum, Suche ----------------------------------------------------------------------------------------------------------------
def test_windows_lists_handle_title_process_class_and_whether_it_can_be_read(tmp_path):
    r = make_ui_rig(tmp_path, extra_windows=[("term", "Eingabeaufforderung", "cmd.exe", notepad_tree()), ("kp", "KeePass - Datenbank", "keepass.exe", notepad_tree())])
    out = r.run(action="windows")
    assert out.success and r.prompts.requests[0].resource == "ui://windows"
    by_title = {w["title"]: w for w in out.output}
    assert by_title["Untitled - Notepad"]["readable"] is True and by_title["Untitled - Notepad"]["process"] == "notepad.exe"
    assert by_title["Eingabeaufforderung"]["readable"] is False and by_title["KeePass - Datenbank"]["readable"] is False
    assert all(set(w) == {"handle", "title", "process", "class", "readable"} for w in out.output)
    assert r.provider.calls == []                                                # die Fensterliste braucht den UIA-Provider nicht


def test_tree_returns_the_bounded_tree_of_the_window(rig):
    out = rig.run(action="tree", window=rig.handles["notepad"])
    assert out.success and out.output["window"] == {"handle": rig.handles["notepad"], "title": "Untitled - Notepad", "process": "notepad.exe"}
    tree = out.output["tree"]
    assert tree["name"] == "Untitled - Notepad" and tree["control_type"] == "Window" and out.output["node_count"] == len(list(walk(tree))) and out.output["truncated"] is False
    assert {"MenuItem", "Edit", "StatusBar"} <= {n["control_type"] for n in walk(tree)}
    assert rig.provider.calls == [("describe", rig.handles["notepad"])]


def test_tree_limits_are_applied_and_invalid_limits_are_refused(rig):
    out = rig.run(action="tree", window=rig.handles["notepad"], max_nodes=3, max_depth=1)
    assert out.success and out.output["node_count"] == 3 and out.output["truncated"] is True
    for bad in ({"max_nodes": 0}, {"max_nodes": 100000}, {"max_depth": 99}, {"max_depth": "x"}, {"max_depth": True}):
        res_ = rig.run(action="tree", window=rig.handles["notepad"], **bad)
        assert not res_.success, bad


def test_find_returns_matching_elements_without_children(rig):
    out = rig.run(action="find", window=rig.handles["notepad"], control_type="MenuItem", name_contains="e")
    assert out.success and out.output["count"] == 4 and [m["name"] for m in out.output["matches"]] == ["File", "Edit", "View", "Help"]
    assert all("children" not in m or isinstance(m["children"], int) for m in out.output["matches"])
    one = rig.run(action="find", window=rig.handles["notepad"], automation_id="15")
    assert [m["name"] for m in one.output["matches"]] == ["Text editor"]
    assert rig.run(action="find", window=rig.handles["notepad"], name_equals="gibt es nicht").output["count"] == 0
    flags = rig.run(action="find", window=rig.handles["login"], enabled="false")
    assert [m["name"] for m in flags.output["matches"]] == ["Remember me"]


@pytest.mark.parametrize("kw", [{"action": "click"}, {"action": "invoke"}, {"action": None}, {"action": "tree"}, {"action": "tree", "window": "abc"}, {"action": "tree", "window": 99999},
                                {"action": "find", "window": "{n}", "control_type": "Unsinn"}, {"action": "find", "window": "{n}", "max_results": 0},
                                {"action": "find", "window": "{n}", "enabled": "vielleicht"}, {"action": "find", "window": "{n}", "name_contains": "x" * 500}])
def test_invalid_requests_are_refused_without_touching_the_provider(rig, kw):
    kw = {k: (rig.handles["notepad"] if v == "{n}" else v) for k, v in kw.items()}
    out = rig.run(**kw)
    assert not out.success and rig.provider.calls == []


# ---- Passwoerter und sensible Felder ------------------------------------------------------------------------------------------------------
def test_password_values_never_appear_anywhere(rig, caplog):
    caplog.set_level(logging.DEBUG)
    for action, extra in (("tree", {}), ("find", {"name_contains": "password"}), ("find", {})):
        out = rig.run(action=action, window=rig.handles["login"], **extra)
        assert out.success and FAKE_SECRET not in dump(out.output) and FAKE_SECRET not in str(out.error)
    tree = rig.run(action="tree", window=rig.handles["login"]).output["tree"]
    pw = next(n for n in walk(tree) if n["name"] == "Password")
    assert pw["is_password"] is True and "value" not in pw
    assert FAKE_SECRET not in rig.blob() and FAKE_SECRET not in caplog.text


def test_fields_that_look_like_secrets_lose_their_value_and_secrets_in_texts_are_redacted(rig):
    out = rig.run(action="tree", window=rig.handles["settings"])
    assert out.success
    by_name = {n["name"]: n for n in walk(out.output["tree"])}
    for hidden in ("API key", "Kennwort"):
        assert "value" not in by_name[hidden], hidden
    assert by_name["Name"]["value"] == "Alice"                                   # normale Felder bleiben lesbar
    notes = by_name["Notizen"]["value"]
    assert SK not in notes and "abcdef123456" not in notes and "[REDACTED]" in notes
    blob = dump(out.output) + rig.blob()
    for leaked in ("geheimer-wert-123456", "noch-ein-geheimnis", SK, "abcdef123456"):
        assert leaked not in blob, leaked


def test_a_checkbox_named_like_a_password_is_not_hidden_it_has_no_value_anyway(rig):
    by_name = {n["name"]: n for n in walk(rig.run(action="tree", window=rig.handles["settings"]).output["tree"])}
    assert by_name["Passwort speichern"]["control_type"] == "CheckBox"


# ---- gesperrte Fenster --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("title,process", [("Eingabeaufforderung", "cmd.exe"), ("Windows PowerShell", "powershell.exe"), ("Task Manager", "taskmgr.exe"),
                                           ("Windows Security", "SecHealthUI.exe"), ("KeePass - Datenbank", "KeePass.exe"), ("Mein Tresor", "Bitwarden.exe"),
                                           ("Tresor", "1Password.exe"), ("Mein Passwortmanager", "app.exe"), ("Online Banking - Meine Bank", "browser.exe"),
                                           ("Run", "explorer.exe")])
def test_blocked_windows_are_never_read(tmp_path, title, process):
    r = make_ui_rig(tmp_path, extra_windows=[("x", title, process, notepad_tree())])
    for action in ("tree", "find"):
        out = r.run(action=action, window=r.handles["x"])
        assert not out.success and r.provider.calls == [], (action, title)
    assert r.prompts.requests == []                                               # RED: nie eine Rueckfrage, nie ein Lesezugriff


def test_the_users_own_title_blocks_apply_to_ui_reads_too(tmp_path):
    r = make_ui_rig(tmp_path, blocked_titles=("notepad",))
    assert not r.run(action="tree", window=r.handles["notepad"]).success and r.provider.calls == []
    assert r.run(action="tree", window=r.handles["login"]).success


def test_a_window_that_changes_its_program_after_the_approval_is_not_read(rig):
    h = rig.handles["notepad"]
    plan = rig.controller.plan_ui("tree", window=h)
    rig.fb.windows[h] = dataclasses.replace(rig.fb.windows[h], process="keepass.exe", title="KeePass")
    with approved(rig.engine, plan):
        with pytest.raises(ComputerError) as exc:
            rig.controller.execute(plan)
    assert exc.value.code in (ErrorCode.TARGET_CHANGED, ErrorCode.BLOCKED_TARGET) and rig.provider.calls == []


def test_a_vanished_window_is_a_controlled_error(rig):
    h = rig.handles["notepad"]
    plan = rig.controller.plan_ui("tree", window=h)
    del rig.fb.windows[h]
    rig.fb.z_order.remove(h)
    with approved(rig.engine, plan):
        with pytest.raises(ComputerError) as exc:
            rig.controller.execute(plan)
    assert exc.value.code in (ErrorCode.TARGET_CHANGED, ErrorCode.WINDOW_NOT_FOUND) and rig.provider.calls == []


# ---- Notaus, Sitzungsbudget, Fehler, Zeitlimits ---------------------------------------------------------------------------------------------
def test_the_computer_halt_stops_further_reads_until_resume(rig):
    h = rig.handles["notepad"]
    assert rig.run(action="tree", window=h).success
    calls = len(rig.provider.calls)
    rig.controller.halt("test")
    out = rig.run(action="tree", window=h)
    assert not out.success and "failsafe" in dump(out.output).lower() + str(out.error).lower() and len(rig.provider.calls) == calls
    rig.controller.resume()
    assert rig.run(action="tree", window=h).success


def test_the_global_emergency_stop_refuses_the_ui_tool_too(rig):
    h = rig.handles["notepad"]
    assert rig.run(action="windows").success
    rig.engine.emergency.engage("test", "t")                      # der Latch der Engine (Kontrollstelle), nicht der des Controllers
    for kw in ({"action": "windows"}, {"action": "tree", "window": h}, {"action": "find", "window": h}):
        out = rig.run(**kw)
        assert not out.success and "emergency stop" in str(out.error)
    assert rig.provider.calls == []


def test_the_session_budget_of_the_engine_counts_ui_reads(tmp_path):
    r = make_ui_rig(tmp_path, budget=SessionBudget(2, 3600))
    h = r.handles["notepad"]
    assert r.run(action="tree", window=h).success and r.run(action="find", window=h).success
    third = r.run(action="tree", window=h)
    assert not third.success and "Sitzungsbudget" in str(third.error) and len(r.provider.calls) == 2


def test_a_failing_or_timed_out_provider_is_a_structured_error_and_the_next_call_works(rig):
    h = rig.handles["notepad"]
    rig.provider.fail_next(ComputerError(ErrorCode.BACKEND_ERROR, "timeout: the UI worker did not answer within 20 s and was stopped"))
    out = rig.run(action="tree", window=h)
    assert not out.success and out.output["code"] == "backend_error" and "timeout" in out.output["message"]
    assert rig.run(action="tree", window=h).success
    rig.provider.fail_next(RuntimeError("Fehler mit Text: " + SK))
    boom = rig.run(action="tree", window=h)
    assert not boom.success and SK not in str(boom.error) + dump(boom.output) and SK not in rig.blob()


def test_the_ui_tool_cannot_lift_the_emergency_stop_or_edit_rules(rig):
    import inspect
    names = {p.name for p in UiTool.parameters}
    assert not names & {"confirmed", "force", "reset", "resume", "policy", "rule"}
    assert re.search(r"\b(resume|halt|update_policy|set_confirmation_provider|_safety|_backend)\b", inspect.getsource(UiTool)) is None


# ---- Aufbau --------------------------------------------------------------------------------------------------------------------------------
def test_only_the_controller_drives_the_ui_provider_and_nothing_acts():
    for f in COMP.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "ui" and f.name not in ("controller.py", "backend.py", "factory.py"):
                raise AssertionError(f"{f.name}: .ui outside controller/backend/factory")
    acting = {"click", "invoke", "type_keys", "send_keys", "set_text", "set_edit_text", "kill", "terminate", "click_input"}
    for f in (COMP / "controller.py", COMP / "tools.py", COMP / "uia_output.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                assert n.func.attr not in acting, f"{f.name}: .{n.func.attr}()"


def test_no_library_and_no_dependency_was_added_for_the_tools():
    for f in (COMP / "controller.py", COMP / "tools.py", COMP / "uia_output.py", COMP / "safety.py", COMP / "resources.py"):
        assert not re.search(r"(?m)^\s*(import|from)\s+(pywinauto|comtypes|pythoncom|win32\w*|ctypes|subprocess|socket|urllib)\b", f.read_text(encoding="utf-8")), f.name
    assert "dependencies = []" in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_the_ui_tool_only_touches_computer_and_documentation_files():
    """bootstrap.py, permissions/, config/ und die Sicherheitstests bleiben unveraendert: die Verdrahtung laeuft ueber die vorhandene build_computer-Fabrik."""
    import subprocess
    try:
        out = subprocess.run(["git", "diff", "--name-only", "origin/main...HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except Exception:
        pytest.skip("git nicht verfuegbar")
    if out.returncode != 0:
        pytest.skip("kein origin/main in diesem Checkout")
    changed = [l for l in out.stdout.splitlines() if l]
    forbidden = [f for f in changed if f.startswith(("src/jarvis/permissions/", ".github/", ".claude/", "config/")) or f in ("src/jarvis/bootstrap.py", "CLAUDE.md", "pyproject.toml")
                 or f.startswith("tests/test_security_") or f in ("tests/test_emergency_stop.py", "tests/test_autonomy_invariants.py")]
    assert forbidden == [], forbidden
