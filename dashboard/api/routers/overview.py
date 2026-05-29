from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
import sqlite3

from dashboard.api.database import PROJECT_ROOT, get_db, read_json_report

router = APIRouter(prefix='/api')


def _get_execution_mode(manifest: dict) -> str:
    for item in manifest.get('schema', []):
        if item.get('key') == 'execution_mode':
            return item.get('default', 'manual_confirm')
    if 'execution_mode' in manifest:
        return manifest['execution_mode']
    return 'manual_confirm'


def _get_bankroll(manifest: dict) -> float:
    for item in manifest.get('schema', []):
        if item.get('key') == 'bankroll_usd':
            try:
                return float(item.get('default', 1000.0))
            except (TypeError, ValueError):
                return 1000.0
    return 1000.0


@router.get('/overview')
def get_overview(conn: sqlite3.Connection = Depends(get_db)):
    summary = read_json_report(PROJECT_ROOT / '.scarf' / 'reports' / 'latest-summary.json')
    gate = read_json_report(PROJECT_ROOT / '.scarf' / 'reports' / 'auto-follow-gate.json')
    manifest = read_json_report(PROJECT_ROOT / '.scarf' / 'manifest.json')

    try:
        rows = conn.execute(
            """
            SELECT job_name, finished_at, status
            FROM job_runs
            ORDER BY id DESC
            LIMIT 10
            """
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []

    leader_count = 0
    try:
        leader_count = conn.execute('SELECT COUNT(*) FROM leaders').fetchone()[0]
    except sqlite3.OperationalError:
        pass

    latest_run = None
    for r in rows:
        d = dict(r)
        if d.get('job_name') == 'select-leaders':
            latest_run = d
            break

    return {
        'execution_mode': _get_execution_mode(manifest),
        'bankroll_usd': _get_bankroll(manifest),
        'total_equity': summary.get('total_equity', 0.0),
        'total_unrealized_pnl': summary.get('total_unrealized_pnl', 0.0),
        'total_realized_pnl': summary.get('total_realized_pnl', 0.0),
        'drawdown_pct': summary.get('drawdown_pct', 0.0),
        'open_position_count': summary.get('open_position_count', 0),
        'accepted_signal_count': summary.get('accepted_signal_count', 0),
        'filled_order_count': summary.get('filled_order_count', 0),
        'rejected_order_count': summary.get('rejected_order_count', 0),
        'tracked_leader_count': leader_count,
        'gate_status': gate.get('status', 'unknown'),
        'gate_decision': gate.get('decision', ''),
        'gate_notes': gate.get('notes', []),
        'gate_thresholds': gate.get('thresholds', {}),
        'last_pipeline_at': latest_run.get('finished_at') if latest_run else None,
        'pipeline_status': latest_run.get('status') if latest_run else None,
    }
