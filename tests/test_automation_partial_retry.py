"""Regression: a partial technical report may retry only with verified CI and bounded approval."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("jarvis_automation_under_test", ROOT / ".github/automation/jarvis_automation.py")
automation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(automation)


class Config:
    halted = False
    auto_continue_enabled = True
    max_chain = 30
    max_per_day = 30


def state(**overrides):
    result = {
        "status": "partial", "merged": True, "ci_gated": True,
        "ci": {"result": "success"},
        "chain": {"auto_continue": True, "index": 1, "budget": 30,
                  "item_id": "cc-windows-smoke", "attempt": 1},
        "report": {"status": "partial", "next_action": "needs_human",
                   "pr_url": "https://github.com/DrUranus/JARVIS/pull/171",
                   "tests": [{"name": "smoke", "result": "passed"}],
                   "acceptance": [{"criterion": 1, "result": "awaiting_ci"},
                                  {"criterion": 2, "result": "met"},
                                  {"criterion": 3, "result": "met"},
                                  {"criterion": 4, "result": "not_met"}]},
    }
    result.update(overrides)
    return result


def decide(s, *, approved=True, max_attempts=2):
    items = [{"id": "cc-windows-smoke", "approved": approved,
              "max_attempts": max_attempts, "task": "Validate on Windows"}]
    return automation.decide_followup(s, Config(), {"labels": []}, items=items,
                                      done=set(), day_count=0, branch_exists=True)


def test_approved_partial_retries_once_without_claiming_acceptance():
    plan, _ = decide(state())
    assert plan and plan["retry"] and plan["attempt"] == 2
    assert plan["item"]["id"] == "cc-windows-smoke"
    assert state()["report"]["acceptance"][-1]["result"] == "not_met"


def test_partial_retry_is_bounded():
    assert decide(state(chain={**state()["chain"], "attempt": 2}))[0] is None
    assert decide(state(), approved=False)[0] is None
    assert decide(state(), max_attempts=1)[0] is None


def test_partial_retry_requires_green_merged_ci_and_tests():
    assert decide(state(merged=False))[0] is None
    assert decide(state(ci={"result": "failure"}))[0] is None
    assert decide(state(ci_gated=False))[0] is None
    assert decide(state(report={**state()["report"], "tests": [{"name": "smoke", "result": "failed"}]}))[0] is None


def test_partial_retry_respects_stop_and_budget():
    assert decide(state(chain={**state()["chain"], "index": 30}))[0] is None
    assert decide(state(followup={"started": True}))[0] is None
