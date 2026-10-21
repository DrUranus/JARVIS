"""The adapters end to end: Orchestrator -> agent -> ToolGateway -> ToolRegistry -> PermissionEngine -> controller -> (fake) provider.
The permission engine is the REAL one with scripted answers; every claim about permissions is checked against what the engine saw."""
import pytest

from agents_util import WAIT, FakeAgent, make, task, tool_rig
from jarvis.agents import AgentOutcome, AgentTask, TaskStatus
from jarvis.agents import policy as P
from jarvis.agents.adapters import BrowserAgent, CodingAgent
from jarvis.coding.models import CommandResult
from jarvis.permissions import ConfirmationChoice

ONCE, SESSION, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.ALLOW_SESSION, ConfirmationChoice.DENY
S = TaskStatus
R = lambda **kw: AgentTask("agent job", **kw)  # noqa: E731


# ---- browser agent --------------------------------------------------------------------------------------------------------------------------------------
def test_browser_agent_reads_a_page_and_every_confirmed_step_was_asked_by_the_engine(tmp_path):
    rig = tool_rig(tmp_path, [ONCE, ONCE])
    orch, _ = rig.agents()
    r = orch.run(R(agent_id="browser", input={"steps": [{"action": "start"}, {"action": "goto", "url": "https://example.com/"}, {"action": "text"}]}))
    assert r.status is S.SUCCEEDED and r.summary == "3 step(s) done"
    steps = r.output["steps"]
    assert [s["action"] for s in steps] == ["start", "goto", "text"] and all(s["ok"] for s in steps)
    assert "Opening hours" in steps[2]["output"]["text"]
    assert [q.action for q in rig.prompts.requests] == ["start", "goto"]       # YELLOW steps asked, the GREEN read was not
    assert rig.browser_provider.calls_named("page.goto") and rig.browser.overview()["session"]


def test_a_declined_step_blocks_the_task_and_nothing_further_runs(tmp_path):
    rig = tool_rig(tmp_path, [NO])
    orch, reg = rig.agents()
    r = orch.run(R(agent_id="browser", input={"steps": [{"action": "start"}, {"action": "goto", "url": "https://example.com/"}]}))
    assert r.status is S.BLOCKED and r.error_code == "permission_denied" and "step 1" in r.error
    assert rig.browser_provider.calls_named("provider.start") == [] and len(rig.prompts.requests) == 1
    assert [s["ok"] for s in r.output["steps"]] == [False] and reg.get("browser").status.value == "AVAILABLE"


def test_red_actions_stay_red_when_an_agent_asks(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 6)
    orch, _ = rig.agents()
    orch.run(R(agent_id="browser", input={"steps": [{"action": "start"}]}))
    for url in ("file:///etc/passwd", "javascript:alert(1)", "http://169.254.169.254/", "http://127.0.0.1/"):
        r = orch.run(R(agent_id="browser", input={"steps": [{"action": "goto", "url": url}]}))
        assert r.status is S.BLOCKED and r.error_code == "permission_denied", url
    assert rig.browser_provider.calls_named("page.goto") == []
    assert any(e.type.value == "permission_denied" for e in rig.sink.events)        # audited by the engine, not by the agent layer


def test_capabilities_narrow_what_an_agent_may_do_for_this_task(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 3)
    orch, _ = rig.agents()
    orch.run(R(agent_id="browser", input={"steps": [{"action": "start"}, {"action": "goto", "url": "https://example.com/"}]}))
    n = len(rig.prompts.requests)
    ro = frozenset({P.BROWSER_READ})
    ok = orch.run(R(agent_id="browser", required_capabilities=ro, input={"steps": [{"action": "info"}, {"action": "text"}, {"action": "links"}]}))
    assert ok.status is S.SUCCEEDED
    bad = orch.run(R(agent_id="browser", required_capabilities=ro, input={"steps": [{"action": "text"}, {"action": "click", "element": "e1"}]}))
    assert bad.status is S.BLOCKED and bad.error_code == "capability_not_allowed" and "browser.interact" in bad.error
    assert rig.browser_provider.calls_named("page.click") == [] and len(rig.prompts.requests) == n      # refused before the engine was even asked


def test_malformed_steps_are_rejected_before_any_tool_is_called(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 3)
    orch, _ = rig.agents()
    cases = [{}, {"steps": []}, {"steps": "goto"}, {"steps": [1]}, {"steps": [{"action": "explode"}]}, {"steps": [{"action": "text", "shell": "ls"}]},
             {"steps": [{"action": "text", "tool": "coding"}]}, {"steps": [{"action": "text", "confirmed": True}]}, {"steps": [{"action": "text"}] * 51},
             {"steps": [{"tool": "keyboard", "action": "type", "text": "x"}]}]
    for inp in cases:
        r = orch.run(R(agent_id="browser", input=inp))
        assert r.status is S.FAILED and r.error_code == "invalid_input", inp
    assert rig.prompts.requests == [] and rig.browser_provider.calls == []


def test_a_tool_that_is_not_enabled_is_reported_not_crashed(tmp_path):
    rig = tool_rig(tmp_path, [ONCE])
    rig.registry.unregister("browser")
    orch, _ = rig.agents()
    r = orch.run(R(agent_id="browser", input={"steps": [{"action": "status"}]}))
    assert r.status is S.FAILED and r.error_code == "tool_unavailable"
    assert orch.run(R(agent_id="research", input={"url": "https://example.com/"})).error_code == "tool_unavailable"


# ---- coding agent ---------------------------------------------------------------------------------------------------------------------------------------
def test_coding_agent_fixes_and_tests_a_project_with_every_write_and_run_confirmed(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 4)
    outputs = iter([CommandResult(1, "FAILED tests/test_calc.py::test_add - assert -1 == 5\n1 failed, 1 passed in 0.02s\n", "", False, False, 0.02),
                    CommandResult(0, "2 passed in 0.02s\n", "", False, False, 0.02)])
    rig.coding_provider.command_handler = lambda spec: next(outputs)
    orch, _ = rig.agents()
    steps = [{"action": "start", "workspace": str(rig.project)}, {"action": "info"}, {"action": "test"},
             {"action": "write", "path": "calc.py", "mode": "replace", "old_text": "a - b", "new_text": "a + b"}, {"action": "test"}, {"action": "changes"}]
    r = orch.run(R(agent_id="coding", input={"steps": steps}))
    assert r.status is S.SUCCEEDED, r.error
    out = r.output["steps"]
    assert out[2]["output"]["passed"] is False and out[2]["output"]["failures"] == ["tests/test_calc.py::test_add"]
    assert out[4]["output"]["passed"] is True and out[5]["output"]["changes"] == ["calc.py: modify +1/-1"]
    assert [q.action for q in rig.prompts.requests] == ["start", "test", "write", "test"]       # exactly the engine's questions, in order
    assert "return a + b" in rig.coding_provider.text(str(rig.project / "calc.py"))


def test_a_read_only_coding_task_cannot_write_test_or_plan(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 3)
    orch, _ = rig.agents()
    ro = frozenset({P.CODING_READ})
    ok = orch.run(R(agent_id="coding", required_capabilities=ro, input={"steps": [{"action": "start", "workspace": str(rig.project)}, {"action": "read", "path": "calc.py"},
                                                                                    {"action": "search", "pattern": "def"}]}))
    assert ok.status is S.SUCCEEDED
    for step in ({"action": "write", "path": "x.py", "mode": "create", "content": "x"}, {"action": "delete", "path": "calc.py"}, {"action": "test"},
                 {"action": "plan", "goal": "g"}):
        r = orch.run(R(agent_id="coding", required_capabilities=ro, input={"steps": [step]}))
        assert r.status is S.BLOCKED and r.error_code == "capability_not_allowed", step
    assert rig.coding_provider.calls_named("write_file") == [] and rig.coding_provider.commands == []


def test_secrets_and_git_writes_are_refused_by_the_engine_for_agents_too(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 3)
    rig.coding_provider.put(str(rig.project / ".env"), "TOKEN=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123\n")
    orch, _ = rig.agents()
    orch.run(R(agent_id="coding", input={"steps": [{"action": "start", "workspace": str(rig.project)}]}))
    for step in ({"action": "read", "path": ".env"}, {"action": "git", "sub": "push"}, {"action": "git", "sub": "commit"},
                 {"action": "write", "path": ".env", "mode": "replace", "old_text": "a", "new_text": "b"}):
        r = orch.run(R(agent_id="coding", input={"steps": [step]}))
        assert r.status is S.BLOCKED and r.error_code == "permission_denied", step
    assert "sk-ant" not in str(r.to_dict()) and "sk-ant" not in rig.audit_blob()
    assert rig.coding_provider.commands == []


def test_cancelling_a_running_test_uses_the_coding_halt_and_ends_the_task_cancelled(tmp_path):
    import threading
    from jarvis.coding.providers.fake import FakeCodingProvider

    class Slow(FakeCodingProvider):
        def __init__(self):
            super().__init__()
            self.running, self.stop = threading.Event(), threading.Event()

        def run_command(self, spec):
            self.running.set()
            self.stop.wait(WAIT)                      # a "long test run" that only ends when it is aborted
            return CommandResult(None, "", "", False, False, 1.0, aborted=True)

        def abort_running(self):
            super().abort_running()
            self.stop.set()

    prov = Slow()
    rig = tool_rig(tmp_path, [ONCE] * 3, coding_provider=prov)
    orch, reg = rig.agents(executor=None)         # real worker thread: the test is running while we cancel
    t = R(agent_id="coding", input={"steps": [{"action": "start", "workspace": str(rig.project)}, {"action": "test"}]})
    orch.submit(t)
    orch.start(t.task_id)
    assert prov.running.wait(WAIT)
    rep = orch.cancel(t.task_id, wait=WAIT)
    r = orch.get(t.task_id)
    assert rep.accepted and r.status is S.CANCELLED, (rep, r.status, r.error)
    assert prov.calls_named("abort_running") and rig.coding.halted is not None            # the existing halt stopped the running test
    assert reg.get("coding").status.value == "AVAILABLE" and orch.active_agents == 0
    halted = orch.run(R(agent_id="coding", input={"steps": [{"action": "info"}]}))
    assert halted.status is S.BLOCKED and halted.error_code == "halted"        # coding stays halted until the USER resumes it
    rig.coding.resume()
    assert orch.run(R(agent_id="coding", input={"steps": [{"action": "info"}]})).status is S.SUCCEEDED


# ---- computer agent -------------------------------------------------------------------------------------------------------------------------------------
def test_computer_agent_types_into_the_active_window_only_after_the_engine_confirms(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 3)
    orch, _ = rig.agents()
    r = orch.run(R(agent_id="computer", input={"steps": [{"tool": "screen", "action": "windows"}, {"tool": "keyboard", "action": "type", "text": "Hallo"}]}))
    assert r.status is S.SUCCEEDED and rig.fb.typed == ["Hallo"]
    assert [q.action for q in rig.prompts.requests] == ["type"] and "Notepad" in rig.prompts.requests[0].to_text()
    assert "Hallo" not in rig.audit_blob()


def test_computer_red_rules_are_unchanged_for_agents(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 6)
    rig.fb.add_window("Windows PowerShell", "powershell.exe", active=True)
    orch, _ = rig.agents()
    r = orch.run(R(agent_id="computer", input={"steps": [{"tool": "keyboard", "action": "type", "text": "Get-Process"}]}))
    assert r.status is S.BLOCKED and r.error_code == "permission_denied" and rig.fb.typed == []
    r = orch.run(R(agent_id="computer", input={"steps": [{"tool": "keyboard", "action": "hotkey", "keys": "win+r"}]}))
    assert r.status is S.BLOCKED and rig.fb.typed == []
    r = orch.run(R(agent_id="computer", input={"steps": [{"tool": "app", "app": "cmd"}]}))
    assert r.status is S.BLOCKED and rig.fb.launched == []


def test_the_computer_agent_has_no_tool_beyond_its_six_and_capabilities_split_screen_from_input(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 3)
    orch, _ = rig.agents()
    for bad in ({"tool": "coding", "action": "info"}, {"tool": "browser", "action": "status"}, {"tool": "shell", "action": "x"}, {"action": "type", "text": "x"}):
        r = orch.run(R(agent_id="computer", input={"steps": [bad]}))
        assert r.status is S.FAILED and r.error_code == "invalid_input", bad
    screen_only = frozenset({P.COMPUTER_SCREEN})
    assert orch.run(R(agent_id="computer", required_capabilities=screen_only, input={"steps": [{"tool": "screen", "action": "monitors"}]})).status is S.SUCCEEDED
    r = orch.run(R(agent_id="computer", required_capabilities=screen_only, input={"steps": [{"tool": "mouse", "action": "click", "x": 1, "y": 1}]}))
    assert r.status is S.BLOCKED and r.error_code == "capability_not_allowed" and rig.fb.calls_named("mouse.click") == []


# ---- hand-over between agents ----------------------------------------------------------------------------------------------------------------------------
def test_research_result_flows_into_the_coding_agent_as_structured_data(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 6)
    seen = {}

    class SpyCoding(CodingAgent):
        def perform(self, task, ctx):
            seen["parents"] = dict(ctx.parent_results)
            return super().perform(task, ctx)

    orch, reg = rig.agents()
    reg.unregister("coding")
    reg.register(SpyCoding(interrupt=None))
    research = R(agent_id="research", input={"url": "https://example.com/"}, task_id="research-1")
    code = AgentTask("apply what was found", agent_id="coding", dependencies=("research-1",), input={"steps": [
        {"action": "start", "workspace": str(rig.project)}, {"action": "write", "path": "NOTES.md", "mode": "create", "content": "# notes\n"}]})
    orch.submit(research), orch.submit(code)
    orch.start(code.task_id)
    assert orch.get(code.task_id).status is S.PENDING
    orch.start("research-1")
    res, rc = orch.get("research-1"), orch.get(code.task_id)
    assert res.status is S.SUCCEEDED and "Opening hours" in res.output["text"] and res.output["untrusted_content"]
    assert rc.status is S.SUCCEEDED and seen["parents"]["research-1"].output["text"] == res.output["text"]
    assert rig.coding_provider.text(str(rig.project / "NOTES.md")) == "# notes\n"


def test_research_agent_needs_a_url_and_respects_the_permission_engine(tmp_path):
    rig = tool_rig(tmp_path, [NO])
    orch, _ = rig.agents()
    assert orch.run(R(agent_id="research", input={})).error_code == "invalid_input"
    r = orch.run(R(agent_id="research", input={"url": "https://example.com/"}))
    assert r.status is S.BLOCKED and r.error_code == "permission_denied" and rig.browser_provider.calls_named("page.goto") == []


# ---- agents can not get around the gateway ------------------------------------------------------------------------------------------------------------------
def test_a_misbehaving_agent_cannot_pass_confirmations_or_use_foreign_tools(tmp_path):
    rig = tool_rig(tmp_path, [ONCE])
    evil1 = FakeAgent("evil1", tool_names=frozenset({"browser"}), tool_calls=[("browser", {"action": "start", "confirmed": True})])
    evil2 = FakeAgent("evil2", tool_names=frozenset({"browser"}), tool_calls=[("keyboard", {"action": "type", "text": "x"})])
    evil3 = FakeAgent("evil3", tool_names=frozenset({"browser"}), tool_calls=[("browser", {"action": "start", "force": True})])
    orch, reg = rig.agents()
    for a in (evil1, evil2, evil3):
        reg.register(a)
        r = orch.run(R(agent_id=a.id))
        assert r.status is S.FAILED and r.error_code == "tool_access_denied", a.id
    assert rig.prompts.requests == [] and rig.fb.typed == [] and rig.browser_provider.calls_named("provider.start") == []


def test_session_permissions_work_exactly_as_without_the_agent_layer(tmp_path):
    rig = tool_rig(tmp_path, [ONCE, ONCE, SESSION])
    orch, _ = rig.agents()
    orch.run(R(agent_id="browser", input={"steps": [{"action": "start"}, {"action": "goto", "url": "https://example.com/"}]}))
    links = rig.registry.execute("browser", action="find", query="Go")
    el = links.output["matches"][0]["element"]
    r1 = orch.run(R(agent_id="browser", input={"steps": [{"action": "click", "element": el}]}))
    assert r1.status is S.SUCCEEDED and rig.prompts.requests[-1].session_allowed is True
    before = len(rig.prompts.requests)
    r2 = orch.run(R(agent_id="browser", input={"steps": [{"action": "click", "element": el}]}))
    assert r2.status is S.SUCCEEDED and len(rig.prompts.requests) == before          # the same session grant the engine itself issued


def test_orchestrator_results_never_contain_what_the_engine_redacts(tmp_path):
    rig = tool_rig(tmp_path, [ONCE] * 3)
    rig.coding_provider.put(str(rig.project / "cfg.py"), 'API_KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"\nX = 1\n')
    orch, _ = rig.agents()
    r = orch.run(R(agent_id="coding", input={"steps": [{"action": "start", "workspace": str(rig.project)}, {"action": "read", "path": "cfg.py"},
                                                         {"action": "search", "pattern": "API_KEY"}]}))
    assert r.status is S.SUCCEEDED and "sk-ant" not in str(r.to_dict()) and "[REDACTED]" in str(r.to_dict())
