import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def list_tasks():
    tasks = task_manager.get_all_tasks()
    return [
        {
            "task_id": t.task_id,
            "name": t.name,
            "status": t.status,
            "progress": t.progress,
            "total": t.total,
            "message": t.message,
        }
        for t in tasks
    ]


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    return {
        "task_id": task.task_id,
        "name": task.name,
        "status": task.status,
        "progress": task.progress,
        "total": task.total,
        "message": task.message,
    }


@router.get("/{task_id}/stream")
async def stream_task(task_id: str):
    async def event_generator():
        async for data in task_manager.stream_progress(task_id):
            yield {"data": json.dumps(data, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    task = task_manager.get_task(task_id)
    if task:
        task_manager.fail_task(task_id, "사용자가 취소함")
        return {"status": "cancelled"}
    return {"error": "Task not found"}
