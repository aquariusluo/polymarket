from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.jobs import run_daily_report, run_pipeline
from app.services.scheduler_service import SchedulerService
from app.storage.db import get_connection, init_db


def test_scheduler_service_run_loop_honors_max_iterations():
    calls: list[str] = []

    def make_step(name: str):
        def _step():
            calls.append(name)
            return {'step': name}
        return _step

    scheduler = SchedulerService(
        {
            'select-leaders': make_step('select-leaders'),
            'poll-trades': make_step('poll-trades'),
            'generate-signals': make_step('generate-signals'),
            'simulate': make_step('simulate'),
            'mark-to-market': make_step('mark-to-market'),
            'daily-report': make_step('daily-report'),
        }
    )

    result = scheduler.run_loop(max_iterations=2, sleep_seconds=0)

    assert result['iteration_count'] == 2
    assert len(result['iterations']) == 2
    assert calls == [
        'select-leaders', 'poll-trades', 'generate-signals', 'simulate', 'mark-to-market', 'daily-report',
        'select-leaders', 'poll-trades', 'generate-signals', 'simulate', 'mark-to-market', 'daily-report',
    ]


def test_run_pipeline_records_pipeline_job_and_step_job_runs(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'pipeline.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '{"positions": []}'),
        )
        conn.commit()

    def noop(name: str):
        return lambda settings=None: {'name': name, 'ok': True}

    result = run_pipeline.run(
        settings,
        steps={
            'select-leaders': noop('select-leaders'),
            'poll-trades': noop('poll-trades'),
            'generate-signals': noop('generate-signals'),
            'simulate': noop('simulate'),
            'mark-to-market': noop('mark-to-market'),
            'daily-report': run_daily_report.run,
        },
    )

    assert result['completed'] is True
    assert result['job_run_id'] is not None

    with get_connection(str(db_path)) as conn:
        rows = conn.execute('SELECT job_name, status FROM job_runs ORDER BY id ASC').fetchall()

    assert [row['job_name'] for row in rows] == [
        'run-loop',
        'daily-report',
    ]
    assert all(row['status'] == 'completed' for row in rows)


def test_run_pipeline_records_failure_and_stops(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'pipeline-fail.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    def ok(name: str):
        return lambda settings=None: {'name': name}

    def boom(settings=None):
        raise RuntimeError('poll failed')

    with pytest.raises(RuntimeError, match='poll failed'):
        run_pipeline.run(
            settings,
            steps={
                'select-leaders': ok('select-leaders'),
                'poll-trades': boom,
                'generate-signals': ok('generate-signals'),
                'simulate': ok('simulate'),
                'mark-to-market': ok('mark-to-market'),
                'daily-report': ok('daily-report'),
            },
        )

    with get_connection(str(db_path)) as conn:
        rows = conn.execute('SELECT job_name, status, error_message FROM job_runs ORDER BY id ASC').fetchall()

    assert [row['job_name'] for row in rows] == ['run-loop']
    assert rows[-1]['status'] == 'failed'
    assert 'poll failed' in rows[-1]['error_message']



def test_run_daily_report_reuses_execute_job_connection(tmp_path: Path, monkeypatch, settings_factory):
    db_path = tmp_path / 'daily-report-single-conn.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '{"positions": []}'),
        )
        conn.commit()

    real_get_connection = run_daily_report.get_connection
    seen_ids: list[int] = []

    def tracking_get_connection(db_path: str):
        conn = real_get_connection(db_path)
        seen_ids.append(id(conn))
        return conn

    monkeypatch.setattr(run_daily_report, 'get_connection', tracking_get_connection)

    result = run_daily_report.run(settings)

    assert result['job_run_id'] is not None
    assert len(seen_ids) == 1


def test_run_generate_signals_reuses_execute_job_connection(tmp_path: Path, monkeypatch, settings_factory):
    from app.jobs import run_generate_signals

    db_path = tmp_path / 'generate-signals-single-conn.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))
    seen_conn_ids: list[int] = []

    real_get_connection = run_generate_signals.get_connection

    def tracking_get_connection(db_path: str):
        conn = real_get_connection(db_path)
        seen_conn_ids.append(id(conn))
        return conn

    class DummyMarketService:
        def __init__(self, conn, settings=None):
            assert id(conn) == seen_conn_ids[0]

    class DummySignalService:
        def __init__(self, conn, settings, market_service):
            assert id(conn) == seen_conn_ids[0]

        def run(self):
            return type(
                'Result',
                (),
                {
                    'processed_count': 1,
                    'accepted_count': 1,
                    'rejected_count': 0,
                    'inserted_count': 1,
                    'skipped_count': 0,
                },
            )()

    monkeypatch.setattr(run_generate_signals, 'get_connection', tracking_get_connection)
    monkeypatch.setattr(run_generate_signals, 'MarketService', DummyMarketService)
    monkeypatch.setattr(run_generate_signals, 'SignalService', DummySignalService)

    result = run_generate_signals.run(settings)

    assert result['job_run_id'] is not None
    assert len(seen_conn_ids) == 1
