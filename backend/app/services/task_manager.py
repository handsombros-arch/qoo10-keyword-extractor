import asyncio
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional


@dataclass
class TaskInfo:
    task_id: str
    name: str
    status: str = "pending"
    progress: int = 0
    total: int = 0
    message: str = ""
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, TaskInfo] = {}

    def create_task(self, name: str, total: int = 0) -> str:
        task_id = str(uuid.uuid4())[:8]
        self._tasks[task_id] = TaskInfo(
            task_id=task_id, name=name, status="pending", total=total
        )
        return task_id

    def start_task(self, task_id: str):
        task = self._tasks.get(task_id)
        if task:
            task.status = "running"
            task._event.set()
            task._event.clear()

    def update_progress(self, task_id: str, increment: int = 1, message: str = ""):
        task = self._tasks.get(task_id)
        if task:
            task.progress += increment
            task.message = message
            task._event.set()
            task._event.clear()

    def complete_task(self, task_id: str, message: str = "완료"):
        task = self._tasks.get(task_id)
        if task:
            task.status = "completed"
            task.progress = task.total
            task.message = message
            task._event.set()

    def fail_task(self, task_id: str, message: str = "실패"):
        task = self._tasks.get(task_id)
        if task:
            task.status = "failed"
            task.message = message
            task._event.set()

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[TaskInfo]:
        return list(self._tasks.values())

    async def stream_progress(self, task_id: str) -> AsyncGenerator[dict, None]:
        task = self._tasks.get(task_id)
        if not task:
            return

        while task.status in ("pending", "running"):
            yield {
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status,
                "progress": task.progress,
                "total": task.total,
                "message": task.message,
            }
            task._event.clear()
            try:
                await asyncio.wait_for(task._event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

        # Final state
        yield {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status,
            "progress": task.progress,
            "total": task.total,
            "message": task.message,
        }


task_manager = TaskManager()
