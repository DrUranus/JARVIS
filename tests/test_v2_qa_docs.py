"""WP08: Vertragstest fuer die V2-QA-Dokumente (docs/V2_TESTPLAN.md, docs/WINDOWS_V2_ABNAHME.md). Reine Textpruefung: nichts wird ausgefuehrt, kein Netzwerk.

Haelt fest: die Abnahmevorlage behauptet keine Ergebnisse, alle Gates G0-G10 sind beschrieben, die Skip-Obergrenzen im Dokument stimmen mit der Baseline-Datei ueberein,
und der Plan aendert keine Workflows."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = (ROOT / "docs" / "V2_TESTPLAN.md").read_text(encoding="utf-8")
ABN = (ROOT / "docs" / "WINDOWS_V2_ABNAHME.md").read_text(encoding="utf-8")
BASE = json.loads((ROOT / "tests" / "support" / "skip_baseline.json").read_text(encoding="utf-8"))


def test_all_release_gates_g0_to_g10_are_defined_once():
    for n in range(11):
        assert len(re.findall(rf"^\| \*\*G{n}\*\* \|", PLAN, re.MULTILINE)) == 1, f"G{n}"
    assert "ohne Zahl gilt das Gate als **offen**" in PLAN


def test_the_acceptance_template_claims_no_results():
    rows = [ln for ln in ABN.splitlines() if ln.startswith("| ") and re.search(r"\|\s*(PASS|FAIL)\s*\|", ln)]
    assert rows == []                                                           # nur PENDING / N/A in der Vorlage
    assert ABN.count("PENDING") >= 40 and "keine Ergebnisse" in ABN


def test_skip_limits_in_the_plan_match_the_baseline_file():
    assert f"Windows **{BASE['windows']['max_skipped']}**" in PLAN and f"Linux **{BASE['linux']['max_skipped']}**" in PLAN
    assert "kein stilles Grün" in PLAN and "nicht bestanden" in PLAN


def test_the_documents_do_not_touch_workflows_or_promise_automation():
    assert "Keine CI-Workflows geändert" in PLAN and "Owner-PR" in PLAN
    assert "kein automatischer Release" in ABN or "kein automatischer Release" in PLAN


def test_interactive_and_runner_evidence_stay_separate():
    assert "ersetzt nicht die interaktive Abnahme" in PLAN or "ersetzen diese Abnahme nicht" in ABN
    for need in ("Hörprobe", "Not-Aus", "Freigabecenter", "UNKNOWN"):
        assert need in ABN
