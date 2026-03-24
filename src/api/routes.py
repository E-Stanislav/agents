from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["projects"])

# In-memory task store (in production, use PostgreSQL)
_tasks: dict[str, dict] = {}


class TaskCreate(BaseModel):
    md_content: str


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str = ""


class TaskStatus(BaseModel):
    task_id: str
    phase: str
    progress: float = 0.0
    output_path: str = ""
    archive_path: str = ""
    errors: list[str] = []
    cost_usd: float = 0.0
    interrupt_type: str = ""
    interrupt_data: dict = {}


@router.post("/tasks", response_model=TaskResponse)
async def create_task(body: TaskCreate):
    """Create a new project generation task from MD content."""
    from src.security.validators import validate_md_input, ValidationError

    try:
        validate_md_input(body.md_content)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {
        "task_id": task_id,
        "status": "created",
        "md_content": body.md_content,
        "phase": "init",
    }

    return TaskResponse(
        task_id=task_id,
        status="created",
        message="Task created. Connect via WebSocket to start generation.",
    )


@router.post("/tasks/upload", response_model=TaskResponse)
async def upload_task(file: UploadFile = File(...)):
    """Create a task by uploading an MD file."""
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="File must be a .md file")

    content = await file.read()
    md_content = content.decode("utf-8", errors="replace")

    from src.security.validators import validate_md_input, ValidationError

    try:
        validate_md_input(md_content)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {
        "task_id": task_id,
        "status": "created",
        "md_content": md_content,
        "phase": "init",
    }

    return TaskResponse(
        task_id=task_id,
        status="created",
        message="Task created from uploaded file.",
    )


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Get the current status of a task."""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _tasks[task_id]
    return TaskStatus(
        task_id=task_id,
        phase=task.get("phase", "unknown"),
        output_path=task.get("output_path", ""),
        archive_path=task.get("archive_path", ""),
        errors=task.get("errors", []),
        cost_usd=task.get("cost_usd", 0.0),
        interrupt_type=task.get("interrupt_type", ""),
        interrupt_data=task.get("interrupt_data", {}),
    )


@router.get("/tasks/{task_id}/download")
async def download_project(task_id: str):
    """Download the generated project as a tar.gz archive."""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _tasks[task_id]
    archive_path = task.get("archive_path", "")

    if not archive_path or not Path(archive_path).exists():
        raise HTTPException(status_code=404, detail="Archive not ready yet")

    return FileResponse(
        path=archive_path,
        media_type="application/gzip",
        filename=Path(archive_path).name,
    )


@router.get("/tasks")
async def list_tasks():
    """List all tasks."""
    return [
        {
            "task_id": t["task_id"],
            "status": t.get("status", "unknown"),
            "phase": t.get("phase", "unknown"),
            "interrupt_type": t.get("interrupt_type", ""),
            "interrupt_data": t.get("interrupt_data", {}),
        }
        for t in _tasks.values()
    ]


def update_task(task_id: str, **kwargs) -> None:
    """Update task state (called from WebSocket handler)."""
    if task_id in _tasks:
        _tasks[task_id].update(kwargs)
