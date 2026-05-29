from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from dashboard.api.database import PROJECT_ROOT, get_db

router = APIRouter(prefix='/api')

MONITOR_LOG = PROJECT_ROOT / 'tmp' / 'polymarket-cli-monitor.jsonl'


def _sanitize_error_message(value: object, max_len: int = 200) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def _safe_monitor_log_path() -> Path:
    base = (PROJECT_ROOT / 'tmp').resolve()
    target = MONITOR_LOG.resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail='Invalid monitor log path') from exc
    return target


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
                    (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds(), 1
                )
            except (ValueError, TypeError):
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
            'error_message': _sanitize_error_message(d.get('error_message')),
        })
    return runs


@router.get('/pipeline/monitor')
def get_monitor_log(limit: int = Query(50, le=200)):
    log_path = _safe_monitor_log_path()
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding='utf-8').strip().split('\n')
    entries = []
    for line in reversed(lines[-limit:]):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
