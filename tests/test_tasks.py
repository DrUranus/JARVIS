import pytest

from jarvis.errors import TaskError
from jarvis.tasks import Task, TaskManager, TaskStatus


def test_defaults_and_validation():
    t = Task("do it")
    assert t.status is TaskStatus.PENDING and t.priority == 5 and t.id
    with pytest.raises(TaskError):
        Task("  ")
    with pytest.raises(TaskError):
        Task("x", priority=0)


def test_lifecycle():
    t = Task("x")
    t.transition(TaskStatus.PLANNING)
    t.transition(TaskStatus.RUNNING)
    t.complete("done")
    assert t.is_terminal and t.result == "done"


def test_illegal_transition():
    t = Task("x")
    with pytest.raises(TaskError):
        t.transition(TaskStatus.COMPLETED)
    t.transition(TaskStatus.CANCELLED)
    with pytest.raises(TaskError):
        t.transition(TaskStatus.RUNNING)


def test_fail_and_retry():
    t = Task("x")
    t.fail("boom")
    assert t.error == "boom"
    t.transition(TaskStatus.PENDING)


def test_subtasks_and_dict():
    t = Task("parent")
    s = t.add_subtask("child", required_tools=["echo"])
    assert s.parent_id == t.id
    d = t.to_dict()
    assert d["subtasks"][0]["required_tools"] == ["echo"]


def test_manager():
    m = TaskManager()
    a = m.create("a", priority=3)
    b = m.create("b", priority=1)
    assert [t.id for t in m.list()] == [b.id, a.id]
    with pytest.raises(TaskError):
        m.get("missing")
    sub = a.add_subtask("s")
    m.add(a)
    assert sub not in m.list() and m.get(sub.id) is sub
    m.cancel(a.id)
    assert sub.status is TaskStatus.CANCELLED
    assert [t.id for t in m.open_tasks()] == [b.id]
