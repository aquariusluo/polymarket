from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.scarf import compute_evaluation_verdict
from app.services.cron_service import project_root_path
from app.storage.db import get_connection
from app.storage.repositories import LeaderRepository


def _find_widget(data: dict[str, Any], title: str) -> dict[str, Any] | None:
    for section in data.get('sections', []):
        for widget in section.get('widgets', []):
            if widget.get('title') == title:
                return widget
    return None


def _latest_iteration(pipeline_result: dict[str, Any]) -> dict[str, Any]:
    iterations = pipeline_result.get('iterations') or []
    if not iterations:
        return {}
    return iterations[-1] or {}


def _step_result(pipeline_result: dict[str, Any], step_name: str) -> dict[str, Any]:
    latest_iteration = _latest_iteration(pipeline_result)
    for step in reversed(latest_iteration.get('steps', [])):
        if step.get('name') == step_name:
            return step.get('result') or {}
    return {}


def _latest_daily_report_result(pipeline_result: dict[str, Any]) -> dict[str, Any]:
    return _step_result(pipeline_result, 'daily-report')


def _load_leader_rows(settings: Settings, project_root: str | Path | None = None) -> list[list[str]]:
    captured_at = 'Not run yet'
    rows: list[list[str]] = []
    if settings.scarf.leader_selection_mode == 'fixed_override':
        for idx, wallet in enumerate(settings.scarf.top_accounts_override or [], start=1):
            rows.append([str(idx), wallet, captured_at, 'active'])
        return rows

    if settings.db_path:
        with get_connection(str(settings.db_path)) as conn:
            latest_leaders = LeaderRepository(conn).get_latest_leaders()
        if latest_leaders:
            for leader in latest_leaders:
                label = leader['wallet'] or leader['name'] or leader['pseudonym']
                rows.append([str(leader['rank']), str(label), captured_at, 'active'])
    if rows:
        return rows
    for idx, wallet in enumerate(settings.scarf.top_accounts_override or [], start=1):
        rows.append([str(idx), wallet, captured_at, 'active'])
    return rows


def _load_recent_job_run_rows(settings: Settings, limit: int = 5) -> list[list[str]]:
    if not settings.db_path:
        return []
    with get_connection(str(settings.db_path)) as conn:
        rows = conn.execute(
            "SELECT job_name, status, inserted_count, skipped_count, error_message FROM job_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [[str(row['job_name']), str(row['status']), str(int(row['inserted_count'] or 0)), str(int(row['skipped_count'] or 0)), str(row['error_message'] or '')] for row in rows]


def _set_stat_value(data: dict[str, Any], title: str, value: Any) -> None:
    widget = _find_widget(data, title)
    if widget is not None:
        widget['value'] = value


def _set_widget_subtitle(data: dict[str, Any], title: str, subtitle: str) -> None:
    widget = _find_widget(data, title)
    if widget is not None:
        widget['subtitle'] = subtitle


def update_dashboard(*, project_root: str | Path | None = None, settings: Settings, pipeline_result: dict[str, Any]) -> str:
    root = project_root_path(project_root)
    path = root / '.scarf' / 'dashboard.json'
    if not path.exists():
        return str(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['updatedAt'] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

    latest_iteration = _latest_iteration(pipeline_result)
    daily_report = _latest_daily_report_result(pipeline_result)
    poll_trades = _step_result(pipeline_result, 'poll-trades')
    generate_signals = _step_result(pipeline_result, 'generate-signals')
    leader_rows = _load_leader_rows(settings, project_root=project_root)
    tracked_leader_count = len(leader_rows) if leader_rows else settings.top_n
    verdict_value, verdict_subtitle = compute_evaluation_verdict(settings.scarf, float(daily_report.get('total_equity', 0.0) or 0.0))

    _set_stat_value(data, 'Execution Mode', settings.scarf.execution_mode)
    _set_stat_value(data, 'Tracked Leaders', tracked_leader_count)
    bankroll_value = int(settings.scarf.bankroll_usd) if float(settings.scarf.bankroll_usd).is_integer() else settings.scarf.bankroll_usd
    _set_stat_value(data, 'Copy Bankroll (USD)', bankroll_value)
    _set_stat_value(data, '60-Day PnL', f"{float(daily_report.get('total_equity', 0.0)):.2f} USD")
    _set_stat_value(data, 'Accepted Signals', int(daily_report.get('accepted_signal_count', 0)))
    _set_stat_value(data, 'Filled Orders', int(daily_report.get('filled_order_count', 0)))
    _set_stat_value(data, 'Rejected Orders', int(daily_report.get('rejected_order_count', 0)))

    _set_stat_value(data, 'Shadow Run Status', 'completed' if pipeline_result.get('completed') else 'failed')
    _set_stat_value(data, 'Pipeline Iterations', int(pipeline_result.get('iteration_count') or latest_iteration.get('iteration') or 0))
    _set_stat_value(data, 'Trades Inserted', int(poll_trades.get('trades_inserted', 0)))
    _set_stat_value(data, 'Trades Skipped', int(poll_trades.get('trades_skipped', 0)))
    _set_stat_value(data, 'Signals Processed', int(generate_signals.get('processed', 0)))
    _set_stat_value(data, '60-Day Verdict', verdict_value)
    _set_widget_subtitle(data, '60-Day Verdict', verdict_subtitle)

    watch_widget = _find_widget(data, 'Top 5 Source Accounts')
    if watch_widget is not None:
        captured_at = daily_report.get('captured_at') or 'Not run yet'
        normalized_rows = []
        for row in leader_rows:
            normalized = list(row)
            if len(normalized) >= 3 and normalized[2] == 'Not run yet':
                normalized[2] = captured_at
            normalized_rows.append(normalized)
        watch_widget['rows'] = normalized_rows

    job_runs_widget = _find_widget(data, 'Recent Job Runs')
    if job_runs_widget is not None:
        job_runs_widget['rows'] = _load_recent_job_run_rows(settings)

    chart_widget = _find_widget(data, 'Cumulative Copy PnL')
    if chart_widget is not None:
        latest_equity = float(daily_report.get('total_equity', 0.0))
        snapshot_count = int(daily_report.get('snapshot_count', 0))
        series = chart_widget.setdefault('series', [{'name': 'PnL', 'color': 'green', 'data': []}])
        if not series:
            series.append({'name': 'PnL', 'color': 'green', 'data': []})
        series[0]['data'] = [{'x': f'Snapshot {snapshot_count or 1}', 'y': latest_equity}]

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return str(path)
