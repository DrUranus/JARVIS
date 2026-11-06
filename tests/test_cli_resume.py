"""`/resume` (CLI und NEXUS-Chat): unterbrochene Aufgaben auflisten und NUR auf ausdruecklichen Befehl fortsetzen.

Echter Kern (build_core, Mock-LLM, echte GoalEngine, echtes Journal in tmp_path), kein Netzwerk. Der Befehl laeuft ueber denselben Slash-Weg wie jede andere Eingabe
(GuiController -> cli.run_command); Rueckfragen stellt der Bestaetigungskanal der PermissionEngine, nichts wird ohne Antwort ausgefuehrt."""
import ast
from pathlib import Path

import pytest

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.interface.cli import run_command
from jarvis.permissions import ConfirmationChoice
from jarvis.permissions.confirmation import ScriptedConfirmation
from test_computer_integration import env_for

ROOT = Path(__file__).resolve().parents[1]


def jstep(n, text, status="SUCCEEDED", side=False):
    return {"step_id": f"s{n}", "status": status, "text": text, "side_effect": side}


def make(tmp_path, **extra):
    env = env_for(tmp_path, JARVIS_AGENTS_ENABLED="true", JARVIS_GOALS_ENABLED="true", JARVIS_ASSISTANT_ENABLED="true", JARVIS_JOURNAL_ENABLED="true",
                  JARVIS_JOURNAL_PATH=str(tmp_path / "j.db"), **extra)
    settings = load_settings(env=env)
    core = build_core(settings)
    return core, settings


def store(core):
    return core.subsystems["assistant"].journal.store


def cmd(core, settings, line):
    return run_command(core, line, settings, lambda _t: None, lambda _p: "")


def test_resume_lists_interrupted_work_and_starts_nothing(tmp_path):
    core, st = make(tmp_path)
    store(core).record("goal", "g-old", "RUNNING", "Bericht schreiben", steps=[jstep(1, "lese Datei"), jstep(2, "schreibe Datei", "PENDING", True)])
    store(core).record("goal", "g-done", "SUCCEEDED", "fertig", steps=[jstep(1, "x")])
    before = list(core.subsystems["goals"].engine.list())
    out = cmd(core, st, "/resume")
    assert "g-old" in out and "Bericht schreiben" in out and "g-done" not in out
    assert "/resume <id>" in out and "neue Bestätigung" in out
    assert list(core.subsystems["goals"].engine.list()) == before                  # Auflisten startet nichts


def test_resume_without_journal_or_assistant_says_why(tmp_path):
    env = env_for(tmp_path)
    core = build_core(load_settings(env=env))
    out = run_command(core, "/resume", load_settings(env=env), lambda _t: None, lambda _p: "")
    assert "nicht" in out.lower() and "assistant" in out.lower()


def test_resume_unknown_and_not_interrupted_are_refused(tmp_path):
    core, st = make(tmp_path)
    store(core).record("goal", "g-done", "SUCCEEDED", "fertig", steps=[jstep(1, "x")])
    assert "unknown_task" in cmd(core, st, "/resume g-nope")
    assert "not_interrupted" in cmd(core, st, "/resume g-done")


def test_resume_blocked_by_emergency_stop(tmp_path):
    core, st = make(tmp_path)
    store(core).record("goal", "g-old", "RUNNING", "Bericht", steps=[jstep(1, "lese Datei", "PENDING")])
    core.permissions.emergency.trigger("test")
    assert core.permissions.emergency.engaged
    out = cmd(core, st, "/resume g-old")
    assert "emergency_stop" in out or "Notaus" in out
    assert not [g for g in core.subsystems["goals"].engine.list()]


def test_side_effect_step_needs_a_new_confirmation_and_deny_is_default(tmp_path):
    core, st = make(tmp_path)
    store(core).record("goal", "g-old", "RUNNING", "Bericht", steps=[jstep(1, "lese Datei"), jstep(2, "schreibe Datei", "PENDING", True)])
    scripted = ScriptedConfirmation([])                                            # keine Antwort -> DENY
    core.permissions.set_confirmation_provider(scripted, source="test")
    out = cmd(core, st, "/resume g-old")
    assert "confirmation_denied" in out or "DECLINED" in out
    assert len(scripted.requests) == 1 and "schreibe Datei" in scripted.requests[0].reason
    assert not [g for g in core.subsystems["goals"].engine.list()]                # nichts gestartet


def test_resume_after_confirmation_creates_one_goal_and_skips_done_steps(tmp_path):
    core, st = make(tmp_path)
    store(core).record("goal", "g-old", "RUNNING", "lese Datei und schreibe Datei", steps=[jstep(1, "lese Datei"), jstep(2, "schreibe Datei", "PENDING", False)])
    out = cmd(core, st, "/resume g-old")
    goals = core.subsystems["goals"].engine.list()
    assert len(goals) == 1 and goals[0].goal_id in out and "ohne erneut: 1" in out
    assert store(core).get("goal", "g-old").status == "RESUMED"


def test_resume_is_only_reachable_through_the_explicit_command():
    users = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "src" / "jarvis").rglob("*.py") if "ResumeManager" in p.read_text(encoding="utf-8"))
    assert users == ["src/jarvis/interface/cli.py", "src/jarvis/journal/__init__.py", "src/jarvis/journal/resume.py"]      # nichts anderes (auch nicht bootstrap) ruft die Wiederaufnahme auf
    cli = (ROOT / "src" / "jarvis" / "interface" / "cli.py").read_text(encoding="utf-8")
    assert '"/resume"' in cli and cli.count("manager.resume(") == 1
