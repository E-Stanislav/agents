from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.agents.orchestrator import build_graph
from src.api.routes import (
    _tasks,
    _task_runners,
    update_task,
    get_cancel_event,
    get_task_bus,
    get_resume_queue,
)
from src.models.state import Phase, ProjectState
from src.security.validators import validate_md_input, ValidationError

logger = logging.getLogger(__name__)
ws_router = APIRouter()

_checkpointer = MemorySaver()


def _compile_graph():
    graph = build_graph()
    return graph.compile(checkpointer=_checkpointer)


# ── Interrupt value helpers ───────────────────────────────────────


def _extract_interrupt_value(node_output) -> dict:
    """Unwrap the interrupt value from whatever LangGraph gives us."""
    data = node_output

    if isinstance(data, (list, tuple)):
        if len(data) == 0:
            return {}
        data = data[0]

    for _ in range(3):
        if isinstance(data, dict):
            break
        inner = getattr(data, "value", None)
        if inner is None:
            break
        data = inner

    if isinstance(data, dict):
        if "type" in data and ("questions" in data or "plan" in data):
            return data
        raw = data.get("value")
        if isinstance(raw, str) and "{" in raw:
            recovered = _parse_dict_from_string(raw)
            if recovered is not None:
                return recovered
        return data

    text = str(data)
    recovered = _parse_dict_from_string(text)
    if recovered is not None:
        return recovered
    return {"value": text}


def _parse_dict_from_string(text: str) -> dict | None:
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
            return result
    except Exception:
        pass
    return None


# ── Background graph runner ───────────────────────────────────────


async def _run_graph(task_id: str) -> None:
    """Execute the LangGraph pipeline in the background.

    Communicates with WS clients exclusively through TaskBus (events out)
    and resume_queue (user input in). WS connects/disconnects do NOT
    affect this coroutine.
    """
    bus = get_task_bus(task_id)
    resume_queue = get_resume_queue(task_id)
    cancel_event = get_cancel_event(task_id)

    task = _tasks.get(task_id)
    if not task:
        return

    md_content = task.get("md_content", "")
    try:
        validate_md_input(md_content)
    except ValidationError as e:
        await bus.publish({"type": "error", "message": str(e)})
        update_task(task_id, status="error", errors=[str(e)])
        return

    app = _compile_graph()
    config = {"configurable": {"thread_id": task_id}}

    current_input: ProjectState | Command | None = ProjectState(
        task_id=task_id,
        md_content=md_content,
    )

    await bus.publish({"type": "progress", "phase": "init", "message": "Starting project generation..."})

    async def _finish_cancelled():
        update_task(task_id, status="cancelled", phase="cancelled",
                    interrupt_type="", interrupt_data={})
        await bus.publish({"type": "cancelled", "message": "Task was cancelled by user."})

    while True:
        if cancel_event.is_set():
            await _finish_cancelled()
            return

        try:
            got_interrupt = False

            async for event in app.astream(current_input, config=config):
                if cancel_event.is_set():
                    await _finish_cancelled()
                    return

                for node_name, node_output in event.items():
                    if node_name == "__interrupt__":
                        interrupt_payload = _extract_interrupt_value(node_output)
                        interrupt_type = interrupt_payload.get("type", "unknown")

                        update_task(
                            task_id,
                            status="waiting_for_input",
                            interrupt_type=interrupt_type,
                            interrupt_data=interrupt_payload,
                        )

                        await bus.publish({
                            "type": "interrupt",
                            "interrupt_type": interrupt_type,
                            "data": interrupt_payload,
                        })

                        # Wait for user response OR cancellation
                        while True:
                            try:
                                resume_data = await asyncio.wait_for(
                                    resume_queue.get(), timeout=1.0,
                                )
                                break
                            except asyncio.TimeoutError:
                                if cancel_event.is_set():
                                    await _finish_cancelled()
                                    return

                        update_task(task_id, status="running",
                                    interrupt_type="", interrupt_data={})

                        current_input = Command(resume=resume_data)
                        got_interrupt = True
                        continue

                    phase = "unknown"
                    if isinstance(node_output, dict):
                        phase = node_output.get("phase", phase)
                        if isinstance(phase, Phase):
                            phase = phase.value

                    await bus.publish({
                        "type": "progress",
                        "phase": phase,
                        "node": node_name,
                        "message": f"Completed: {node_name}",
                    })
                    update_task(task_id, phase=phase, status="running")

                    if isinstance(node_output, dict):
                        if node_output.get("phase") == Phase.DONE:
                            done_evt = {
                                "type": "done",
                                "output_path": node_output.get("output_path", ""),
                                "archive_path": node_output.get("archive_path", ""),
                                "git_log": node_output.get("git_log", ""),
                            }
                            await bus.publish(done_evt)
                            update_task(
                                task_id, status="done", phase="done",
                                output_path=node_output.get("output_path", ""),
                                archive_path=node_output.get("archive_path", ""),
                                interrupt_type="", interrupt_data={},
                            )
                            return

                        if node_output.get("phase") == Phase.ERROR:
                            errors = node_output.get("errors", [])
                            await bus.publish({
                                "type": "error",
                                "message": "; ".join(errors) if errors else "Unknown error",
                            })
                            update_task(
                                task_id, status="error", errors=errors,
                                interrupt_type="", interrupt_data={},
                            )
                            return

            if not got_interrupt:
                break

        except Exception as e:
            logger.error("Graph runner error for task %s: %s", task_id, e, exc_info=True)
            await bus.publish({"type": "error", "message": str(e)})
            update_task(task_id, status="error", errors=[str(e)])
            return

    logger.info("Graph runner for task %s finished", task_id)


def ensure_runner(task_id: str) -> None:
    """Start the background graph runner if not already running."""
    existing = _task_runners.get(task_id)
    if existing and not existing.done():
        return
    runner = asyncio.create_task(_run_graph(task_id), name=f"graph-{task_id}")
    _task_runners[task_id] = runner
    logger.info("Started graph runner for task %s", task_id)


# ── WebSocket endpoint ────────────────────────────────────────────


@ws_router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint — thin client that subscribes to graph events.

    The graph runs independently in a background task. This handler:
    1. Subscribes to the task event bus
    2. Forwards events to the WS client
    3. Forwards user responses to the resume queue
    4. Can connect/disconnect freely without affecting the graph
    """
    await websocket.accept()
    logger.info("WebSocket connected for task %s", task_id)

    task = _tasks.get(task_id)
    if not task:
        await websocket.send_json({"type": "error", "message": "Task not found"})
        await websocket.close()
        return

    # Start the graph runner if this is a fresh task
    status = task.get("status", "unknown")
    if status == "created":
        update_task(task_id, status="running")
        ensure_runner(task_id)
    elif status in ("done", "error", "cancelled"):
        await websocket.send_json({
            "type": "error",
            "message": f"Task already finished with status: {status}",
        })
        await websocket.close()
        return
    elif status in ("running", "waiting_for_input"):
        # Runner should be alive; ensure it is
        ensure_runner(task_id)

    bus = get_task_bus(task_id)
    sub = bus.subscribe()
    resume_queue = get_resume_queue(task_id)

    # If the task has a pending interrupt, re-send it immediately
    if task.get("status") == "waiting_for_input" and task.get("interrupt_type"):
        interrupt_data = task.get("interrupt_data", {})
        await websocket.send_json({
            "type": "progress",
            "phase": task.get("phase", "unknown"),
            "message": "Reconnected. Resuming where you left off...",
        })
        await websocket.send_json({
            "type": "interrupt",
            "interrupt_type": task.get("interrupt_type", "unknown"),
            "data": interrupt_data,
        })

    try:
        recv_task: asyncio.Task | None = None

        while True:
            # Start listening for WS messages if not already
            if recv_task is None or recv_task.done():
                recv_task = asyncio.ensure_future(websocket.receive_text())

            # Wait for either a bus event or a WS message
            bus_wait = asyncio.ensure_future(sub.get())

            done, pending = await asyncio.wait(
                [recv_task, bus_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for p in pending:
                p.cancel()

            if bus_wait in done:
                event = bus_wait.result()
                try:
                    await websocket.send_json(event)
                except Exception:
                    break

                if event.get("type") in ("done", "error", "cancelled"):
                    break

            if recv_task in done:
                try:
                    raw = recv_task.result()
                except WebSocketDisconnect:
                    break

                recv_task = None

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "resume":
                    data = msg.get("data", msg)
                    await resume_queue.put(data)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket error for task %s: %s", task_id, e, exc_info=True)
    finally:
        bus.unsubscribe(sub)
        logger.info("WebSocket disconnected for task %s", task_id)
