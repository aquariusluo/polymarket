from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query
import sqlite3

from dashboard.api.database import get_db

router = APIRouter(prefix='/api')

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MONITOR_LOG = PROJECT_ROOT / 'tmp' / 'polymarket-cli-monitor.jsonl'


@router.get('/pipeline/runs')
def get_job_runs(conn: sqlite3.Connection = Depends(get_db), limit: int = Query(30, le=100)):
    rows = conn.execute(
        'SELECT id, job_name, started_at, finished_at, status, inserted_count, skipped_count, error_message '
        'FROM job_runs ORDER BY id DESC LIMIT ?',
        (limit,),
    ).fetchall()
    runs = []
    for r in rows:
        d = dict(r)
        finished = d.get('finished_at')
        started = d.get('started_at')
        duration = None
        if finished and started:
            try:
                duration = round(
                    (json.loads(f'"{finished}"') - json.loads(f'"{started}"')).total_seconds(), 1
                )
            except Exception:
                duration = None
        runs.append({
            'id': d.get('id'),
            'job_name': d.get('job_name'),
            'started_at': started,
            'finished_at': finished,
            'duration': duration,
            'status': d.get('status'),
            'inserted_count': d.get('inserted_count'),
            'skipped_count': d.get('skipped_count'),
            'error_message': d.get('error_message'),
        })
    return runs


@router.get('/pipeline/monitor')
def get_monitor_log(limit: int = Query(50, le=200)):
    if not MONITOR_LOG.exists():
        return []
    lines = MONITOR_LOG.read_text(encoding='utf-8').strip().split('\n')
    entries = []
    for line in reversed(lines[-limit:]):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
