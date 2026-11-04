"""coding-llm-edits: the model drafts edits (action `propose`). Off by default, only in the confirmed workspace, never in the JARVIS repository,
nothing is written by `propose`; every drafted edit is applied through `write` (hash-guarded, confirmed one by one). Fake LLM, no network."""
import json

import pytest

from coding_util import CALC, ONCE, PYPROJECT, SESSION, TEST_CALC, Y, make_rig
from jarvis.config import CodingSettings, load_settings
from jarvis.llm.base import LLMProvider, LLMResponse
from test_coding_controller import JARVIS_FILES, code, level, sha

FIX = {"edits": [{"path": "calc.py", "old_text": "return a - b", "new_text": "return a + b"}]}


class FakeLLM(LLMProvider):
    name = "fakellm"

    def __init__(self, reply=None):
        self.requests = []
        self.reply = json.dumps(FIX) if reply is None else reply

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(self.reply if isinstance(self.reply, str) else json.dumps(self.reply))


def rig(tmp_path, llm, answers=None, **kw):
    kw.setdefault("llm_edits", True)
    r = make_rig(tmp_path, answers if answers is not None else [ONCE] * 20, llm=llm, **kw)
    r.start()
    return r


def baseline(r):
    return r.run(action="test")


def propose(r, **kw):
    return r.run(action="propose", goal="fix add", paths="calc.py", **kw)


# ---- off by default ---------------------------------------------------------------------------------------------------------------------
def test_default_is_off_and_config_is_validated():
    assert CodingSettings().llm_edits is False and load_settings(env={}).coding.llm_edits is False
    assert load_settings(env={"JARVIS_CODING_LLM_EDITS": "true"}).coding.llm_edits is True
    for bad in (0, 11):
        with pytest.raises(Exception):
            load_settings(env={"JARVIS_CODING_LLM_EDITS_MAX": str(bad)})


def test_disabled_refuses_without_calling_the_llm_or_asking(tmp_path):
    llm = FakeLLM()
    r = make_rig(tmp_path, [ONCE] * 5, llm=llm)  # llm_edits default False
    r.start()
    n = len(r.prompts.requests)
    assert code(propose(r)) == "disabled" and llm.requests == [] and len(r.prompts.requests) == n


def test_no_confirm_rule_without_the_switch_and_one_with_it(tmp_path):
    assert "coding-baseline-propose-confirm" not in {x.id for x in make_rig(tmp_path / "a", []).engine.policy.rules}
    r = make_rig(tmp_path / "b", [], llm_edits=True, confirm_llm_each_time=False)
    assert "coding-baseline-propose-confirm" in {x.id for x in r.engine.policy.rules}  # not switchable off


# ---- workspace only, never the JARVIS repository --------------------------------------------------------------------------------------------
def test_never_in_the_jarvis_repository(tmp_path):
    llm = FakeLLM()
    r = make_rig(tmp_path, [ONCE] * 10, llm=llm, files=JARVIS_FILES, llm_edits=True)
    r.start(); r.run(action="test")
    out = r.run(action="propose", goal="g", paths="src/jarvis/core.py")
    assert code(out) == "blocked" and llm.requests == []


def test_paths_must_stay_in_workspace_and_protected_files_are_never_sent(tmp_path):
    llm = FakeLLM()
    r = rig(tmp_path, llm, files={"pyproject.toml": PYPROJECT, "calc.py": CALC, ".env": "A=1", "tests/test_calc.py": TEST_CALC})
    baseline(r)
    assert code(r.run(action="propose", goal="g", paths="../x.py")) == "path_denied"
    assert code(r.run(action="propose", goal="g", paths=".env")) == "protected_path"
    assert code(r.run(action="propose", goal="g", paths="")) == "invalid_input"
    assert llm.requests == []


def test_needs_a_connected_llm_and_a_baseline_test_run(tmp_path):
    r = rig(tmp_path, None)
    baseline(r)
    assert code(propose(r)) == "llm_unavailable"
    llm = FakeLLM()
    r2 = rig(tmp_path / "b", llm)
    assert code(propose(r2)) == "invalid_input"  # no test run yet: the state before the change is unknown
    assert llm.requests == []


# ---- proposal: asked, redacted, validated, never applied ----------------------------------------------------------------------------------
def test_propose_asks_each_time_shows_provider_and_writes_nothing(tmp_path):
    llm = FakeLLM()
    r = rig(tmp_path, llm, [ONCE, ONCE, SESSION, SESSION])
    baseline(r)
    out = propose(r)
    assert out.success and level(out) is Y
    q = r.prompts.requests[-1]
    assert q.action == "propose" and not q.session_allowed and "fakellm" in q.to_text() and "calc.py" in q.to_text()
    assert r.provider.calls_named("write_file") == [] and r.provider.text(str(r.file("calc.py"))) == CALC
    (e,) = out.output["edits"]
    assert e["path"] == "calc.py" and e["new_text"] == "return a + b" and e["expected_sha256"] == sha(CALC) and e["applied"] is False
    assert isinstance(out.output["tests_before"]["passed"], bool) and out.output["untrusted_content"]
    assert "DATA" in llm.requests[0].messages[0].content


def test_secrets_are_redacted_before_sending_and_secret_edits_dropped(tmp_path):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
    reply = {"edits": [{"path": "calc.py", "old_text": "return a - b", "new_text": f'return "{secret}"'}]}
    llm = FakeLLM(reply)
    r = rig(tmp_path, llm, files={"pyproject.toml": PYPROJECT, "calc.py": CALC + f'KEY = "{secret}"\n', "tests/test_calc.py": TEST_CALC})
    baseline(r)
    out = propose(r)
    assert out.success and out.output["edits"] == [] and out.output["rejected"]
    assert secret not in "\n".join(m.content for m in llm.requests[0].messages) and secret not in str(out) and secret not in r.audit_blob()


@pytest.mark.parametrize("reply", [
    "not json", "[]", {"edits": "x"}, {"edits": [{"path": "other.py", "old_text": "a", "new_text": "b"}]},
    {"edits": [{"path": "calc.py", "old_text": "nonexistent", "new_text": "b"}]},
    {"edits": [{"path": "calc.py", "old_text": "a", "new_text": "b"}]},                       # not unique
    {"edits": [{"path": "../x.py", "old_text": "a", "new_text": "b"}]},
    {"edits": [{"path": "calc.py", "old_text": "return a - b", "new_text": 5}]},
    {"edits": [{"path": "calc.py", "old_text": "return a - b", "new_text": "x\x00"}]},
    {"edits": [{"path": "calc.py", "content": "all new", "old_text": "", "new_text": ""}]}])
def test_unusable_or_out_of_scope_model_output_yields_no_edit(tmp_path, reply):
    r = rig(tmp_path, FakeLLM(reply))
    baseline(r)
    out = propose(r)
    assert out.success and out.output["edits"] == [] and r.provider.calls_named("write_file") == []


def test_at_most_llm_edits_max_proposals(tmp_path):
    many = {"edits": [{"path": "calc.py", "old_text": "return a - b", "new_text": "return a + b"}] * 4}
    r = rig(tmp_path, FakeLLM(many), llm_edits_max=2)
    baseline(r)
    assert len(propose(r).output["edits"]) <= 2


def test_json_in_a_code_fence_is_accepted(tmp_path):
    r = rig(tmp_path, FakeLLM("```json\n" + json.dumps(FIX) + "\n```"))
    baseline(r)
    assert len(propose(r).output["edits"]) == 1


# ---- applying: hash-guarded, one confirmation per edit, tests before and after ---------------------------------------------------------------
def test_applying_needs_its_own_confirmation_even_after_a_session_grant(tmp_path):
    r = rig(tmp_path, FakeLLM(), [ONCE, ONCE, SESSION, SESSION, SESSION, SESSION])
    baseline(r)
    (e,) = propose(r).output["edits"]
    kw = dict(action="write", path=e["path"], mode="replace", old_text=e["old_text"], new_text=e["new_text"], expected_sha256=e["expected_sha256"])
    out = r.run(**kw)
    assert out.success and out.permission.scope.value == "once"
    assert r.prompts.requests[-1].action.startswith("write.") and not r.prompts.requests[-1].session_allowed
    assert "return a + b" in r.provider.text(str(r.file("calc.py")))


def test_a_file_that_changed_since_the_proposal_is_not_overwritten(tmp_path):
    r = rig(tmp_path, FakeLLM())
    baseline(r)
    (e,) = propose(r).output["edits"]
    changed = CALC + "# edited meanwhile\n"
    r.provider.put(str(r.file("calc.py")), changed)
    out = r.run(action="write", path="calc.py", mode="replace", old_text=e["old_text"], new_text=e["new_text"], expected_sha256=e["expected_sha256"])
    assert code(out) == "file_changed" and r.provider.text(str(r.file("calc.py"))) == changed


def test_changes_report_tests_before_and_after_honestly(tmp_path):
    r = rig(tmp_path, FakeLLM())
    baseline(r)
    rep = r.ok(action="changes")["tests_report"]
    assert rep["before"] is not None and rep["after"] == "not_run"
    (e,) = propose(r).output["edits"]
    r.ok(action="write", path="calc.py", mode="replace", old_text=e["old_text"], new_text=e["new_text"], expected_sha256=e["expected_sha256"])
    assert r.ok(action="changes")["tests_report"]["after"] == "not_run"  # the change is not yet tested
    r.run(action="test")
    rep = r.ok(action="changes")["tests_report"]
    assert rep["before"]["command"] and rep["after"] != "not_run" and "passed" in rep["after"]


def test_llm_failure_is_reported_safely(tmp_path):
    class Boom(FakeLLM):
        def complete(self, request):
            raise RuntimeError("api failed token=abc123456789")
    r = rig(tmp_path, Boom())
    baseline(r)
    out = propose(r)
    assert code(out) == "backend_error" and "abc123456789" not in out.error
