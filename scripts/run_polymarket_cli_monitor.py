#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
LOCK_DIR = PROJECT_DIR / 'tmp' / 'polymarket-cli-monitor.lock'
PID_FILE = LOCK_DIR / 'pid'
LOG_PATH = PROJECT_DIR / 'tmp' / 'polymarket-cli-monitor.jsonl'
PYTHON = PROJECT_DIR / '.venv' / 'bin' / 'python'
STEPS = ['select-leaders', 'poll-trades', 'generate-signals', 'simulate', 'mark-to-market', 'daily-report', 'gate-report']
PRUNE_STEP = 'prune-data'
PRUNE_MARKER = PROJECT_DIR / 'tmp' / 'last-prune-date.txt'


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_matches_monitor(pid: int) -> bool:
    if not _pid_is_running(pid):
        return False
    completed = subprocess.run(
        ['ps', '-p', str(pid), '-o', 'command='],
        text=True,
        capture_output=True,
        check=False,
    )
    return 'run_polymarket_cli_monitor.py' in completed.stdout


def acquire_lock() -> bool:
    PROJECT_DIR.joinpath('tmp').mkdir(parents=True, exist_ok=True)
    try:
        LOCK_DIR.mkdir()
    except FileExistsError:
        try:
            pid = int(PID_FILE.read_text().strip())
        except (OSError, ValueError):
            pid = 0
        if pid and _pid_matches_monitor(pid):
            print(f'monitor already active; skipping {_utc_now()}')
            log_event({'event': 'monitor_skipped_lock_active', 'pid': pid})
            return False
        shutil.rmtree(LOCK_DIR, ignore_errors=True)
        LOCK_DIR.mkdir()
    PID_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    shutil.rmtree(LOCK_DIR, ignore_errors=True)


def log_event(event: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {'timestamp': _utc_now(), **event}
    with LOG_PATH.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, sort_keys=True) + '\n')


def step_timeout_seconds() -> int:
    return int(os.environ.get('MONITOR_STEP_TIMEOUT_SECONDS', '180'))


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    env.setdefault('DATA_SOURCE', 'polymarket_cli')
    env.setdefault('DB_PATH', 'data/app.db')
    env.setdefault('TRADE_FETCH_LIMIT', '5')
    env.setdefault('SIGNAL_BATCH_LIMIT', '10')
    env.setdefault('RUN_LOOP_MAX_ITERATIONS', '1')
    env.setdefault('RUN_LOOP_SLEEP_SECONDS', '0')
    env['PYTHONUNBUFFERED'] = '1'
    return env


def run_step(step: str, env: dict[str, str]) -> dict:
    started = _utc_now()
    completed = subprocess.run(
        [str(PYTHON), '-m', 'app.main', step],
        cwd=PROJECT_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=step_timeout_seconds(),
        check=False,
    )
    result = {
        'step': step,
        'started_at': started,
        'finished_at': _utc_now(),
        'returncode': completed.returncode,
        'stdout': completed.stdout[-4000:],
        'stderr': completed.stderr[-4000:],
    }
    log_event({'event': 'step_finished', **result})
    return result


def _today_utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def should_run_prune() -> bool:
    if os.environ.get('MONITOR_ENABLE_DAILY_PRUNE', '1').strip().lower() in {'0', 'false', 'no', 'off'}:
        return False
    try:
        last = PRUNE_MARKER.read_text(encoding='utf-8').strip()
    except OSError:
        last = ''
    return last != _today_utc_date()


def mark_prune_ran_today() -> None:
    PRUNE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    PRUNE_MARKER.write_text(_today_utc_date(), encoding='utf-8')


def run_daily_prune(env: dict[str, str]) -> int:
    if not should_run_prune():
        log_event({'event': 'daily_prune_skipped_already_ran'})
        return 0
    try:
        prune_result = run_step(PRUNE_STEP, env)
    except subprocess.TimeoutExpired as exc:
        log_event({
            'event': 'step_timeout',
            'step': PRUNE_STEP,
            'timeout_seconds': step_timeout_seconds(),
            'stdout': (exc.stdout or '')[-4000:] if isinstance(exc.stdout, str) else '',
            'stderr': (exc.stderr or '')[-4000:] if isinstance(exc.stderr, str) else '',
        })
        return 124
    if prune_result['returncode'] == 0:
        mark_prune_ran_today()
        log_event({'event': 'daily_prune_completed'})
        return 0
    log_event({'event': 'daily_prune_failed', 'returncode': prune_result['returncode']})
    return prune_result['returncode'] or 1


def main() -> int:
    if not acquire_lock():
        return 0

    def _cleanup(_signum=None, _frame=None):
        release_lock()
        if _signum is not None:
            raise SystemExit(128 + int(_signum))

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    env = build_env()
    log_event({
        'event': 'monitor_started',
        'data_source': env['DATA_SOURCE'],
        'trade_fetch_limit': env['TRADE_FETCH_LIMIT'],
        'signal_batch_limit': env['SIGNAL_BATCH_LIMIT'],
    })

    exit_code = 0
    try:
        for step in STEPS:
            try:
                result = run_step(step, env)
            except subprocess.TimeoutExpired as exc:
                log_event({
                    'event': 'step_timeout',
                    'step': step,
                    'timeout_seconds': step_timeout_seconds(),
                    'stdout': (exc.stdout or '')[-4000:] if isinstance(exc.stdout, str) else '',
                    'stderr': (exc.stderr or '')[-4000:] if isinstance(exc.stderr, str) else '',
                })
                exit_code = 124
                break
            if result['returncode'] != 0:
                log_event({'event': 'monitor_failed', 'failed_step': step})
                exit_code = result['returncode'] or 1
                break
        if exit_code == 0:
            prune_code = run_daily_prune(env)
            if prune_code != 0:
                log_event({'event': 'daily_prune_non_blocking_failure', 'returncode': prune_code})
        else:
            log_event({'event': 'daily_prune_skipped_pipeline_failed'})
        if exit_code != 0:
            return exit_code
        log_event({'event': 'monitor_completed'})
        return 0
    finally:
        release_lock()


if __name__ == '__main__':
    raise SystemExit(main())
