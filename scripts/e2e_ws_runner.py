#!/usr/bin/env python3
"""Клиент WebSocket для E2E: вызывается внутри контейнера app (зависимости уже в образе)."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

# Внутри контейнера приложение слушает APP_PORT (см. docker-compose)
PORT = int(os.environ.get("APP_PORT", "8000"))
HOST = os.environ.get("E2E_WS_HOST", "127.0.0.1")
MAX_RETRIES = int(os.environ.get("E2E_WS_RETRIES", "3"))
RETRY_DELAY = float(os.environ.get("E2E_WS_RETRY_DELAY", "5"))


async def run(task_id: str) -> None:
    uri = f"ws://{HOST}:{PORT}/ws/{task_id}"
    timeout = float(os.environ.get("E2E_WS_TIMEOUT_SEC", "3600"))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await _session(uri, timeout)
            return
        except (ConnectionClosedError, ConnectionClosedOK) as e:
            print(f"[retry {attempt}/{MAX_RETRIES}] WS closed: {e}", file=sys.stderr, flush=True)
            if attempt == MAX_RETRIES:
                print("Max retries reached", file=sys.stderr)
                sys.exit(1)
            await asyncio.sleep(RETRY_DELAY)


async def _session(uri: str, timeout: float) -> None:
    async with websockets.connect(uri, max_size=None) as ws:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)

            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "progress":
                print(f"[progress] {msg.get('phase', '')} {msg.get('message', '')}", flush=True)
                continue

            if mtype == "interrupt":
                it = msg.get("interrupt_type", "")
                data = msg.get("data") or {}
                if it == "clarification":
                    questions = data.get("questions") or []
                    answers = [
                        {
                            "question_id": q.get("id", f"q{i}"),
                            "answer": os.environ.get(
                                "E2E_CLARIFICATION_ANSWER",
                                "E2E: минимальный вариант, без дополнительных фич.",
                            ),
                        }
                        for i, q in enumerate(questions)
                    ]
                    await ws.send(json.dumps({"type": "resume", "data": answers}))
                elif it == "architecture_approval":
                    await ws.send(json.dumps({"type": "resume", "data": {"approved": True}}))
                else:
                    print(f"Unexpected interrupt: {it}", file=sys.stderr)
                    sys.exit(1)
                continue

            if mtype == "done":
                print(json.dumps(msg, indent=2, ensure_ascii=False))
                op = msg.get("output_path", "")
                ap = msg.get("archive_path", "")
                if not op and not ap:
                    print("done without paths", file=sys.stderr)
                    sys.exit(1)
                return

            if mtype == "error":
                print(msg.get("message", raw), file=sys.stderr)
                sys.exit(1)

            if mtype == "cancelled":
                print("cancelled", file=sys.stderr)
                sys.exit(1)

            print(f"[?] {mtype}: {raw[:200]}", flush=True)


def main() -> None:
    tid = os.environ.get("TASK_ID") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not tid:
        print("Usage: TASK_ID=... e2e_ws_runner.py [task_id]", file=sys.stderr)
        sys.exit(2)
    asyncio.run(run(tid))


if __name__ == "__main__":
    main()
