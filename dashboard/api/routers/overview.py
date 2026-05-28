from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends
import sqlite3

from dashboard.api.database import get_db

router = APIRouter(prefix='/api')

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


@router.get('/overview')
def get_overview(conn: sqlite3.Connection = Depends(get_db)):
    summary = _read_json(PROJECT_ROOT / '.scarf' / 'reports' / 'latest-summary.json')
    gate = _read_json(PROJECT_ROOT / '.scarf' / 'reports' / 'auto-follow-gate.json')

    rows = conn.execute(
        'SELECT * FROM job_runs ORDER BY id DESC LIMIT 10'
    ).fetchall()

    leader_count = conn.execute('SELECT COUNT(*) FROM leaders').fetchone()[0]

    latest_run = None
    for r in rows:
        d = dict(r)
        if d.get('job_name') == 'select-leaders':
            latest_run = d
            break

    return {
        'execution_mode': summary.get('execution_mode', 'unknown'),
        'bankroll_usd': 1000.0,
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
        'last_pipeline_at': latest_run.get('finished_at') if latest_run else None,
        'pipeline_status': latest_run.get('status') if latest_run else None,
    }
