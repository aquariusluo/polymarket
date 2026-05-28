from __future__ import annotations

import pytest


def test_scheduler_service_runs_pipeline_steps_in_order():
    from app.services.scheduler_service import SchedulerService

    calls: list[str] = []

    def make_step(name: str):
        def _step():
            calls.append(name)
            return {"step": name, "ok": True}
        return _step

    scheduler = SchedulerService(
        {
            "select-leaders": make_step("select-leaders"),
            "poll-trades": make_step("poll-trades"),
            "generate-signals": make_step("generate-signals"),
            "simulate": make_step("simulate"),
            "mark-to-market": make_step("mark-to-market"),
            "daily-report": make_step("daily-report"),
        }
    )

    result = scheduler.run_once()

    assert calls == [
        "select-leaders",
        "poll-trades",
        "generate-signals",
        "simulate",
        "mark-to-market",
        "daily-report",
    ]
    assert result["steps"][0]["name"] == "select-leaders"
    assert result["steps"][-1]["name"] == "daily-report"
    assert result["failed_step"] is None


def test_scheduler_service_stops_and_returns_failed_step():
    from app.services.scheduler_service import SchedulerService

    calls: list[str] = []

    def ok(name: str):
        def _step():
            calls.append(name)
            return {"step": name}
        return _step

    def boom():
        calls.append("simulate")
        raise RuntimeError("boom")

    scheduler = SchedulerService(
        {
            "select-leaders": ok("select-leaders"),
            "poll-trades": ok("poll-trades"),
            "generate-signals": ok("generate-signals"),
            "simulate": boom,
            "mark-to-market": ok("mark-to-market"),
            "daily-report": ok("daily-report"),
        }
    )

    result = scheduler.run_once()

    assert calls == ["select-leaders", "poll-trades", "generate-signals", "simulate"]
    assert result["failed_step"] == "simulate"
    assert result["steps"][-1]["status"] == "failed"
    assert "boom" in result["steps"][-1]["error"]
