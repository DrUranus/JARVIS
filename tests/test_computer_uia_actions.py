"""UIA-Aktionen (Backlog-Schritt uia-actions): ein Tool `ui_act` (invoke | set_value | select | toggle | focus) hinter ToolRegistry und PermissionEngine.

Aktionen laufen nur ueber UIA-Muster (nie Koordinaten, nie pyautogui), sind mindestens YELLOW (Bestaetigung) mit describe_action (Fenster, Steuerelement, Aktion), lehnen Passwortfelder,
geheimnisartige Felder und gesperrte Fenster immer ab, folgen Notaus (Controller und Engine) und Sitzungsbudget und melden nach jeder Aktion den NACH der Aktion gelesenen Zustand
(Beobachten, Handeln, Pruefen). Standardmaessig ist alles aus. Fake-Backend und Fake-Provider: kein Netzwerk, kein Windows, keine Bibliothek; laeuft unter Linux und Windows gleich."""
from __future__ import annotations

import ast
import dataclasses
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from computer_util import ONCE
from jarvis.computer import ComputerBackend, ComputerController, ComputerError, ErrorCode
from jarvis.computer import resources as res
from jarvis.computer.policy import baseline_rules
from jarvis.computer.providers.fake import FakeBackend
from jarvis.computer.providers.fake_uia import FakeUiaProvider
from jarvis.computer.providers.fake_uia_actions import FakeUiaActionProvider
from jarvis.computer.tools import TOOL_CLASSES, UiActTool, UiTool, register_computer_tools
from jarvis.computer.uia import UiElement, UiRect
from jarvis.computer.uia_actions import UiAction, UiState, UiTarget, judge
from jarvis.config import ComputerSettings, Settings
from jarvis.permissions import PermissionLevel, Policy, ScriptedConfirmation
from jarvis.permissions.budget import SessionBudget
from jarvis.tools import ToolRegistry
from jarvis.tools.base import ProtectedTool
from secutil import make_engine

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "src" / "jarvis" / "computer"
SK = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"          # sieht wie ein API-Schluessel aus (nur Testdaten)


def el(rid, name, ctype="Pane", children=(), **kw):
    return UiElement(runtime_id=rid, name=name, control_type=ctype, children=tuple(children), **kw)


def form_tree():
    return el("0", "Einstellungen", "Window", children=[
        el("0.0", "Name", "Edit", automation_id="name", value="Alice"),
        el("0.1", "Newsletter", "CheckBox", automation_id="news"),
        el("0.2", "Option A", "ListItem", automation_id="optA"),
        el("0.3", "OK", "Button", automation_id="ok"),
        el("0.4", "Kennwort", "Edit", automation_id="pw", is_password=True, value="geheim-123"),
        el("0.5", "API key", "Edit", automation_id="key", value="egal"),
        el("0.6", "Gesperrt", "Button", automation_id="off", enabled=False),
        el("0.7", "Speichern", "Button", automation_id="save1"),
        el("0.8", "Speichern", "Button", automation_id="save2"),
        el("0.9", "Nur lesen", "Text"),
    ], rect=UiRect(0, 0, 100, 100))


@dataclass
class Rig:
    engine: Any
    sink: Any
    prompts: ScriptedConfirmation
    registry: ToolRegistry
    fb: FakeBackend
    reader: FakeUiaProvider
    actor: FakeUiaActionProvider
    controller: ComputerController
    handles: dict

    def act(self, **kw):
        return self.registry.execute("ui_act", **kw)

    def blob(self) -> str:
        return json.dumps([e.to_dict() for e in self.sink.events]) + "\n".join(r.to_text() + json.dumps(dict(r.context)) for r in self.prompts.requests)


def make_rig(tmp_path, *, budget=None, with_actions=True, **settings_kw) -> Rig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = ScriptedConfirmation([ONCE] * 60)
    engine, sink, _ws = make_engine(tmp_path, confirmation=prompts, **({"budget": budget} if budget else {}))
    fb = FakeBackend()
    handles, trees = {}, {}
    for key, title, process, tree in (("form", "Einstellungen", "settings.exe", form_tree()), ("term", "Eingabeaufforderung", "cmd.exe", form_tree()),
                                      ("bank", "Online Banking - Mein Konto", "browser.exe", form_tree())):
        w = fb.add_window(title, process, width=40, height=30, active=(key == "form"))
        handles[key], trees[w.handle] = w.handle, tree
    reader, actor = FakeUiaProvider(trees), FakeUiaActionProvider(trees)
    bundle = fb.bundle()
    bundle.ui = reader
    if with_actions:
        bundle.ui_actions = actor
    settings = ComputerSettings(enabled=True, apps={}, use_default_apps=False, action_delay=0.0, uia_enabled=True, uia_actions_enabled=with_actions, **settings_kw)
    controller = ComputerController(bundle, settings, sleep=lambda s: None, own_pids=())
    engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
    registry = ToolRegistry(engine)
    register_computer_tools(registry, controller)
    return Rig(engine, sink, prompts, registry, fb, reader, actor, controller, handles)


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path)


def dump(x) -> str:
    return json.dumps(x, default=str, ensure_ascii=False)


# ---- Registrierung und Standard aus --------------------------------------------------------------------------------------------------------
def test_the_tool_exists_only_with_an_action_provider_and_is_not_part_of_the_default_tool_set(tmp_path):
    with_a, without = make_rig(tmp_path / "a"), make_rig(tmp_path / "b", with_actions=False)
    assert "ui_act" in with_a.registry.names() and "ui_act" not in without.registry.names() and "ui" in without.registry.names()
    assert UiActTool not in TOOL_CLASSES and "ui_act" not in res.ALL_TOOLS and res.TOOL_UI_ACT == "ui_act"
    assert ComputerBackend("x").capabilities() == [] and "ui_actions" in ComputerBackend("x", ui_actions=FakeUiaActionProvider({})).capabilities()


def test_it_is_a_protected_tool_declared_yellow_with_no_coordinates_and_no_bypass_parameters():
    assert issubclass(UiActTool, ProtectedTool) and UiActTool.permission is PermissionLevel.YELLOW
    names = {p.name for p in UiActTool.parameters}
    assert names == {"action", "window", "name_equals", "name_contains", "automation_id", "control_type", "value", "max_depth", "max_nodes"}
    assert not names & {"x", "y", "monitor", "confirmed", "force", "reset", "resume", "policy", "rule", "pattern", "coordinates"}


def test_everything_is_off_by_default():
    assert ComputerSettings().uia_actions_enabled is False and ComputerSettings().uia_enabled is False
    assert Settings().computer.uia_actions_enabled is False


@pytest.mark.parametrize("uia,actions,expect", [(True, False, False), (False, True, False), (True, True, True), (False, False, False)])
def test_the_factory_registers_ui_act_only_when_both_switches_are_on(tmp_path, uia, actions, expect):
    from jarvis.computer import factory
    (tmp_path / f"{uia}{actions}").mkdir()
    engine, _s, _w = make_engine(tmp_path / f"{uia}{actions}", confirmation=ScriptedConfirmation([ONCE] * 5))
    registry = ToolRegistry(engine)
    settings = dataclasses.replace(Settings(), computer=ComputerSettings(enabled=True, backend="fake", uia_enabled=uia, uia_actions_enabled=actions))
    sub = factory.build_computer(settings, registry, engine)
    assert sub.status == "enabled" and ("ui_act" in registry.names()) is expect and ("ui_act" in sub.tool_names) is expect
    if actions and not uia:
        assert "UI actions unavailable" in sub.reason


def test_a_missing_library_gives_a_clear_message_instead_of_a_crash(monkeypatch):
    from jarvis.computer.errors import ComputerUnavailableError
    from jarvis.computer.providers import pywinauto_uia_actions as mod
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(ComputerUnavailableError) as exc:
        mod.create_uia_action_provider()
    assert "pywinauto is not installed" in str(exc.value) and "pip install -e .[uia]" in str(exc.value)
    monkeypatch.setattr(mod.sys, "platform", "linux")
    with pytest.raises(ComputerUnavailableError):
        mod.create_uia_action_provider()


# ---- Aktionen ueber UIA-Muster, YELLOW mit describe_action ------------------------------------------------------------------------------------
CASES = [("set_value", {"name_equals": "Name", "value": "Bob"}, True), ("toggle", {"automation_id": "news"}, True), ("select", {"name_equals": "Option A"}, True),
         ("focus", {"automation_id": "name"}, True), ("invoke", {"automation_id": "ok"}, None)]


@pytest.mark.parametrize("action,kw,verified", CASES)
def test_each_action_goes_through_the_engine_is_confirmed_and_reports_the_state_read_afterwards(rig, action, kw, verified):
    h = rig.handles["form"]
    out = rig.act(action=action, window=h, **kw)
    assert out.success, (out.error, out.output)
    assert out.output["performed"] is True and out.output["verified"] is verified and out.output["action"] == action
    assert len(rig.prompts.requests) == 1 and rig.prompts.requests[0].level is PermissionLevel.YELLOW
    assert [c[:3] for c in rig.actor.calls if c[0] == "perform"] == [("perform", h, rig.actor.performed[0][1])]
    ops = [c[0] for c in rig.actor.calls]
    assert ops == ["read", "read", "perform", "read"] or ops == ["read", "perform", "read"], ops      # beobachten, handeln, pruefen
    assert out.output["state_after"] is not None


def test_describe_action_names_window_control_and_action_and_the_level_is_yellow(rig):
    h = rig.handles["form"]
    tool = rig.registry.get("ui_act")
    spec = tool.describe_action(action="toggle", window=h, automation_id="news")
    assert spec.level is PermissionLevel.YELLOW and spec.resource.startswith("uiact://toggle/") and spec.resource.endswith("/0.1")
    ctx = dump(dict(spec.context)) + spec.reason
    assert "Einstellungen" in ctx and "Newsletter" in ctx and "toggle" in ctx and "CheckBox" in ctx
    rig.act(action="toggle", window=h, automation_id="news")
    text = rig.prompts.requests[0].to_text() + json.dumps(dict(rig.prompts.requests[0].context))
    assert "Einstellungen" in text and "Newsletter" in text and "toggle" in text


def test_the_state_is_read_back_and_the_values_really_changed(rig):
    h = rig.handles["form"]
    rig.act(action="set_value", window=h, automation_id="name", value="Bob")
    rig.act(action="toggle", window=h, automation_id="news")
    out = rig.act(action="toggle", window=h, automation_id="news")
    assert out.output["state_before"]["toggle_state"] == "on" and out.output["state_after"]["toggle_state"] == "off"
    target = UiTarget("0.0", "Name", "Edit", "name")
    assert rig.actor.read_state(h, target).value == "Bob"
    assert rig.act(action="select", window=h, name_equals="Option A").output["state_after"]["selected"] is True
    assert rig.act(action="focus", window=h, automation_id="name").output["state_after"]["has_focus"] is True


def test_a_deviation_is_reported_honestly_as_not_successful(rig):
    h = rig.handles["form"]
    rig.actor.misbehave = True                      # das Programm nimmt die Aktion an und aendert nichts
    for action, kw in (("set_value", {"automation_id": "name", "value": "Bob"}), ("toggle", {"automation_id": "news"}), ("select", {"name_equals": "Option A"}),
                       ("focus", {"automation_id": "name"})):
        out = rig.act(action=action, window=h, **kw)
        assert not out.success and out.output["performed"] is True and out.output["verified"] is False, (action, out.output)
        assert "NICHT bestaetigt" in out.output["message"] and "not confirmed" in str(out.error)


def test_invoke_reports_that_the_result_cannot_be_checked_and_a_vanished_control_is_not_a_failure_for_invoke(rig):
    h = rig.handles["form"]
    rig.actor.vanish_after = {"invoke"}
    out = rig.act(action="invoke", window=h, automation_id="ok")
    assert out.success and out.output["verified"] is None and out.output["state_after"] is None and "nicht mehr vorhanden" in out.output["observed"]
    rig.actor.vanish_after = {"toggle"}
    gone = rig.act(action="toggle", window=h, automation_id="news")
    assert not gone.success and gone.output["verified"] is False


def test_judge_is_a_pure_comparison_of_before_and_after():
    on, off = UiState(toggle_state="on"), UiState(toggle_state="off")
    assert judge(UiAction.TOGGLE, off, on)["verified"] is True and judge(UiAction.TOGGLE, off, off)["verified"] is False
    assert judge(UiAction.SET_VALUE, UiState(value="a"), UiState(value="b"), "b")["verified"] is True
    assert judge(UiAction.SET_VALUE, UiState(value="a"), UiState(value="a"), "b")["verified"] is False
    assert judge(UiAction.SET_VALUE, UiState(), UiState(), "b")["verified"] is False            # nicht lesbar = nicht bestaetigt
    assert judge(UiAction.SELECT, UiState(selected=False), UiState(selected=False))["verified"] is False
    assert judge(UiAction.INVOKE, UiState(), UiState())["verified"] is None
    assert "zzz" not in dump(judge(UiAction.SET_VALUE, UiState(value="a"), UiState(value="zzz"), "b"))


def test_the_set_text_is_never_echoed_nor_audited_and_a_secret_in_it_is_redacted_in_the_prompt(rig):
    h = rig.handles["form"]
    text = f"merke {SK} ende"
    out = rig.act(action="set_value", window=h, automation_id="name", value=text)
    assert out.success and text not in dump(out.output) and SK not in dump(out.output)
    assert SK not in rig.blob() and text not in rig.blob()


# ---- Eingabepruefung: kein Raten, keine Koordinaten ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kw", [
    {"action": "click", "automation_id": "ok"},                                          # unbekannte Aktion
    {"action": "invoke"},                                                                # kein Steuerelement benannt
    {"action": "invoke", "name_equals": "Gibt es nicht"},                                # nicht gefunden
    {"action": "invoke", "name_equals": "Speichern"},                                    # mehrdeutig
    {"action": "invoke", "automation_id": "off"},                                        # deaktiviert
    {"action": "set_value", "automation_id": "ok", "value": "x"},                        # set_value nur auf Textfeldern
    {"action": "set_value", "automation_id": "name"},                                    # Wert fehlt
    {"action": "set_value", "automation_id": "name", "value": ""},                       # leer
    {"action": "set_value", "automation_id": "name", "value": "a\x00b"},                 # Steuerzeichen
    {"action": "invoke", "automation_id": "ok", "value": "x"},                           # Wert nur fuer set_value
    {"action": "toggle", "automation_id": "name"},                                       # Muster nicht unterstuetzt
    {"action": "invoke", "automation_id": "name"},
])
def test_bad_or_unsupported_requests_do_nothing(rig, kw):
    out = rig.act(window=rig.handles["form"], **kw)
    assert not out.success and rig.actor.performed == []


def test_an_unknown_window_receives_nothing(rig):
    out = rig.act(action="set_value", window=999999, automation_id="name", value="x")
    assert not out.success and rig.actor.performed == [] and rig.actor.calls == []
    assert not rig.act(action="set_value", automation_id="name", value="x").success


def test_a_window_that_vanished_after_the_approval_receives_nothing(rig):
    h = rig.handles["form"]
    from computer_util import approved
    plan = rig.controller.plan_ui_act("set_value", window=h, automation_id="name", value="x")
    del rig.fb.windows[h]
    rig.fb.z_order.remove(h)
    with approved(rig.engine, plan):
        with pytest.raises(ComputerError) as exc:
            rig.controller.execute(plan)
    assert exc.value.code in (ErrorCode.TARGET_CHANGED, ErrorCode.WINDOW_NOT_FOUND) and rig.actor.performed == []


def test_without_the_engine_nothing_runs(rig):
    from jarvis.errors import PermissionDeniedError
    h = rig.handles["form"]
    tool = rig.registry.get("ui_act")
    with pytest.raises(PermissionDeniedError):
        tool.run(action="toggle", window=h, automation_id="news")
    plan = rig.controller.plan_ui_act("toggle", window=h, automation_id="news")
    with pytest.raises(ComputerError) as exc:
        rig.controller.execute(plan)
    assert exc.value.code is ErrorCode.NOT_AUTHORIZED and rig.actor.performed == []
    forged = dataclasses.replace(plan, resource=plan.resource.replace("/0.1", "/0.3"))
    with pytest.raises(ComputerError):
        rig.controller.execute(forged)
    assert rig.actor.performed == []


def test_an_approval_for_one_control_does_not_cover_another(rig):
    from computer_util import approved
    h = rig.handles["form"]
    a = rig.controller.plan_ui_act("toggle", window=h, automation_id="news")
    b = rig.controller.plan_ui_act("invoke", window=h, automation_id="ok")
    with approved(rig.engine, a):
        with pytest.raises(ComputerError):
            rig.controller.execute(b)
    assert rig.actor.performed == []


# ---- Passwortfelder, geheimnisartige Felder, gesperrte Fenster: immer abgelehnt ---------------------------------------------------------------
@pytest.mark.parametrize("action,kw", [("set_value", {"automation_id": "pw", "value": "neu"}), ("focus", {"automation_id": "pw"}), ("invoke", {"automation_id": "pw"}),
                                       ("set_value", {"automation_id": "key", "value": "neu"}), ("focus", {"name_equals": "API key"})])
def test_password_and_secret_looking_fields_are_always_refused_without_a_prompt(rig, action, kw):
    out = rig.act(action=action, window=rig.handles["form"], **kw)
    assert not out.success and rig.actor.performed == [] and rig.prompts.requests == [] and rig.actor.calls == []
    assert "geheim-123" not in rig.blob() + dump(out.output)


def test_a_session_permission_cannot_open_a_password_field(rig):
    rig.engine.update_policy(Policy(tuple(rig.engine.policy.rules)))
    for _ in range(2):
        assert not rig.act(action="set_value", window=rig.handles["form"], automation_id="pw", value="x").success
    assert rig.actor.performed == []


def test_the_controller_checks_the_live_state_again_and_refuses_a_control_that_turned_into_a_password_field(rig):
    from computer_util import approved
    h = rig.handles["form"]
    plan = rig.controller.plan_ui_act("set_value", window=h, automation_id="name", value="x")
    rig.actor._trees[h] = el("0", "Einstellungen", "Window", children=[el("0.0", "Name", "Edit", automation_id="name", is_password=True)])
    with approved(rig.engine, plan):
        with pytest.raises(ComputerError) as exc:
            rig.controller.execute(plan)
    assert exc.value.code is ErrorCode.BLOCKED_TARGET and rig.actor.performed == []


@pytest.mark.parametrize("key", ["term", "bank"])
def test_protected_windows_are_refused_and_not_even_read(rig, key):
    out = rig.act(action="set_value", window=rig.handles[key], automation_id="name", value="x")
    assert not out.success and rig.actor.performed == [] and rig.actor.calls == [] and rig.reader.calls == [] and rig.prompts.requests == []


def test_own_blocked_titles_and_processes_apply(tmp_path):
    r = make_rig(tmp_path, blocked_titles=("einstellungen",))
    assert not r.act(action="toggle", window=r.handles["form"], automation_id="news").success and r.actor.performed == [] and r.prompts.requests == []


# ---- Notaus, Budget, Rate ---------------------------------------------------------------------------------------------------------------------
def test_the_computer_halt_stops_actions_until_resume(rig):
    h = rig.handles["form"]
    rig.controller.halt("test")
    out = rig.act(action="toggle", window=h, automation_id="news")
    assert not out.success and rig.actor.performed == [] and rig.actor.halted == "test"
    rig.controller.resume()
    assert rig.actor.halted is None and rig.act(action="toggle", window=h, automation_id="news").success


def test_the_global_emergency_stop_refuses_actions(rig):
    h = rig.handles["form"]
    rig.engine.emergency.engage("test", "t")
    out = rig.act(action="toggle", window=h, automation_id="news")
    assert not out.success and "emergency stop" in str(out.error) and rig.actor.performed == [] and rig.actor.calls == []


def test_an_emergency_stop_during_the_action_is_reported_and_the_result_is_not_claimed(rig):
    h = rig.handles["form"]
    rig.actor.on_perform = lambda: rig.controller.halt("waehrend der Aktion")
    out = rig.act(action="toggle", window=h, automation_id="news")
    assert out.success is True and out.output["performed"] is True and out.output["verified"] is None and "emergency stop" in out.output["observed"]


def test_an_emergency_stop_before_the_pattern_call_prevents_it(rig):
    h = rig.handles["form"]
    from computer_util import approved
    plan = rig.controller.plan_ui_act("toggle", window=h, automation_id="news")
    with approved(rig.engine, plan):
        rig.controller.halt("vorher")
        with pytest.raises(ComputerError) as exc:
            rig.controller.execute(plan)
    assert exc.value.code is ErrorCode.FAILSAFE and rig.actor.performed == []


def test_the_session_budget_of_the_engine_counts_actions(tmp_path):
    r = make_rig(tmp_path, budget=SessionBudget(2, 3600))
    h = r.handles["form"]
    assert r.act(action="toggle", window=h, automation_id="news").success and r.act(action="focus", window=h, automation_id="name").success
    third = r.act(action="toggle", window=h, automation_id="news")
    assert not third.success and "Sitzungsbudget" in str(third.error) and len(r.actor.performed) == 2


def test_the_action_rate_limit_applies(tmp_path):
    r = make_rig(tmp_path, max_actions_per_minute=2)
    h = r.handles["form"]
    results = [r.act(action="focus", window=h, automation_id="name").success for _ in range(3)]
    assert results == [True, True, False] and len(r.actor.performed) == 2


def test_provider_failures_are_structured_errors_without_leaking_text(rig):
    h = rig.handles["form"]
    rig.actor.fail_next(RuntimeError("Fehler mit Text: " + SK))
    out = rig.act(action="toggle", window=h, automation_id="news")
    assert not out.success and SK not in dump(out.output) + str(out.error) + rig.blob() and rig.actor.performed == []
    assert rig.act(action="toggle", window=h, automation_id="news").success


def test_the_fake_action_provider_checks_the_fingerprint(rig):
    h = rig.handles["form"]
    with pytest.raises(ComputerError) as exc:
        rig.actor.perform(h, UiTarget("0.1", "Falscher Name", "CheckBox", "news"), UiAction.TOGGLE)
    assert exc.value.code is ErrorCode.TARGET_CHANGED and rig.actor.performed == []
    with pytest.raises(ComputerError):
        rig.actor.perform(h, UiTarget("0.4", "Kennwort", "Edit", "pw"), UiAction.SET_VALUE, "x")
    assert rig.actor.performed == []


# ---- Das Modell ------------------------------------------------------------------------------------------------------------------------------
def test_a_password_state_never_carries_a_value_and_repr_hides_values():
    s = UiState(is_password=True, value="geheim-123", patterns={UiAction.SET_VALUE})
    assert s.value is None and "geheim" not in repr(s)
    t = UiState(value="sichtbar")
    assert "sichtbar" not in repr(t) and "value" not in t.info()
    assert UiState(value="a\nb\tc").value == "a\nb\tc"
    for bad in ("a.b", "0..1", "", "1.x", None, 5):
        with pytest.raises(ComputerError):
            UiTarget(bad, "n", "Button")


# ---- Aufbau: nur UIA-Muster, keine Koordinaten, keine neue Pflichtabhaengigkeit, keine Verdrahtung ausserhalb der Fabrik -----------------------
NEW_MODULES = [COMP / "uia_actions.py", COMP / "providers" / "fake_uia_actions.py", COMP / "providers" / "pywinauto_uia_actions.py", COMP / "providers" / "uia_act_worker.py"]
COORDINATE_OR_INPUT = ("pyautogui", "SendInput", "keybd_event", "mouse_event", "SetCursorPos", "PostMessage", "SendMessage", "WM_CLOSE", "click_input", "type_keys", "send_keys",
                       "pywinauto.keyboard", "pywinauto.mouse", "Application(", "taskkill", "shell=True", "os.system", "TerminateProcess")


@pytest.mark.parametrize("path", NEW_MODULES, ids=lambda p: p.name)
def test_the_new_modules_have_no_coordinate_input_and_no_process_control(path):
    text = path.read_text(encoding="utf-8")
    for token in COORDINATE_OR_INPUT:
        assert token not in text, f"{path.name}: {token}"
    assert not re.search(r"(?m)^\s*(import|from)\s+(socket|urllib|http|requests|ftplib|smtplib|pyautogui|ctypes)\b", text)
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            assert n.func.attr not in {"click", "double_click", "move_mouse", "press", "hotkey", "type_text", "kill", "terminate", "close", "minimize", "maximize"}, f"{path.name}: .{n.func.attr}()"


def test_the_controller_and_tool_reach_actions_only_through_the_provider_interface_and_never_through_the_input_providers():
    ctrl = ast.parse((COMP / "controller.py").read_text(encoding="utf-8"))
    plan_and_run = [n for n in ast.walk(ctrl) if isinstance(n, ast.FunctionDef) and n.name in ("plan_ui_act", "_run_ui_act")]
    assert len(plan_and_run) == 2
    for fn in plan_and_run:
        for n in ast.walk(fn):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                assert n.value not in ("mouse", "keyboard"), fn.name
            if isinstance(n, ast.Attribute):
                assert n.attr not in {"mouse", "keyboard", "_mouse", "_keyboard"}, f"{fn.name}: .{n.attr}"
    for f in COMP.glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Attribute) and n.attr == "ui_actions":
                assert f.name in ("controller.py", "backend.py", "factory.py"), f"{f.name}: .ui_actions outside controller/backend/factory"


def test_no_library_is_imported_eagerly_and_no_dependency_was_added():
    for f in (COMP / "controller.py", COMP / "tools.py", COMP / "factory.py", COMP / "uia_actions.py", COMP / "providers" / "pywinauto_uia_actions.py",
              COMP / "providers" / "fake_uia_actions.py"):
        assert not re.search(r"(?m)^(import|from)\s+(pywinauto|comtypes|pythoncom|win32\w*)\b", f.read_text(encoding="utf-8")), f.name
    worker = (COMP / "providers" / "uia_act_worker.py").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^(import|from)\s+(pywinauto|comtypes)\b", worker) and "from pywinauto" in worker       # nur lazy, innerhalb von PywinautoActor
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject and pyproject.count("pywinauto") == 2
    assert "pywinauto" not in sys.modules or sys.platform == "win32"


def test_the_factory_imports_the_real_provider_only_inside_the_builder():
    tree = ast.parse((COMP / "factory.py").read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("pywinauto" in (getattr(n, "module", "") or "") for n in top)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_create_uia_actions")
    assert any(isinstance(n, ast.ImportFrom) and "pywinauto_uia_actions" in (n.module or "") for n in ast.walk(fn))


def test_the_safety_settings_and_the_wiring_are_untouched():
    boot = (ROOT / "src" / "jarvis" / "bootstrap.py").read_text(encoding="utf-8")
    assert "build_computer" in boot and "ui_act" not in boot and "uia_actions" not in boot
    import tomllib
    cfg = tomllib.loads((ROOT / "config" / "jarvis.toml").read_text(encoding="utf-8"))
    assert cfg["computer"].get("uia_actions_enabled", False) is False and cfg["computer"]["uia_enabled"] is False


def test_an_emergency_stop_between_observing_and_acting_prevents_the_pattern_call(rig):
    h = rig.handles["form"]
    original = rig.actor.read_state

    def read_then_halt(handle, target):
        state = original(handle, target)
        rig.controller._halted = "zwischen Beobachten und Handeln"          # der Notaus kommt genau nach dem ersten Lesen
        return state
    rig.actor.read_state = read_then_halt
    out = rig.act(action="toggle", window=h, automation_id="news")
    assert not out.success and rig.actor.performed == [] and "failsafe" in dump(out.output).lower()
