from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TaskMetrics:
    """Tracks cost, latency, and call counts for a single generation task."""

    task_id: str
    total_cost_usd: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    llm_calls: int = 0
    review_iterations: int = 0
    start_time: float = field(default_factory=time.time)
    phase_timings: dict[str, float] = field(default_factory=dict)

    def record_llm_call(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        self.llm_calls += 1
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_cost_usd += cost_usd

    def start_phase(self, phase: str) -> None:
        self.phase_timings[f"{phase}_start"] = time.time()

    def end_phase(self, phase: str) -> None:
        start_key = f"{phase}_start"
        if start_key in self.phase_timings:
            duration = time.time() - self.phase_timings[start_key]
            self.phase_timings[phase] = duration
            logger.info("Task %s phase %s took %.1fs", self.task_id, phase, duration)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def summary(self) -> dict:
        return {
            "task_id": self.task_id,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "llm_calls": self.llm_calls,
            "review_iterations": self.review_iterations,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "phase_timings": {
                k: round(v, 1)
                for k, v in self.phase_timings.items()
                if not k.endswith("_start")
            },
        }
