from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.agents.orchestrator import build_graph
from src.api.routes import _tasks, update_task
from src.models.state import Phase, ProjectState
from src.security.validators import validate_md_input, ValidationError

logger = logging.getLogger(__name__)
ws_router = APIRouter()

# Shared checkpointer for interrupt/resume
_checkpointer = MemorySaver()


def _compile_graph():
    graph = build_graph()
    return graph.compile(checkpointer=_checkpointer)


@ws_router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for interactive project generation.

    Protocol:
    1. Client connects with task_id
    2. Server streams progress events: {"type": "progress", "phase": "...", "message": "..."}
    3. On interrupt, server sends: {"type": "interrupt", "interrupt_type": "...", "data": {...}}
    4. Client responds with: {"type": "resume", "data": {...}}
    5. On completion: {"type": "done", "output_path": "...", "archive_path": "..."}
    6. On error: {"type": "error", "message": "..."}
    """
    await websocket.accept()
    logger.info("WebSocket connected for task %s", task_id)

    try:
        # Get task data
        task = _tasks.get(task_id)
        if not task:
            await websocket.send_json({"type": "error", "message": "Task not found"})
            return

        md_content = task.get("md_content", "")
        try:
            validate_md_input(md_content)
        except ValidationError as e:
            await websocket.send_json({"type": "error", "message": str(e)})
            return

        app = _compile_graph()
        thread_id = task_id
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = ProjectState(
            task_id=task_id,
            md_content=md_content,
        )

        await websocket.send_json({
            "type": "progress",
            "phase": "init",
            "message": "Starting project generation...",
        })

        # Run the graph with interrupt handling
        current_input = initial_state
        is_resume = False

        while True:
            try:
                if is_resume:
                    stream = app.astream(current_input, config=config)
                else:
                    stream = app.astream(current_input, config=config)
                    is_resume = True

                async for event in stream:
                    for node_name, node_output in event.items():
                        if node_name == "__interrupt__":
                            # Handle interrupt
                            interrupt_data = node_output
                            if isinstance(interrupt_data, list) and interrupt_data:
                                interrupt_data = interrupt_data[0]

                            interrupt_value = getattr(interrupt_data, "value", interrupt_data)

                            await websocket.send_json({
                                "type": "interrupt",
                                "interrupt_type": interrupt_value.get("type", "unknown") if isinstance(interrupt_value, dict) else "unknown",
                                "data": interrupt_value if isinstance(interrupt_value, dict) else {"value": str(interrupt_value)},
                            })

                            # Wait for user response
                            response_raw = await websocket.receive_text()
                            response = json.loads(response_raw)
                            resume_data = response.get("data", response)

                            current_input = Command(resume=resume_data)
                            continue

                        # Send progress update
                        phase = "unknown"
                        if isinstance(node_output, dict):
                            phase = node_output.get("phase", phase)
                            if isinstance(phase, Phase):
                                phase = phase.value

                        await websocket.send_json({
                            "type": "progress",
                            "phase": phase,
                            "node": node_name,
                            "message": f"Completed: {node_name}",
                        })

                        update_task(task_id, phase=phase, status="running")

                        # Check for completion
                        if isinstance(node_output, dict):
                            if node_output.get("phase") == Phase.DONE:
                                await websocket.send_json({
                                    "type": "done",
                                    "output_path": node_output.get("output_path", ""),
                                    "archive_path": node_output.get("archive_path", ""),
                                    "git_log": node_output.get("git_log", ""),
                                })
                                update_task(
                                    task_id,
                                    status="done",
                                    phase="done",
                                    output_path=node_output.get("output_path", ""),
                                    archive_path=node_output.get("archive_path", ""),
                                )
                                return

                            if node_output.get("phase") == Phase.ERROR:
                                errors = node_output.get("errors", [])
                                await websocket.send_json({
                                    "type": "error",
                                    "message": "; ".join(errors) if errors else "Unknown error",
                                })
                                update_task(task_id, status="error", errors=errors)
                                return

                # If stream completed without DONE/ERROR, we're done
                break

            except WebSocketDisconnect:
                logger.info("WebSocket disconnected for task %s", task_id)
                return

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for task %s", task_id)
    except Exception as e:
        logger.error("WebSocket error for task %s: %s", task_id, e, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
