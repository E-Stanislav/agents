from __future__ import annotations

import asyncio
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

# Per-task cancellation events: set() means "please cancel"
_cancel_events: dict[str, asyncio.Event] = {}

# Tracks whether a WebSocket handler is actively processing each task
_active_ws: dict[str, bool] = {}


class TaskCreate(BaseModel):
    md_content: str


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str = ""


class TaskStatus(BaseModel):
    task_id: str
    status: str = "unknown"
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
        status=task.get("status", "unknown"),
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


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Request cancellation of a running task."""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _tasks[task_id]
    if task.get("status") in ("done", "error", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Task already finished with status: {task.get('status')}",
        )

    if task_id not in _cancel_events:
        _cancel_events[task_id] = asyncio.Event()

    _cancel_events[task_id].set()
    logger.info("Cancel requested for task %s", task_id)

    if not _active_ws.get(task_id):
        _tasks[task_id].update(
            status="cancelled",
            phase="cancelled",
            interrupt_type="",
            interrupt_data={},
        )
        logger.info("Task %s cancelled directly (no active WS handler)", task_id)
        return {"task_id": task_id, "status": "cancelled"}

    return {"task_id": task_id, "status": "cancel_requested"}


def get_cancel_event(task_id: str) -> asyncio.Event:
    """Get or create the cancellation event for a task."""
    if task_id not in _cancel_events:
        _cancel_events[task_id] = asyncio.Event()
    return _cancel_events[task_id]


def update_task(task_id: str, **kwargs) -> None:
    """Update task state (called from WebSocket handler)."""
    if task_id in _tasks:
        _tasks[task_id].update(kwargs)
