"""V2-Vorbereitung: prueft NUR LESEND, dass alle V2-Funktionen im ausgelieferten Standard AUS sind und dass die Sicherheitswaechter intakt sind. Plattformunabhaengig (Linux und Windows).
Es installiert nichts, schreibt nur in ein temporaeres Verzeichnis, aendert weder Konfiguration noch Rechte noch Git. Exit 0 = alles im Standard aus und Waechter in Ordnung.

    python scripts/v2/verify_v2_defaults.py              # Code-Standardwerte + config/jarvis.toml, Umgebung wird ignoert
    python scripts/v2/verify_v2_defaults.py --effective  # zusaetzlich: was die AKTUELLEN Umgebungsvariablen einschalten (nur Anzeige)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

FLAGS = {"agents.enabled": lambda s: s.agents.enabled, "agents.quality_gate": lambda s: s.agents.quality_gate, "agents.agent_budgets_enabled": lambda s: s.agents.agent_budgets_enabled,
         "agents.artifacts": lambda s: s.agents.artifacts, "goals.enabled": lambda s: s.goals.enabled, "goals.plan_analysis": lambda s: s.goals.plan_analysis,
         "goals.replanning": lambda s: s.goals.replanning, "business.enabled": lambda s: s.business.enabled, "business.strategist": lambda s: s.business.strategist,
         "finance.enabled": lambda s: s.finance.enabled, "research.enabled": lambda s: s.research.enabled, "self_improvement.enabled": lambda s: s.self_improvement.enabled,
         "control_center.enabled": lambda s: s.control_center.enabled, "assistant.enabled": lambda s: s.assistant.enabled, "journal.enabled": lambda s: s.journal.enabled,
         "computer.enabled": lambda s: s.computer.enabled, "browser.enabled": lambda s: s.browser.enabled, "coding.enabled": lambda s: s.coding.enabled,
         "files.enabled": lambda s: s.files.enabled, "office.enabled": lambda s: s.office.enabled}


def _run(args: list[str]) -> tuple[int, str]:
    p = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr).strip().splitlines()[-1] if (p.stdout + p.stderr).strip() else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--effective", action="store_true", help="auch die Wirkung der aktuellen Umgebungsvariablen anzeigen")
    a = ap.parse_args(argv)
    from jarvis.config import Settings, load_settings
    report: dict[str, object] = {"platform": sys.platform, "python": sys.version.split()[0], "checks": {}}
    bad: list[str] = []
    shipped = load_settings(ROOT / "config" / "jarvis.toml", env={})
    for name, get in FLAGS.items():
        for label, settings in (("code", Settings()), ("toml", shipped)):
            if get(settings):
                bad.append(f"{name} ist im {label}-Standard AN")
    report["flags_checked"] = len(FLAGS)
    if shipped.finance.paper_trading_only is not True or shipped.security.audit_strict is not True:
        bad.append("Sicherheitsstandard veraendert (paper_trading_only / audit_strict)")
    from jarvis.bootstrap import build_core
    with tempfile.TemporaryDirectory() as tmp:
        env = {"JARVIS_WORKSPACE": str(Path(tmp) / "ws"), "JARVIS_LOG_DIR": str(Path(tmp) / "logs"), "JARVIS_MEMORY_PATH": str(Path(tmp) / "m.db"), "JARVIS_SECURITY_CONFIRMATION": "deny"}
        (Path(tmp) / "ws").mkdir()
        core = build_core(load_settings(ROOT / "config" / "jarvis.toml", env=env))
        agents = core.subsystems.get("agents")
        if getattr(agents, "available", False):
            bad.append("die Agentenschicht ist im Standard aktiv")
        for name in ("goals", "self_improvement", "business", "finance", "research"):
            sub = core.subsystems.get(name)
            if getattr(sub, "available", False):
                bad.append(f"Subsystem {name} ist im Standard aktiv")
        report["default_subsystems_available"] = sorted(n for n, s in core.subsystems.items() if getattr(s, "available", False) is True)
        for h in list(__import__("logging").getLogger("jarvis").handlers):                     # Log-Datei freigeben (Windows kann offene Dateien nicht loeschen)
            h.close()
    code, last = _run(["-m", "tests.support.protected_manifest", "--check"])
    report["checks"]["protected_manifest"] = {"exit": code, "last_line": last}                # nur Bericht: eine Abweichung ist Sache des Owners (N3-D)
    code2, last2 = _run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_v21_bootstrap_wiring.py", "tests/test_protected_files.py"])
    report["checks"]["wiring_and_n3"] = {"exit": code2, "last_line": last2}
    if a.effective:
        import os
        eff = load_settings(ROOT / "config" / "jarvis.toml", env=dict(os.environ))
        report["enabled_by_environment"] = sorted(n for n, g in FLAGS.items() if g(eff))
    report["deviations"] = bad
    report["ok"] = not bad and code == 0 and code2 == 0
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
