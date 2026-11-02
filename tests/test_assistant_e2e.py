"""Assistent Ende-zu-Ende (Backlog-Schritt assistant-e2e, Strang A / A9).

Eingabe -> Planung (GoalEngine) -> Router (je Schritt) -> Agenten -> ToolRegistry.execute -> ECHTE PermissionEngine -> Bestaetigung ueber den UI-Vertrag -> Ergebnis ->
Journal -> Vertragsereignisse. Fake-Browser/-Coding/-Computer-Backends, kein Netzwerk, keine echten Aktionen, kein Tk; Linux und Windows gleich."""
from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from agents_util import tool_rig
from jarvis.agents import AgentPlanner
from jarvis.agents.factory import AgentsSubsystem
from jarvis.bootstrap import _routed_agents, build_core
from jarvis.config import AgentRouterSettings, AgentsSettings, AssistantSettings, ConfigError, JournalSettings, Settings, load_settings
from jarvis.core import JarvisCore
from jarvis.goals import GoalEngine, GoalPlanner
from jarvis.goals.factory import GoalsSubsystem
from jarvis.interface import assistant as assistant_module
from jarvis.interface.assistant import RoutingSink, build_assistant
from jarvis.interface.cli import run_command
from jarvis.interface.ui_events import ControllerUiBackend
from jarvis.journal import JournalRecorder, JournalStore
from jarvis.llm.mock import MockProvider
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.audit import AuditEventType
from jarvis.redaction import SecretDetector
from jarvis.ui_contract import FakeClock
from test_computer_integration import env_for

ROOT = Path(__file__).resolve().parents[1]
GOAL = "/goal Analysiere example.com und finde die Öffnungszeiten"


def wait_for(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def cmd(type_, data=None, cid="c1"):
    return {"v": "1.0", "id": cid, "type": type_, "data": data or {}}


class Rig:
    def __init__(self, tmp_path, *, confirmation_timeout_s=30.0):
        self.tr = tool_rig(tmp_path, [])
        orch, reg = self.tr.agents(clock=None, scheduler=None, executor=None)       # real threads: the human answers from another thread
        base = AgentPlanner(reg)
        settings = Settings(assistant=AssistantSettings(enabled=True), agents=AgentsSettings(enabled=True, router=AgentRouterSettings(enabled=True)),
                            journal=JournalSettings(enabled=True, path=str(tmp_path / "journal.db")))
        self.clock = FakeClock()
        sink = RoutingSink()
        agents = AgentsSubsystem("enabled", "", orch, base, reg)
        routed = _routed_agents(settings, agents, sink, self.tr.engine.audit)           # the REAL bootstrap helper: router-backed planner
        planner = GoalPlanner(routed.planner, max_attempts=2)
        engine = GoalEngine(orch, planner, max_steps=20, max_attempts=2, goal_timeout=60, step_timeout=30)
        self.core = JarvisCore(MockProvider(), tools=self.tr.registry)
        self.core.subsystems.update(agents=agents, goals=GoalsSubsystem("enabled", "", engine, planner))
        journal = JournalRecorder(JournalStore(settings.journal.path, max_entries=100, max_steps_per_entry=50, max_text_length=300, max_evidence=5,
                                               detector=SecretDetector()), goals=engine, agents=orch)
        factory = lambda ctl: ControllerUiBackend(ctl, choice_enum=ConfirmationChoice, clock=self.clock, confirmation_timeout_s=confirmation_timeout_s)
        self.sub = build_assistant(settings, self.core, ui_factory=factory, journal=journal, router=routed.router, sink=sink)
        self.core.subsystems["assistant"] = self.sub
        self.ui = self.sub.ui
        self.tr.engine.set_confirmation_provider(self.ui.confirmation_provider, source="test")
        self.answered = []

    def events(self, type_=None):
        evs = self.ui.events_since(0, 1000)
        return [e for e in evs if type_ is None or e["type"] == type_]

    def drive(self, choice, *, until="result", max_answers=50):
        """Plays the human: answers every open question with `choice` until the flow has produced `until`."""
        end = time.monotonic() + 20
        while time.monotonic() < end and len(self.answered) < max_answers:
            if self.events(until):
                return True
            for e in self.ui.snapshot():
                if e["type"] == "confirmation_request" and e["data"]["request_id"] not in self.answered:
                    self.answered.append(e["data"]["request_id"])
                    self.ui.send(cmd("confirm", {"request_id": e["data"]["request_id"], "choice": choice}, cid=f"a{len(self.answered)}"))
            time.sleep(0.01)
        return bool(self.events(until))

    def wait_request(self):
        assert wait_for(lambda: any(e["type"] == "confirmation_request" for e in self.ui.snapshot()))
        return next(e for e in self.ui.snapshot() if e["type"] == "confirmation_request")


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


# ---- Abnahme 1: Ende-zu-Ende ------------------------------------------------------------------------------------------------------------------
def test_end_to_end_input_plan_router_agent_confirmation_result_journal_events(rig):
    ack = rig.ui.send(cmd("submit_text", {"text": GOAL}))
    assert ack["data"]["ok"] is True
    assert rig.drive("allow_once")
    assert wait_for(lambda: any(e["data"]["status"] == "SUCCEEDED" for e in rig.events("task_update")))
    types = [e["type"] for e in rig.events()]
    # Eingabe ... Router ... Bestaetigung ... Ergebnis, in dieser Reihenfolge
    first = {t: types.index(t) for t in ("chat", "routing", "confirmation_request", "confirmation_closed", "task_update", "result")}
    # (die Chat-Ereignisse des Controllers kommen per Pump; ihre Position gegenueber `routing` haengt vom Pump-Zeitpunkt ab, daher nur: vor dem Ergebnis)
    assert first["routing"] < first["confirmation_request"] < first["confirmation_closed"] < first["result"] and first["chat"] < first["result"]
    assert [e["data"]["sender"] for e in rig.events("chat")][0] == "user"
    routing = rig.events("routing")
    assert routing and {r["data"]["agent"] for r in routing} <= {"research", "browser"} and all(r["data"]["source"] == "rules" for r in routing)
    assert {c["data"]["outcome"] for c in rig.events("confirmation_closed")} == {"allow_once"}
    result = rig.events("result")[0]["data"]
    assert result["summary"].startswith("SUCCEEDED") and result["task_id"].startswith("g")
    # Agent -> Werkzeug -> echte Engine: die Seite wurde wirklich (im Fake) geladen, die Engine hat gefragt und auditiert
    assert rig.tr.browser_provider.calls_named("page.goto")
    audited = {e.type for e in rig.tr.sink.events}
    assert {AuditEventType.CONFIRMATION_REQUESTED, AuditEventType.CONFIRMATION_ACCEPTED, AuditEventType.EXECUTION_RESULT, AuditEventType.LLM_ROUTE} <= audited
    # Journal: das Ziel samt Schritten ist gespeichert
    entries = rig.sub.journal.entries(10)
    goal = next(e for e in entries if e.kind == "goal")
    assert goal.status == "SUCCEEDED" and goal.steps
    # jedes Ereignis folgt dem Vertrag, lueckenlos nummeriert
    seqs = [e["seq"] for e in rig.events()]
    assert seqs == list(range(1, len(seqs) + 1))


def test_each_finished_goal_is_published_exactly_once(rig):
    rig.ui.send(cmd("submit_text", {"text": GOAL}))
    assert rig.drive("allow_once")
    for _ in range(5):
        rig.ui.events_since(0)
    assert len(rig.events("result")) == 1
    assert rig.sub.describe()["results_published"] == 1


# ---- Abnahme 2: Ablehnung, Zeitueberschreitung, Notaus ----------------------------------------------------------------------------------------
def test_denial_ends_the_flow_safely_and_nothing_is_executed(rig):
    rig.ui.send(cmd("submit_text", {"text": GOAL}))
    assert rig.drive("deny")
    assert {c["data"]["outcome"] for c in rig.events("confirmation_closed")} == {"denied"}
    assert not rig.tr.browser_provider.calls_named("page.goto")
    status = rig.events("task_update")[-1]["data"]["status"]
    assert status in ("BLOCKED", "FAILED") and rig.events("result")[0]["data"]["summary"].split(":")[0] == status
    assert rig.sub.journal.entries(5)[0].status == status


def test_timeout_without_an_answer_counts_as_denied(tmp_path):
    rig = Rig(tmp_path, confirmation_timeout_s=5.0)
    rig.ui.send(cmd("submit_text", {"text": GOAL}))
    rig.wait_request()
    rig.clock.advance(10)                                            # nobody answers: time passes
    assert wait_for(lambda: any(e["data"]["outcome"] == "timeout" for e in rig.events("confirmation_closed")))
    assert wait_for(lambda: bool(rig.events("result")))
    assert not rig.tr.browser_provider.calls_named("page.goto")
    assert rig.events("task_update")[-1]["data"]["status"] in ("BLOCKED", "FAILED")


def test_detach_closes_the_open_question_as_cancelled_and_denies(rig):
    rig.ui.send(cmd("submit_text", {"text": GOAL}))
    rig.wait_request()
    rig.ui.detach()
    assert any(e["data"]["outcome"] == "cancelled" for e in rig.events("confirmation_closed"))
    assert wait_for(lambda: bool(rig.events("result")))
    assert not rig.tr.browser_provider.calls_named("page.goto")


def test_emergency_stop_ends_the_flow_and_blocks_new_input(rig):
    rig.ui.send(cmd("submit_text", {"text": GOAL}))
    rig.wait_request()
    ack = rig.ui.send(cmd("emergency_stop", cid="n1"))
    assert ack["data"]["ok"] is True
    assert wait_for(lambda: bool(rig.events("result")))
    assert any(e["data"]["outcome"] == "cancelled" for e in rig.events("confirmation_closed"))
    assert not rig.tr.browser_provider.calls_named("page.goto")
    assert rig.events("task_update")[-1]["data"]["status"] != "SUCCEEDED"
    emergency = [e for e in rig.events("emergency") if e["data"]["engaged"]]
    assert emergency and rig.core.permissions.emergency.engaged
    assert rig.ui.send(cmd("submit_text", {"text": GOAL}, cid="c9"))["data"]["code"] == "emergency"       # no new work while the stop is engaged


# ---- Abnahme 3: Standard aus, jede Aktion ueber Registry und Engine (Strukturtests) -------------------------------------------------------------
def test_defaults_are_off(tmp_path):
    s = Settings().assistant
    assert s.enabled is False and s == AssistantSettings()
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_JOURNAL_PATH=str(tmp_path / "j.db"),
                                                JARVIS_JOURNAL_ENABLED="true")))
    sub = core.subsystems["assistant"]
    assert sub.status == "disabled" and sub.ui is None and sub.journal is None and not sub.available
    assert not (tmp_path / "j.db").exists()                                        # journal.enabled alone writes nothing: only the assistant builds it
    assert type(core.permissions.confirmation).__name__ != "UiConfirmationProvider"
    assert "assistant" not in core.permissions.emergency.names()
    assert run_command(core, "/assistant status").startswith("Assistent: deaktiviert")


def test_enabled_by_environment_wires_journal_router_and_adapter_without_starting_anything(tmp_path):
    before = threading.active_count()
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_JOURNAL_ENABLED="true",
                  JARVIS_JOURNAL_PATH=str(tmp_path / "j.db"), JARVIS_SECURITY_CONFIRMATION="cli")
    toml = tmp_path / "c.toml"
    toml.write_text("[agents.router]\nenabled = true\n", encoding="utf-8")                  # the router flag has no environment variable
    core = build_core(load_settings(toml, env=env))
    sub = core.subsystems["assistant"]
    assert sub.status == "enabled" and sub.available and sub.journal is not None and sub.router is not None and sub.goals is not None
    assert type(core.permissions.confirmation).__name__ == "UiConfirmationProvider"          # the engine's provider is the contract's
    assert "assistant" in core.permissions.emergency.names()
    assert threading.active_count() == before                                               # no thread, no timer, nothing runs on its own
    assert core.list_goals() == [] and core.subsystems["agents"].orchestrator.list() == []   # no goal, no task was started
    text = run_command(core, "/assistant status")
    assert text.startswith("Assistent: aktiviert") and "Journal: an" in text and "Router: an" in text
    assert core.list_goals() == []                                                           # /assistant status is read only


def test_confirmation_deny_setting_keeps_the_engine_provider_untouched(tmp_path):
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_SECURITY_CONFIRMATION="deny")
    core = build_core(load_settings(env=env))
    assert core.subsystems["assistant"].status == "enabled" and type(core.permissions.confirmation).__name__ != "UiConfirmationProvider"


def test_assistant_needs_the_agent_layer(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path, JARVIS_ASSISTANT_ENABLED="true")))
    sub = core.subsystems["assistant"]
    assert sub.status == "disabled" and "agents.enabled" in sub.reason and sub.ui is None


def test_router_is_off_without_both_flags():
    base = AgentsSubsystem("enabled", "", object(), object(), object())
    for s in (Settings(assistant=AssistantSettings(enabled=True)), Settings(agents=AgentsSettings(enabled=True, router=AgentRouterSettings(enabled=True)))):
        assert _routed_agents(s, base, lambda t, d: None, None) is base


def test_every_agent_action_runs_through_registry_and_engine(rig):
    rig.ui.send(cmd("submit_text", {"text": GOAL}))
    assert rig.drive("allow_once")
    tool_calls = rig.tr.browser_provider.calls_named("page.goto")
    executed = [e for e in rig.tr.sink.events if e.type is AuditEventType.EXECUTION_RESULT and e.tool == "browser"]
    asked = [e for e in rig.tr.sink.events if e.type is AuditEventType.PERMISSION_REQUESTED and e.tool == "browser"]
    assert tool_calls and executed and len(asked) >= len(executed)                            # every executed browser action was first requested at the engine


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}


def test_the_assistant_module_executes_nothing_and_starts_nothing():
    path = Path(assistant_module.__file__)
    text = path.read_text(encoding="utf-8")
    forbidden = ("jarvis.permissions", "jarvis.tools", "jarvis.computer", "jarvis.browser", "jarvis.coding", "jarvis.files", "jarvis.core")
    assert not [m for m in _imports(path) if m.startswith(forbidden)]
    for word in (".execute(", "create_goal", "run_goal", "Thread(", "Timer(", ".start(", ".resume(", "subprocess", "socket", "requests", "urllib"):
        assert word not in text, word
    assert "daemon" not in text


def test_only_bootstrap_wires_the_assistant_and_the_cli_command_is_read_only():
    for f in (ROOT / "src" / "jarvis").rglob("*.py"):
        if f.name in ("bootstrap.py", "assistant.py", "cli.py"):
            continue
        assert "build_assistant" not in f.read_text(encoding="utf-8"), f.relative_to(ROOT)
    cli = (ROOT / "src" / "jarvis" / "interface" / "cli.py").read_text(encoding="utf-8")
    body = cli[cli.index("def _assistant("):cli.index("def _fmt_goal(")]
    assert "status_text" in body and not any(w in body for w in ("create_goal", "run_goal", ".execute(", "handle(", "sync(", "publish("))


def test_repo_config_does_not_enable_the_assistant():
    text = (ROOT / "config" / "jarvis.toml").read_text(encoding="utf-8")
    assert "[assistant]" not in text
    assert load_settings(env={}).assistant.enabled is False


def test_config_validation_and_environment():
    assert load_settings(env={"JARVIS_ASSISTANT_ENABLED": "true"}).assistant.enabled is True
    for bad in ("0", "601", "-5"):
        with pytest.raises(ConfigError):
            load_settings(env={"JARVIS_ASSISTANT_CONFIRMATION_TIMEOUT_SECONDS": bad})


def test_cli_status_rejects_other_arguments_and_changes_nothing(rig):
    assert run_command(rig.core, "/assistant status").startswith("Assistent: aktiviert")
    assert run_command(rig.core, "/assistant start") == "Verwendung: /assistant status"
    assert rig.core.list_goals() == [] and rig.events("routing") == []
    assert "/assistant" in run_command(rig.core, "/help")
