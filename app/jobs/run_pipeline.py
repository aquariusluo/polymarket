from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from app.config import get_settings
from app.jobs import run_daily_report, run_generate_signals, run_mark_to_market, run_poll_trades, run_select_leaders, run_simulate
from app.services.artifact_service import append_detection_log, write_shadow_run
from app.services.job_run_service import execute_job
from app.services.scheduler_service import SchedulerService
from app.storage.db import get_connection, init_db


def _default_steps() -> Mapping[str, Callable[..., dict[str, Any]]]:
    return {
        'select-leaders': run_select_leaders.run,
        'poll-trades': run_poll_trades.run,
        'generate-signals': run_generate_signals.run,
        'simulate': run_simulate.run,
        'mark-to-market': run_mark_to_market.run,
        'daily-report': run_daily_report.run,
    }


def run(settings=None, *, steps: Mapping[str, Callable[..., dict[str, Any]]] | None = None, max_iterations: int | None = None, sleep_seconds: int | None = None, project_root=None, **kwargs) -> dict:
    settings = settings or get_settings(project_root)
    steps = steps or _default_steps()

    def _invoke(fn: Callable[..., dict[str, Any]], conn) -> dict:
        params = inspect.signature(fn).parameters
        call_kwargs: dict[str, Any] = {}
        if 'project_root' in params:
            call_kwargs['project_root'] = project_root
        if 'conn' in params:
            call_kwargs['conn'] = conn
        return fn(settings, **call_kwargs)

    max_iterations = settings.run_loop_max_iterations if max_iterations is None else max_iterations
    sleep_seconds = settings.run_loop_sleep_seconds if sleep_seconds is None else sleep_seconds

    def runner(conn) -> dict:
        scheduler = SchedulerService({name: (lambda fn=fn: _invoke(fn, conn)) for name, fn in steps.items()})
        result = scheduler.run_loop(max_iterations=max_iterations, sleep_seconds=sleep_seconds)
        append_detection_log(result, project_root=project_root, job_name='run-loop')
        result['shadow_run_path'] = write_shadow_run(result, project_root=project_root)
        if not result['completed']:
            failed_step = result.get('failed_step') or 'unknown'
            failed_iteration = result.get('failed_iteration') or 1
            step_info = result['iterations'][-1]['steps'][-1] if result.get('iterations') else {}
            error = step_info.get('error', f'pipeline failed at {failed_step}')
            raise RuntimeError(error)
        return result

    with get_connection(settings.db_path) as conn:
        init_db(settings.db_path, conn=conn)
        return execute_job(conn, job_name='run-loop', runner=runner)
