"""In-memory task store. Persistence arrives with the Memory system (Phase 3)."""
from __future__ import annotations

from jarvis.errors import TaskError
from jarvis.tasks.task import Task, TaskStatus


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add(self, task: Task) -> Task:
        self._tasks[task.id] = task
        for sub in task.subtasks:
            self._tasks.setdefault(sub.id, sub)
        return task

    def create(self, description: str, priority: int = 5) -> Task:
        return self.add(Task(description=description, priority=priority))

    def get(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise TaskError(f"unknown task id: {task_id}") from None

    def list(self, status: TaskStatus | None = None, top_level_only: bool = True) -> list[Task]:
        tasks = [t for t in self._tasks.values()
                 if (status is None or t.status is status) and not (top_level_only and t.parent_id)]
        return sorted(tasks, key=lambda t: (t.priority, t.created_at))

    def open_tasks(self) -> list[Task]:
        return [t for t in self.list() if not t.is_terminal]

    def cancel(self, task_id: str) -> Task:
        task = self.get(task_id)
        for sub in task.subtasks:
            if not sub.is_terminal:
                sub.transition(TaskStatus.CANCELLED)
        task.transition(TaskStatus.CANCELLED)
        return task
