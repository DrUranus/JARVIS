"""Wiederaufnahme des Merge-Gates nach der CI (Workflow jarvis-gate-resume.yml, Code des Standard-Branches).

Ein pr-tests-Lauf, den das Gate mit GITHUB_TOKEN per workflow_dispatch startet, loest kein workflow_run-Ereignis aus; der Zeitplan laeuft nur unregelmaessig.
Dieser Lauf wartet darum (begrenzt) auf die Pflichtpruefungen genau eines Commits und stoesst danach das Gate genau einmal an (workflow_dispatch ist von der
GITHUB_TOKEN-Regel ausgenommen). Er entscheidet nichts: Freigabe, Commit-Pruefung, Merge und Not-Aus bleiben allein im Gate. Das Gate startet diesen Lauf je Kopf
hoechstens einmal (ci_dispatched) und nie sich selbst; es gibt keine Rekursion.
"""
from __future__ import annotations

import re
import sys
import time
from typing import Any, Callable

import jarvis_automation as ja
import merge_gate as mg

POLL_SECONDS, MAX_TRIES = 60, 65                  # hoechstens 65 Minuten warten (Windows-Suite ~25 Minuten); Workflow-Limit 75 Minuten
SHA_RE = re.compile(r"[0-9a-f]{40}")
GATE_WORKFLOW = "jarvis-merge-gate.yml"


def wait_for_checks(api: Any, sha: str, sleep: Callable[[float], None] = time.sleep, tries: int = MAX_TRIES) -> str:
    """'done', sobald beide Pflichtpruefungen der GitHub-Actions-App fuer genau diesen Commit abgeschlossen sind (gleich mit welchem Ergebnis), sonst 'timeout'."""
    for attempt in range(tries):
        runs = [r for r in mg.check_runs(api, sha) if (r.get("app") or {}).get("slug") == mg.CHECK_APP and r.get("head_sha") == sha]
        by_name = mg.latest_by_name(runs)
        if all(n in by_name and by_name[n].get("status") == "completed" for n in mg.REQUIRED_CHECKS):
            return "done"
        if attempt + 1 < tries:
            sleep(POLL_SECONDS)
    return "timeout"


def resume(api: Any, ref: str, sha: str, sleep: Callable[[float], None] = time.sleep) -> str:
    """Wartet auf die Pflichtpruefungen und startet das Gate genau einmal (auch nach Zeitueberschreitung: dann berichtet es den Stand). Kein erneuter Versuch."""
    outcome = wait_for_checks(api, sha, sleep)
    api.dispatch_workflow(GATE_WORKFLOW, ref, {})
    return outcome


def main(argv: list[str], env: dict[str, str], api: Any = None, sleep: Callable[[float], None] = time.sleep) -> int:
    cfg = ja.Config(env)
    sha = env.get("RESUME_SHA", "")
    if not SHA_RE.fullmatch(sha):
        print("::error::RESUME_SHA ist kein vollstaendiger Commit-Hash.")
        return 1
    if cfg.halted:
        ja.log("Automatisierung angehalten (JARVIS_AUTOMATION_HALT): kein Gate-Anstoss.")
        return 0
    try:
        outcome = resume(api or ja._api(cfg, env), cfg.default_branch, sha, sleep)
    except ja.AutomationError as exc:
        print(f"::error::{exc}")
        return 1
    ja.log(f"Pflichtpruefungen fuer {sha[:12]}: {'abgeschlossen' if outcome == 'done' else 'Zeitlimit erreicht'}; Gate angestossen.")
    return 0


if __name__ == "__main__":
    import os

    sys.exit(main(sys.argv, dict(os.environ)))
