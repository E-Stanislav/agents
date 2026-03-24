from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.agents.orchestrator import build_graph
from src.api.routes import _tasks, update_task
from src.models.state import Phase, ProjectState
from src.security.validators import validate_md_input, ValidationError

logger = logging.getLogger(__name__)
ws_router = APIRouter()

# Shared checkpointer for interrupt/resume — survives across WS reconnects
_checkpointer = MemorySaver()


def _compile_graph():
    graph = build_graph()
    return graph.compile(checkpointer=_checkpointer)


def _extract_interrupt_value(node_output) -> dict:
    """Unwrap the interrupt value from whatever LangGraph gives us.

    Handles all known shapes:
      - tuple/list of Interrupt objects: (Interrupt(value={...}, id='...'),)
      - single Interrupt object with .value attribute
      - plain dict with actual data: {"type": "clarification", "questions": [...]}
      - corrupted dict from previous save: {"value": "(Interrupt(value={...},...))"}
    """
    data = node_output

    # Step 1: unwrap tuple / list
    if isinstance(data, (list, tuple)):
        if len(data) == 0:
            return {}
        data = data[0]

    # Step 2: unwrap Interrupt-like objects (have .value attribute, but are NOT dicts)
    for _ in range(3):
        if isinstance(data, dict):
            break
        inner = getattr(data, "value", None)
        if inner is None:
            break
        data = inner

    # Step 3: if we have a well-formed dict, check if it's the real payload or a wrapper
    if isinstance(data, dict):
        if "type" in data and ("questions" in data or "plan" in data):
            return data

        # Corrupted wrapper: {"value": "(Interrupt(value={...},...))"}
        raw = data.get("value")
        if isinstance(raw, str) and "{" in raw:
            recovered = _parse_dict_from_string(raw)
            if recovered is not None:
                return recovered

        return data

    # Step 4: last resort — parse from string representation
    text = str(data)
    recovered = _parse_dict_from_string(text)
    if recovered is not None:
        return recovered

    return {"value": text}


def _parse_dict_from_string(text: str) -> dict | None:
    """Try to extract a Python dict literal from a string like
    "(Interrupt(value={'type': 'clarification', ...}, id='...'),)".
    """
    import ast

    if "{" not in text:
        return None

    try:
        start = text.index("{")
        depth, end = 0, start
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        candidate = text[start:end]
        result = ast.literal_eval(candidate)
        if isinstance(result, dict):
            logger.info("Recovered interrupt data from string representation")
            return result
    except Exception as e:
        logger.warning("Failed to parse dict from string: %s", e)

    return None


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

    Reconnection support:
    - If the task has a pending interrupt (user disconnected mid-dialog),
      the server re-sends the interrupt immediately so the user can continue.
    """
    await websocket.accept()
    logger.info("WebSocket connected for task %s", task_id)

    try:
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

        # ── Reconnection: check for pending interrupt ──
        pending_interrupt = task.get("interrupt_type", "")
        if pending_interrupt and task.get("status") == "waiting_for_input":
            logger.info("Task %s: reconnecting to pending %s interrupt", task_id, pending_interrupt)

            await websocket.send_json({
                "type": "progress",
                "phase": task.get("phase", "unknown"),
                "message": "Reconnected. Resuming where you left off...",
            })

            interrupt_data = _extract_interrupt_value(task.get("interrupt_data", {}))
            reconnect_type = interrupt_data.get("type", pending_interrupt)

            await websocket.send_json({
                "type": "interrupt",
                "interrupt_type": reconnect_type,
                "data": interrupt_data,
            })

            response_raw = await websocket.receive_text()
            response = json.loads(response_raw)
            resume_data = response.get("data", response)

            update_task(task_id, interrupt_type="", interrupt_data={}, status="running")

            current_input = Command(resume=resume_data)
            is_resume = True
        else:
            if task.get("status") in ("done", "error"):
                await websocket.send_json({
                    "type": "error",
                    "message": f"Task already finished with status: {task.get('status')}",
                })
                return

            initial_state = ProjectState(
                task_id=task_id,
                md_content=md_content,
            )

            await websocket.send_json({
                "type": "progress",
                "phase": "init",
                "message": "Starting project generation...",
            })

            current_input = initial_state
            is_resume = False

        # ── Main graph execution loop ──
        while True:
            try:
                stream = app.astream(current_input, config=config)
                is_resume = True

                async for event in stream:
                    for node_name, node_output in event.items():
                        if node_name == "__interrupt__":
                            interrupt_payload = _extract_interrupt_value(node_output)
                            interrupt_type = interrupt_payload.get("type", "unknown")

                            # Persist interrupt state so reconnection works
                            update_task(
                                task_id,
                                status="waiting_for_input",
                                interrupt_type=interrupt_type,
                                interrupt_data=interrupt_payload,
                            )

                            await websocket.send_json({
                                "type": "interrupt",
                                "interrupt_type": interrupt_type,
                                "data": interrupt_payload,
                            })

                            response_raw = await websocket.receive_text()
                            response = json.loads(response_raw)
                            resume_data = response.get("data", response)

                            # Clear interrupt state on successful resume
                            update_task(
                                task_id,
                                status="running",
                                interrupt_type="",
                                interrupt_data={},
                            )

                            current_input = Command(resume=resume_data)
                            continue

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
                                    interrupt_type="",
                                    interrupt_data={},
                                )
                                return

                            if node_output.get("phase") == Phase.ERROR:
                                errors = node_output.get("errors", [])
                                await websocket.send_json({
                                    "type": "error",
                                    "message": "; ".join(errors) if errors else "Unknown error",
                                })
                                update_task(
                                    task_id,
                                    status="error",
                                    errors=errors,
                                    interrupt_type="",
                                    interrupt_data={},
                                )
                                return

                break

            except WebSocketDisconnect:
                logger.info("WebSocket disconnected for task %s (interrupt state preserved)", task_id)
                return

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for task %s", task_id)
    except Exception as e:
        logger.error("WebSocket error for task %s: %s", task_id, e, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
