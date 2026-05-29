from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_monitor_module():
    script_path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_polymarket_cli_monitor.py'
    spec = importlib.util.spec_from_file_location('run_polymarket_cli_monitor', script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_should_run_prune_when_marker_missing(tmp_path, monkeypatch):
    monitor = _load_monitor_module()
    marker = tmp_path / 'last-prune-date.txt'
    monkeypatch.setattr(monitor, 'PRUNE_MARKER', marker)
    monkeypatch.delenv('MONITOR_ENABLE_DAILY_PRUNE', raising=False)

    assert monitor.should_run_prune() is True


def test_should_skip_prune_when_already_ran_today(tmp_path, monkeypatch):
    monitor = _load_monitor_module()
    marker = tmp_path / 'last-prune-date.txt'
    monkeypatch.setattr(monitor, 'PRUNE_MARKER', marker)
    monkeypatch.delenv('MONITOR_ENABLE_DAILY_PRUNE', raising=False)

    monitor.mark_prune_ran_today()

    assert monitor.should_run_prune() is False


def test_should_skip_prune_when_disabled(tmp_path, monkeypatch):
    monitor = _load_monitor_module()
    marker = tmp_path / 'last-prune-date.txt'
    monkeypatch.setattr(monitor, 'PRUNE_MARKER', marker)
    monkeypatch.setenv('MONITOR_ENABLE_DAILY_PRUNE', 'false')

    assert monitor.should_run_prune() is False


def test_main_still_runs_daily_prune_when_pipeline_step_fails(monkeypatch):
    monitor = _load_monitor_module()
    calls: list[str] = []
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(monitor, 'acquire_lock', lambda: True)
    monkeypatch.setattr(monitor, 'release_lock', lambda: None)
    monkeypatch.setattr(monitor.signal, 'signal', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        monitor,
        'build_env',
        lambda: {
            'DATA_SOURCE': 'test',
            'TRADE_FETCH_LIMIT': '5',
            'SIGNAL_BATCH_LIMIT': '10',
        },
    )
    monkeypatch.setattr(monitor, 'should_run_prune', lambda: True)
    monkeypatch.setattr(monitor, 'mark_prune_ran_today', lambda: events.append({'event': 'marked'}))
    monkeypatch.setattr(monitor, 'log_event', lambda event: events.append(event))

    def _run_step(step: str, env: dict[str, str]):
        calls.append(step)
        if step == monitor.STEPS[0]:
            return {'step': step, 'returncode': 2}
        if step == monitor.PRUNE_STEP:
            return {'step': step, 'returncode': 0}
        return {'step': step, 'returncode': 0}

    monkeypatch.setattr(monitor, 'run_step', _run_step)
    code = monitor.main()
    assert code == 2
    assert calls == [monitor.STEPS[0]]
    assert any(event.get('event') == 'monitor_failed' for event in events)
    assert any(event.get('event') == 'daily_prune_skipped_pipeline_failed' for event in events)


def test_main_keeps_success_exit_when_only_prune_fails(monkeypatch):
    monitor = _load_monitor_module()
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(monitor, 'acquire_lock', lambda: True)
    monkeypatch.setattr(monitor, 'release_lock', lambda: None)
    monkeypatch.setattr(monitor.signal, 'signal', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        monitor,
        'build_env',
        lambda: {
            'DATA_SOURCE': 'test',
            'TRADE_FETCH_LIMIT': '5',
            'SIGNAL_BATCH_LIMIT': '10',
        },
    )
    monkeypatch.setattr(monitor, 'log_event', lambda event: events.append(event))
    monkeypatch.setattr(monitor, 'run_step', lambda step, env: {'step': step, 'returncode': 0})
    monkeypatch.setattr(monitor, 'run_daily_prune', lambda env: 2)

    code = monitor.main()
    assert code == 0
    assert any(event.get('event') == 'daily_prune_non_blocking_failure' for event in events)
