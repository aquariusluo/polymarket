from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


DEFAULT_STEP_ORDER = [
    "select-leaders",
    "poll-trades",
    "generate-signals",
    "simulate",
    "mark-to-market",
    "daily-report",
]


@dataclass
class SchedulerService:
    steps: Mapping[str, Callable[[], dict[str, Any]]]

    def run_once(self) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        failed_step: str | None = None

        for name in DEFAULT_STEP_ORDER:
            step = self.steps[name]
            try:
                data = step() or {}
                results.append({"name": name, "status": "ok", "result": data})
            except Exception as exc:
                failed_step = name
                results.append({"name": name, "status": "failed", "error": str(exc)})
                break

        return {
            "steps": results,
            "failed_step": failed_step,
            "completed": failed_step is None,
        }

    def run_loop(self, *, max_iterations: int = 1, sleep_seconds: int = 0) -> dict[str, Any]:
        if max_iterations <= 0:
            raise ValueError('max_iterations must be >= 1')
        if sleep_seconds < 0:
            raise ValueError('sleep_seconds must be >= 0')

        iterations: list[dict[str, Any]] = []
        failed_iteration: int | None = None

        for index in range(max_iterations):
            result = self.run_once()
            result['iteration'] = index + 1
            iterations.append(result)
            if not result['completed']:
                failed_iteration = index + 1
                break
            if sleep_seconds and index < max_iterations - 1:
                time.sleep(sleep_seconds)

        return {
            'iteration_count': len(iterations),
            'iterations': iterations,
            'completed': failed_iteration is None,
            'failed_iteration': failed_iteration,
            'failed_step': iterations[-1]['failed_step'] if iterations else None,
        }
