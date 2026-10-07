"""Goal / GoalStep / GoalStepResult, lifecycles, context and policy helpers."""
from __future__ import annotations

import json

import pytest

from jarvis.agents.state import TaskStatus
from jarvis.goals import (Goal, GoalContext, GoalStatus, GoalStep, GoalStepResult, InvalidGoalError, StepStatus, check_user_context)
from jarvis.goals import policy as P
from jarvis.goals.errors import GoalStateError
from jarvis.goals.state import GOAL_TERMINAL, GOAL_TRANSITIONS, STEP_TERMINAL, STEP_TRANSITIONS


def test_goal_defaults_and_ids():
    g = Goal("Analysiere example.com")
    assert g.status is GoalStatus.PENDING and g.priority == 5 and g.timeout is None and g.max_steps is None
    assert g.goal_id.startswith("g-") and Goal("x").goal_id != Goal("x").goal_id
    assert g.created_at <= g.updated_at


@pytest.mark.parametrize("kw", [{"objective": ""}, {"objective": "   "}, {"objective": "x" * 2001}, {"objective": "a\x00b"},
                                {"objective": "ok", "priority": 0}, {"objective": "ok", "priority": 11}, {"objective": "ok", "priority": True},
                                {"objective": "ok", "timeout": 0}, {"objective": "ok", "timeout": -1}, {"objective": "ok", "timeout": 10**9},
                                {"objective": "ok", "max_steps": 0}, {"objective": "ok", "max_steps": 51}, {"objective": "ok", "goal_id": "a b"},
                                {"objective": "ok", "metadata": {"k": 1}}, {"objective": "ok", "status": "RUNNING"}])
def test_goal_rejects_invalid(kw):
    with pytest.raises(InvalidGoalError):
        Goal(**kw)


def test_goal_repr_and_dict_do_not_leak_in_repr():
    g = Goal("mein geheimes Passwort ist hunter2hunter2", metadata={"k": "v"})
    assert "hunter2" not in repr(g) and "geheim" not in repr(g)
    json.dumps(g.to_dict())      # serialisable


def test_goal_lifecycle_forward_only():
    g = Goal("x")
    g = g.with_status(GoalStatus.PLANNING).with_status(GoalStatus.RUNNING).with_status(GoalStatus.WAITING).with_status(GoalStatus.RUNNING)
    assert g.with_status(GoalStatus.SUCCEEDED).is_terminal
    for bad in (GoalStatus.PENDING, GoalStatus.PLANNING):
        with pytest.raises(GoalStateError):
            g.with_status(bad)


@pytest.mark.parametrize("terminal", sorted(GOAL_TERMINAL, key=lambda s: s.value))
def test_terminal_goal_status_is_final(terminal):
    assert GOAL_TRANSITIONS[terminal] == frozenset()
    for target in GoalStatus:
        with pytest.raises(GoalStateError):
            Goal("x", status=terminal).with_status(target)


def test_goal_transition_table_has_no_way_back_to_pending_or_planning():
    for old, targets in GOAL_TRANSITIONS.items():
        assert GoalStatus.PENDING not in targets
        if old is not GoalStatus.PENDING:
            assert GoalStatus.PLANNING not in targets


def test_step_validation():
    s = GoalStep("s1", "g-1", "do it", frozenset({"research.web"}), "research", (), input={"url": "https://x.test/"})
    assert s.status is StepStatus.PENDING and s.attempts == 0 and s.result is None
    for kw in ({"step_id": "bad id"}, {"goal_id": ""}, {"objective": " "}, {"dependencies": ("s1",)}, {"dependencies": ("a", "a")},
               {"max_attempts": 0}, {"max_attempts": 6}, {"attempts": 2}, {"timeout": 0}, {"timeout": 10**6}, {"input": {"x": object()}},
               {"input": {"x": float("nan")}}, {"input": []}):
        base = dict(step_id="s1", goal_id="g-1", objective="o", required_capabilities=frozenset(), assigned_agent="a", dependencies=(), max_attempts=1)
        base.update(kw)
        with pytest.raises(InvalidGoalError):
            GoalStep(**base)


def test_step_lifecycle_and_attempts_and_no_back_transition():
    s = GoalStep("s1", "g-1", "o", frozenset(), "a", max_attempts=2)
    s = s.with_status(StepStatus.RUNNING).with_attempt().with_attempt()
    assert s.attempts == 2
    with pytest.raises(InvalidGoalError):
        s.with_attempt()
    done = s.with_result(GoalStepResult("s1", StepStatus.SUCCEEDED, "ok", {"a": 1}))
    assert done.status is StepStatus.SUCCEEDED and done.result.output == {"a": 1}
    for target in StepStatus:
        with pytest.raises(GoalStateError):
            done.with_status(target)
    with pytest.raises(GoalStateError):
        s.with_status(StepStatus.PENDING)


def test_step_transition_tables_terminal_final():
    for t in STEP_TERMINAL:
        assert STEP_TRANSITIONS[t] == frozenset()


def test_step_repr_and_dict_hide_input_values():
    s = GoalStep("s1", "g-1", "type my password hunter2hunter2", frozenset(), "a", input={"steps": [{"action": "type", "text": "hunter2hunter2"}]})
    assert "hunter2" not in repr(s)
    d = s.to_dict()
    assert "hunter2" not in json.dumps(d) or "hunter2" in d["objective"]   # the objective is shown (bounded), the input values never
    assert d["input_keys"] == ["steps"] and "input" not in d


def test_step_result_is_bounded_serialisable_and_validated():
    r = GoalStepResult("s1", StepStatus.SUCCEEDED, "x" * 5000, {"text": "y" * 100_000}, "browser", "t-1", 1.5, 2, None,
                       ({"attempt": 1}, {"attempt": 2}))
    assert len(r.summary) <= P.MAX_SUMMARY and r.output.get("truncated") is True
    json.dumps(r.to_dict())
    assert "yyyy" not in repr(r) and "xxxx" not in repr(r)
    assert GoalStepResult("s1", StepStatus.FAILED, output=object()).output == {"unserialisable": True}
    assert GoalStepResult("s1", StepStatus.FAILED, duration=float("nan")).duration == 0.0
    with pytest.raises(InvalidGoalError):
        GoalStepResult("s1", StepStatus.SUCCEEDED, attempts=0)
    with pytest.raises(InvalidGoalError):
        GoalStepResult("bad id", StepStatus.SUCCEEDED)
    with pytest.raises(InvalidGoalError):
        GoalStepResult("s1", "SUCCEEDED")  # type: ignore[arg-type]


def test_user_context_only_known_keys_plain_data_no_bypass():
    assert check_user_context(None) == {}
    assert check_user_context({"url": "https://a.test/"}) == {"url": "https://a.test/"}
    for bad in ({"password": "x"}, {"confirmed": True}, {"edits": [{"path": "a", "force": True}]}, {"url": object()},
                {"edits": [{"confirm": True}]}, {"url": "x" * 200_000}, "text", {f"k{i}": 1 for i in range(11)}):
        with pytest.raises(InvalidGoalError):
            check_user_context(bad)  # type: ignore[arg-type]


def test_context_holds_only_what_it_is_given():
    s = GoalStep("s1", "g-1", "o", frozenset(), "a")
    r = GoalStepResult("s0", StepStatus.SUCCEEDED, "x")
    ctx = GoalContext("g-1", "obj", s, (r,), {"url": "https://a.test/"})
    assert ctx.result_of("s0") is r and ctx.result_of("zz") is None
    assert "obj" not in repr(ctx) and "a.test" not in repr(ctx)
    assert {f for f in GoalContext.__dataclass_fields__} == {"goal_id", "objective", "current_step", "previous_step_results", "explicit_user_context"}


def test_policy_retry_rules():
    assert P.is_retryable(TaskStatus.FAILED, "timeout") and P.is_retryable(TaskStatus.FAILED, "agent_crashed")
    for code in ("permission_denied", "halted", "invalid_input", "unknown_agent", "capability_missing", "tool_access_denied", None, "weird"):
        assert not P.is_retryable(TaskStatus.FAILED, code)
    assert not P.is_retryable(TaskStatus.BLOCKED, "timeout")
    assert not P.is_retryable(TaskStatus.CANCELLED, "timeout")
    assert not (P.RETRYABLE_CODES & P.FATAL_CODES)


def test_policy_find_reserved_and_urls():
    assert P.find_reserved({"a": [{"Confirmed": 1}]}) == "Confirmed"
    assert P.find_reserved({"steps": [{"action": "goto", "url": "x"}]}) is None
    assert P.valid_url("https://example.com/a") and not P.valid_url("javascript:alert(1)") and not P.valid_url("file:///etc/passwd")
