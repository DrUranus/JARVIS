"""End to end: user input -> core -> planner -> task -> response, plus CLI and bootstrap."""
from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.core import ResponseKind
from jarvis.interface.cli import main, repl
from jarvis.tasks import TaskStatus


def test_user_input_to_task_response(core):
    resp = core.handle("Erstelle ein Python-Programm, das eine CSV-Datei analysiert.")
    assert resp.kind is ResponseKind.PLAN
    task = resp.task
    assert task.status is TaskStatus.WAITING and len(task.subtasks) == 3
    assert core.tasks.open_tasks() == [task]
    assert task.description in resp.text and "1. Anforderungen analysieren" in resp.text


def test_bootstrap_default_settings(tmp_path):
    core = build_core(load_settings(env={"JARVIS_LOG_DIR": str(tmp_path)}))
    assert core.handle("Hallo JARVIS").text == "Hallo. Ich bin bereit."
    assert "echo" in core.tools


def _run_repl(core, lines):
    it = iter(lines)
    out: list[str] = []

    def fake_input(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    repl(core, fake_input, out.append)
    return "\n".join(out)


def test_cli_session(core):
    out = _run_repl(core, ["Hallo", "/tools", "/tasks", "Baue eine Website", "/tasks", "/plan", "/nope", "/reset", "/exit"])
    assert "echo:" in out and "Keine offenen Tasks." in out
    assert "WAITING" in out and "Verwendung: /plan" in out and "Unbekannter Befehl" in out
    assert out.endswith("Bis bald.")


def test_cli_eof_exits_cleanly(core):
    assert "JARVIS" in _run_repl(core, [])


def test_main_reports_config_error(capsys, tmp_path):
    assert main(["-c", str(tmp_path / "missing.toml")]) == 2
    assert "Startfehler" in capsys.readouterr().err
