from typing import Optional

from pydantic import BaseModel


class TaskOut(BaseModel):
    task_id: str
    name: str
    status: str  # pending, running, completed, failed
    progress: int = 0
    total: int = 0
    message: Optional[str] = None


class TaskCreateResponse(BaseModel):
    task_id: str
