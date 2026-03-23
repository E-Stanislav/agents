from __future__ import annotations

import logging

from src.config import settings

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    """Tracks LLM call counts per task and enforces limits."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def check(self, task_id: str) -> None:
        count = self._counts.get(task_id, 0)
        if count >= settings.max_llm_calls_per_task:
            raise RateLimitExceeded(
                f"Task {task_id} exceeded max LLM calls ({settings.max_llm_calls_per_task})"
            )

    def increment(self, task_id: str) -> int:
        self._counts[task_id] = self._counts.get(task_id, 0) + 1
        return self._counts[task_id]

    def reset(self, task_id: str) -> None:
        self._counts.pop(task_id, None)

    def get_count(self, task_id: str) -> int:
        return self._counts.get(task_id, 0)
