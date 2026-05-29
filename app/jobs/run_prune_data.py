from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings, get_settings
from app.services.job_run_service import execute_job
from app.storage.db import get_connection, init_db
from app.storage.repositories import JobRunRepository, LeaderTradeRepository, PortfolioSnapshotRepository, SignalRepository


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(int(days), 1))).isoformat()


def run(settings: Settings | None = None, *, project_root=None, conn=None) -> dict:
    settings = settings or get_settings(project_root)

    def runner(conn) -> dict:
        signal_repo = SignalRepository(conn)
        trade_repo = LeaderTradeRepository(conn)
        job_repo = JobRunRepository(conn)
        snapshot_repo = PortfolioSnapshotRepository(conn)

        signals_cutoff = _cutoff(settings.retention_days_signals)
        trades_cutoff = _cutoff(settings.retention_days_leader_trades)
        jobs_cutoff = _cutoff(settings.retention_days_job_runs)
        snapshots_cutoff = _cutoff(settings.retention_days_portfolio_snapshots)

        pruned_signals = signal_repo.prune_older_than(signals_cutoff, commit=False)
        pruned_leader_trades = trade_repo.prune_older_than(trades_cutoff, commit=False)
        pruned_job_runs = job_repo.prune_older_than(jobs_cutoff, commit=False)
        pruned_portfolio_snapshots = snapshot_repo.prune_older_than(snapshots_cutoff, commit=False)

        total = pruned_signals + pruned_leader_trades + pruned_job_runs + pruned_portfolio_snapshots
        return {
            'pruned_signals': pruned_signals,
            'pruned_leader_trades': pruned_leader_trades,
            'pruned_job_runs': pruned_job_runs,
            'pruned_portfolio_snapshots': pruned_portfolio_snapshots,
            'total_pruned': total,
            'inserted': 0,
            'retention_days': {
                'signals': settings.retention_days_signals,
                'leader_trades': settings.retention_days_leader_trades,
                'job_runs': settings.retention_days_job_runs,
                'portfolio_snapshots': settings.retention_days_portfolio_snapshots,
            },
        }

    if conn is not None:
        return execute_job(conn, job_name='prune-data', runner=runner, atomic=True)
    with get_connection(settings.db_path) as own_conn:
        init_db(settings.db_path, conn=own_conn)
        return execute_job(own_conn, job_name='prune-data', runner=runner, atomic=True)
