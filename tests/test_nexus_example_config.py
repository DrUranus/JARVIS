"""config/nexus.example.toml: die Beispielkonfiguration fuer den Windows-Assistenten ist gueltig, startet das Control Center mit echtem Backend und aendert keine Sicherheitseinstellung.
Echter Kern mit Mock-LLM, nur Loopback, kein Netzwerk."""
import tomllib
from pathlib import Path

from jarvis.bootstrap import build_core
from jarvis.config import Settings, load_settings
from jarvis.control_center.launcher import build_server
from test_computer_integration import env_for

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "nexus.example.toml"


def test_example_enables_only_the_assistant_layers_and_touches_no_security_setting(tmp_path):
    raw = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    assert "security" not in raw and "permissions" not in raw                                  # kein Eingriff in Sicherheitsgrenzen
    assert set(raw) == {"control_center", "assistant", "agents", "goals", "journal", "files"}
    s = load_settings(str(CONFIG), env=env_for(tmp_path))
    assert (s.control_center.enabled, s.assistant.enabled, s.agents.enabled, s.agents.router.enabled, s.goals.enabled, s.journal.enabled, s.files.enabled) == (True,) * 7
    d = Settings()
    assert s.security == d.security and s.goals.max_steps == d.goals.max_steps and s.goals.max_attempts_per_step == d.goals.max_attempts_per_step
    assert not (s.computer.enabled or s.browser.enabled or s.coding.enabled or s.research.enabled or s.finance.enabled if hasattr(s, "finance") else False)
    assert s.llm.provider == "mock" and not s.goals.llm_planning and not s.goals.replanning


def test_example_builds_a_real_backend_for_the_control_center(tmp_path):
    s = load_settings(str(CONFIG), env=env_for(tmp_path, JARVIS_JOURNAL_PATH=str(tmp_path / "j.db")))
    core = build_core(s)
    assert core.subsystems["assistant"].available and core.subsystems["goals"].engine is not None and core.subsystems["assistant"].journal is not None
    srv = build_server(s, core)
    srv.start()
    try:
        assert srv.host == "127.0.0.1" and srv.port
    finally:
        srv.stop()
