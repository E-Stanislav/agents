from __future__ import annotations

import logging

from src.config import settings

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    pass


class BudgetGuard:
    """Tracks spending per task and stops execution when budget is exceeded."""

    def __init__(self) -> None:
        self._spending: dict[str, float] = {}

    def check(self, task_id: str) -> None:
        spent = self._spending.get(task_id, 0.0)
        if spent >= settings.max_budget_per_task_usd:
            raise BudgetExceeded(
                f"Task {task_id} exceeded budget: "
                f"${spent:.2f} >= ${settings.max_budget_per_task_usd:.2f}"
            )

    def record(self, task_id: str, cost_usd: float) -> float:
        self._spending[task_id] = self._spending.get(task_id, 0.0) + cost_usd
        total = self._spending[task_id]
        if total > settings.max_budget_per_task_usd * 0.8:
            logger.warning(
                "Task %s approaching budget limit: $%.2f / $%.2f",
                task_id,
                total,
                settings.max_budget_per_task_usd,
            )
        return total

    def reset(self, task_id: str) -> None:
        self._spending.pop(task_id, None)

    def get_spent(self, task_id: str) -> float:
        return self._spending.get(task_id, 0.0)
