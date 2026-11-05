"""Tests for GitHub-verified legacy controller recovery."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("automation", Path(__file__).resolve().parents[1] / ".github/automation/jarvis_automation.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Api:
    repo = "DrUranus/JARVIS"
    def __init__(self, merged=True, green=True):
        self.merged, self.green = merged, green
        self.calls = []
    def request(self, method, path):
        self.calls.append(path)
        if "/pulls/" in path:
            return {"merged": self.merged, "merge_commit_sha": "a" * 40,
                    "head": {"sha": "b" * 40}}
        return {"workflow_runs": [{"head_sha": "b" * 40, "name": "pr-tests",
                                  "status": "completed", "conclusion": "success" if self.green else "failure"}]}


def state():
    return {"status": "partial", "followup": {"started": False},
            "chain": {"item_id": "cc-windows-smoke"},
            "report": {"status": "partial", "next_action": "needs_human",
                       "pr_url": "https://github.com/DrUranus/JARVIS/pull/171",
                       "tests": [{"result": "passed"}]}}


def test_verified_legacy_recovery():
    assert mod.verified_legacy_partial_recovery(Api(), state(), 170)


def test_recovery_denies_unmerged_or_red_ci():
    assert not mod.verified_legacy_partial_recovery(Api(merged=False), state(), 170)
    assert not mod.verified_legacy_partial_recovery(Api(green=False), state(), 170)


def test_recovery_denies_untrusted_pr_and_started_followup():
    s = state()
    s["report"]["pr_url"] = "https://github.com/other/repo/pull/171"
    api = Api()
    assert not mod.verified_legacy_partial_recovery(api, s, 170)
    assert api.calls == []
    s = state()
    s["followup"]["started"] = True
    assert not mod.verified_legacy_partial_recovery(Api(), s, 170)


def test_recovery_denies_failed_tests_and_unrelated_status():
    s = state()
    s["report"]["tests"] = [{"result": "failed"}]
    assert not mod.verified_legacy_partial_recovery(Api(), s, 170)
    s = state()
    s["status"] = "completed"
    assert not mod.verified_legacy_partial_recovery(Api(), s, 170)
