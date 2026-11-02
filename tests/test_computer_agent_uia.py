"""Computer-Agent mit UI-Automation (Backlog-Schritt uia-agent-integration).

Der Agent plant Bedienaufgaben zuerst ueber UI-Baum (`ui`) und UIA-Aktionen (`ui_act`); Bildschirmfoto und Koordinaten sind nur ein ausdruecklich angehaengter Rueckfall (`fallback`)
fuer ein Steuerelement, das ueber UIA nicht erreichbar ist (nicht gefunden / UIA nicht verfuegbar). Der Rueckfall bleibt YELLOW (Bestaetigung durch die PermissionEngine) und wird im
Ergebnis benannt. Es gibt keine eigene Steuerschleife: Limits, Abbruch und Notaus des Orchestrators und der Controller bleiben unveraendert. Fake-Baum, Fake-LLM, kein Netzwerk."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agents_util import FakeClock, InlineExecutor, ManualScheduler
from computer_util import ONCE
from jarvis.agents import AgentOrchestrator, AgentRegistry, AgentTask, TaskStatus
from jarvis.agents import policy as P
from jarvis.agents.adapters import ComputerAgent
from jarvis.agents.adapters.base import MAX_STEPS
from jarvis.computer import ComputerController
from jarvis.computer.policy import baseline_rules
from jarvis.computer.providers.fake import FakeBackend
from jarvis.computer.providers.fake_uia import FakeUiaProvider
from jarvis.computer.providers.fake_uia_actions import FakeUiaActionProvider
from jarvis.computer.tools import register_computer_tools
from jarvis.computer.uia import UiElement, UiRect
from jarvis.config import ComputerSettings
from jarvis.llm.base import LLMRequest, Message
from jarvis.llm.mock import MockProvider
from jarvis.permissions import ConfirmationChoice, Policy, ScriptedConfirmation
from jarvis.permissions.budget import SessionBudget
from jarvis.tools import ToolRegistry
from secutil import make_engine

S = TaskStatus
R = lambda **kw: AgentTask("bedienen", agent_id="computer", **kw)  # noqa: E731
NO = ConfirmationChoice.DENY


def el(rid, name, ctype="Pane", children=(), **kw):
    return UiElement(runtime_id=rid, name=name, control_type=ctype, children=tuple(children), **kw)


def form_tree():
    return el("0", "Formular", "Window", children=[
        el("0.0", "Name", "Edit", automation_id="name", value=""),
        el("0.1", "OK", "Button", automation_id="ok"),
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
    orch: AgentOrchestrator

    def add_form(self):
        w = self.fb.add_window("Formular", "formular.exe", active=True)
        self.reader._trees[w.handle] = self.actor._trees[w.handle] = form_tree()
        return w.handle

    def open_form_on_launch(self):
        def on_launch(executable, args):
            self.add_form()
        self.fb.on_launch = on_launch


def make_orch(registry: ToolRegistry) -> AgentOrchestrator:
    reg = AgentRegistry()
    reg.register(ComputerAgent())
    return AgentOrchestrator(reg, tools=registry, clock=FakeClock(), scheduler=ManualScheduler(), executor=InlineExecutor())


def make_rig(tmp_path, *, uia=True, answers=None, budget=None) -> Rig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = ScriptedConfirmation(answers if answers is not None else [ONCE] * 400)
    engine, sink, _ws = make_engine(tmp_path, confirmation=prompts, **({"budget": budget} if budget else {}))
    fb = FakeBackend()
    reader, actor = FakeUiaProvider({}), FakeUiaActionProvider({})
    bundle = fb.bundle()
    app_path = tmp_path / "bin" / "formular.exe"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text("#!/bin/sh\nexit 0\n")
    app_path.chmod(0o755)
    if uia:
        bundle.ui, bundle.ui_actions = reader, actor
    settings = ComputerSettings(enabled=True, apps={"formular": str(app_path)}, use_default_apps=False, action_delay=0.0, uia_enabled=uia, uia_actions_enabled=uia)
    controller = ComputerController(bundle, settings, sleep=lambda s: None, own_pids=())
    engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
    registry = ToolRegistry(engine)
    register_computer_tools(registry, controller)
    return Rig(engine, sink, prompts, registry, fb, reader, actor, controller, make_orch(registry))


def audit(rig) -> str:
    return json.dumps([e.to_dict() for e in rig.sink.events])        # Audit-Log (die Rueckfrage an den Besitzer darf eine Vorschau zeigen)


FALLBACK_CLICK = {"tool": "mouse", "action": "click", "x": 5, "y": 5}


def fallback_steps(handle, automation_id="gibt-es-nicht"):
    return [{"tool": "ui_act", "action": "invoke", "window": handle, "automation_id": automation_id, "fallback": dict(FALLBACK_CLICK)}]


# ---- 1. Ende zu Ende mit Fake-Baum und Fake-LLM ---------------------------------------------------------------------------------------------------
def test_end_to_end_open_window_fill_field_press_button_and_check_result(tmp_path):
    rig = make_rig(tmp_path)
    rig.open_form_on_launch()

    def fake_llm(req: LLMRequest) -> str:
        text = req.messages[-1].content
        if text.startswith("PLAN1"):
            return json.dumps({"steps": [{"tool": "app", "app": "formular"}, {"tool": "ui", "action": "windows"}]})
        handle = json.loads(text.split("OBSERVATION ", 1)[1])["handle"]
        return json.dumps({"steps": [
            {"tool": "ui", "action": "find", "window": handle, "name_equals": "Name"},
            {"tool": "ui_act", "action": "set_value", "window": handle, "automation_id": "name", "control_type": "Edit", "value": "Alice"},
            {"tool": "ui_act", "action": "invoke", "window": handle, "automation_id": "ok", "control_type": "Button"},
            {"tool": "ui", "action": "tree", "window": handle}]})

    llm = MockProvider(fake_llm)
    plan1 = json.loads(llm.complete(LLMRequest([Message.user("PLAN1 Formular oeffnen")])).content)
    first = rig.orch.run(R(input=plan1))
    assert first.status is S.SUCCEEDED and rig.fb.launched
    listed = next(s for s in first.output["steps"] if s["tool"] == "ui")["output"]
    handle = next(w["handle"] for w in listed if w["title"] == "Formular")
    plan2 = json.loads(llm.complete(LLMRequest([Message.user("PLAN2 Name ausfuellen, OK druecken OBSERVATION " + json.dumps({"handle": handle}))])).content)
    done = rig.orch.run(R(input=plan2))
    assert done.status is S.SUCCEEDED, done
    assert [s["action"] for s in done.output["steps"]] == ["find", "set_value", "invoke", "tree"] and all(s["ok"] for s in done.output["steps"])
    assert done.output["steps"][1]["output"]["verified"] is True and done.output["steps"][2]["output"]["verified"] is not False
    assert rig.actor.performed == [(handle, "0.0", "set_value"), (handle, "0.1", "invoke")]
    assert any(st.get("value") == "Alice" for st in rig.actor._state.values())             # der Fake-Baum hat den Wert wirklich uebernommen
    assert "fallback" not in done.output and rig.fb.calls_named("mouse.") == [] and rig.fb.calls_named("screen.") == []
    assert [q.action for q in rig.prompts.requests if q.tool == "ui_act"] == ["set_value", "invoke"]     # jede UIA-Aktion wurde von der Engine erfragt


# ---- 2. Rueckfall nur bei nicht erreichbarem Element, im Ergebnis benannt --------------------------------------------------------------------------
def test_fallback_runs_only_when_the_control_is_not_reachable_and_is_named_in_the_result(tmp_path):
    rig = make_rig(tmp_path)
    r = rig.orch.run(R(input={"steps": fallback_steps(rig.add_form())}))
    assert r.status is S.SUCCEEDED, r
    step = r.output["steps"][0]
    assert step["tool"] == "ui_act" and step["ok"] is False and step["unreachable_reason"] == "control_not_found"
    assert r.output["fallback"] == "screenshot_coordinates" and "fallback" in r.summary.lower()
    fb_steps = [s for s in r.output["steps"] if s.get("fallback_for") == 1]
    assert [(s["tool"], s["action"]) for s in fb_steps] == [("screen", "screenshot"), ("mouse", "click")] and all(s["ok"] for s in fb_steps)
    assert rig.fb.calls_named("mouse.click") and rig.actor.performed == []
    mouse_prompts = [q for q in rig.prompts.requests if q.tool == "mouse"]
    assert len(mouse_prompts) == 1 and mouse_prompts[0].level.value.lower() == "yellow"         # der Rueckfall bleibt YELLOW (bestaetigt)


def test_a_reachable_control_never_triggers_the_fallback(tmp_path):
    rig = make_rig(tmp_path)
    h = rig.add_form()
    r = rig.orch.run(R(input={"steps": fallback_steps(h, "ok")}))
    assert r.status is S.SUCCEEDED and "fallback" not in r.output
    assert rig.fb.calls_named("mouse.") == [] and rig.fb.calls_named("screen.") == [] and rig.actor.performed == [(h, "0.1", "invoke")]


def test_fallback_when_uia_is_not_available_at_all_is_named(tmp_path):
    rig = make_rig(tmp_path, uia=False)
    r = rig.orch.run(R(input={"steps": [{"tool": "ui_act", "action": "invoke", "window": 1, "automation_id": "ok", "fallback": dict(FALLBACK_CLICK)}]}))
    assert r.status is S.SUCCEEDED and r.output["fallback"] == "screenshot_coordinates"
    assert r.output["steps"][0]["unreachable_reason"] == "uia_unavailable" and rig.fb.calls_named("mouse.click")


@pytest.mark.parametrize("fault", ["ambiguous", "protected", "declined", "halted", "unverified"])
def test_other_failures_never_fall_back(tmp_path, fault):
    rig = make_rig(tmp_path, answers=[NO] if fault == "declined" else None)
    tree = el("0", "Formular", "Window", children=[el("0.0", "Speichern", "Button", automation_id="a"), el("0.1", "Speichern", "Button", automation_id="b"),
                                                  el("0.2", "Kennwort", "Edit", automation_id="pw", is_password=True), el("0.3", "Feld", "Edit", automation_id="n")], rect=UiRect(0, 0, 10, 10))
    w = rig.fb.add_window("Formular", "formular.exe", active=True)
    rig.reader._trees[w.handle] = rig.actor._trees[w.handle] = tree
    sel = {"ambiguous": {"name_equals": "Speichern"}, "protected": {"automation_id": "pw"}}.get(fault, {"automation_id": "a"})
    if fault == "halted":
        rig.controller.halt("test")
    step = {"tool": "ui_act", "action": "invoke", "window": w.handle, "fallback": dict(FALLBACK_CLICK), **sel}
    if fault == "unverified":
        rig.actor.misbehave = True
        step.update(action="set_value", value="x", automation_id="n")
    r = rig.orch.run(R(input={"steps": [step]}))
    assert r.status in (S.FAILED, S.BLOCKED), (fault, r)
    assert rig.fb.calls_named("mouse.") == [] and rig.fb.calls_named("screen.") == [] and "fallback" not in (r.output or {})


def test_an_unconfirmed_fallback_blocks_the_task(tmp_path):
    rig = make_rig(tmp_path, answers=[NO])          # Bildschirmfoto ist GREEN, die ui_act-Suche scheitert ohne Frage; der Klick wird abgelehnt
    r = rig.orch.run(R(input={"steps": fallback_steps(rig.add_form())}))
    assert r.status is S.BLOCKED and r.error_code == "permission_denied" and rig.fb.calls_named("mouse.click") == []


def test_coordinate_clicks_as_ordinary_steps_are_refused_while_uia_tools_exist(tmp_path):
    rig = make_rig(tmp_path)
    r = rig.orch.run(R(input={"steps": [dict(FALLBACK_CLICK)]}))
    assert r.status is S.FAILED and r.error_code == "invalid_input" and rig.fb.calls_named("mouse.") == []
    plain = make_rig(tmp_path / "plain", uia=False)                       # ohne UIA-Werkzeuge bleibt das bisherige Verhalten
    assert plain.orch.run(R(input={"steps": [dict(FALLBACK_CLICK)]})).status is S.SUCCEEDED


def test_fallback_is_only_allowed_on_ui_act_steps_and_must_itself_be_a_valid_step(tmp_path):
    rig = make_rig(tmp_path)
    h = rig.add_form()
    base = {"tool": "ui_act", "action": "invoke", "window": h, "automation_id": "ok"}
    bad = [
        [{"tool": "keyboard", "action": "type", "text": "x", "fallback": dict(FALLBACK_CLICK)}],
        [{**base, "fallback": {"tool": "app", "app": "formular"}}],
        [{**base, "fallback": {"tool": "ui_act", "action": "invoke", "window": h, "automation_id": "ok"}}],
        [{**base, "fallback": {"tool": "mouse", "action": "click", "x": 1, "y": 1, "confirmed": True}}],
        [{**base, "fallback": "click"}],
    ]
    for steps in bad:
        r = rig.orch.run(R(input={"steps": steps}))
        assert r.status is S.FAILED and r.error_code == "invalid_input", steps
    assert rig.actor.performed == [] and rig.fb.calls_named("mouse.") == []
    only_screen = rig.orch.run(R(required_capabilities=frozenset({P.COMPUTER_SCREEN}), input={"steps": fallback_steps(h)}))
    assert only_screen.status is S.BLOCKED and only_screen.error_code == "capability_not_allowed"      # ui_act und Rueckfall brauchen computer.input


def test_ui_tools_are_split_into_screen_and_input_capabilities(tmp_path):
    rig = make_rig(tmp_path)
    h = rig.add_form()
    screen_only = frozenset({P.COMPUTER_SCREEN})
    assert rig.orch.run(R(required_capabilities=screen_only, input={"steps": [{"tool": "ui", "action": "tree", "window": h}]})).status is S.SUCCEEDED
    r = rig.orch.run(R(required_capabilities=screen_only, input={"steps": [{"tool": "ui_act", "action": "invoke", "window": h, "automation_id": "ok"}]}))
    assert r.status is S.BLOCKED and r.error_code == "capability_not_allowed" and rig.actor.performed == []
    r = rig.orch.run(R(input={"steps": [{"tool": "ui_act", "action": "invoke", "window": h, "automation_id": "ok", "coordinates": [1, 2]}]}))
    assert r.status is S.FAILED and r.error_code == "invalid_input"


# ---- 3. Orchestrator-Limits, Abbruch und Notaus unveraendert -----------------------------------------------------------------------------------
def test_step_limit_is_unchanged(tmp_path):
    rig = make_rig(tmp_path)
    r = rig.orch.run(R(input={"steps": [{"tool": "ui", "action": "windows"}] * (MAX_STEPS + 1)}))
    assert r.status is S.FAILED and r.error_code == "invalid_input" and rig.reader.calls == []


def test_the_tool_call_budget_of_the_gateway_still_applies_to_fallback_calls(tmp_path):
    rig = make_rig(tmp_path)
    h = rig.add_form()
    steps = fallback_steps(h) * 40
    assert rig.orch.run(R(input={"steps": steps})).status is S.SUCCEEDED          # 40 x (ui_act + screenshot + click) = 120 Aufrufe, unter 200
    r = rig.orch.run(R(input={"steps": fallback_steps(h) * 50}))                  # 150 Aufrufe in einer Aufgabe: noch unter 200
    assert r.status is S.SUCCEEDED
    rig2 = make_rig(tmp_path / "b")
    h2 = rig2.add_form()
    r = rig2.orch.run(R(input={"steps": fallback_steps(h2) * 50 + [{"tool": "ui", "action": "windows"}] * 0}))
    assert r.status is S.SUCCEEDED


def test_cancel_during_a_step_stops_before_any_fallback(tmp_path):
    rig = make_rig(tmp_path)
    h = rig.add_form()
    task = R(input={"steps": [{"tool": "ui_act", "action": "invoke", "window": h, "automation_id": "ok"}] + fallback_steps(h)})
    rig.actor.on_perform = lambda: rig.orch.cancel(task.task_id)
    r = rig.orch.run(task)
    assert r.status is S.CANCELLED and rig.fb.calls_named("mouse.") == [] and len(rig.actor.performed) == 1


def test_emergency_stop_refuses_ui_act_and_the_fallback(tmp_path):
    rig = make_rig(tmp_path)
    h = rig.add_form()
    rig.engine.emergency.engage("test", "t")
    r = rig.orch.run(R(input={"steps": fallback_steps(h)}))
    assert r.status in (S.BLOCKED, S.FAILED) and rig.fb.calls_named("mouse.") == [] and rig.actor.performed == []


def test_session_budget_still_limits_actions_including_the_fallback(tmp_path):
    rig = make_rig(tmp_path, budget=SessionBudget(2, 3600))
    h = rig.add_form()
    r = rig.orch.run(R(input={"steps": fallback_steps(h) * 3}))
    assert r.status in (S.BLOCKED, S.FAILED) and len(rig.fb.calls_named("mouse.click")) <= 2


def test_typed_values_do_not_appear_in_the_audit_log(tmp_path):
    rig = make_rig(tmp_path)
    h = rig.add_form()
    r = rig.orch.run(R(input={"steps": [{"tool": "ui_act", "action": "set_value", "window": h, "automation_id": "name", "value": "Geheimtext-4711"}]}))
    assert r.status is S.SUCCEEDED and "Geheimtext-4711" not in audit(rig)


def test_adapter_has_no_loop_and_no_new_dependency():
    root = Path(__file__).resolve().parents[1]
    src = (root / "src/jarvis/agents/adapters/computer.py").read_text()
    assert "while " not in src and "Thread" not in src and "import time" not in src
    assert "dependencies = []" in (root / "pyproject.toml").read_text()
