import pytest

from jarvis.errors import LLMError, PlanningError
from jarvis.llm.mock import MockProvider
from jarvis.planning import Planner
from jarvis.planning.planner import FALLBACK_STEPS, _extract_json
from jarvis.tasks import TaskStatus


def test_llm_plan(provider, registry):
    task = Planner(provider, registry).plan("Erstelle ein CSV-Tool")
    assert task.status is TaskStatus.WAITING
    assert [s.description for s in task.subtasks][1] == "Code schreiben"
    assert task.subtasks[1].required_tools == ["echo"]  # unknown tool filtered
    assert task.required_agents == ["coding", "research", "testing"]
    assert task.result["plan_source"] == "llm"
    assert all(s.parent_id == task.id for s in task.subtasks)


def test_fenced_json_and_string_steps():
    p = MockProvider(responder=lambda r: '```json\n{"steps": ["a", "b"]}\n```')
    assert [s.description for s in Planner(p).plan("goal").subtasks] == ["a", "b"]


@pytest.mark.parametrize("reply", ["no json", "{bad", '{"steps": []}', '{"steps": [{"x": 1}]}', "[1]"])
def test_fallback_on_bad_reply(reply):
    t = Planner(MockProvider(responder=lambda r: reply)).plan("goal")
    assert [s.description for s in t.subtasks] == FALLBACK_STEPS
    assert t.result["plan_source"] == "fallback"


def test_fallback_on_llm_error():
    def boom(r):
        raise LLMError("down")
    assert Planner(MockProvider(responder=boom)).plan("goal").result["plan_source"] == "fallback"


def test_empty_goal(provider):
    with pytest.raises(PlanningError):
        Planner(provider).plan("   ")


def test_extract_json_errors():
    with pytest.raises(PlanningError):
        _extract_json("nothing")
